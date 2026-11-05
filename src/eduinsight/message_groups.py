"""Group conversations and starred messages, next to private direct messages.

A group is created from the creator's current course contacts (the same set
that direct messages allow). Afterwards access is by group membership only, so
history stays readable when enrollment changes, as for direct conversations.
Non-members get 404 rather than 403 so group IDs do not reveal existence.
Only the creator adds members; anyone may leave. When the creator leaves, the
earliest remaining member becomes the owner.
Unread state is the highest message ID each member has read. Stars are
per user and only cover messages the user can still see.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, messaging
from .auth import AuthUser, get_current_user
from .db import schema_once
from .messaging import Contact, MessageCreate, _contact, _contacts
from .notifications import create_notification

router = APIRouter(tags=["messaging"])

MAX_GROUP_MEMBERS = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS message_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    owner_id INTEGER REFERENCES users(id),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS message_group_members (
    group_id INTEGER NOT NULL REFERENCES message_groups(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at REAL NOT NULL,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_group_members_user ON message_group_members(user_id);
CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES message_groups(id),
    sender_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL CHECK(length(text) <= 2000),
    created_at REAL NOT NULL,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS ix_group_messages ON group_messages(group_id, id DESC);
CREATE TABLE IF NOT EXISTS message_stars (
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK(kind IN ('direct', 'group')),
    message_id INTEGER NOT NULL,
    starred_at REAL NOT NULL,
    PRIMARY KEY (user_id, kind, message_id)
);
"""


@contextmanager
def _db(*, write: bool = False):
    with auth._db() as conn:  # noqa: SLF001
        conn.execute("PRAGMA foreign_keys = ON")
        # Starred direct messages join direct_messages, so ensure both schemas.
        with schema_once(conn, "messaging") as initialize:
            if initialize:
                conn.executescript(messaging._SCHEMA)  # noqa: SLF001
        with schema_once(conn, "message_groups") as initialize:
            if initialize:
                conn.executescript(_SCHEMA)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if write:
                conn.commit()
        except Exception:
            conn.rollback()
            raise


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(min_length=1, max_length=MAX_GROUP_MEMBERS - 1)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Group name cannot be blank")
        return value.strip()


class MembersAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[int] = Field(min_length=1, max_length=MAX_GROUP_MEMBERS - 1)


class GroupSummary(BaseModel):
    id: int
    name: str
    owner_id: int | None
    member_count: int
    last_message_preview: str
    last_at: float
    unread_count: int


class GroupDetail(BaseModel):
    id: int
    name: str
    owner_id: int | None
    created_at: float
    members: list[Contact]


class GroupMessage(BaseModel):
    id: int
    group_id: int
    sender_id: int
    sender_name: str
    text: str
    created_at: float
    is_deleted: bool


class GroupHistory(BaseModel):
    group: GroupDetail
    messages: list[GroupMessage]
    total: int
    limit: int
    offset: int
    has_more: bool


class StarredMessage(BaseModel):
    kind: Literal["direct", "group"]
    message_id: int
    sender_id: int
    sender_name: str
    text: str
    created_at: float
    starred_at: float
    is_deleted: bool
    peer: Contact | None = None
    group_id: int | None = None
    group_name: str | None = None


def _new_member_ids(user: AuthUser, user_ids: list[int], existing: set[int]) -> list[int]:
    ids = [user_id for user_id in dict.fromkeys(user_ids) if user_id != user.id]
    if not ids:
        raise HTTPException(422, "Choose at least one other member")
    allowed = {member.user_id for member in _contacts(user)}
    if not set(ids) <= allowed:
        raise HTTPException(403, "Members must be your course contacts")
    ids = [user_id for user_id in ids if user_id not in existing]
    if len(existing) + len(ids) > MAX_GROUP_MEMBERS:
        raise HTTPException(422, f"A group can have at most {MAX_GROUP_MEMBERS} members")
    return ids


def _membership(conn: sqlite3.Connection, user: AuthUser, group_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT g.*, m.last_read_id FROM message_groups g JOIN message_group_members m "
        "ON m.group_id = g.id WHERE g.id = ? AND m.user_id = ?", (group_id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Group not found")
    return row


def _detail(conn: sqlite3.Connection, group: sqlite3.Row) -> GroupDetail:
    members = conn.execute(
        "SELECT u.id, u.display_name, u.role, u.username, u.moodle_user_id "
        "FROM message_group_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.group_id = ? ORDER BY u.id IS NOT ?, m.joined_at, u.username, u.id",
        (group["id"], group["owner_id"]),
    ).fetchall()
    return GroupDetail(
        id=group["id"], name=group["name"], owner_id=group["owner_id"],
        created_at=group["created_at"], members=[_contact(row) for row in members],
    )


def _group_message(row: sqlite3.Row) -> GroupMessage:
    return GroupMessage(
        id=row["id"], group_id=row["group_id"], sender_id=row["sender_id"],
        sender_name=row["sender_name"], text=row["text"], created_at=row["created_at"],
        is_deleted=row["deleted_at"] is not None,
    )


def _mark_group_read(conn: sqlite3.Connection, user_id: int, group_id: int) -> None:
    conn.execute(
        "UPDATE message_group_members SET last_read_id = "
        "(SELECT COALESCE(MAX(id), 0) FROM group_messages WHERE group_id = ?) "
        "WHERE group_id = ? AND user_id = ?", (group_id, group_id, user_id),
    )


def group_unread_count(user_id: int) -> int:
    with _db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM group_messages gm JOIN message_group_members m "
            "ON m.group_id = gm.group_id AND m.user_id = ? "
            "WHERE gm.id > m.last_read_id AND gm.sender_id != ? AND gm.deleted_at IS NULL",
            (user_id, user_id),
        ).fetchone()[0]


@router.get("/message-groups", response_model=list[GroupSummary])
def list_groups(user: AuthUser = Depends(get_current_user)) -> list[GroupSummary]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT g.id, g.name, g.owner_id, g.created_at, "
            "(SELECT COUNT(*) FROM message_group_members c "
            "WHERE c.group_id = g.id) AS member_count, "
            "l.text AS preview, l.created_at AS last_at, "
            "(SELECT COUNT(*) FROM group_messages u WHERE u.group_id = g.id "
            "AND u.id > m.last_read_id AND u.sender_id != m.user_id "
            "AND u.deleted_at IS NULL) AS unread_count "
            "FROM message_groups g "
            "JOIN message_group_members m ON m.group_id = g.id AND m.user_id = ? "
            "LEFT JOIN group_messages l ON l.id = "
            "(SELECT MAX(id) FROM group_messages WHERE group_id = g.id) "
            "ORDER BY COALESCE(l.created_at, g.created_at) DESC, g.id DESC", (user.id,),
        ).fetchall()
    return [GroupSummary(
        id=row["id"], name=row["name"], owner_id=row["owner_id"],
        member_count=row["member_count"], last_message_preview=(row["preview"] or "")[:200],
        last_at=row["last_at"] or row["created_at"], unread_count=row["unread_count"],
    ) for row in rows]


@router.post("/message-groups", response_model=GroupDetail, status_code=201)
def create_group(body: GroupCreate, user: AuthUser = Depends(get_current_user)) -> GroupDetail:
    member_ids = _new_member_ids(user, body.member_ids, {user.id})
    now = time.time()
    with _db(write=True) as conn:
        group_id = conn.execute(
            "INSERT INTO message_groups (name, owner_id, created_at) VALUES (?, ?, ?)",
            (body.name, user.id, now),
        ).lastrowid
        conn.executemany(
            "INSERT INTO message_group_members (group_id, user_id, joined_at) VALUES (?, ?, ?)",
            [(group_id, member_id, now) for member_id in (user.id, *member_ids)],
        )
        detail = _detail(conn, _membership(conn, user, group_id))
    for member_id in member_ids:
        create_notification(
            member_id, f"{user.display_name} 將您加入群組「{body.name}」", "", "group_message",
            f"/message-groups/{group_id}",
        )
    return detail


@router.get("/message-groups/{group_id}", response_model=GroupDetail)
def get_group(
    group_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user),
) -> GroupDetail:
    with _db() as conn:
        return _detail(conn, _membership(conn, user, group_id))


@router.post("/message-groups/{group_id}/members", response_model=GroupDetail)
def add_members(
    body: MembersAdd, group_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user),
) -> GroupDetail:
    with _db() as conn:
        group = _membership(conn, user, group_id)
        existing = {row[0] for row in conn.execute(
            "SELECT user_id FROM message_group_members WHERE group_id = ?", (group_id,),
        )}
    if group["owner_id"] != user.id:
        raise HTTPException(403, "Only the group owner can add members")
    member_ids = _new_member_ids(user, body.user_ids, existing)
    now = time.time()
    with _db(write=True) as conn:
        # New members start with the existing history marked read.
        conn.executemany(
            "INSERT OR IGNORE INTO message_group_members "
            "(group_id, user_id, joined_at, last_read_id) VALUES (?, ?, ?, "
            "(SELECT COALESCE(MAX(id), 0) FROM group_messages WHERE group_id = ?))",
            [(group_id, member_id, now, group_id) for member_id in member_ids],
        )
        detail = _detail(conn, _membership(conn, user, group_id))
    for member_id in member_ids:
        create_notification(
            member_id, f"{user.display_name} 將您加入群組「{group['name']}」", "", "group_message",
            f"/message-groups/{group_id}",
        )
    return detail


@router.delete("/message-groups/{group_id}/members/me")
def leave_group(group_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        group = _membership(conn, user, group_id)
        conn.execute(
            "DELETE FROM message_group_members WHERE group_id = ? AND user_id = ?",
            (group_id, user.id),
        )
        conn.execute(
            "DELETE FROM message_stars WHERE user_id = ? AND kind = 'group' AND message_id IN "
            "(SELECT id FROM group_messages WHERE group_id = ?)", (user.id, group_id),
        )
        if group["owner_id"] == user.id:
            conn.execute(
                "UPDATE message_groups SET owner_id = (SELECT user_id FROM message_group_members "
                "WHERE group_id = ? ORDER BY joined_at, user_id LIMIT 1) WHERE id = ?",
                (group_id, group_id),
            )
    return {"left": True, "group_id": group_id}


@router.get("/message-groups/{group_id}/messages", response_model=GroupHistory)
def get_group_history(
    group_id: int = Path(ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(get_current_user),
) -> GroupHistory:
    with _db(write=True) as conn:
        group = _membership(conn, user, group_id)
        _mark_group_read(conn, user.id, group_id)
        total = conn.execute(
            "SELECT COUNT(*) FROM group_messages WHERE group_id = ?", (group_id,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT gm.*, u.display_name AS sender_name FROM group_messages gm "
            "JOIN users u ON u.id = gm.sender_id WHERE gm.group_id = ? "
            "ORDER BY gm.id DESC LIMIT ? OFFSET ?", (group_id, limit, offset),
        ).fetchall()
        detail = _detail(conn, group)
    return GroupHistory(
        group=detail, messages=[_group_message(row) for row in reversed(rows)],
        total=total, limit=limit, offset=offset, has_more=offset + len(rows) < total,
    )


@router.post("/message-groups/{group_id}/messages", response_model=GroupMessage, status_code=201)
def send_group_message(
    body: MessageCreate, group_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user),
) -> GroupMessage:
    with _db(write=True) as conn:
        group = _membership(conn, user, group_id)
        message_id = conn.execute(
            "INSERT INTO group_messages (group_id, sender_id, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (group_id, user.id, body.text, time.time()),
        ).lastrowid
        _mark_group_read(conn, user.id, group_id)
        row = conn.execute(
            "SELECT gm.*, u.display_name AS sender_name FROM group_messages gm "
            "JOIN users u ON u.id = gm.sender_id WHERE gm.id = ?", (message_id,),
        ).fetchone()
        recipients = [r[0] for r in conn.execute(
            "SELECT user_id FROM message_group_members WHERE group_id = ? AND user_id != ?",
            (group_id, user.id),
        )]
    for recipient in recipients:
        create_notification(
            recipient, f"{user.display_name} 在「{group['name']}」傳來新訊息", body.text,
            "group_message", f"/message-groups/{group_id}",
        )
    return _group_message(row)


@router.delete("/message-groups/{group_id}/messages/{message_id}")
def delete_group_message(
    group_id: int = Path(ge=1), message_id: int = Path(ge=1),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    with _db(write=True) as conn:
        _membership(conn, user, group_id)
        row = conn.execute(
            "SELECT id FROM group_messages WHERE id = ? AND group_id = ? AND sender_id = ?",
            (message_id, group_id, user.id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Message not found")
        conn.execute(
            "UPDATE group_messages SET text = '', deleted_at = ? "
            "WHERE id = ? AND deleted_at IS NULL", (time.time(), message_id),
        )
    return {"deleted": True, "id": message_id}


def _visible_direct(conn: sqlite3.Connection, user: AuthUser, message_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM direct_messages WHERE id = ? AND (sender_id = ? OR recipient_id = ?)",
        (message_id, user.id, user.id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Message not found")


def _visible_group(
    conn: sqlite3.Connection, user: AuthUser, group_id: int, message_id: int,
) -> None:
    _membership(conn, user, group_id)
    row = conn.execute(
        "SELECT 1 FROM group_messages WHERE id = ? AND group_id = ?", (message_id, group_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Message not found")


def _set_star(
    conn: sqlite3.Connection, user: AuthUser, kind: str, message_id: int, starred: bool,
) -> dict:
    if starred:
        conn.execute(
            "INSERT OR IGNORE INTO message_stars (user_id, kind, message_id, starred_at) "
            "VALUES (?, ?, ?, ?)", (user.id, kind, message_id, time.time()),
        )
    else:
        conn.execute(
            "DELETE FROM message_stars WHERE user_id = ? AND kind = ? AND message_id = ?",
            (user.id, kind, message_id),
        )
    return {"kind": kind, "message_id": message_id, "starred": starred}


@router.put("/messages/{message_id}/star")
def star_direct(message_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _visible_direct(conn, user, message_id)
        return _set_star(conn, user, "direct", message_id, True)


@router.delete("/messages/{message_id}/star")
def unstar_direct(message_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _visible_direct(conn, user, message_id)
        return _set_star(conn, user, "direct", message_id, False)


@router.put("/message-groups/{group_id}/messages/{message_id}/star")
def star_group(
    group_id: int = Path(ge=1), message_id: int = Path(ge=1),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    with _db(write=True) as conn:
        _visible_group(conn, user, group_id, message_id)
        return _set_star(conn, user, "group", message_id, True)


@router.delete("/message-groups/{group_id}/messages/{message_id}/star")
def unstar_group(
    group_id: int = Path(ge=1), message_id: int = Path(ge=1),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    with _db(write=True) as conn:
        _visible_group(conn, user, group_id, message_id)
        return _set_star(conn, user, "group", message_id, False)


@router.get("/messages/starred", response_model=list[StarredMessage])
def list_starred(user: AuthUser = Depends(get_current_user)) -> list[StarredMessage]:
    with _db() as conn:
        direct = conn.execute(
            "SELECT d.*, s.starred_at, su.display_name AS sender_name, "
            "p.id AS peer_id, p.display_name AS peer_display_name, p.role AS peer_role, "
            "p.username AS peer_username, p.moodle_user_id AS peer_moodle_user_id "
            "FROM message_stars s JOIN direct_messages d ON d.id = s.message_id "
            "JOIN users su ON su.id = d.sender_id "
            "JOIN users p ON p.id = "
            "CASE WHEN d.sender_id = ? THEN d.recipient_id ELSE d.sender_id END "
            "WHERE s.user_id = ? AND s.kind = 'direct' AND (d.sender_id = ? OR d.recipient_id = ?)",
            (user.id, user.id, user.id, user.id),
        ).fetchall()
        group = conn.execute(
            "SELECT gm.*, s.starred_at, su.display_name AS sender_name, g.name AS group_name "
            "FROM message_stars s JOIN group_messages gm ON gm.id = s.message_id "
            "JOIN message_groups g ON g.id = gm.group_id JOIN users su ON su.id = gm.sender_id "
            "JOIN message_group_members m ON m.group_id = gm.group_id AND m.user_id = s.user_id "
            "WHERE s.user_id = ? AND s.kind = 'group'", (user.id,),
        ).fetchall()
    items = [StarredMessage(
        kind="direct", message_id=row["id"], sender_id=row["sender_id"],
        sender_name=row["sender_name"], text=row["text"], created_at=row["created_at"],
        starred_at=row["starred_at"], is_deleted=row["deleted_at"] is not None,
        peer=_contact({key: row[f"peer_{key}"] for key in (
            "id", "display_name", "role", "username", "moodle_user_id",
        )}),
    ) for row in direct] + [StarredMessage(
        kind="group", message_id=row["id"], sender_id=row["sender_id"],
        sender_name=row["sender_name"], text=row["text"], created_at=row["created_at"],
        starred_at=row["starred_at"], is_deleted=row["deleted_at"] is not None,
        group_id=row["group_id"], group_name=row["group_name"],
    ) for row in group]
    return sorted(items, key=lambda item: (-item.starred_at, item.kind, -item.message_id))


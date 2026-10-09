"""Private direct messages and scoped presence in the auth SQLite database.

Message and presence IDs refer to users.id, never Moodle enrollment IDs.
History pages select newest first and return each page in chronological order.
Reading a conversation marks all its incoming messages read. Soft-deleted
messages remain as empty tombstones and do not contribute to unread counts.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, courses
from .auth import AuthUser, get_current_user
from .notifications import create_notification

router = APIRouter(tags=["messaging"])

_SCHEMA = """
CREATE TABLE IF NOT EXISTS direct_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    recipient_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL CHECK(length(text) <= 2000),
    created_at REAL NOT NULL,
    read_at REAL,
    deleted_at REAL,
    demo_key TEXT UNIQUE,
    CHECK(sender_id != recipient_id)
);
CREATE INDEX IF NOT EXISTS ix_dm_pair
    ON direct_messages(sender_id, recipient_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_dm_unread
    ON direct_messages(recipient_id, read_at, deleted_at);
CREATE TABLE IF NOT EXISTS message_presence (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    last_seen REAL NOT NULL
);
"""


@contextmanager
def _db(*, write: bool = False):
    with auth._db() as conn:  # noqa: SLF001
        conn.execute("PRAGMA foreign_keys = ON")
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


def init_db() -> None:
    """Optional initializer; all routes create this module's tables lazily."""
    with _db():
        pass


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class Contact(BaseModel):
    user_id: int
    display_name: str
    role: auth.Role
    username: str
    moodle_user_id: int | None


class Message(BaseModel):
    id: int
    sender_id: int
    recipient_id: int
    text: str
    created_at: float
    read_at: float | None
    deleted_at: float | None
    is_deleted: bool


class Conversation(BaseModel):
    peer: Contact
    last_message_preview: str
    unread_count: int
    last_at: float


class MessageHistory(BaseModel):
    peer: Contact
    messages: list[Message]
    total: int
    limit: int
    offset: int
    has_more: bool


class Presence(BaseModel):
    user_id: int
    last_seen: float | None
    online: bool


def _contact(row: sqlite3.Row | dict) -> Contact:
    return Contact(
        user_id=row["id"], display_name=row["display_name"], role=row["role"],
        username=row["username"], moodle_user_id=row["moodle_user_id"],
    )


def _course_members(course_id: str) -> list[Contact]:
    # Match courses.course_participants without importing the app or memory DB.
    with auth._db() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT id, display_name, role, username, moodle_user_id FROM users u "
            "WHERE (role = 'teacher' AND username = ?) OR "
            "(role = 'student' AND EXISTS (SELECT 1 FROM chat_sessions s "
            "WHERE s.course_id = ? AND s.moodle_user_id = u.moodle_user_id)) "
            "ORDER BY username, id",
            (courses._teacher_username(course_id), course_id),  # noqa: SLF001
        ).fetchall()
    return [_contact(row) for row in rows]


def _contacts(user: AuthUser) -> list[Contact]:
    members = {}
    for course_id in courses._visible_course_ids(user):  # noqa: SLF001
        for member in _course_members(course_id):
            if member.user_id != user.id:
                members[member.user_id] = member
    return sorted(members.values(), key=lambda member: (member.username, member.user_id))


def _peer(user: AuthUser, peer_user_id: int, *, sending: bool = False) -> Contact:
    if peer_user_id == user.id:
        raise HTTPException(422, "Cannot message yourself")
    row = auth.get_user_by_id(peer_user_id)
    if row is None:
        raise HTTPException(404, "User not found")
    # Existing personal conversations remain readable after enrollment changes.
    # New sends always require current course membership.
    if not sending:
        with _db() as conn:
            existing = conn.execute(
                "SELECT 1 FROM direct_messages WHERE "
                "(sender_id = ? AND recipient_id = ?) OR "
                "(sender_id = ? AND recipient_id = ?) LIMIT 1",
                (user.id, peer_user_id, peer_user_id, user.id),
            ).fetchone()
        if existing is not None:
            return _contact(row)
    if peer_user_id not in {member.user_id for member in _contacts(user)}:
        raise HTTPException(403, "User is outside your course contacts")
    return _contact(row)


def _message(row: sqlite3.Row) -> Message:
    return Message(
        **{key: row[key] for key in Message.model_fields if key != "is_deleted"},
        is_deleted=row["deleted_at"] is not None,
    )


def _mark_read(conn: sqlite3.Connection, user_id: int, peer_user_id: int) -> int:
    return conn.execute(
        "UPDATE direct_messages SET read_at = ? WHERE recipient_id = ? "
        "AND sender_id = ? AND read_at IS NULL AND deleted_at IS NULL",
        (time.time(), user_id, peer_user_id),
    ).rowcount


@router.get("/messages/contacts", response_model=list[Contact])
def list_contacts(user: AuthUser = Depends(get_current_user)) -> list[Contact]:
    return _contacts(user)


@router.get("/messages/unread-count")
def unread_count(user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM direct_messages WHERE recipient_id = ? "
            "AND read_at IS NULL AND deleted_at IS NULL", (user.id,),
        ).fetchone()[0]
    return {"unread_count": count}


@router.get("/messages/conversations", response_model=list[Conversation])
def list_conversations(user: AuthUser = Depends(get_current_user)) -> list[Conversation]:
    with _db() as conn:
        rows = conn.execute(
            "WITH mine AS (SELECT *, CASE WHEN sender_id = ? THEN recipient_id "
            "ELSE sender_id END AS peer_id FROM direct_messages "
            "WHERE sender_id = ? OR recipient_id = ?), "
            "ranked AS (SELECT *, ROW_NUMBER() OVER "
            "(PARTITION BY peer_id ORDER BY created_at DESC, id DESC) AS rn, "
            "SUM(CASE WHEN recipient_id = ? AND read_at IS NULL "
            "AND deleted_at IS NULL THEN 1 ELSE 0 END) OVER "
            "(PARTITION BY peer_id) AS unread_count FROM mine) "
            "SELECT r.text, r.created_at, r.unread_count, "
            "u.id, u.display_name, u.role, u.username, u.moodle_user_id "
            "FROM ranked r JOIN users u ON u.id = r.peer_id WHERE r.rn = 1 "
            "ORDER BY r.created_at DESC, r.id DESC",
            (user.id, user.id, user.id, user.id),
        ).fetchall()
    return [Conversation(
        peer=_contact(row), last_message_preview=row["text"][:200],
        unread_count=row["unread_count"], last_at=row["created_at"],
    ) for row in rows]


@router.get("/messages/conversations/{peer_user_id}", response_model=MessageHistory)
def get_history(
    peer_user_id: int = Path(ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(get_current_user),
) -> MessageHistory:
    peer = _peer(user, peer_user_id)
    with _db(write=True) as conn:
        _mark_read(conn, user.id, peer_user_id)
        pair = (user.id, peer_user_id, peer_user_id, user.id)
        where = "(sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)"
        total = conn.execute(
            f"SELECT COUNT(*) FROM direct_messages WHERE {where}", pair,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM direct_messages WHERE {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (*pair, limit, offset),
        ).fetchall()
    return MessageHistory(
        peer=peer, messages=[_message(row) for row in reversed(rows)],
        total=total, limit=limit, offset=offset, has_more=offset + len(rows) < total,
    )


@router.post("/messages/conversations/{peer_user_id}", response_model=Message, status_code=201)
def send_message(
    body: MessageCreate,
    peer_user_id: int = Path(ge=1),
    user: AuthUser = Depends(get_current_user),
) -> Message:
    _peer(user, peer_user_id, sending=True)
    with _db(write=True) as conn:
        cur = conn.execute(
            "INSERT INTO direct_messages (sender_id, recipient_id, text, created_at) "
            "VALUES (?, ?, ?, ?)", (user.id, peer_user_id, body.text, time.time()),
        )
        row = conn.execute(
            "SELECT * FROM direct_messages WHERE id = ?", (cur.lastrowid,),
        ).fetchone()
    create_notification(
        peer_user_id, f"Message from {user.display_name}", body.text, "direct_message",
        f"/messages/conversations/{user.id}",
    )
    return _message(row)


@router.post("/messages/conversations/{peer_user_id}/read")
def read_conversation(
    peer_user_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user),
) -> dict:
    _peer(user, peer_user_id)
    with _db(write=True) as conn:
        updated = _mark_read(conn, user.id, peer_user_id)
    return {"updated_count": updated, "unread_count": 0}


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int = Path(ge=1), user: AuthUser = Depends(get_current_user),
) -> dict:
    with _db(write=True) as conn:
        row = conn.execute(
            "SELECT id FROM direct_messages WHERE id = ? AND sender_id = ?",
            (message_id, user.id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Message not found")
        conn.execute(
            "UPDATE direct_messages SET text = '', deleted_at = ? "
            "WHERE id = ? AND deleted_at IS NULL", (time.time(), message_id),
        )
    return {"deleted": True, "id": message_id}


def _presence(user_ids: list[int]) -> list[Presence]:
    if not user_ids:
        return []
    now = time.time()
    with _db() as conn:
        placeholders = ",".join("?" for _ in user_ids)
        seen = dict(conn.execute(
            f"SELECT user_id, last_seen FROM message_presence WHERE user_id IN ({placeholders})",
            user_ids,
        ).fetchall())
    return [Presence(
        user_id=user_id, last_seen=seen.get(user_id),
        online=user_id in seen and 0 <= now - seen[user_id] <= 120,
    ) for user_id in user_ids]


@router.post("/presence/heartbeat", response_model=Presence)
def heartbeat(user: AuthUser = Depends(get_current_user)) -> Presence:
    now = time.time()
    with _db(write=True) as conn:
        conn.execute(
            "INSERT INTO message_presence (user_id, last_seen) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen",
            (user.id, now),
        )
    return Presence(user_id=user.id, last_seen=now, online=True)


@router.get("/presence", response_model=list[Presence])
def get_presence(
    user_ids: str = Query(min_length=1, max_length=2048),
    user: AuthUser = Depends(get_current_user),
) -> list[Presence]:
    try:
        ids = list(dict.fromkeys(int(part.strip()) for part in user_ids.split(",")))
    except ValueError as exc:
        raise HTTPException(422, "user_ids must be comma-separated positive integers") from exc
    if len(ids) > 100 or any(user_id <= 0 for user_id in ids):
        raise HTTPException(422, "Provide 1-100 positive user IDs")
    allowed = {user.id, *(member.user_id for member in _contacts(user))}
    if not set(ids) <= allowed:
        raise HTTPException(403, "Presence is limited to your course contacts")
    return _presence(ids)


@router.get("/presence/course/{course_id}", response_model=list[Presence])
def course_presence(
    course_id: str, user: AuthUser = Depends(get_current_user),
) -> list[Presence]:
    courses._check_course_access(user, course_id)  # noqa: SLF001
    return _presence([member.user_id for member in _course_members(course_id)])


def seed_demo_messages() -> int:
    """Seed existing, enrolled demo accounts; return the number of new messages.

    Call after demo users and chat-session enrollment are seeded. No accounts or
    enrollments are created. Unique demo keys preserve deletions and read state
    on repeated calls. Seed messages do not generate duplicate notifications.
    """
    demos = [
        ("student1001", "teacher", "老師您好，請問作業可以補充解題步驟嗎？"),
        ("teacher", "student1001", "可以，請把思考過程一起寫下來。"),
        ("student1002", "teacher", "謝謝老師今天的說明！"),
        ("student1001", "student1002", "我們一起複習今天的課程吧。"),
        ("student1003", "teacher_huang", "老師您好，我想請教課程專題。"),
    ]
    inserted = 0
    for index, (sender_name, recipient_name, text) in enumerate(demos):
        sender = auth.get_user_by_username(sender_name)
        recipient = auth.get_user_by_username(recipient_name)
        if sender is None or recipient is None:
            continue
        user = auth._row_to_user(sender)  # noqa: SLF001
        if recipient["id"] not in {member.user_id for member in _contacts(user)}:
            continue
        with _db(write=True) as conn:
            inserted += conn.execute(
                "INSERT INTO direct_messages "
                "(sender_id, recipient_id, text, created_at, demo_key) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(demo_key) DO NOTHING",
                (user.id, recipient["id"], text, time.time() - (len(demos) - index) * 60,
                 f"demo-message-{index}"),
            ).rowcount
    return inserted

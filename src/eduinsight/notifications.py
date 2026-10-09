"""Private notifications in a separate table in settings.auth_db_path."""

from __future__ import annotations

import time
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth
from .auth import AuthUser, get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    kind TEXT NOT NULL,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0, 1)),
    created_at REAL NOT NULL,
    demo_key TEXT,
    UNIQUE(user_id, demo_key)
);
CREATE INDEX IF NOT EXISTS ix_notifications_user_created
    ON notifications(user_id, created_at DESC, id DESC);
"""


@contextmanager
def _db():
    with auth._db() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        conn.commit()
        yield conn


def init_db() -> None:
    """Initialize this module's table; routes also initialize it lazily."""
    with _db():
        pass


class NotificationContent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=5000)
    kind: str = Field(min_length=1, max_length=64)
    link: str | None = Field(default=None, max_length=2048)


class Notification(NotificationContent):
    id: int
    user_id: int
    is_read: bool
    created_at: float


class NotificationList(BaseModel):
    notifications: list[Notification]
    unread_count: int


def create_notification(
    user_id: int, title: str, body: str, kind: str, link: str | None = None,
) -> dict:
    """Create an unread notification for an auth users.id (not a Moodle ID).

    Returns the notification. The user must already exist in the auth database.
    Links may be relative frontend paths; this helper is internal, not an API.
    """
    content = NotificationContent(title=title, body=body, kind=kind, link=link)
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (user_id, title, body, kind, link, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, content.title, content.body, content.kind, content.link, time.time()),
        )
        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.commit()
    return Notification.model_validate(dict(row)).model_dump()


def seed_demo_notifications() -> int:
    """Seed three notifications per existing demo account; return inserted count.

    Call after auth.seed_demo_users(). Repeated calls preserve read state and
    do not duplicate notifications. Legacy demo links are repaired without
    changing read state or timestamps. This does not create or change any users.
    """
    usernames = [*auth.TEACHER_COURSE_MAP, *(f"student{i}" for i in range(1001, 1006))]
    demos = [
        ("assignment_due", "Assignment due", "Your next assignment is due soon.", "/my"),
        ("grade_released", "Grade released", "A new grade is available.", "/analytics"),
        ("ai_tip", "AI study tip", "Review one difficult concept with your AI tutor.",
         "/ai-assistant"),
    ]
    inserted = 0
    with _db() as conn:
        for username in usernames:
            user = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if user is None:
                continue
            for kind, title, body, link in demos:
                cur = conn.execute(
                    "INSERT INTO notifications "
                    "(user_id, title, body, kind, link, created_at, demo_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_id, demo_key) DO NOTHING",
                    (user["id"], title, body, kind, link, time.time(), kind),
                )
                inserted += cur.rowcount
                conn.execute(
                    "UPDATE notifications SET link = ? WHERE user_id = ? AND demo_key = ? "
                    "AND link IN ('/assignments', '/grades', '/chat')",
                    (link, user["id"], kind),
                )
        conn.commit()
    return inserted


@router.get("", response_model=NotificationList)
async def list_notifications(user: AuthUser = Depends(get_current_user)) -> NotificationList:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user.id,),
        ).fetchall()
    items = [Notification.model_validate(dict(row)) for row in rows]
    return NotificationList(notifications=items, unread_count=sum(not n.is_read for n in items))


@router.post("/read-all")
async def read_all(user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user.id,),
        )
        conn.commit()
    return {"updated_count": cur.rowcount, "unread_count": 0}


@router.post("/{id}/read", response_model=Notification)
async def read_notification(id: int, user: AuthUser = Depends(get_current_user)) -> Notification:
    with _db() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (id, user.id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Notification not found")
        row = conn.execute(
            "SELECT * FROM notifications WHERE id = ? AND user_id = ?", (id, user.id),
        ).fetchone()
        conn.commit()
    return Notification.model_validate(dict(row))


@router.delete("/{id}")
async def delete_notification(id: int, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        cur = conn.execute("DELETE FROM notifications WHERE id = ? AND user_id = ?", (id, user.id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Notification not found")
        conn.commit()
    return {"deleted": True, "id": id}

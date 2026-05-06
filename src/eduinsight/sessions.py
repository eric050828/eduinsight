"""Per-course chat sessions for EduInsight.

Each (student, course) has multiple "agents-with-history" sessions, like
ChatGPT's left sidebar. A session groups its own message thread; the
student can switch between sessions inside the same course.

This module owns its own SQLite table colocated with eduinsight_auth.db
to avoid touching Lite-Mem's schema (memory remains a third-party dep).
The actual messages live in Lite-Mem's `messages` table — we only
manage the session metadata + course_id mapping here.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings


def _ensure_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _db():
    _ensure_dir(settings.auth_db_path)
    conn = sqlite3.connect(settings.auth_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_sessions_table() -> None:
    """Create the sessions table if missing. Idempotent."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id    TEXT PRIMARY KEY,
                moodle_user_id INTEGER NOT NULL,
                course_id     TEXT NOT NULL,
                title         TEXT NOT NULL,
                created_at    REAL NOT NULL,
                last_msg_at   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_sessions_user_course
                ON chat_sessions(moodle_user_id, course_id, last_msg_at DESC);
            """
        )
        conn.commit()


def create_session(
    moodle_user_id: int,
    course_id: str,
    title: str = "",
) -> dict[str, Any]:
    sid = f"chat-{course_id}-{moodle_user_id}-{int(time.time() * 1000)}"
    title = title or "新對話"
    now = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (session_id, moodle_user_id, course_id, title, created_at, last_msg_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, moodle_user_id, course_id, title, now, now),
        )
        conn.commit()
    return {
        "session_id": sid,
        "moodle_user_id": moodle_user_id,
        "course_id": course_id,
        "title": title,
        "created_at": now,
        "last_msg_at": now,
    }


def list_sessions(moodle_user_id: int, course_id: str) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions WHERE moodle_user_id = ? AND course_id = ? "
            "ORDER BY last_msg_at DESC",
            (moodle_user_id, course_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def touch_session(session_id: str) -> None:
    """Update last_msg_at timestamp when a new message arrives."""
    with _db() as conn:
        conn.execute(
            "UPDATE chat_sessions SET last_msg_at = ? WHERE session_id = ?",
            (time.time(), session_id),
        )
        conn.commit()


def rename_session(session_id: str, title: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE chat_sessions SET title = ? WHERE session_id = ?",
            (title, session_id),
        )
        conn.commit()


def delete_session(session_id: str) -> None:
    with _db() as conn:
        conn.execute(
            "DELETE FROM chat_sessions WHERE session_id = ?", (session_id,)
        )
        conn.commit()

"""Authenticated course discussions and indexed-material ZIP exports.

Forum tables live in settings.auth_db_path. Authors are auth users.id, whereas
enrollment uses Moodle IDs. Call seed_demo_forum after users and enrollment.
"""

from __future__ import annotations

import io
import sqlite3
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import AuthUser, TEACHER_COURSE_MAP, get_current_user
from .config import settings
from .courses import COURSE_CATALOG
from .notifications import create_notification

router = APIRouter(tags=["forum"])


def _visible_course_ids(user: AuthUser) -> set[str]:
    # Read enrollment directly: the catalog helper may initialize/write tables,
    # which would deadlock when called inside a forum write transaction.
    if user.role == "teacher":
        owned = TEACHER_COURSE_MAP.get(user.username)
        return {owned} if owned else set()
    conn = sqlite3.connect(settings.auth_db_path, timeout=30)
    try:
        if user.role == "admin":
            ids = set(COURSE_CATALOG)
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='course_catalog'").fetchone():
                ids.update(row[0] for row in conn.execute("SELECT id FROM course_catalog"))
            return ids
        if user.moodle_user_id is None:
            return set()
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_sessions'").fetchone():
            return set()
        return {row[0] for row in conn.execute(
            "SELECT DISTINCT course_id FROM chat_sessions WHERE moodle_user_id=?",
            (user.moodle_user_id,))}
    finally:
        conn.close()


def _check_course_access(user: AuthUser, course_id: str) -> None:
    # Preserve the explicit forum policy even if catalog teacher assignments
    # change: teachers are scoped strictly by TEACHER_COURSE_MAP.
    if user.role == "admin":
        if course_id not in _visible_course_ids(user):
            raise HTTPException(404, "Course not found")
    elif course_id not in _visible_course_ids(user):
        raise HTTPException(403, "Course access denied")


class PostBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Body cannot be blank")
        return value


class ThreadBody(PostBody):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def title_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()


class ThreadPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def valid_text(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("Fields cannot be null or blank")
        return value


class PinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pinned: bool = True


@contextmanager
def _db(*, write: bool = False):
    Path(settings.auth_db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.auth_db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS forum_threads (
                id TEXT PRIMARY KEY, course_id TEXT NOT NULL,
                author_id INTEGER NOT NULL, author_name TEXT NOT NULL,
                author_role TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_forum_threads_course ON forum_threads(course_id);
            CREATE TABLE IF NOT EXISTS forum_posts (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
                author_id INTEGER NOT NULL, author_name TEXT NOT NULL,
                author_role TEXT NOT NULL, body TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_forum_posts_thread ON forum_posts(thread_id);
            CREATE TABLE IF NOT EXISTS forum_thread_subscriptions (
                thread_id TEXT NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY(thread_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS forum_course_subscriptions (
                course_id TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY(course_id, user_id)
            );
        """)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _thread(conn, thread_id: str, user: AuthUser) -> dict:
    row = conn.execute("SELECT * FROM forum_threads WHERE id=?", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Thread not found")
    _check_course_access(user, row["course_id"])
    return dict(row)


def _post(conn, post_id: str, user: AuthUser) -> dict:
    row = conn.execute("SELECT * FROM forum_posts WHERE id=?", (post_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Post not found")
    _thread(conn, row["thread_id"], user)
    return dict(row)


def _owner(item: dict, user: AuthUser, *, delete: bool = False):
    if item["author_id"] != user.id and not (delete and user.role in ("teacher", "admin")):
        raise HTTPException(403, "Only the author may edit; course staff may delete")


def _view(conn, thread: dict, user: AuthUser) -> dict:
    result = dict(thread)
    result["pinned"] = bool(result["pinned"])
    count, last = conn.execute(
        "SELECT COUNT(*), MAX(updated_at) FROM forum_posts WHERE thread_id=?",
        (thread["id"],),
    ).fetchone()
    result["post_count"] = count
    result["last_activity"] = max(thread["updated_at"], last or thread["updated_at"])
    result["subscribed"] = conn.execute(
        "SELECT 1 FROM forum_thread_subscriptions WHERE thread_id=? AND user_id=?",
        (thread["id"], user.id),
    ).fetchone() is not None
    return result


def _notify(recipients: list[int], thread: dict, author: AuthUser, body: str, kind: str):
    # Recheck enrollment/teacher mapping: a stale subscription must not leak text.
    from .auth import _row_to_user, get_user_by_id

    for user_id in recipients:
        if user_id == author.id:
            continue
        row = get_user_by_id(user_id)
        if row is None:
            continue
        try:
            _check_course_access(_row_to_user(row), thread["course_id"])
        except HTTPException:
            continue
        create_notification(user_id, thread["title"], body[:5000], kind,
                            f"/forum/threads/{thread['id']}")


@router.get("/courses/{course_id}/forum/threads")
def list_threads(course_id: str, user: AuthUser = Depends(get_current_user)) -> list[dict]:
    _check_course_access(user, course_id)
    with _db() as conn:
        rows = conn.execute("SELECT * FROM forum_threads WHERE course_id=?", (course_id,)).fetchall()
        items = [_view(conn, dict(row), user) for row in rows]
    return sorted(items, key=lambda t: (t["pinned"], t["last_activity"], t["id"]), reverse=True)


@router.post("/courses/{course_id}/forum/threads", status_code=201)
def create_thread(course_id: str, body: ThreadBody,
                  user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    thread_id, now = f"thread-{uuid.uuid4().hex}", time.time()
    with _db(write=True) as conn:
        conn.execute("INSERT INTO forum_threads VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                     (thread_id, course_id, user.id, user.display_name, user.role,
                      body.title, body.body, now, now))
        conn.execute("INSERT INTO forum_thread_subscriptions VALUES (?, ?)", (thread_id, user.id))
        recipients = [r[0] for r in conn.execute(
            "SELECT user_id FROM forum_course_subscriptions WHERE course_id=?", (course_id,))]
        result = _view(conn, _thread(conn, thread_id, user), user)
    _notify(recipients, result, user, body.body, "forum_thread")
    return result


@router.get("/forum/threads/{thread_id}")
def thread_detail(thread_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        thread = _view(conn, _thread(conn, thread_id, user), user)
        posts = [dict(row) for row in conn.execute(
            "SELECT * FROM forum_posts WHERE thread_id=? ORDER BY created_at, id", (thread_id,))]
    return {"thread": thread, "posts": posts}


@router.post("/forum/threads/{thread_id}/posts", status_code=201)
def create_post(thread_id: str, body: PostBody,
                user: AuthUser = Depends(get_current_user)) -> dict:
    post_id, now = f"post-{uuid.uuid4().hex}", time.time()
    with _db(write=True) as conn:
        thread = _thread(conn, thread_id, user)
        conn.execute("INSERT INTO forum_posts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (post_id, thread_id, user.id, user.display_name, user.role, body.body, now, now))
        recipients = [r[0] for r in conn.execute(
            "SELECT user_id FROM forum_thread_subscriptions WHERE thread_id=?", (thread_id,))]
        result = _post(conn, post_id, user)
    _notify(recipients, thread, user, body.body, "forum_post")
    return result


@router.patch("/forum/threads/{thread_id}")
def edit_thread(thread_id: str, body: ThreadPatch,
                user: AuthUser = Depends(get_current_user)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    with _db(write=True) as conn:
        _owner(_thread(conn, thread_id, user), user)
        if changes:
            changes["updated_at"] = time.time()
            conn.execute(f"UPDATE forum_threads SET {', '.join(k + '=?' for k in changes)} WHERE id=?",
                         (*changes.values(), thread_id))
        return _view(conn, _thread(conn, thread_id, user), user)


@router.patch("/forum/posts/{post_id}")
def edit_post(post_id: str, body: PostBody, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _owner(_post(conn, post_id, user), user)
        conn.execute("UPDATE forum_posts SET body=?, updated_at=? WHERE id=?",
                     (body.body, time.time(), post_id))
        return _post(conn, post_id, user)


@router.delete("/forum/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, user: AuthUser = Depends(get_current_user)) -> Response:
    with _db(write=True) as conn:
        _owner(_thread(conn, thread_id, user), user, delete=True)
        conn.execute("DELETE FROM forum_threads WHERE id=?", (thread_id,))
    return Response(status_code=204)


@router.delete("/forum/posts/{post_id}", status_code=204)
def delete_post(post_id: str, user: AuthUser = Depends(get_current_user)) -> Response:
    with _db(write=True) as conn:
        _owner(_post(conn, post_id, user), user, delete=True)
        conn.execute("DELETE FROM forum_posts WHERE id=?", (post_id,))
    return Response(status_code=204)


@router.post("/forum/threads/{thread_id}/pin")
def pin_thread(thread_id: str, body: PinBody | None = None,
               user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _thread(conn, thread_id, user)
        if user.role not in ("teacher", "admin"):
            raise HTTPException(403, "Requires course staff")
        conn.execute("UPDATE forum_threads SET pinned=? WHERE id=?",
                     (int(body.pinned if body else True), thread_id))
        return _view(conn, _thread(conn, thread_id, user), user)


def _subscription(conn, table: str, column: str, resource: str, user: AuthUser,
                  enabled: bool | None) -> dict:
    if enabled is True:
        conn.execute(f"INSERT OR IGNORE INTO {table} VALUES (?, ?)", (resource, user.id))
    elif enabled is False:
        conn.execute(f"DELETE FROM {table} WHERE {column}=? AND user_id=?", (resource, user.id))
    subscribed = conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? AND user_id=?",
                              (resource, user.id)).fetchone() is not None
    return {column: resource, "subscribed": subscribed}


@router.get("/courses/{course_id}/forum/subscription")
def course_subscription(course_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    with _db() as conn:
        return _subscription(conn, "forum_course_subscriptions", "course_id", course_id, user, None)


@router.put("/courses/{course_id}/forum/subscription")
def subscribe_course(course_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    with _db(write=True) as conn:
        return _subscription(conn, "forum_course_subscriptions", "course_id", course_id, user, True)


@router.delete("/courses/{course_id}/forum/subscription")
def unsubscribe_course(course_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    _check_course_access(user, course_id)
    with _db(write=True) as conn:
        return _subscription(conn, "forum_course_subscriptions", "course_id", course_id, user, False)


@router.put("/forum/threads/{thread_id}/subscription")
def subscribe_thread(thread_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _thread(conn, thread_id, user)
        return _subscription(conn, "forum_thread_subscriptions", "thread_id", thread_id, user, True)


@router.delete("/forum/threads/{thread_id}/subscription")
def unsubscribe_thread(thread_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db(write=True) as conn:
        _thread(conn, thread_id, user)
        return _subscription(conn, "forum_thread_subscriptions", "thread_id", thread_id, user, False)


@router.get("/forum/stats/me")
def my_stats(user: AuthUser = Depends(get_current_user)) -> dict:
    courses = sorted(_visible_course_ids(user))
    if not courses:
        return {"threads": 0, "posts": 0}
    marks = ",".join("?" for _ in courses)
    with _db() as conn:
        threads = conn.execute(
            f"SELECT COUNT(*) FROM forum_threads WHERE author_id=? AND course_id IN ({marks})",
            (user.id, *courses)).fetchone()[0]
        posts = conn.execute(
            "SELECT COUNT(*) FROM forum_posts p JOIN forum_threads t ON t.id=p.thread_id "
            f"WHERE p.author_id=? AND t.course_id IN ({marks})", (user.id, *courses)).fetchone()[0]
    return {"threads": threads, "posts": posts}


@router.get("/courses/{course_id}/materials/download-all")
def download_materials(course_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    _check_course_access(user, course_id)
    from . import app as app_module
    from .rag import _course_uid, _parse_tagged_text

    rag = app_module._rag
    if rag is None:
        raise HTTPException(404, "No indexed materials")
    buffer = io.BytesIO()
    included = []
    with rag._material_lock, rag._lock:
        filenames = rag.list_documents(course_id)
        if not filenames:
            raise HTTPException(404, "No indexed materials")
        grouped = {filename: [] for filename in filenames}
        for fact in rag._memory.list(_course_uid(course_id), category="course_material"):
            source, _, heading, _, text = _parse_tagged_text(fact)
            if source in grouped:
                grouped[source].append((f"## {heading}\n\n" if heading else "") + text)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, filename in enumerate(filenames, 1):
                # The upload pipeline deletes originals, retaining only Markdown.
                md_path = app_module._material_markdown_path(course_id, filename)
                content = md_path.read_text(encoding="utf-8") if md_path.is_file() else "\n\n".join(grouped[filename])
                # Numeric prefix avoids filename collisions and ZIP traversal.
                name = f"{index:03d}-{Path(filename).name}.md"
                archive.writestr(name, content)
                included.append(f"{name}: conversion of {filename}")
            archive.writestr("README.txt", "Original uploads are not retained. This archive contains cached Markdown\n"
                             "or text reconstructed from indexed chunks.\n\n" + "\n".join(included) + "\n")
    buffer.seek(0)

    def chunks():
        try:
            while chunk := buffer.read(64 * 1024):
                yield chunk
        finally:
            buffer.close()

    return StreamingResponse(chunks(), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename=\"materials.zip\"; filename*=UTF-8''{quote(course_id + '-materials.zip', safe='')}",
    })


def seed_demo_forum() -> dict[str, int]:
    """Idempotently add two threads with replies per existing mapped teacher.

    Never creates users/enrollments or sends demo notifications. Existing posts,
    edits, subscription choices and pin state are preserved on repeated calls.
    """
    created = replies = 0
    now = time.time()
    with _db(write=True) as conn:
        for username, course_id in TEACHER_COURSE_MAP.items():
            teacher = conn.execute("SELECT * FROM users WHERE username=? AND role='teacher'",
                                   (username,)).fetchone()
            if teacher is None:
                continue
            for index, title in enumerate(("Welcome to the course discussion", "Questions and study tips"), 1):
                thread_id = f"demo-forum-{course_id}-{index}"
                added = conn.execute("INSERT OR IGNORE INTO forum_threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (thread_id, course_id, teacher["id"], teacher["display_name"], "teacher", title,
                     "Share your questions and ideas with the class.", int(index == 1), now, now)).rowcount
                created += added
                if added:
                    conn.execute("INSERT OR IGNORE INTO forum_thread_subscriptions VALUES (?, ?)",
                                 (thread_id, teacher["id"]))
                replies += conn.execute("INSERT OR IGNORE INTO forum_posts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{thread_id}-reply", thread_id, teacher["id"], teacher["display_name"], "teacher",
                     "Please include an example when asking a question so we can help.", now, now)).rowcount
    return {"threads_created": created, "posts_created": replies}

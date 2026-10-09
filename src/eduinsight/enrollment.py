"""Course applications and invitations grant authoritative enrollment atomically."""

from __future__ import annotations

import secrets
import time
import uuid
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, courses
from .auth import AuthUser, get_current_user, require_role
from .notifications import create_notification

router = APIRouter(tags=["enrollment"])
INVITATION_TTL = 7 * 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrollment_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    student_id INTEGER NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'approved', 'rejected', 'cancelled')),
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by INTEGER REFERENCES users(id),
    demo_key TEXT UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_enrollment_pending
    ON enrollment_requests(course_id, student_id) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS course_invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id TEXT NOT NULL,
    email_or_username TEXT NOT NULL,
    invited_user_id INTEGER REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'student' CHECK(role = 'student'),
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    accepted_at REAL,
    accepted_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_invitations_course ON course_invitations(course_id);
"""


@contextmanager
def _db(*, write: bool = False):
    courses.init_enrollments()
    with auth._db() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            conn.rollback()
            raise


class EnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str = Field(min_length=1, max_length=200)
    message: str = Field(default="", max_length=5000)


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_or_username: str = Field(min_length=1, max_length=254)
    role: Literal["student"] = "student"

    @field_validator("email_or_username")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Recipient cannot be blank")
        return value.strip()


def _catalog(course_id: str) -> str:
    """Resolve dynamic catalogs too; call before opening a write transaction."""
    if hasattr(courses, "catalog_entries"):
        entry = courses.catalog_entries().get(course_id)
        if entry is None:
            raise HTTPException(404, "Course not found")
        if entry.get("archived"):
            raise HTTPException(409, "Course is archived")
        return entry["name"]
    if course_id not in courses.COURSE_CATALOG:
        raise HTTPException(404, "Course not found")
    return courses.COURSE_CATALOG[course_id]


def _student(user: AuthUser) -> int:
    if user.role != "student" or user.moodle_user_id is None:
        raise HTTPException(403, "An identified student is required")
    return user.moodle_user_id


def _enrolled(conn, course_id: str, student_id: int) -> bool:
    return courses.is_enrolled(course_id, student_id, conn=conn)


def _enroll(conn, course_id: str, student_id: int) -> None:
    courses.enroll(course_id, student_id, source="approval_or_invitation", conn=conn)
    # Preserve the initial conversation UX; only course_enrollments grants access.
    if not conn.execute("SELECT 1 FROM chat_sessions WHERE course_id=? AND moodle_user_id=?",
                        (course_id, student_id)).fetchone():
        now = time.time()
        conn.execute("INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?, ?)",
                     (f"chat-enrollment-{uuid.uuid4().hex}", student_id, course_id,
                      "Course learning session", now, now))


def _recipient(conn, recipient: str):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    where = "username = ?"
    params = [recipient]
    if "email" in columns:
        where += " OR email = ? COLLATE NOCASE"
        params.append(recipient)
    profile_columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
    if {"email", "user_id"} <= profile_columns:
        where += " OR id IN (SELECT user_id FROM profiles WHERE email = ? COLLATE NOCASE)"
        params.append(recipient)
    rows = conn.execute(f"SELECT * FROM users WHERE {where}", params).fetchall()
    if len(rows) > 1:
        raise HTTPException(409, "Recipient is ambiguous; use their username")
    return rows[0] if rows else None


def _request(conn, request_id: int):
    row = conn.execute(
        "SELECT * FROM enrollment_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Enrollment request not found")
    return row


def _request_view(row) -> dict:
    return {
        key: row[key]
        for key in (
            "id",
            "course_id",
            "user_id",
            "student_id",
            "message",
            "status",
            "created_at",
            "decided_at",
            "decided_by",
        )
    }


def _invitation_view(row) -> dict:
    result = dict(row)
    if result["status"] == "pending" and result["expires_at"] <= time.time():
        result["status"] = "expired"
    return result


@router.post("/enrollment/requests", status_code=201)
def request_enrollment(
    body: EnrollmentRequest,
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    student_id = _student(user)
    _catalog(body.course_id)
    with _db(write=True) as conn:
        if _enrolled(conn, body.course_id, student_id):
            raise HTTPException(409, "Already enrolled in this course")
        if conn.execute(
            "SELECT 1 FROM enrollment_requests "
            "WHERE course_id = ? AND student_id = ? AND status = 'pending'",
            (body.course_id, student_id),
        ).fetchone():
            raise HTTPException(409, "A pending request already exists")
        cur = conn.execute(
            "INSERT INTO enrollment_requests "
            "(course_id, user_id, student_id, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (body.course_id, user.id, student_id, body.message, time.time()),
        )
        result = _request_view(_request(conn, cur.lastrowid))
    return result


@router.get("/enrollment/requests/mine")
def my_requests(user: AuthUser = Depends(require_role("student"))) -> list[dict]:
    _student(user)
    with _db() as conn:
        return [
            _request_view(row)
            for row in conn.execute(
                "SELECT * FROM enrollment_requests WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (user.id,),
            ).fetchall()
        ]


@router.delete("/enrollment/requests/{request_id}", status_code=204)
def cancel_request(
    request_id: int,
    user: AuthUser = Depends(require_role("student")),
) -> Response:
    _student(user)
    with _db(write=True) as conn:
        row = _request(conn, request_id)
        if row["user_id"] != user.id:
            raise HTTPException(403, "Request belongs to another student")
        if row["status"] != "pending":
            raise HTTPException(409, "Only pending requests can be cancelled")
        conn.execute(
            "UPDATE enrollment_requests SET status = 'cancelled', decided_at = ?, "
            "decided_by = ? WHERE id = ?",
            (time.time(), user.id, request_id),
        )
    return Response(status_code=204)


@router.get("/courses/{course_id}/enrollment/requests")
def course_requests(
    course_id: str,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> list[dict]:
    courses._check_course_access(user, course_id)
    with _db() as conn:
        return [
            _request_view(row)
            for row in conn.execute(
                "SELECT * FROM enrollment_requests WHERE course_id = ? ORDER BY created_at, id",
                (course_id,),
            ).fetchall()
        ]


def _decide(request_id: int, user: AuthUser, status: str) -> dict:
    with _db() as conn:
        course_id = _request(conn, request_id)["course_id"]
    courses._check_course_access(user, course_id)
    course_name = _catalog(course_id)
    with _db(write=True) as conn:
        row = _request(conn, request_id)
        if row["status"] != "pending":
            raise HTTPException(409, "Request has already been decided or cancelled")
        if status == "approved":
            student = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
            if (
                student is None
                or student["role"] != "student"
                or student["moodle_user_id"] != row["student_id"]
            ):
                raise HTTPException(409, "Applicant's student identity has changed")
            _enroll(conn, row["course_id"], row["student_id"])
        conn.execute(
            "UPDATE enrollment_requests SET status = ?, decided_at = ?, decided_by = ? "
            "WHERE id = ?",
            (status, time.time(), user.id, request_id),
        )
        result = _request_view(_request(conn, request_id))
    create_notification(
        result["user_id"],
        f"Enrollment {status}",
        f"Your request for {course_name} was {status}.",
        "enrollment",
        f"/courses/{result['course_id']}",
    )
    return result


@router.post("/enrollment/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    return _decide(request_id, user, "approved")


@router.post("/enrollment/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    return _decide(request_id, user, "rejected")


@router.post("/courses/{course_id}/invitations", status_code=201)
def create_invitation(
    course_id: str,
    body: InvitationCreate,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    courses._check_course_access(user, course_id)
    course_name = _catalog(course_id)
    with _db(write=True) as conn:
        recipient = _recipient(conn, body.email_or_username)
        if recipient is not None:
            if recipient["role"] != "student" or recipient["moodle_user_id"] is None:
                raise HTTPException(422, "Recipient must be an identified student")
            if _enrolled(conn, course_id, recipient["moodle_user_id"]):
                raise HTTPException(409, "Recipient is already enrolled")
        now = time.time()
        if conn.execute(
            "SELECT 1 FROM course_invitations WHERE course_id = ? "
            "AND (email_or_username = ? OR invited_user_id = ?) "
            "AND status = 'pending' AND expires_at > ?",
            (course_id, body.email_or_username, recipient["id"] if recipient else None, now),
        ).fetchone():
            raise HTTPException(409, "A pending invitation already exists")
        cur = conn.execute(
            "INSERT INTO course_invitations "
            "(course_id, email_or_username, invited_user_id, token, created_by, "
            "created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                course_id,
                body.email_or_username,
                recipient["id"] if recipient else None,
                secrets.token_urlsafe(32),
                user.id,
                now,
                now + INVITATION_TTL,
            ),
        )
        result = _invitation_view(
            conn.execute(
                "SELECT * FROM course_invitations WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        )
    if recipient is not None:
        create_notification(
            recipient["id"],
            "Course invitation",
            f"You are invited to {course_name}.",
            "invitation",
            f"/invitations/{result['token']}",
        )
    return result


@router.get("/courses/{course_id}/invitations")
def list_invitations(
    course_id: str,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> list[dict]:
    courses._check_course_access(user, course_id)
    with _db() as conn:
        return [
            _invitation_view(row)
            for row in conn.execute(
                "SELECT * FROM course_invitations WHERE course_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (course_id,),
            ).fetchall()
        ]


@router.post("/invitations/{token}/accept")
def accept_invitation(
    token: str,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    student_id = _student(user)
    with _db() as conn:
        initial = conn.execute(
            "SELECT course_id FROM course_invitations WHERE token = ?",
            (token,),
        ).fetchone()
        if initial is None:
            raise HTTPException(404, "Invitation not found")
    course_name = _catalog(initial["course_id"])
    with _db(write=True) as conn:
        row = conn.execute("SELECT * FROM course_invitations WHERE token = ?", (token,)).fetchone()
        if row is None:
            raise HTTPException(404, "Invitation not found")
        if row["invited_user_id"] is not None:
            matches = row["invited_user_id"] == user.id
        else:
            recipient = _recipient(conn, row["email_or_username"])
            matches = recipient is not None and recipient["id"] == user.id
        if not matches:
            raise HTTPException(403, "Invitation belongs to another user")
        if row["status"] != "pending":
            raise HTTPException(409, "Invitation has already been accepted")
        if row["expires_at"] <= time.time():
            raise HTTPException(410, "Invitation has expired")
        _enroll(conn, row["course_id"], student_id)
        conn.execute(
            "UPDATE course_invitations SET status = 'accepted', accepted_at = ?, accepted_by = ?, "
            "invited_user_id = ? WHERE id = ?",
            (time.time(), user.id, user.id, row["id"]),
        )
        # Accepting an invitation also resolves any pending application to the course.
        conn.execute(
            "UPDATE enrollment_requests SET status = 'approved', decided_at = ?, decided_by = ? "
            "WHERE course_id = ? AND student_id = ? AND status = 'pending'",
            (time.time(), user.id, row["course_id"], student_id),
        )
        result = _invitation_view(
            conn.execute(
                "SELECT * FROM course_invitations WHERE id = ?",
                (row["id"],),
            ).fetchone()
        )
    create_notification(
        user.id,
        "Enrollment confirmed",
        f"You have joined {course_name}.",
        "enrollment",
        f"/courses/{result['course_id']}",
    )
    create_notification(
        result["created_by"],
        "Invitation accepted",
        f"{user.display_name} joined {result['course_id']}.",
        "enrollment",
        f"/courses/{result['course_id']}",
    )
    return result


def seed_demo_enrollment() -> dict[str, int]:
    """Idempotent requests for existing demo users; creates no users or enrollment."""
    created = 0
    with _db(write=True) as conn:
        for username in ("student1001", "student1002"):
            student = conn.execute(
                "SELECT * FROM users WHERE username = ? AND role = 'student'",
                (username,),
            ).fetchone()
            if student is None or student["moodle_user_id"] is None:
                continue
            if "py101" not in courses.COURSE_CATALOG or _enrolled(
                conn, "py101", student["moodle_user_id"]
            ):
                continue
            created += conn.execute(
                "INSERT OR IGNORE INTO enrollment_requests "
                "(course_id, user_id, student_id, message, created_at, demo_key) "
                "VALUES ('py101', ?, ?, ?, ?, ?)",
                (
                    student["id"],
                    student["moodle_user_id"],
                    "I would like to learn Python.",
                    time.time(),
                    f"demo-enrollment-{username}-py101",
                ),
            ).rowcount
    return {"requests_created": created}

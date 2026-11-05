"""Persisted course assignments and private student submissions.

Tables are created lazily in settings.auth_db_path, alongside chat enrollment.
Deadlines must include a timezone. Only course staff can enable allow_late.
An assignment with audience rows (e.g. a diagnostic intervention) is visible
only to those students; it is invisible, not forbidden, to other students.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .auth import TEACHER_COURSE_MAP, AuthUser, get_current_user, require_role
from .config import settings
from .courses import _check_course_access
from .db import connect, schema_once

router = APIRouter(tags=["assignments"])


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    due_at: AwareDatetime
    max_score: float = Field(default=100, gt=0, allow_inf_nan=False)
    allow_late: bool = False

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value.strip()


class AssignmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    due_at: AwareDatetime | None = None
    max_score: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    allow_late: bool | None = None

    @field_validator("title", "description", "due_at", "max_score", "allow_late")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Fields cannot be null")
        return value


class SubmissionPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=100000)
    file_name: str | None = Field(default=None, max_length=255)
    file_metadata: dict[str, Any] | None = None
    state: Literal["draft", "submitted"] = "draft"

    @field_validator("file_metadata")
    @classmethod
    def valid_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 20000:
            raise ValueError("File metadata is too large")
        return value


class SubmissionGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, allow_inf_nan=False)
    feedback: str = Field(default="", max_length=20000)


@contextmanager
def _db(*, write: bool = False):
    Path(settings.auth_db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.auth_db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with schema_once(conn, "assignments") as initialize:
            if initialize:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS assignments (
                        id TEXT PRIMARY KEY,
                        course_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        due_at REAL NOT NULL,
                        max_score REAL NOT NULL CHECK(max_score > 0),
                        allow_late INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ix_assignments_course
                        ON assignments(course_id, due_at);
                    CREATE TABLE IF NOT EXISTS assignment_submissions (
                        assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                        student_id INTEGER NOT NULL,
                        text TEXT NOT NULL DEFAULT '',
                        file_name TEXT,
                        file_metadata TEXT,
                        state TEXT NOT NULL CHECK(state IN ('draft', 'submitted', 'graded')),
                        late INTEGER NOT NULL DEFAULT 0,
                        submitted_at REAL,
                        score REAL CHECK(score >= 0),
                        feedback TEXT,
                        graded_at REAL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (assignment_id, student_id)
                    );
                    CREATE TABLE IF NOT EXISTS assignment_audience (
                        assignment_id TEXT NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                        student_id INTEGER NOT NULL,
                        PRIMARY KEY (assignment_id, student_id)
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


def assigned_to(alias: str = "a") -> str:
    """SQL condition: the assignment has no audience or includes the bound student ID."""
    return (
        f"(NOT EXISTS (SELECT 1 FROM assignment_audience x WHERE x.assignment_id = {alias}.id) "
        f"OR EXISTS (SELECT 1 FROM assignment_audience x "
        f"WHERE x.assignment_id = {alias}.id AND x.student_id = ?))"
    )


def untargeted(alias: str = "a") -> str:
    """SQL condition: the assignment is for the whole course."""
    return f"NOT EXISTS (SELECT 1 FROM assignment_audience x WHERE x.assignment_id = {alias}.id)"


def _audience(conn: sqlite3.Connection, assignment_id: str) -> list[int] | None:
    rows = conn.execute(
        "SELECT student_id FROM assignment_audience WHERE assignment_id = ? ORDER BY student_id",
        (assignment_id,),
    ).fetchall()
    return [row[0] for row in rows] or None


def _assignment(conn: sqlite3.Connection, assignment_id: str, user: AuthUser) -> dict:
    row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Assignment not found")
    _check_course_access(user, row["course_id"])
    if user.role == "student":
        audience = _audience(conn, assignment_id)
        if audience is not None and user.moodle_user_id not in audience:
            raise HTTPException(404, "Assignment not found")
    return dict(row)


def _submission(conn: sqlite3.Connection, assignment_id: str, student_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM assignment_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, student_id),
    ).fetchone()
    return dict(row) if row is not None else None


def _status(assignment: dict, submission: dict | None) -> str:
    if submission is not None and submission["state"] == "graded":
        return "已評分"
    if submission is not None and submission["state"] == "submitted":
        return "已繳交"
    if time.time() > assignment["due_at"]:
        return "已逾期"
    return "草稿" if submission is not None else "未繳交"


def _submission_view(assignment: dict, submission: dict) -> dict:
    result = dict(submission)
    result["file_metadata"] = (
        json.loads(result["file_metadata"]) if result["file_metadata"] is not None else None
    )
    result["late"] = bool(result["late"])
    result["status"] = _status(assignment, submission)
    return result


def _assignment_view(conn: sqlite3.Connection, assignment: dict, user: AuthUser) -> dict:
    result = dict(assignment)
    result["due_at"] = datetime.fromtimestamp(assignment["due_at"], UTC).isoformat()
    result["allow_late"] = bool(result["allow_late"])
    audience = _audience(conn, assignment["id"])
    result["targeted"] = audience is not None
    if user.role != "student":
        result["audience"] = audience
    if user.role == "student":
        own = _submission(conn, assignment["id"], user.moodle_user_id)
        result["status"] = _status(assignment, own)
        result["score"] = own["score"] if own else None
        result["feedback"] = own["feedback"] if own else None
        result["submission"] = _submission_view(assignment, own) if own else None
    return result


@router.post("/assignments", status_code=201)
def create_assignment(
    body: AssignmentCreate,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    _check_course_access(user, body.course_id)
    with _db(write=True) as conn:
        assignment_id = insert_assignment(conn, body)
        return _assignment_view(conn, _assignment(conn, assignment_id, user), user)


def insert_assignment(
    conn: sqlite3.Connection, body: AssignmentCreate, audience: list[int] | None = None,
) -> str:
    """Insert in the caller's write transaction; the caller checks course access."""
    now = time.time()
    assignment_id = f"assignment-{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            assignment_id,
            body.course_id,
            body.title,
            body.description,
            body.due_at.timestamp(),
            body.max_score,
            int(body.allow_late),
            now,
            now,
        ),
    )
    conn.executemany(
        "INSERT INTO assignment_audience (assignment_id, student_id) VALUES (?, ?)",
        [(assignment_id, student_id) for student_id in dict.fromkeys(audience or [])],
    )
    return assignment_id


@router.get("/courses/{course_id}/assignments")
def list_assignments(course_id: str, user: AuthUser = Depends(get_current_user)) -> list[dict]:
    _check_course_access(user, course_id)
    with _db() as conn:
        if user.role == "student":
            rows = conn.execute(
                f"SELECT * FROM assignments a WHERE course_id = ? AND {assigned_to()} "
                "ORDER BY due_at, id", (course_id, user.moodle_user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM assignments WHERE course_id = ? ORDER BY due_at, id",
                (course_id,),
            ).fetchall()
        return [_assignment_view(conn, dict(row), user) for row in rows]


@router.get("/assignments/{assignment_id}")
def assignment_detail(assignment_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        return _assignment_view(conn, _assignment(conn, assignment_id, user), user)


@router.patch("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: str,
    body: AssignmentPatch,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(422, "Title cannot be blank")
    if "due_at" in changes:
        changes["due_at"] = changes["due_at"].timestamp()
    with _db(write=True) as conn:
        assignment = _assignment(conn, assignment_id, user)
        if "max_score" in changes:
            highest = conn.execute(
                "SELECT MAX(score) FROM assignment_submissions WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()[0]
            if highest is not None and highest > changes["max_score"]:
                raise HTTPException(409, "Maximum score is below an existing grade")
        if changes:
            changes["updated_at"] = time.time()
            columns = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE assignments SET {columns} WHERE id = ?",
                (*changes.values(), assignment_id),
            )
            assignment = _assignment(conn, assignment_id, user)
        result = _assignment_view(conn, assignment, user)
    # Title and max_score feed grade center items.
    sync_grade_center(assignment["course_id"])
    return result


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(
    assignment_id: str,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> Response:
    with _db(write=True) as conn:
        course_id = _assignment(conn, assignment_id, user)["course_id"]
        conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    sync_grade_center(course_id)
    return Response(status_code=204)


@router.get("/assignments/{assignment_id}/submissions")
def list_submissions(
    assignment_id: str,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> list[dict]:
    with _db() as conn:
        assignment = _assignment(conn, assignment_id, user)
        rows = conn.execute(
            "SELECT * FROM assignment_submissions WHERE assignment_id = ? ORDER BY student_id",
            (assignment_id,),
        ).fetchall()
        return [_submission_view(assignment, dict(row)) for row in rows]


@router.put("/assignments/{assignment_id}/submission")
def put_submission(
    assignment_id: str,
    body: SubmissionPut,
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    with _db(write=True) as conn:
        assignment = _assignment(conn, assignment_id, user)
        own = _submission(conn, assignment_id, user.moodle_user_id)
        if own and own["state"] == "graded":
            raise HTTPException(409, "Graded submissions cannot be changed")
        if own and own["state"] == "submitted" and body.state == "draft":
            raise HTTPException(409, "Withdraw the submission before editing a draft")
        now = time.time()
        late = body.state == "submitted" and now > assignment["due_at"]
        if late and not assignment["allow_late"]:
            raise HTTPException(409, "Deadline passed; late submissions are disabled")
        metadata = json.dumps(body.file_metadata, ensure_ascii=False, allow_nan=False)
        conn.execute(
            "INSERT INTO assignment_submissions "
            "(assignment_id, student_id, text, file_name, file_metadata, state, late, "
            "submitted_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(assignment_id, student_id) DO UPDATE SET "
            "text=excluded.text, file_name=excluded.file_name, "
            "file_metadata=excluded.file_metadata, "
            "state=excluded.state, late=excluded.late, "
            "submitted_at=excluded.submitted_at, "
            "updated_at=excluded.updated_at",
            (
                assignment_id,
                user.moodle_user_id,
                body.text,
                body.file_name,
                metadata if body.file_metadata is not None else None,
                body.state,
                int(late),
                now if body.state == "submitted" else None,
                now,
            ),
        )
        return _submission_view(assignment, _submission(conn, assignment_id, user.moodle_user_id))


@router.post("/assignments/{assignment_id}/submission/withdraw")
def withdraw_submission(
    assignment_id: str,
    user: AuthUser = Depends(require_role("student")),
) -> dict:
    with _db(write=True) as conn:
        assignment = _assignment(conn, assignment_id, user)
        own = _submission(conn, assignment_id, user.moodle_user_id)
        if own is None:
            raise HTTPException(404, "Submission not found")
        if own["state"] == "graded":
            raise HTTPException(409, "Graded submissions cannot be withdrawn")
        conn.execute(
            "UPDATE assignment_submissions SET state = 'draft', late = 0, submitted_at = NULL, "
            "updated_at = ? WHERE assignment_id = ? AND student_id = ?",
            (time.time(), assignment_id, user.moodle_user_id),
        )
        return _submission_view(assignment, _submission(conn, assignment_id, user.moodle_user_id))


@router.post("/assignments/{assignment_id}/submissions/{student_id}/grade")
def grade_submission(
    assignment_id: str,
    student_id: int,
    body: SubmissionGrade,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    with _db(write=True) as conn:
        assignment = _assignment(conn, assignment_id, user)
        enrolled = conn.execute(
            "SELECT 1 FROM course_enrollments WHERE course_id = ? AND moodle_user_id = ? LIMIT 1",
            (assignment["course_id"], student_id),
        ).fetchone()
        if enrolled is None:
            raise HTTPException(403, "Student is not enrolled in this course")
        own = _submission(conn, assignment_id, student_id)
        if own is None:
            raise HTTPException(404, "Submission not found")
        if own["state"] == "draft":
            raise HTTPException(409, "Draft submissions cannot be graded")
        if body.score > assignment["max_score"]:
            raise HTTPException(422, "Score exceeds the assignment maximum")
        now = time.time()
        conn.execute(
            "UPDATE assignment_submissions SET state = 'graded', score = ?, feedback = ?, "
            "graded_at = ?, updated_at = ? WHERE assignment_id = ? AND student_id = ?",
            (body.score, body.feedback, now, now, assignment_id, student_id),
        )
        result = _submission_view(assignment, _submission(conn, assignment_id, student_id))
    sync_grade_center(assignment["course_id"])
    return result


GRADE_CENTER_CATEGORY = "作業"
# (course_id) -> {(student_id, item)} written by the last sync, to drop stale items
# after a regrade to draft, an assignment rename or deletion, or a new duplicate title.
_SYNCED_ITEMS: dict[str, set[tuple[int, str]]] = {}


def sync_grade_center(course_id: str | None = None) -> int:
    """Mirror graded submissions into the grade center under the 「作業」 category.

    The grade manager is in-memory, so call this after grading, at startup and after
    a demo reset. A course without categories gets 「作業」 at 100%; a course whose
    staff configured categories without 「作業」 is left untouched. Items are keyed by
    assignment title (suffixed when titles repeat). Each course is rebuilt as a whole:
    items from the previous sync that no longer apply are removed. Returns the number
    of scores written.
    """
    from .analytics_extra import get_grade_manager

    manager = get_grade_manager()
    query = (
        "SELECT a.course_id, a.id, a.title, a.max_score, s.student_id, s.score "
        "FROM assignment_submissions s JOIN assignments a ON a.id = s.assignment_id "
        "WHERE s.state = 'graded' AND s.score IS NOT NULL"
    )
    params: tuple = ()
    if course_id is not None:
        query += " AND a.course_id = ?"
        params = (course_id,)
    with _db() as conn:
        query += " ORDER BY a.course_id, a.due_at, a.id"
        rows = [dict(row) for row in conn.execute(query, params)]
        titles = {
            (row["course_id"], row["title"]): row["n"]
            for row in conn.execute("SELECT course_id, title, COUNT(*) AS n FROM assignments "
                                    "GROUP BY course_id, title")
        }
    by_course: dict[str, list[dict]] = {}
    for row in rows:
        by_course.setdefault(row["course_id"], []).append(row)
    targets = {course_id} if course_id is not None else set(by_course) | set(_SYNCED_ITEMS)
    written = 0
    for course in sorted(targets):
        course_rows = by_course.get(course, [])
        try:
            names = [category.name for category in manager.get_categories(course)]
        except KeyError:
            if not course_rows:
                _SYNCED_ITEMS.pop(course, None)
                continue
            names = [category.name for category in manager.set_categories(
                course, [{"name": GRADE_CENTER_CATEGORY, "weight": 100}],
            )]
        if GRADE_CENTER_CATEGORY not in names:
            _SYNCED_ITEMS.pop(course, None)
            continue
        current: set[tuple[int, str]] = set()
        for row in course_rows:
            item = row["title"]
            if titles.get((course, item), 1) > 1:
                item = f"{item}（{row['id'][-6:]}）"
            manager.record_score(
                course, student_id=row["student_id"], category=GRADE_CENTER_CATEGORY,
                item=item, score=row["score"], total=row["max_score"],
            )
            current.add((row["student_id"], item))
            written += 1
        for student_id, item in _SYNCED_ITEMS.get(course, set()) - current:
            manager.delete_score(
                course, student_id=student_id, category=GRADE_CENTER_CATEGORY, item=item,
            )
        _SYNCED_ITEMS[course] = current
    return written


def seed_demo_assignments() -> dict[str, int]:
    """Create three assignments per mapped course without overwriting existing work.

    Call from /demo/reset after demo chat sessions (enrollment) have been seeded.
    Seed only enrolled demo students; enrollment itself belongs to the caller.
    """
    created = submissions = 0
    now = datetime.now(UTC)
    with _db(write=True) as conn:
        for course_id in sorted(set(TEACHER_COURSE_MAP.values())):
            for index, title in enumerate(("概念練習", "應用作業", "期末專題"), start=1):
                assignment_id = f"demo-assignment-{course_id}-{index}"
                due = (now + timedelta(days=(-2, 7, 14)[index - 1])).timestamp()
                created += conn.execute(
                    "INSERT OR IGNORE INTO assignments VALUES (?, ?, ?, ?, ?, 100, ?, ?, ?)",
                    (
                        assignment_id,
                        course_id,
                        title,
                        "請完成課程練習並說明解題過程。",
                        due,
                        int(index == 1),
                        now.timestamp(),
                        now.timestamp(),
                    ),
                ).rowcount
                for student_id in range(1001, 1006):
                    enrolled = conn.execute(
                        "SELECT 1 FROM course_enrollments WHERE course_id = ? AND moodle_user_id = ? "
                        "LIMIT 1",
                        (course_id, student_id),
                    ).fetchone()
                    # Leave some assignments unsubmitted to demonstrate all statuses.
                    if not enrolled or index == 3 or (index == 1 and student_id == 1005):
                        continue
                    state = "draft"
                    if index == 1:
                        state = "graded" if student_id == 1001 else "submitted"
                    submissions += conn.execute(
                        "INSERT OR IGNORE INTO assignment_submissions "
                        "(assignment_id, student_id, text, state, submitted_at, score, feedback, "
                        "graded_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            assignment_id,
                            student_id,
                            "這是我的示範解答。",
                            state,
                            due - 3600 if index == 1 else None,
                            88 if state == "graded" else None,
                            "觀念清楚，請補充推導過程。" if state == "graded" else None,
                            now.timestamp() if state == "graded" else None,
                            now.timestamp(),
                        ),
                    ).rowcount
    return {"assignments_created": created, "submissions_created": submissions}

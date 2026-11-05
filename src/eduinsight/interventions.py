"""Diagnosis -> intervention -> follow-up for a struggle topic.

A teacher dispatches a review assignment to the students struggling with a
topic (as listed by /diagnostics/{course_id}/clusters). The assignment is
targeted: only those students see it, and class-wide assignment analytics
leave it out. Follow-up reports, per member, the submission status and score
and whether the current diagnostics still list the student under that topic.
"No longer listed" is evidence of change, not proof the review caused it.
Deleting the assignment deletes the intervention with it.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from . import assignments
from .auth import AuthUser, require_role
from .db import schema_once
from .diagnostics import _authorized_course, _Evidence, _evidence, _topic_groups
from .notifications import create_notification

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
_TAIPEI = timezone(timedelta(hours=8))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interventions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    assignment_id TEXT NOT NULL UNIQUE REFERENCES assignments(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_interventions_course ON interventions(course_id, created_at);
"""


@contextmanager
def _db(*, write: bool = False):
    # Same database as assignments; create this schema before a write transaction.
    with assignments._db() as conn:  # noqa: SLF001
        with schema_once(conn, "interventions") as initialize:
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


def _default_due() -> datetime:
    return datetime.now(UTC) + timedelta(days=7)


class InterventionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=200)
    student_ids: list[int] = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=20000)
    due_at: AwareDatetime = Field(default_factory=_default_due)
    max_score: float = Field(default=100, gt=0, allow_inf_nan=False)

    @field_validator("topic")
    @classmethod
    def nonblank_topic(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Topic cannot be blank")
        return value


class InterventionMember(BaseModel):
    moodle_user_id: int
    display_name: str
    status: str
    score: float | None
    still_struggling: bool


class InterventionAssignment(BaseModel):
    id: str
    title: str
    due_at: str
    max_score: float


class Intervention(BaseModel):
    id: str
    course_id: str
    topic: str
    created_by: str
    created_at: float
    assignment: InterventionAssignment
    members: list[InterventionMember]
    member_count: int
    submitted_count: int
    completion_rate: float = Field(ge=0, le=1)
    average_score: float | None
    still_struggling_count: int


def _display_names(conn, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    return {row["moodle_user_id"]: row["display_name"] for row in conn.execute(
        "SELECT moodle_user_id, display_name FROM users WHERE role = 'student' "
        f"AND moodle_user_id IN ({placeholders})", ids,
    )}


def _view(conn, row, groups: dict[str, set[int]]) -> Intervention:
    assignment = dict(conn.execute(
        "SELECT * FROM assignments WHERE id = ?", (row["assignment_id"],),
    ).fetchone())
    audience = assignments._audience(conn, assignment["id"]) or []  # noqa: SLF001
    names = _display_names(conn, audience)
    struggling = groups.get(row["topic"].casefold(), set())
    members = []
    for student_id in audience:
        submission = assignments._submission(conn, assignment["id"], student_id)  # noqa: SLF001
        members.append(InterventionMember(
            moodle_user_id=student_id,
            display_name=names.get(student_id) or f"Student {student_id}",
            status=assignments._status(assignment, submission),  # noqa: SLF001
            score=submission["score"] if submission else None,
            still_struggling=student_id in struggling,
        ))
    done = [m for m in members if m.status in ("已繳交", "已評分")]
    scores = [m.score for m in members if m.score is not None]
    return Intervention(
        id=row["id"], course_id=row["course_id"], topic=row["topic"],
        created_by=row["created_by"], created_at=row["created_at"],
        assignment=InterventionAssignment(
            id=assignment["id"], title=assignment["title"],
            due_at=datetime.fromtimestamp(assignment["due_at"], UTC).isoformat(),
            max_score=assignment["max_score"],
        ),
        members=members, member_count=len(members), submitted_count=len(done),
        completion_rate=len(done) / len(members) if members else 0,
        average_score=round(sum(scores) / len(scores), 2) if scores else None,
        still_struggling_count=sum(m.still_struggling for m in members),
    )


def _current_groups(evidence: _Evidence) -> dict[str, set[int]]:
    return {topic.casefold(): set(members) for topic, members in _topic_groups(evidence)}


@router.post("/{course_id}/interventions", response_model=Intervention, status_code=201)
def create_intervention(
    body: InterventionCreate,
    course_id: str = Depends(_authorized_course),
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> Intervention:
    student_ids = list(dict.fromkeys(body.student_ids))
    with _db(write=True) as conn:
        placeholders = ",".join("?" for _ in student_ids)
        enrolled = {row[0] for row in conn.execute(
            "SELECT moodle_user_id FROM course_enrollments WHERE course_id = ? "
            f"AND moodle_user_id IN ({placeholders})", (course_id, *student_ids),
        )}
        if set(student_ids) - enrolled:
            raise HTTPException(422, "Every student must be enrolled in this course")
        assignment_id = assignments.insert_assignment(conn, assignments.AssignmentCreate(
            course_id=course_id, title=body.title or f"複習：{body.topic}",
            description=body.description, due_at=body.due_at, max_score=body.max_score,
        ), audience=student_ids)
        intervention_id = f"intervention-{uuid.uuid4().hex}"
        conn.execute(
            "INSERT INTO interventions VALUES (?, ?, ?, ?, ?, ?)",
            (intervention_id, course_id, body.topic, assignment_id, user.username, time.time()),
        )
        row = conn.execute(
            "SELECT * FROM interventions WHERE id = ?", (intervention_id,),
        ).fetchone()
        # The teacher picked these students as struggling; GET recomputes from diagnostics.
        result = _view(conn, row, {body.topic.casefold(): set(student_ids)})
        recipients = [r[0] for r in conn.execute(
            f"SELECT id FROM users WHERE role = 'student' AND moodle_user_id IN ({placeholders})",
            student_ids,
        )]
    for recipient in recipients:
        create_notification(
            recipient, f"老師指派了複習任務：{result.assignment.title}",
            f"截止：{body.due_at.astimezone(_TAIPEI).strftime('%Y-%m-%d %H:%M')}",
            "assignment", f"/course/{course_id}/assignment/{assignment_id}",
        )
    return result


@router.get("/{course_id}/interventions", response_model=list[Intervention])
def list_interventions(evidence: _Evidence = Depends(_evidence)) -> list[Intervention]:
    groups = _current_groups(evidence)
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM interventions WHERE course_id = ? ORDER BY created_at DESC, id",
            (evidence.course_id,),
        ).fetchall()
        return [_view(conn, row, groups) for row in rows]

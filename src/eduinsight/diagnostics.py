"""Teacher diagnostics from stored learning evidence, without LLM calls.

Enrollment is inferred from chat_sessions, as in the existing dashboards.
Lite-Mem student facts have no course metadata: estimates aggregate facts for
the course's enrolled students, rather than claiming course-specific grades.
Question excerpts require both the correct student and a session in the course;
legacy/orphan messages without a course mapping are deliberately excluded.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from litemem import Memory
from pydantic import BaseModel, Field

from . import sessions
from .analytics import StudentAnalytics, analyze_student, assess_risk
from .auth import TEACHER_COURSE_MAP, AuthUser, require_role
from .rag import CourseRAG

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
_ACTIVE_DAYS = 14


class Overview(BaseModel):
    course_id: str
    mastery_estimate: float | None = Field(ge=0, le=100)
    total_students: int
    total_facts: int
    struggle_fact_count: int
    at_risk_student_count: int
    at_risk_student_ratio: float = Field(ge=0, le=1)
    active_learner_count: int
    indexed_material_chunk_count: int


class MaterialLocation(BaseModel):
    filename: str
    page: int | None
    heading: str
    anchor_id: str


class HardTopic(BaseModel):
    topic: str
    student_count: int
    representative_questions: list[str]
    matched_material_locations: list[MaterialLocation]


class ClusterMember(BaseModel):
    moodle_user_id: int
    display_name: str


class Cluster(BaseModel):
    cluster_id: str
    topic: str
    members: list[ClusterMember]
    size: int
    suggested_intervention: str


def get_memory() -> Memory:
    """Reuse the initialized application memory (also after /demo/reset).

    Import lazily so app.py can include this router without a circular import.
    Small standalone test apps can override this dependency.
    """
    from .app import get_assistant

    return get_assistant().memory


def _authorized_course(
    course_id: str, user: AuthUser = Depends(require_role("teacher", "admin")),
) -> str:
    # This router requires a mapped teacher; only admins have unrestricted scope.
    if user.role == "teacher" and TEACHER_COURSE_MAP.get(user.username) != course_id:
        raise HTTPException(403, "Course is outside your teaching scope")
    return course_id


@dataclass
class _Evidence:
    course_id: str
    memory: Memory
    students: dict[int, StudentAnalytics]
    messages: dict[int, list[dict[str, Any]]]
    names: dict[int, str]
    identities: set[str]


def _evidence(
    course_id: str = Depends(_authorized_course), memory: Memory = Depends(get_memory),
) -> _Evidence:
    with sessions._db() as conn:  # Same metadata store used by existing dashboards.
        rows = conn.execute(
            "SELECT moodle_user_id, session_id FROM chat_sessions WHERE course_id = ?",
            (course_id,),
        ).fetchall()
        users = conn.execute(
            "SELECT moodle_user_id, username, display_name, role FROM users ORDER BY id",
        ).fetchall()
    session_ids: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        session_ids[row["moodle_user_id"]].add(row["session_id"])
    names = {
        row["moodle_user_id"]: row["display_name"] for row in users
        if row["role"] == "student" and row["moodle_user_id"] in session_ids
    }
    identities = {
        str(value) for row in users
        for value in (row["username"], row["display_name"], row["moodle_user_id"])
        if value is not None and str(value).strip()
    }
    identities.update(str(student_id) for student_id in session_ids)
    students = {}
    messages = {}
    for student_id, ids in sorted(session_ids.items()):
        students[student_id] = analyze_student(memory, student_id)
        messages[student_id] = [
            msg for msg in memory._store.get_messages(f"moodle:{student_id}")
            if msg["role"] == "user" and msg.get("session_id") in ids
        ]
    return _Evidence(course_id, memory, students, messages, names, identities)


def _topic_groups(evidence: _Evidence) -> list[tuple[str, list[int]]]:
    """One membership per student/topic; case and whitespace variants coalesce."""
    groups: dict[str, set[int]] = defaultdict(set)
    labels: dict[str, str] = {}
    for student_id, student in evidence.students.items():
        for struggle in student.struggles:
            topic = " ".join(struggle.topic.split())
            if topic:
                key = topic.casefold()
                labels.setdefault(key, topic)
                groups[key].add(student_id)
    return [
        (labels[key], sorted(members))
        for key, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _anonymize(text: str, identities: set[str]) -> str:
    # Remove known account identifiers even when someone names a classmate.
    for identity in sorted(identities, key=lambda value: (-len(value), value)):
        escaped = re.escape(identity)
        pattern = (
            rf"(?<!\w){escaped}(?!\w)" if identity.isascii() else escaped
        )
        text = re.sub(pattern, "[匿名]", text, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[匿名]", text)
    return text


def _mentions_topic(text: str, topic: str) -> bool:
    """Match the topic phrase or a jargon token (e.g. JOIN in 'JOIN queries')."""
    text = " ".join(text.casefold().split())
    if topic.casefold() in text:
        return True
    generic = {"with", "and", "the", "queries", "reading", "usage", "decisions", "techniques"}
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]+", topic.casefold())
    return any(
        re.search(rf"\b{re.escape(token)}\b", text)
        for token in tokens if len(token) >= 3 and token not in generic
    )


@router.get("/{course_id}/overview", response_model=Overview)
def overview(evidence: _Evidence = Depends(_evidence)) -> Overview:
    """Mastery = 100 * (1 - struggle_fact_count / total_facts), rounded to 2 dp.

    No facts means unknown mastery (null), not demonstrated proficiency.
    At-risk ratio counts assess_risk levels medium/high divided by enrollment;
    the helper's class average uses this course's students, including zero facts.
    Active learners have a fact or course user message within the last 14 days.
    An empty session alone does not establish activity. Empty enrollment has a
    zero risk ratio. 教材掃描單位 counts stored course_material facts/chunks.
    """
    memory = evidence.memory
    total = sum(student.total_facts for student in evidence.students.values())
    struggles = sum(len(student.struggles) for student in evidence.students.values())
    count = len(evidence.students)
    now = time.time()
    at_risk = 0
    active = 0
    for student_id in evidence.students:
        risk = assess_risk(memory, student_id, class_avg_facts=total / count, now=now)
        at_risk += risk.risk_level in {"medium", "high"}
        timestamps = [record.created_at for record in memory.export(f"moodle:{student_id}").records]
        timestamps.extend(msg["created_at"] for msg in evidence.messages[student_id])
        active += any(now - _ACTIVE_DAYS * 86400 <= ts <= now for ts in timestamps)
    return Overview(
        course_id=evidence.course_id,
        mastery_estimate=round(100 * (1 - struggles / total), 2) if total else None,
        total_students=count, total_facts=total, struggle_fact_count=struggles,
        at_risk_student_count=at_risk, at_risk_student_ratio=at_risk / count if count else 0,
        active_learner_count=active,
        indexed_material_chunk_count=len(memory.list(
            f"course:{evidence.course_id}", category="course_material",
        )),
    )


@router.get("/{course_id}/hard-topics", response_model=list[HardTopic])
def hard_topics(evidence: _Evidence = Depends(_evidence)) -> list[HardTopic]:
    """Return distinct struggling learners, up to 3 excerpts and 3 RAG locations."""
    rag = CourseRAG(evidence.memory)
    filenames = set(rag.list_documents(evidence.course_id))
    topics = []
    for topic, members in _topic_groups(evidence):
        questions = []
        for student_id in members:
            for msg in evidence.messages[student_id]:
                if _mentions_topic(msg["content"], topic):
                    question = _anonymize(msg["content"], evidence.identities)
                    if question not in questions:
                        questions.append(question)
        locations = []
        if filenames:
            for hit in rag.search(evidence.course_id, topic, top_k=3):
                if hit.source in filenames:
                    location = MaterialLocation(
                        filename=hit.source, page=hit.page,
                        heading=hit.heading, anchor_id=hit.anchor_id,
                    )
                    if location not in locations:
                        locations.append(location)
        topics.append(HardTopic(
            topic=topic, student_count=len(members), representative_questions=questions[:3],
            matched_material_locations=locations,
        ))
    return topics


@router.get("/{course_id}/clusters", response_model=list[Cluster])
def clusters(evidence: _Evidence = Depends(_evidence)) -> list[Cluster]:
    """Overlapping topic groups; a student can need multiple interventions."""
    result = []
    for topic, members in _topic_groups(evidence):
        digest = hashlib.sha256(f"{evidence.course_id}\0{topic.casefold()}".encode()).hexdigest()[:16]
        if len(members) == 1:
            intervention = f"安排個別輔導，針對「{topic}」示範一個例題，再請學生獨立練習並說明步驟。"
        else:
            intervention = f"安排 {len(members)} 人小組複習「{topic}」，以例題示範和同儕討論釐清困難，再以短測驗確認理解。"
        result.append(Cluster(
            cluster_id=f"cluster-{digest}", topic=topic, size=len(members),
            members=[ClusterMember(
                moodle_user_id=student_id,
                display_name=evidence.names.get(student_id) or f"Student {student_id}",
            ) for student_id in members],
            suggested_intervention=intervention,
        ))
    return result

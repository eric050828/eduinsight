"""Additional authenticated analytics derived from existing stores.

Chat activity and grades are course-scoped. Lite-Mem facts have no course
ownership in this application: as in /teacher/students/{id}/memories, an
authorized teacher can read an enrolled student's facts. Responses explicitly
label this student-wide knowledge scope; topics are never guessed into courses.

Hours are estimates, not time tracking. Adjacent user messages in a registered
chat session count only when separated by at most 30 minutes. Without two
messages, a positive created_at/last_msg_at span of at most 30 minutes is used.
Long idle gaps and zero-length sessions contribute zero. Overlapping spans are
merged, clipped to now, and split at Taipei Monday boundaries.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite

from fastapi import APIRouter, Depends, HTTPException
from litemem import Memory

from . import assignments, sessions
from .analytics import _extract_natural_topic, _is_natural_struggle
from .auth import TEACHER_COURSE_MAP, AuthUser, get_current_user, require_role
from .courses import _check_course_access
from .grades import GradeManager

router = APIRouter(prefix="/analytics-extra", tags=["analytics-extra"])
_TAIPEI = timezone(timedelta(hours=8))
_MAX_GAP = 30 * 60
_TAG = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
_STRUGGLE = re.compile(r"^Struggling with:?\s+(.+?)(?:\s*[—:：]\s*.*)?$", re.I)
_MASTERED = re.compile(r"^Mastered:?\s+(.+?)(?:\s*[—:：]\s*.*)?$", re.I)


def get_memory() -> Memory:
    # Lazy imports avoid the application/router import cycle. Always resolve
    # the live assistant so /demo/reset replacing its Memory is respected.
    from .app import get_assistant

    return get_assistant().memory


def get_grade_manager() -> GradeManager:
    from .app import _grades

    return _grades


def _now() -> datetime:
    return datetime.now(_TAIPEI)


def _student_sessions(user: AuthUser, student_id: int) -> list[dict]:
    if user.role == "student" and user.moodle_user_id != student_id:
        raise HTTPException(403, "Students may only view their own data")
    owned = None
    if user.role == "teacher":
        owned = TEACHER_COURSE_MAP.get(user.username)
        if owned is None:
            raise HTTPException(403, "Teacher has no assigned course")
    with sessions._db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions WHERE moodle_user_id = ? ORDER BY session_id",
            (student_id,),
        ).fetchall()
    result = [dict(row) for row in rows if owned is None or row["course_id"] == owned]
    if owned is not None and not result:
        raise HTTPException(403, "Student is not enrolled in your course")
    return result


def _messages(memory: Memory, student_id: int, allowed: list[dict], *, scoped: bool) -> list[dict]:
    ids = {row["session_id"] for row in allowed}
    # Legacy messages without chat-session metadata are visible to their owner
    # and admins. They cannot be attributed to a teacher's course.
    return [
        row
        for row in memory._store.get_messages(f"moodle:{student_id}")
        if row["role"] == "user" and (not scoped or row["session_id"] in ids)
    ]


def _timestamp(value: object) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def _activity_spans(rows: list[dict], messages: list[dict]) -> list[tuple[float, float]]:
    by_session = defaultdict(list)
    for message in messages:
        timestamp = _timestamp(message["created_at"])
        if timestamp is not None:
            by_session[message["session_id"]].append(timestamp)
    spans = []
    for row in rows:
        stamps = sorted(set(by_session[row["session_id"]]))
        if len(stamps) >= 2:
            spans.extend((a, b) for a, b in zip(stamps, stamps[1:]) if 0 < b - a <= _MAX_GAP)
        else:
            start, end = _timestamp(row["created_at"]), _timestamp(row["last_msg_at"])
            if start is not None and end is not None and 0 < end - start <= _MAX_GAP:
                spans.append((start, end))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _knowledge(memory: Memory, student_id: int) -> list[dict]:
    """Score = 100 * mastered / (mastered + struggling); no evidence => 0.

    Only explicit mastered categories/prefixes or positive mastery phrases are
    evidence of mastery. Questions, assistant explanations and neutral facts
    are unknown, never evidence of mastery. Struggle takes precedence when a
    fact contains both signals (e.g. '尚未掌握'). Counts describe stored facts,
    not an externally validated assessment of ability.
    """
    topics = defaultdict(Counter)
    for record in memory.export(f"moodle:{student_id}").records:
        text = record.text.strip()
        tag = _TAG.match(text)
        body = tag.group(2) if tag else text
        struggle, mastered = _STRUGGLE.match(body), _MASTERED.match(body)
        topic = (
            tag.group(1).strip()
            if tag
            else struggle.group(1).strip()
            if struggle
            else mastered.group(1).strip()
            if mastered
            else _extract_natural_topic(text)
        )
        if not topic or record.category == "preference" or text.startswith("Learning preference:"):
            continue
        if (
            record.category == "struggling"
            or struggle
            or _is_natural_struggle(body)
            or any(word in body for word in ("尚未掌握", "未掌握", "不熟悉"))
        ):
            status = "struggling"
        elif (
            record.category == "mastered"
            or mastered
            or any(word in body for word in ("已掌握", "已熟練", "已精通"))
        ):
            status = "mastered"
        else:
            status = "unknown"
        topics[topic][status] += 1
    result = []
    for topic, counts in sorted(topics.items()):
        struggle, mastered = counts["struggling"], counts["mastered"]
        evidence = struggle + mastered
        result.append(
            {
                "topic": topic,
                "score": round(100 * mastered / evidence, 2) if evidence else 0,
                "status": "mixed"
                if struggle and mastered
                else "struggling"
                if struggle
                else "mastered"
                if mastered
                else "unknown",
                "struggling": struggle,
                "mastered": mastered,
                "unknown": counts["unknown"],
            }
        )
    return result


# Intent classification: case-insensitive substring matches, first category wins.
# Priority is debugging > exam > assignment > concept > other. Thus "debug my
# homework" is debugging; "exam homework" is exam prep. Only user messages count,
# each exactly once; no LLM calls or inference from assistant answers.
_INTENT_RULES = (
    ("除錯", ("除錯", "報錯", "錯誤", "bug", "debug", "error", "exception", "traceback")),
    ("考試準備", ("考試", "期中", "期末", "測驗", "複習", "exam", "midterm", "final", "quiz")),
    ("作業協助", ("作業", "功課", "繳交", "assignment", "homework")),
    (
        "概念釐清",
        (
            "概念",
            "什麼",
            "為什麼",
            "差別",
            "不同",
            "解釋",
            "不懂",
            "what",
            "why",
            "explain",
            "concept",
            "difference",
        ),
    ),
)


def _intents(messages: list[dict]) -> dict[str, int]:
    counts = dict.fromkeys(("概念釐清", "除錯", "作業協助", "考試準備", "其他"), 0)
    for message in messages:
        text = message["content"].casefold()
        category = next(
            (name for name, keywords in _INTENT_RULES if any(word in text for word in keywords)),
            "其他",
        )
        counts[category] += 1
    return counts


@router.get("/student/{moodle_user_id}/weekly-hours")
async def weekly_hours(moodle_user_id: int, user: AuthUser = Depends(get_current_user)) -> dict:
    rows = _student_sessions(user, moodle_user_id)
    messages = _messages(get_memory(), moodle_user_id, rows, scoped=user.role == "teacher")
    now = _now()
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    start = monday - timedelta(weeks=7)
    spans = _activity_spans(rows, messages)
    weeks = []
    for index in range(8):
        lower = start + timedelta(weeks=index)
        upper = min(lower + timedelta(weeks=1), now).timestamp()
        seconds = sum(
            max(0, min(end, upper) - max(begin, lower.timestamp())) for begin, end in spans
        )
        weeks.append({"week_start": lower.date().isoformat(), "hours": round(seconds / 3600, 4)})
    return {
        "moodle_user_id": moodle_user_id,
        "timezone": "Asia/Taipei",
        "estimated": True,
        "weeks": weeks,
    }


@router.get("/student/{moodle_user_id}/focus-heatmap")
async def focus_heatmap(moodle_user_id: int, user: AuthUser = Depends(get_current_user)) -> dict:
    rows = _student_sessions(user, moodle_user_id)
    messages = _messages(get_memory(), moodle_user_id, rows, scoped=user.role == "teacher")
    counts = [[0] * 24 for _ in range(7)]
    now = _now().timestamp()
    # Count all recorded user-message events through now. Metadata-only sessions
    # with a positive activity span contribute one last_msg_at event. Empty
    # sessions and assistant messages contribute none. No invented hourly spread.
    represented = {message["session_id"] for message in messages}
    stamps = [message["created_at"] for message in messages]
    stamps.extend(
        row["last_msg_at"]
        for row in rows
        if row["session_id"] not in represented and row["last_msg_at"] > row["created_at"]
    )
    for value in stamps:
        ts = _timestamp(value)
        if ts is None or ts < 0 or ts > now:
            continue
        when = datetime.fromtimestamp(ts, _TAIPEI)
        counts[when.weekday()][when.hour] += 1
    return {
        "moodle_user_id": moodle_user_id,
        "timezone": "Asia/Taipei",
        "weekday_order": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "counts": counts,
    }


@router.get("/student/{moodle_user_id}/skills")
async def skills(moodle_user_id: int, user: AuthUser = Depends(get_current_user)) -> dict:
    _student_sessions(user, moodle_user_id)
    return {
        "moodle_user_id": moodle_user_id,
        "memory_scope": "student",
        "skills": _knowledge(get_memory(), moodle_user_id),
    }


@router.get("/student/{moodle_user_id}/assignment-completion")
async def assignment_completion(
    moodle_user_id: int,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    rows = _student_sessions(user, moodle_user_id)
    now = _now().timestamp()
    courses = []
    with assignments._db() as conn:
        for course_id in sorted({row["course_id"] for row in rows}):
            work = conn.execute(
                "SELECT a.due_at, s.state FROM assignments a LEFT JOIN assignment_submissions s "
                "ON s.assignment_id = a.id AND s.student_id = ? WHERE a.course_id = ?",
                (moodle_user_id, course_id),
            ).fetchall()
            courses.append(
                {
                    "course_id": course_id,
                    "total": len(work),
                    # Graded work is also submitted. Overdue means still unsubmitted;
                    # a late submitted/graded assignment is not an outstanding task.
                    "submitted": sum(row["state"] in ("submitted", "graded") for row in work),
                    "graded": sum(row["state"] == "graded" for row in work),
                    "overdue": sum(
                        row["due_at"] < now and row["state"] not in ("submitted", "graded")
                        for row in work
                    ),
                }
            )
    return {"moodle_user_id": moodle_user_id, "courses": courses}


def _grade_averages(course_id: str, enrolled: set[int]) -> dict[int, float]:
    grades = defaultdict(list)
    for row in get_grade_manager().get_scores(course_id):
        if row.student_id in enrolled and row.total > 0:
            grades[row.student_id].append(100 * row.score / row.total)
    # The gradebook is authoritative where populated. Otherwise graded
    # assignment submissions supply actual grades. Never combine both sources
    # for a student, which could double count the same assignment.
    with assignments._db() as conn:
        rows = conn.execute(
            "SELECT s.student_id, s.score, a.max_score FROM assignment_submissions s "
            "JOIN assignments a ON a.id = s.assignment_id "
            "WHERE a.course_id = ? AND s.state = 'graded' AND s.score IS NOT NULL",
            (course_id,),
        ).fetchall()
    from_assignments = defaultdict(list)
    for row in rows:
        if row["student_id"] in enrolled:
            from_assignments[row["student_id"]].append(100 * row["score"] / row["max_score"])
    for student_id, values in from_assignments.items():
        if student_id not in grades:
            grades[student_id] = values
    return {student_id: sum(values) / len(values) for student_id, values in grades.items()}


@router.get("/course/{course_id}/student/{moodle_user_id}/overview")
async def student_overview(
    course_id: str,
    moodle_user_id: int,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> dict:
    _check_course_access(user, course_id)
    rows = [row for row in _student_sessions(user, moodle_user_id) if row["course_id"] == course_id]
    if not rows:
        raise HTTPException(403, "Student is not enrolled in this course")
    with sessions._db() as conn:
        enrolled = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT moodle_user_id FROM chat_sessions WHERE course_id = ?",
                (course_id,),
            )
        }
    averages = _grade_averages(course_id, enrolled)
    average = averages.get(moodle_user_id)
    # Competition ranking: tied averages share rank; missing grades have no rank.
    rank = 1 + sum(value > average for value in averages.values()) if average is not None else None
    memory = get_memory()
    return {
        "course_id": course_id,
        "moodle_user_id": moodle_user_id,
        "course_rank": rank,
        "grade_average": round(average, 2) if average is not None else None,
        "ranked_students": len(averages),
        "knowledge_scope": "student",
        "knowledge_mastery": _knowledge(memory, moodle_user_id),
        "intent_summary": _intents(_messages(memory, moodle_user_id, rows, scoped=True)),
    }

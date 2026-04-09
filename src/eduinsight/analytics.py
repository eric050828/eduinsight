"""Learning analytics extracted from Lite-Mem memory.

Analyzes student memory facts to identify:
- Weak topics per student
- Common class-wide struggles
- Learning trajectory over time
- Topic distribution and engagement patterns

All data comes from Lite-Mem's API (list, query_detail, detailed_stats).
No direct database access.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from litemem import Memory


def _student_uid(moodle_user_id: int) -> str:
    return f"moodle:{moodle_user_id}"


# ------------------------------------------------------------------
# Pattern extraction from fact text
# ------------------------------------------------------------------

_TOPIC_RE = re.compile(r"^\[([^\]]+)\]")
_STRUGGLE_RE = re.compile(r"^Struggling with:\s*(.+?)(?:\s*—\s*(.+))?$")
_PREFERENCE_RE = re.compile(r"^Learning preference:\s*(.+)$")
_QUESTION_RE = re.compile(r"^\[([^\]]+)\]\s*Q:\s*(.+)$")


@dataclass
class Struggle:
    """A single struggle extracted from a memory fact."""

    topic: str
    details: str = ""


@dataclass
class StudentAnalytics:
    """Analytics summary for a single student."""

    moodle_user_id: int
    total_facts: int = 0
    struggles: list[Struggle] = field(default_factory=list)
    weak_topics: list[str] = field(default_factory=list)  # topics sorted by struggle count
    question_topics: dict[str, int] = field(default_factory=dict)  # topic -> question count
    preferences: list[str] = field(default_factory=list)


@dataclass
class ClassAnalytics:
    """Analytics summary across all students."""

    total_students: int = 0
    total_facts: int = 0
    common_struggles: list[tuple[str, int]] = field(default_factory=list)  # (topic, count)
    topic_distribution: dict[str, int] = field(default_factory=dict)  # topic -> total mentions
    students: list[StudentAnalytics] = field(default_factory=list)


def analyze_student(memory: Memory, moodle_user_id: int) -> StudentAnalytics:
    """Extract learning patterns for a single student.

    Parses all stored facts to identify struggles, question topics,
    and learning preferences.
    """
    uid = _student_uid(moodle_user_id)
    facts = memory.list(uid)

    result = StudentAnalytics(
        moodle_user_id=moodle_user_id,
        total_facts=len(facts),
    )

    struggle_topics: Counter[str] = Counter()
    question_topics: Counter[str] = Counter()

    for fact in facts:
        # Check for struggle pattern
        m = _STRUGGLE_RE.match(fact)
        if m:
            topic = m.group(1).strip()
            details = (m.group(2) or "").strip()
            result.struggles.append(Struggle(topic=topic, details=details))
            struggle_topics[topic] += 1
            continue

        # Check for learning preference
        m = _PREFERENCE_RE.match(fact)
        if m:
            result.preferences.append(m.group(1).strip())
            continue

        # Check for question with topic tag
        m = _QUESTION_RE.match(fact)
        if m:
            question_topics[m.group(1).strip()] += 1
            continue

        # Also count topic from any [Topic] tagged fact
        m = _TOPIC_RE.match(fact)
        if m:
            question_topics[m.group(1).strip()] += 1

    # Sort weak topics by struggle frequency (most struggled first)
    result.weak_topics = [t for t, _ in struggle_topics.most_common()]
    result.question_topics = dict(question_topics)

    return result


def analyze_class(memory: Memory) -> ClassAnalytics:
    """Extract learning patterns across all students.

    Identifies common struggles and topic distribution class-wide.
    """
    stats = memory.detailed_stats()

    result = ClassAnalytics()
    all_struggles: Counter[str] = Counter()
    all_topics: Counter[str] = Counter()

    for user_stat in stats.users:
        if not user_stat.user_id.startswith("moodle:"):
            continue

        moodle_id = int(user_stat.user_id.removeprefix("moodle:"))
        student = analyze_student(memory, moodle_id)
        result.students.append(student)

        # Aggregate struggles
        for s in student.struggles:
            all_struggles[s.topic] += 1

        # Aggregate topics
        for topic, count in student.question_topics.items():
            all_topics[topic] += count

    result.total_students = len(result.students)
    result.total_facts = sum(s.total_facts for s in result.students)
    result.common_struggles = all_struggles.most_common()
    result.topic_distribution = dict(all_topics.most_common())

    return result


# ------------------------------------------------------------------
# Learning trajectory over time
# ------------------------------------------------------------------


@dataclass
class TrajectoryPoint:
    """A single point in a student's learning trajectory (one week)."""

    week_start: str  # ISO date string (YYYY-MM-DD)
    new_facts: int = 0
    new_struggles: list[str] = field(default_factory=list)
    new_topics: list[str] = field(default_factory=list)
    cumulative_facts: int = 0
    cumulative_struggles: int = 0


@dataclass
class LearningTrajectory:
    """A student's learning progression over time."""

    moodle_user_id: int
    total_weeks: int = 0
    points: list[TrajectoryPoint] = field(default_factory=list)


def _week_key(ts: float) -> str:
    """Convert a Unix timestamp to the Monday of that week (ISO date)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    # Monday = 0, so subtract weekday to get Monday
    monday = dt.date() - __import__("datetime").timedelta(days=dt.weekday())
    return monday.isoformat()


def learning_trajectory(memory: Memory, moodle_user_id: int) -> LearningTrajectory:
    """Build a weekly learning trajectory for a student.

    Uses Memory.export() to get all facts with timestamps, then groups
    them by week to show how learning progresses over time.
    """
    uid = _student_uid(moodle_user_id)
    bundle = memory.export(uid)

    result = LearningTrajectory(moodle_user_id=moodle_user_id)

    if not bundle.records:
        return result

    # Group records by week
    weeks: dict[str, list] = {}
    for record in bundle.records:
        wk = _week_key(record.created_at)
        weeks.setdefault(wk, []).append(record)

    # Sort weeks chronologically
    sorted_weeks = sorted(weeks.keys())

    cumulative_facts = 0
    cumulative_struggles = 0

    for wk in sorted_weeks:
        records = weeks[wk]
        new_struggles: list[str] = []
        new_topics: list[str] = []

        for rec in records:
            m = _STRUGGLE_RE.match(rec.text)
            if m:
                new_struggles.append(m.group(1).strip())
                continue
            m = _TOPIC_RE.match(rec.text)
            if m:
                new_topics.append(m.group(1).strip())

        cumulative_facts += len(records)
        cumulative_struggles += len(new_struggles)

        result.points.append(
            TrajectoryPoint(
                week_start=wk,
                new_facts=len(records),
                new_struggles=new_struggles,
                new_topics=new_topics,
                cumulative_facts=cumulative_facts,
                cumulative_struggles=cumulative_struggles,
            )
        )

    result.total_weeks = len(sorted_weeks)
    return result

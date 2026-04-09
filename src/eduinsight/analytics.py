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
from collections import Counter
from dataclasses import dataclass, field

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

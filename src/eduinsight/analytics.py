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


# Maximum days of inactivity before a student is considered "inactive"
_INACTIVE_DAYS = 14


# ------------------------------------------------------------------
# Pattern extraction from fact text
# ------------------------------------------------------------------

_TOPIC_RE = re.compile(r"^\[([^\]]+)\]")
# Old format: "Struggling with: TOPIC — DETAILS"
# New format: "Struggling with TOPIC: DETAILS"
_STRUGGLE_RE = re.compile(r"^Struggling with:?\s+(.+?)(?:\s*[—:]\s*(.*))?$")
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


# ------------------------------------------------------------------
# Student risk assessment
# ------------------------------------------------------------------


@dataclass
class RiskFactor:
    """A single factor contributing to a student's risk level."""

    label: str
    severity: str  # "high", "medium", "low"
    detail: str = ""


@dataclass
class StudentRisk:
    """Risk assessment for a student based on memory activity patterns."""

    moodle_user_id: int
    risk_level: str  # "high", "medium", "low"
    persistence_score: int  # 0-100
    factors: list[RiskFactor] = field(default_factory=list)
    days_since_last_activity: int | None = None


def assess_risk(
    memory: Memory,
    moodle_user_id: int,
    *,
    class_avg_facts: float | None = None,
    now: float | None = None,
) -> StudentRisk:
    """Assess a student's risk level from their memory activity.

    Calculates a persistence score (0-100) based on:
    - Activity recency: how recently the student interacted
    - Activity volume: total facts compared to class average
    - Struggle ratio: proportion of struggles vs total facts
    - Activity trend: recent activity compared to earlier weeks

    Parameters
    ----------
    memory : Memory
        The Lite-Mem instance.
    moodle_user_id : int
        The student's Moodle user ID.
    class_avg_facts : float | None
        Average fact count across the class. If None, computed automatically.
    now : float | None
        Current timestamp (for testing). Defaults to time.time().
    """
    uid = _student_uid(moodle_user_id)
    now = now or time.time()
    factors: list[RiskFactor] = []

    # Get student data
    bundle = memory.export(uid)
    facts = memory.list(uid)
    total_facts = len(facts)

    # Edge case: no data at all
    if total_facts == 0:
        return StudentRisk(
            moodle_user_id=moodle_user_id,
            risk_level="high",
            persistence_score=0,
            factors=[RiskFactor(label="零互動", severity="high", detail="該學生沒有任何學習紀錄")],
            days_since_last_activity=None,
        )

    # --- Component scores (each 0-100) ---

    # 1. Recency score: based on days since last activity
    timestamps = [r.created_at for r in bundle.records]
    last_activity = max(timestamps)
    days_inactive = (now - last_activity) / 86400
    days_since = int(days_inactive)

    if days_inactive <= 3:
        recency_score = 100
    elif days_inactive <= 7:
        recency_score = 80
    elif days_inactive <= 14:
        recency_score = 50
        factors.append(RiskFactor(
            label="活動下降",
            severity="medium",
            detail=f"已 {days_since} 天未互動",
        ))
    else:
        recency_score = max(0, 30 - int(days_inactive - 14) * 2)
        factors.append(RiskFactor(
            label="長期消失",
            severity="high",
            detail=f"已 {days_since} 天未互動",
        ))

    # 2. Volume score: total facts relative to class average
    if class_avg_facts is None:
        stats = memory.detailed_stats()
        moodle_users = [u for u in stats.users if u.user_id.startswith("moodle:")]
        if len(moodle_users) > 1:
            class_avg_facts = sum(u.fact_count for u in moodle_users) / len(moodle_users)
        else:
            class_avg_facts = float(total_facts)  # only student, use own count

    if class_avg_facts > 0:
        volume_ratio = total_facts / class_avg_facts
    else:
        volume_ratio = 1.0

    if volume_ratio >= 1.0:
        volume_score = 100
    elif volume_ratio >= 0.7:
        volume_score = 80
    elif volume_ratio >= 0.4:
        volume_score = 50
        factors.append(RiskFactor(
            label="互動量偏低",
            severity="medium",
            detail=f"記憶數 {total_facts}，班級平均 {class_avg_facts:.0f}",
        ))
    else:
        volume_score = 20
        factors.append(RiskFactor(
            label="互動量嚴重不足",
            severity="high",
            detail=f"記憶數 {total_facts}，僅班級平均的 {volume_ratio:.0%}",
        ))

    # 3. Struggle ratio score
    sa = analyze_student(memory, moodle_user_id)
    struggle_count = len(sa.struggles)
    if total_facts > 0:
        struggle_ratio = struggle_count / total_facts
    else:
        struggle_ratio = 0.0

    if struggle_ratio <= 0.1:
        struggle_score = 100
    elif struggle_ratio <= 0.2:
        struggle_score = 80
    elif struggle_ratio <= 0.35:
        struggle_score = 55
        factors.append(RiskFactor(
            label="困難比例偏高",
            severity="medium",
            detail=f"{struggle_count} 項困難 / {total_facts} 筆記憶",
        ))
    else:
        struggle_score = 30
        factors.append(RiskFactor(
            label="困難比例過高",
            severity="high",
            detail=f"{struggle_count} 項困難 / {total_facts} 筆記憶 ({struggle_ratio:.0%})",
        ))

    # 4. Trend score: compare recent 2 weeks vs earlier activity
    two_weeks_ago = now - 14 * 86400
    recent_facts = sum(1 for ts in timestamps if ts >= two_weeks_ago)
    older_facts = total_facts - recent_facts

    if total_facts <= 3:
        # Not enough data to judge trend
        trend_score = 50
    elif older_facts == 0:
        # All activity is recent — good
        trend_score = 90
    else:
        # Compare rate: recent 2 weeks vs everything before
        total_days = max((now - min(timestamps)) / 86400, 1)
        older_days = max(total_days - 14, 1)
        older_rate = older_facts / older_days
        recent_rate = recent_facts / 14

        if older_rate > 0:
            trend_ratio = recent_rate / older_rate
        else:
            trend_ratio = 1.0

        if trend_ratio >= 0.8:
            trend_score = 90
        elif trend_ratio >= 0.4:
            trend_score = 60
        elif trend_ratio >= 0.1:
            trend_score = 35
            factors.append(RiskFactor(
                label="活動量驟降",
                severity="medium",
                detail=f"近兩週活動量僅為先前的 {trend_ratio:.0%}",
            ))
        else:
            trend_score = 10
            factors.append(RiskFactor(
                label="近乎停止活動",
                severity="high",
                detail=f"近兩週幾乎零互動（先前有 {older_facts} 筆記憶）",
            ))

    # --- Weighted persistence score ---
    persistence_score = int(
        recency_score * 0.35
        + volume_score * 0.25
        + struggle_score * 0.15
        + trend_score * 0.25
    )
    persistence_score = max(0, min(100, persistence_score))

    # --- Determine risk level ---
    if persistence_score >= 70:
        risk_level = "low"
    elif persistence_score >= 40:
        risk_level = "medium"
    else:
        risk_level = "high"

    return StudentRisk(
        moodle_user_id=moodle_user_id,
        risk_level=risk_level,
        persistence_score=persistence_score,
        factors=factors,
        days_since_last_activity=days_since,
    )

"""Teaching analytics report — weekly metrics, AI-grade correlation, exportable data.

Aggregates data from all subsystems (memory, grades, attendance, interaction,
quiz) to produce teaching effectiveness reports for teachers.

Usage::

    gen = ReportGenerator(
        memory=memory,
        grades=grades_mgr,
        attendance=att_mgr,
        interaction=interaction_mgr,
        quiz=quiz_mgr,
    )
    weekly = gen.weekly_report("ds101")
    correlation = gen.ai_grade_correlation("ds101")
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from litemem import Memory

from .analytics import analyze_class, assess_risk
from .attendance import AttendanceManager
from .grades import GradeManager
from .interaction import InteractionManager
from .live_quiz import QuizSessionManager, SessionStatus

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class StudentWeeklyMetric:
    """Per-student metrics for the weekly report."""

    student_id: int
    fact_count: int = 0
    struggle_count: int = 0
    risk_level: str = "unknown"
    persistence_score: int = 0
    weighted_grade: float | None = None
    attendance_rate: float | None = None  # 0-100


@dataclass
class WeeklyReport:
    """Aggregated weekly teaching effectiveness report for a course."""

    course_id: str
    total_students: int = 0

    # Memory / AI engagement
    total_facts: int = 0
    avg_facts_per_student: float = 0.0
    common_struggles: list[tuple[str, int]] = field(default_factory=list)
    high_risk_students: list[dict] = field(default_factory=list)

    # Grades
    grade_mean: float | None = None
    grade_median: float | None = None
    grade_std_dev: float | None = None
    grade_distribution: dict[str, int] = field(default_factory=dict)

    # Attendance
    total_sessions: int = 0
    avg_attendance_rate: float | None = None  # 0-100

    # Interaction
    total_polls: int = 0
    total_questions: int = 0
    total_danmaku: int = 0

    # Quiz
    total_quiz_sessions: int = 0
    avg_quiz_score: float | None = None  # 0-100

    # Per-student details
    students: list[StudentWeeklyMetric] = field(default_factory=list)


@dataclass
class CorrelationPoint:
    """A single student's AI engagement vs grade data point."""

    student_id: int
    fact_count: int
    struggle_count: int
    persistence_score: int
    weighted_grade: float


@dataclass
class AIGradeCorrelation:
    """Analysis of relationship between AI engagement and grades."""

    course_id: str
    points: list[CorrelationPoint] = field(default_factory=list)
    fact_grade_correlation: float | None = None
    persistence_grade_correlation: float | None = None
    insight: str = ""


# ------------------------------------------------------------------
# Pearson correlation (no scipy dependency)
# ------------------------------------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient.

    Returns None if fewer than 3 data points or zero variance.
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5

    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y), 4)


def _correlation_insight(r: float | None) -> str:
    """Generate a human-readable insight from a correlation coefficient."""
    if r is None:
        return "資料不足，無法計算相關性"
    abs_r = abs(r)
    direction = "正" if r > 0 else "負"
    if abs_r >= 0.7:
        strength = "強"
    elif abs_r >= 0.4:
        strength = "中等"
    elif abs_r >= 0.2:
        strength = "弱"
    else:
        return "AI 互動量與成績幾乎無相關性"
    return f"AI 互動量與成績呈{strength}{direction}相關 (r={r:.2f})"


# ------------------------------------------------------------------
# Report generator
# ------------------------------------------------------------------


class ReportGenerator:
    """Generates teaching analytics reports by aggregating all subsystems."""

    def __init__(
        self,
        *,
        memory: Memory,
        grades: GradeManager,
        attendance: AttendanceManager,
        interaction: InteractionManager,
        quiz: QuizSessionManager,
    ) -> None:
        self._memory = memory
        self._grades = grades
        self._attendance = attendance
        self._interaction = interaction
        self._quiz = quiz

    def weekly_report(self, course_id: str) -> WeeklyReport:
        """Generate a comprehensive weekly teaching report for a course."""
        report = WeeklyReport(course_id=course_id)

        # 1. Memory / AI engagement (class-wide)
        class_analytics = analyze_class(self._memory)
        report.total_students = class_analytics.total_students
        report.total_facts = class_analytics.total_facts
        report.avg_facts_per_student = (
            class_analytics.total_facts / class_analytics.total_students
            if class_analytics.total_students > 0
            else 0.0
        )
        report.common_struggles = class_analytics.common_struggles[:10]

        # Risk assessment per student
        avg_facts = report.avg_facts_per_student
        for sa in class_analytics.students:
            risk = assess_risk(
                self._memory,
                sa.moodle_user_id,
                class_avg_facts=avg_facts,
            )
            if risk.risk_level == "high":
                report.high_risk_students.append({
                    "student_id": sa.moodle_user_id,
                    "persistence_score": risk.persistence_score,
                    "factors": [f.label for f in risk.factors],
                })

        # 2. Grades (if configured for this course)
        try:
            overview = self._grades.class_overview(course_id)
            report.grade_mean = round(overview.mean, 2)
            report.grade_median = round(overview.median, 2)
            report.grade_std_dev = round(overview.std_dev, 2)
            report.grade_distribution = overview.distribution
        except KeyError:
            pass  # no grades configured for this course

        # 3. Attendance
        sessions = self._attendance.list_sessions(course_id=course_id)
        report.total_sessions = len(sessions)
        if sessions:
            rates = []
            for s in sessions:
                stats = self._attendance.session_stats(s.session_id)
                if report.total_students > 0:
                    rates.append(stats.total_checkins / report.total_students * 100)
            if rates:
                report.avg_attendance_rate = round(statistics.mean(rates), 1)

        # 4. Interaction (course-filtered)
        polls = [
            p for p in self._interaction.list_polls()
            if p.course_id == course_id
        ]
        report.total_polls = len(polls)
        questions = self._interaction.list_questions(course_id=course_id)
        report.total_questions = len(questions)
        danmaku = self._interaction.get_danmaku(course_id=course_id)
        report.total_danmaku = len(danmaku)

        # 5. Quiz sessions
        quiz_sessions = self._quiz.list_sessions(course_id=course_id)
        report.total_quiz_sessions = len(quiz_sessions)

        # Compute average quiz score from closed sessions
        quiz_scores: list[float] = []
        for qs in quiz_sessions:
            if qs.status == SessionStatus.CLOSED:
                stats = self._quiz.get_stats(qs.session_id)
                if stats.overall_correct_rate is not None:
                    quiz_scores.append(stats.overall_correct_rate * 100)
        if quiz_scores:
            report.avg_quiz_score = round(statistics.mean(quiz_scores), 1)

        # 6. Per-student metrics
        for sa in class_analytics.students:
            sid = sa.moodle_user_id
            metric = StudentWeeklyMetric(
                student_id=sid,
                fact_count=sa.total_facts,
                struggle_count=len(sa.struggles),
            )
            # Risk
            risk = assess_risk(
                self._memory,
                sid,
                class_avg_facts=avg_facts,
            )
            metric.risk_level = risk.risk_level
            metric.persistence_score = risk.persistence_score

            # Grade
            try:
                summary = self._grades.student_summary(course_id, sid)
                metric.weighted_grade = summary.weighted_total
            except KeyError:
                pass

            # Attendance rate
            history = self._attendance.student_history(sid, course_id=course_id)
            if report.total_sessions > 0:
                metric.attendance_rate = round(
                    len(history) / report.total_sessions * 100, 1
                )

            report.students.append(metric)

        return report

    def ai_grade_correlation(self, course_id: str) -> AIGradeCorrelation:
        """Analyze correlation between AI engagement and grades.

        Pairs each student's memory fact count / persistence score with
        their weighted grade to compute Pearson correlation.
        """
        result = AIGradeCorrelation(course_id=course_id)

        class_analytics = analyze_class(self._memory)
        avg_facts = (
            class_analytics.total_facts / class_analytics.total_students
            if class_analytics.total_students > 0
            else 0.0
        )

        for sa in class_analytics.students:
            sid = sa.moodle_user_id
            try:
                summary = self._grades.student_summary(course_id, sid)
            except KeyError:
                continue
            if summary.weighted_total == 0:
                continue

            risk = assess_risk(
                self._memory,
                sid,
                class_avg_facts=avg_facts,
            )
            result.points.append(
                CorrelationPoint(
                    student_id=sid,
                    fact_count=sa.total_facts,
                    struggle_count=len(sa.struggles),
                    persistence_score=risk.persistence_score,
                    weighted_grade=summary.weighted_total,
                )
            )

        if result.points:
            facts = [p.fact_count for p in result.points]
            grades = [p.weighted_grade for p in result.points]
            persistence = [float(p.persistence_score) for p in result.points]

            result.fact_grade_correlation = _pearson(
                [float(f) for f in facts], grades
            )
            result.persistence_grade_correlation = _pearson(persistence, grades)

        # Pick the stronger correlation for insight
        r1 = result.fact_grade_correlation
        r2 = result.persistence_grade_correlation
        best_r = r1
        if r2 is not None and (r1 is None or abs(r2) > abs(r1)):
            best_r = r2
        result.insight = _correlation_insight(best_r)

        return result

"""AI Classroom Assistant — real-time teaching insights during class.

Aggregates live signals from quiz, polls, anonymous questions, danmaku,
and attendance to produce actionable suggestions for the teacher.

The assistant works in two modes:
1. **Rule-based** (instant, no LLM): pattern matching on live data
2. **AI-enhanced** (optional): LLM summarizes signals into natural language advice

Usage::

    assistant = ClassroomAssistant(
        quiz_mgr=quiz_manager,
        interaction_mgr=interaction_manager,
        attendance_mgr=attendance_manager,
    )
    snapshot = assistant.get_snapshot("CS101")
    # snapshot.alerts = ["40% 答錯第 2 題 (binary search)", ...]
    # snapshot.suggestions = ["建議再補充 binary search 概念", ...]
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .attendance import AttendanceManager, AttendanceSession
from .interaction import InteractionManager, PollStatus
from .live_quiz import QuizSessionManager, SessionStatus

# ── Thresholds ───────────────────────────────────────────────────────

LOW_CORRECT_RATE = 0.5  # Below this → flag as poorly understood
HIGH_CONFUSION_RATIO = 0.3  # ≥30% voted "confused" in poll → alert
QUESTION_SURGE_THRESHOLD = 5  # ≥5 unresolved questions → alert
LATE_RATIO_ALERT = 0.25  # ≥25% late arrivals → alert
LOW_PARTICIPATION = 0.4  # <40% of expected students answered → alert


@dataclass
class Alert:
    """A single real-time alert for the teacher."""

    level: str  # "warning" | "critical"
    source: str  # "quiz" | "poll" | "question" | "attendance" | "danmaku"
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class Suggestion:
    """An actionable suggestion derived from alerts."""

    text: str
    priority: int = 0  # higher = more urgent


@dataclass
class ClassroomSnapshot:
    """A point-in-time snapshot of classroom state with insights."""

    course_id: str
    timestamp: float
    alerts: list[Alert] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)

    # Raw metrics for the dashboard
    quiz_participation: float = 0.0  # fraction of students who answered
    quiz_avg_correct: float = 0.0  # average correct rate
    active_questions: int = 0  # unresolved anonymous questions
    attendance_present: int = 0
    attendance_late: int = 0
    attendance_total: int = 0
    poll_active: bool = False
    poll_confusion: float = 0.0  # fraction voted "confused" in latest poll
    danmaku_rate: float = 0.0  # messages per minute (last 5 min)

    @property
    def alert_count(self) -> int:
        return len(self.alerts)

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.alerts if a.level == "critical")


class ClassroomAssistant:
    """Real-time classroom insight engine.

    Pulls data from quiz, interaction, and attendance managers to generate
    alerts and suggestions for the teacher during class.
    """

    def __init__(
        self,
        *,
        quiz_mgr: QuizSessionManager | None = None,
        interaction_mgr: InteractionManager | None = None,
        attendance_mgr: AttendanceManager | None = None,
        expected_students: int = 30,
    ) -> None:
        self._quiz = quiz_mgr
        self._interaction = interaction_mgr
        self._attendance = attendance_mgr
        self._expected_students = expected_students

    def get_snapshot(
        self,
        course_id: str,
        *,
        now: float | None = None,
    ) -> ClassroomSnapshot:
        """Generate a real-time classroom snapshot with alerts and suggestions.

        Args:
            course_id: Course to analyze.
            now: Override current time (for testing).

        Returns:
            ClassroomSnapshot with alerts, suggestions, and raw metrics.
        """
        ts = now or time.time()
        snap = ClassroomSnapshot(course_id=course_id, timestamp=ts)

        self._analyze_quiz(course_id, snap)
        self._analyze_polls(course_id, snap)
        self._analyze_questions(course_id, snap)
        self._analyze_attendance(course_id, snap)
        self._analyze_danmaku(course_id, snap, ts)
        self._generate_suggestions(snap)

        # Sort: critical first, then warning
        snap.alerts.sort(key=lambda a: (0 if a.level == "critical" else 1))
        # Sort suggestions by priority descending
        snap.suggestions.sort(key=lambda s: s.priority, reverse=True)

        return snap

    # ── Quiz analysis ────────────────────────────────────────────

    def _analyze_quiz(self, course_id: str, snap: ClassroomSnapshot) -> None:
        if not self._quiz:
            return

        # Find the most recent active or closed session for this course
        sessions = self._quiz.list_sessions(course_id)
        active = [s for s in sessions if s.status in (SessionStatus.ACTIVE, SessionStatus.CLOSED)]
        if not active:
            return

        session = active[0]  # most recent
        stats = self._quiz.get_stats(session.session_id)

        snap.quiz_avg_correct = stats.overall_correct_rate
        if stats.total_students > 0 and self._expected_students > 0:
            snap.quiz_participation = stats.total_students / self._expected_students

        # Low participation alert
        if (
            snap.quiz_participation < LOW_PARTICIPATION
            and session.status == SessionStatus.ACTIVE
            and stats.total_students >= 1
        ):
            snap.alerts.append(Alert(
                level="warning",
                source="quiz",
                message=(
                    f"測驗參與率偏低：僅 {stats.total_students}"
                    f"/{self._expected_students} 位學生作答"
                ),
                data={"participation": snap.quiz_participation, "answered": stats.total_students},
            ))

        # Per-question analysis
        for qs in stats.questions:
            if qs.total_answers == 0:
                continue
            if qs.correct_rate < LOW_CORRECT_RATE:
                q_text = session.questions[qs.question_idx].question[:60]
                level = "critical" if qs.correct_rate < 0.3 else "warning"
                snap.alerts.append(Alert(
                    level=level,
                    source="quiz",
                    message=(
                        f"第 {qs.question_idx + 1} 題答對率僅 {qs.correct_rate:.0%}"
                        f"：{q_text}"
                    ),
                    data={
                        "question_idx": qs.question_idx,
                        "correct_rate": qs.correct_rate,
                        "distribution": qs.option_distribution,
                    },
                ))

    # ── Poll analysis ────────────────────────────────────────────

    def _analyze_polls(self, course_id: str, snap: ClassroomSnapshot) -> None:
        if not self._interaction:
            return

        polls = self._interaction.list_polls(course_id)
        active_polls = [p for p in polls if p.status == PollStatus.ACTIVE]
        if not active_polls:
            # Check most recently closed poll
            closed = [p for p in polls if p.status == PollStatus.CLOSED]
            if not closed:
                return
            poll = closed[0]
        else:
            poll = active_polls[0]
            snap.poll_active = True

        stats = self._interaction.poll_stats(poll.poll_id)

        # Detect confusion polls (common patterns: 懂/不太懂/完全不懂 or 理解/不理解)
        confusion_indices = self._detect_confusion_options(stats.options)
        if confusion_indices and stats.total_votes > 0:
            confused_votes = sum(stats.distribution[i] for i in confusion_indices)
            snap.poll_confusion = confused_votes / stats.total_votes

            if snap.poll_confusion >= HIGH_CONFUSION_RATIO:
                pct = snap.poll_confusion
                level = "critical" if pct >= 0.5 else "warning"
                snap.alerts.append(Alert(
                    level=level,
                    source="poll",
                    message=f"投票「{stats.title}」中 {pct:.0%} 的學生表示不理解",
                    data={
                        "poll_id": stats.poll_id,
                        "confusion_ratio": pct,
                        "distribution": stats.distribution,
                    },
                ))

    @staticmethod
    def _detect_confusion_options(options: list[str]) -> list[int]:
        """Identify which option indices represent confusion/not-understanding."""
        confusion_keywords = ["不懂", "不理解", "不太懂", "完全不懂", "不了解", "沒聽懂", "聽不懂"]
        indices = []
        for i, opt in enumerate(options):
            if any(kw in opt for kw in confusion_keywords):
                indices.append(i)
        return indices

    # ── Anonymous question analysis ──────────────────────────────

    def _analyze_questions(self, course_id: str, snap: ClassroomSnapshot) -> None:
        if not self._interaction:
            return

        questions = self._interaction.list_questions(course_id)
        unresolved = [q for q in questions if not q.resolved]
        snap.active_questions = len(unresolved)

        if snap.active_questions >= QUESTION_SURGE_THRESHOLD:
            # Find most upvoted unresolved question
            top_q = max(unresolved, key=lambda q: q.upvote_count)
            snap.alerts.append(Alert(
                level="warning",
                source="question",
                message=(
                    f"{snap.active_questions} 則未解答提問待處理，"
                    f"最多人關注：「{top_q.text[:50]}」"
                    f"({top_q.upvote_count} 👍)"
                ),
                data={"unresolved": snap.active_questions, "top_question": top_q.text},
            ))

        # High-upvote individual question
        for q in unresolved:
            if q.upvote_count >= 3:
                snap.alerts.append(Alert(
                    level="warning",
                    source="question",
                    message=f"提問獲 {q.upvote_count} 人附議：「{q.text[:50]}」",
                    data={"question_id": q.question_id, "upvotes": q.upvote_count},
                ))

    # ── Attendance analysis ──────────────────────────────────────

    def _analyze_attendance(self, course_id: str, snap: ClassroomSnapshot) -> None:
        if not self._attendance:
            return

        sessions = self._attendance.list_sessions(course_id)
        # Find the most recent open or recently closed session
        open_sessions = [s for s in sessions if s.status == "open"]
        if not open_sessions:
            return

        session: AttendanceSession = open_sessions[0]
        stats = self._attendance.session_stats(session.session_id)

        snap.attendance_present = stats.present_count
        snap.attendance_late = stats.late_count
        snap.attendance_total = stats.present_count + stats.late_count

        total_checked = snap.attendance_total
        if total_checked > 0 and stats.late_count > 0:
            late_ratio = stats.late_count / total_checked
            if late_ratio >= LATE_RATIO_ALERT:
                snap.alerts.append(Alert(
                    level="warning",
                    source="attendance",
                    message=(
                        f"遲到比例偏高：{stats.late_count}"
                        f"/{total_checked} 位學生遲到"
                        f" ({late_ratio:.0%})"
                    ),
                    data={"late_count": stats.late_count, "late_ratio": late_ratio},
                ))

    # ── Danmaku analysis ─────────────────────────────────────────

    def _analyze_danmaku(
        self, course_id: str, snap: ClassroomSnapshot, now: float
    ) -> None:
        if not self._interaction:
            return

        # Get recent danmaku (last 5 minutes)
        recent = self._interaction.get_danmaku(course_id, limit=200)
        window = 5 * 60  # 5 minutes
        in_window = [m for m in recent if (now - m.created_at) <= window]

        if in_window:
            snap.danmaku_rate = len(in_window) / (window / 60)  # per minute

        # Check for confusion keywords in danmaku
        confusion_kw = ["聽不懂", "不懂", "好難", "太快了", "什麼意思", "?", "？"]
        confused_msgs = [
            m for m in in_window
            if any(kw in m.text for kw in confusion_kw)
        ]
        if len(confused_msgs) >= 3:
            snap.alerts.append(Alert(
                level="warning",
                source="danmaku",
                message=f"彈幕出現 {len(confused_msgs)} 則「聽不懂」相關訊息（過去 5 分鐘）",
                data={"confused_count": len(confused_msgs), "window_minutes": 5},
            ))

    # ── Suggestion generation ────────────────────────────────────

    def _generate_suggestions(self, snap: ClassroomSnapshot) -> None:
        """Generate actionable suggestions from collected alerts."""
        quiz_alerts = [a for a in snap.alerts if a.source == "quiz"]
        poll_alerts = [a for a in snap.alerts if a.source == "poll"]
        question_alerts = [a for a in snap.alerts if a.source == "question"]
        danmaku_alerts = [a for a in snap.alerts if a.source == "danmaku"]
        attendance_alerts = [a for a in snap.alerts if a.source == "attendance"]

        # Quiz-based suggestions
        critical_quiz = [a for a in quiz_alerts if a.level == "critical"]
        if critical_quiz:
            topics = ", ".join(
                str(a.data.get("question_idx", 0) + 1)
                for a in critical_quiz[:3]
            )
            snap.suggestions.append(Suggestion(
                text=f"建議停下來重新講解：第 {topics} 題答對率極低，多數學生尚未理解",
                priority=10,
            ))
        elif quiz_alerts:
            snap.suggestions.append(Suggestion(
                text="部分測驗題目答對率偏低，建議快速複習相關概念後繼續",
                priority=5,
            ))

        # Low participation
        participation_alerts = [
            a for a in quiz_alerts
            if "參與率" in a.message
        ]
        if participation_alerts:
            snap.suggestions.append(Suggestion(
                text="測驗參與率不足，建議提醒學生作答，或延長作答時間",
                priority=7,
            ))

        # Poll confusion
        if poll_alerts:
            snap.suggestions.append(Suggestion(
                text="投票顯示部分學生不理解，建議換一種方式說明或舉例",
                priority=8,
            ))

        # Unresolved questions
        if question_alerts:
            snap.suggestions.append(Suggestion(
                text="多則匿名提問待回覆，建議撥 2-3 分鐘回應最多人關注的問題",
                priority=6,
            ))

        # Danmaku confusion signals
        if danmaku_alerts:
            snap.suggestions.append(Suggestion(
                text="彈幕出現較多「聽不懂」訊息，建議放慢速度或重複重點",
                priority=7,
            ))

        # Attendance
        if attendance_alerts:
            snap.suggestions.append(Suggestion(
                text="遲到比例偏高，可能需要提醒或調整上課時間",
                priority=3,
            ))

        # Positive feedback when no alerts
        if not snap.alerts:
            snap.suggestions.append(Suggestion(
                text="目前課堂狀況良好，學生理解度正常 👍",
                priority=0,
            ))

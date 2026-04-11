"""Live quiz session management for real-time classroom quizzes.

Supports the classroom quiz workflow:
1. Teacher creates a session from generated questions
2. Students join and submit answers
3. Real-time statistics: per-question correct rate, class performance

Usage::

    manager = QuizSessionManager()
    session = manager.create_session("CS101", questions, teacher_id=1001)
    manager.submit_answer(session.session_id, student_id=2001, question_idx=0, answer="B")
    stats = manager.get_stats(session.session_id)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class SessionStatus(StrEnum):
    """Quiz session lifecycle states."""

    WAITING = "waiting"  # Created, not yet open for answers
    ACTIVE = "active"  # Students can submit answers
    CLOSED = "closed"  # No more answers accepted


@dataclass
class QuizSessionQuestion:
    """A question within a live quiz session."""

    question: str
    options: dict[str, str]  # {"A": "...", "B": "...", "C": "...", "D": "..."}
    answer: str  # Correct answer key
    explanation: str = ""
    source: str = ""


@dataclass
class StudentAnswer:
    """A single student's answer to a question."""

    student_id: int
    question_idx: int
    selected: str  # "A", "B", "C", or "D"
    is_correct: bool
    submitted_at: float = field(default_factory=time.time)


@dataclass
class QuestionStats:
    """Real-time statistics for a single question."""

    question_idx: int
    total_answers: int = 0
    correct_count: int = 0
    option_distribution: dict[str, int] = field(
        default_factory=lambda: {"A": 0, "B": 0, "C": 0, "D": 0}
    )

    @property
    def correct_rate(self) -> float:
        """Fraction of students who answered correctly (0.0 - 1.0)."""
        if self.total_answers == 0:
            return 0.0
        return self.correct_count / self.total_answers


@dataclass
class SessionStats:
    """Aggregate statistics for the entire quiz session."""

    session_id: str
    status: SessionStatus
    total_students: int  # Unique students who answered at least one question
    total_questions: int
    questions: list[QuestionStats]
    overall_correct_rate: float  # Average correct rate across all questions


@dataclass
class QuizSession:
    """A live quiz session."""

    session_id: str
    course_id: str
    teacher_id: int
    title: str
    status: SessionStatus
    questions: list[QuizSessionQuestion]
    answers: list[StudentAnswer] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def get_student_ids(self) -> set[int]:
        """Get unique student IDs who submitted at least one answer."""
        return {a.student_id for a in self.answers}


class QuizSessionManager:
    """Manages live quiz sessions (in-memory store for demo).

    Thread-safety note: This is a single-process in-memory store.
    For production, replace with a database-backed implementation.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, QuizSession] = {}

    def create_session(
        self,
        course_id: str,
        questions: list[QuizSessionQuestion],
        *,
        teacher_id: int,
        title: str = "",
    ) -> QuizSession:
        """Create a new quiz session.

        Args:
            course_id: Course identifier.
            questions: List of questions for the session.
            teacher_id: Teacher who created the session.
            title: Optional session title.

        Returns:
            The created QuizSession.

        Raises:
            ValueError: If questions list is empty.
        """
        if not questions:
            raise ValueError("Cannot create session with no questions")

        session_id = f"qs_{uuid.uuid4().hex[:12]}"
        session = QuizSession(
            session_id=session_id,
            course_id=course_id,
            teacher_id=teacher_id,
            title=title or f"{course_id} Quiz",
            status=SessionStatus.WAITING,
            questions=questions,
        )
        self._sessions[session_id] = session
        return session

    def activate_session(self, session_id: str) -> QuizSession:
        """Open a session for student answers.

        Raises:
            KeyError: If session not found.
            ValueError: If session is already closed.
        """
        session = self._get_session(session_id)
        if session.status == SessionStatus.CLOSED:
            raise ValueError("Cannot activate a closed session")
        session.status = SessionStatus.ACTIVE
        return session

    def close_session(self, session_id: str) -> QuizSession:
        """Close a session (no more answers accepted).

        Raises:
            KeyError: If session not found.
        """
        session = self._get_session(session_id)
        session.status = SessionStatus.CLOSED
        return session

    def get_session(self, session_id: str) -> QuizSession:
        """Get session by ID.

        Raises:
            KeyError: If session not found.
        """
        return self._get_session(session_id)

    def list_sessions(self, course_id: str | None = None) -> list[QuizSession]:
        """List sessions, optionally filtered by course."""
        sessions = list(self._sessions.values())
        if course_id:
            sessions = [s for s in sessions if s.course_id == course_id]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    def submit_answer(
        self,
        session_id: str,
        *,
        student_id: int,
        question_idx: int,
        selected: str,
    ) -> StudentAnswer:
        """Submit a student's answer to a question.

        Args:
            session_id: Quiz session ID.
            student_id: Student identifier.
            question_idx: 0-based question index.
            selected: Answer choice ("A", "B", "C", or "D").

        Returns:
            The recorded StudentAnswer.

        Raises:
            KeyError: If session not found.
            ValueError: If session not active, invalid question index, or invalid option.
        """
        session = self._get_session(session_id)

        if session.status != SessionStatus.ACTIVE:
            raise ValueError(
                f"Session is '{session.status.value}', not accepting answers"
            )

        if question_idx < 0 or question_idx >= len(session.questions):
            raise ValueError(
                f"Invalid question index {question_idx} "
                f"(session has {len(session.questions)} questions)"
            )

        selected = selected.upper()
        if selected not in ("A", "B", "C", "D"):
            raise ValueError(f"Invalid option '{selected}', must be A/B/C/D")

        # Check for duplicate: same student, same question → replace
        session.answers = [
            a
            for a in session.answers
            if not (a.student_id == student_id and a.question_idx == question_idx)
        ]

        correct_answer = session.questions[question_idx].answer
        answer = StudentAnswer(
            student_id=student_id,
            question_idx=question_idx,
            selected=selected,
            is_correct=(selected == correct_answer),
        )
        session.answers.append(answer)
        return answer

    def get_stats(self, session_id: str) -> SessionStats:
        """Get real-time statistics for a session.

        Raises:
            KeyError: If session not found.
        """
        session = self._get_session(session_id)

        question_stats = []
        for idx in range(len(session.questions)):
            q_answers = [a for a in session.answers if a.question_idx == idx]
            dist = {"A": 0, "B": 0, "C": 0, "D": 0}
            correct = 0
            for a in q_answers:
                dist[a.selected] = dist.get(a.selected, 0) + 1
                if a.is_correct:
                    correct += 1
            question_stats.append(
                QuestionStats(
                    question_idx=idx,
                    total_answers=len(q_answers),
                    correct_count=correct,
                    option_distribution=dist,
                )
            )

        total_students = len(session.get_student_ids())
        rates = [qs.correct_rate for qs in question_stats if qs.total_answers > 0]
        overall_rate = sum(rates) / len(rates) if rates else 0.0

        return SessionStats(
            session_id=session_id,
            status=session.status,
            total_students=total_students,
            total_questions=len(session.questions),
            questions=question_stats,
            overall_correct_rate=overall_rate,
        )

    def get_student_results(
        self, session_id: str, student_id: int
    ) -> list[StudentAnswer]:
        """Get all answers submitted by a specific student.

        Raises:
            KeyError: If session not found.
        """
        session = self._get_session(session_id)
        return [a for a in session.answers if a.student_id == student_id]

    def _get_session(self, session_id: str) -> QuizSession:
        """Get session or raise KeyError."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found")
        return self._sessions[session_id]

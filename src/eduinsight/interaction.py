"""Real-time classroom interaction: polls, anonymous questions, danmaku (text wall).

Supports three interaction modes:
1. **Polls** — Teacher creates a poll, students vote, results shown in real-time.
2. **Anonymous Questions** — Students post questions anonymously, teacher sees them.
3. **Danmaku (Text Wall)** — Students send short messages displayed as a live stream.

Usage::

    mgr = InteractionManager()

    # Poll
    poll = mgr.create_poll(
        "CS101", teacher_id=1001, title="理解度",
        options=["懂了", "不太懂", "完全不懂"],
    )
    mgr.activate_poll(poll.poll_id)
    mgr.vote(poll.poll_id, student_id=2001, option_idx=0)
    stats = mgr.poll_stats(poll.poll_id)

    # Anonymous question
    q = mgr.post_question("CS101", text="什麼是 binary search?", student_id=2001)
    mgr.upvote_question(q.question_id, student_id=2002)

    # Danmaku
    msg = mgr.post_danmaku("CS101", text="+1 聽不懂", student_id=2001)
    recent = mgr.get_danmaku("CS101", limit=50)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

# ── Poll ──────────────────────────────────────────────────────────────


class PollStatus(StrEnum):
    WAITING = "waiting"
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass
class Poll:
    poll_id: str
    course_id: str
    teacher_id: int
    title: str
    options: list[str]
    status: PollStatus
    votes: dict[int, int] = field(default_factory=dict)  # student_id → option_idx
    created_at: float = field(default_factory=time.time)


@dataclass
class PollStats:
    poll_id: str
    title: str
    status: PollStatus
    options: list[str]
    total_votes: int
    distribution: list[int]  # vote count per option index


# ── Anonymous Question ────────────────────────────────────────────────


@dataclass
class AnonQuestion:
    question_id: str
    course_id: str
    student_id: int  # stored internally but never exposed via API
    text: str
    upvoters: set[int] = field(default_factory=set)
    resolved: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def upvote_count(self) -> int:
        return len(self.upvoters)


# ── Danmaku (Text Wall) ──────────────────────────────────────────────


@dataclass
class DanmakuMessage:
    message_id: str
    course_id: str
    student_id: int
    text: str
    created_at: float = field(default_factory=time.time)


# ── Manager ───────────────────────────────────────────────────────────


class InteractionManager:
    """In-memory manager for classroom interaction features.

    Thread-safety note: single-process demo store.
    """

    def __init__(self) -> None:
        self._polls: dict[str, Poll] = {}
        self._questions: dict[str, AnonQuestion] = {}
        self._danmaku: dict[str, list[DanmakuMessage]] = {}  # course_id → messages

    # ── Poll operations ───────────────────────────────────────────

    def create_poll(
        self,
        course_id: str,
        *,
        teacher_id: int,
        title: str,
        options: list[str],
    ) -> Poll:
        """Create a new poll.

        Raises:
            ValueError: If fewer than 2 options provided.
        """
        if len(options) < 2:
            raise ValueError("Poll must have at least 2 options")

        poll_id = f"poll_{uuid.uuid4().hex[:12]}"
        poll = Poll(
            poll_id=poll_id,
            course_id=course_id,
            teacher_id=teacher_id,
            title=title,
            options=options,
            status=PollStatus.WAITING,
        )
        self._polls[poll_id] = poll
        return poll

    def activate_poll(self, poll_id: str) -> Poll:
        """Open poll for voting.

        Raises:
            KeyError: If poll not found.
            ValueError: If poll is already closed.
        """
        poll = self._get_poll(poll_id)
        if poll.status == PollStatus.CLOSED:
            raise ValueError("Cannot activate a closed poll")
        poll.status = PollStatus.ACTIVE
        return poll

    def close_poll(self, poll_id: str) -> Poll:
        """Close poll (no more votes).

        Raises:
            KeyError: If poll not found.
        """
        poll = self._get_poll(poll_id)
        poll.status = PollStatus.CLOSED
        return poll

    def vote(self, poll_id: str, *, student_id: int, option_idx: int) -> None:
        """Cast or change a vote.

        Raises:
            KeyError: If poll not found.
            ValueError: If poll not active or option index invalid.
        """
        poll = self._get_poll(poll_id)
        if poll.status != PollStatus.ACTIVE:
            raise ValueError(f"Poll is '{poll.status.value}', not accepting votes")
        if option_idx < 0 or option_idx >= len(poll.options):
            raise ValueError(
                f"Invalid option index {option_idx} (poll has {len(poll.options)} options)"
            )
        poll.votes[student_id] = option_idx

    def poll_stats(self, poll_id: str) -> PollStats:
        """Get real-time poll results.

        Raises:
            KeyError: If poll not found.
        """
        poll = self._get_poll(poll_id)
        dist = [0] * len(poll.options)
        for opt_idx in poll.votes.values():
            dist[opt_idx] += 1
        return PollStats(
            poll_id=poll.poll_id,
            title=poll.title,
            status=poll.status,
            options=poll.options,
            total_votes=len(poll.votes),
            distribution=dist,
        )

    def get_poll(self, poll_id: str) -> Poll:
        """Get poll by ID.

        Raises:
            KeyError: If poll not found.
        """
        return self._get_poll(poll_id)

    def list_polls(self, course_id: str | None = None) -> list[Poll]:
        """List polls, optionally filtered by course."""
        polls = list(self._polls.values())
        if course_id:
            polls = [p for p in polls if p.course_id == course_id]
        return sorted(polls, key=lambda p: p.created_at, reverse=True)

    def _get_poll(self, poll_id: str) -> Poll:
        if poll_id not in self._polls:
            raise KeyError(f"Poll '{poll_id}' not found")
        return self._polls[poll_id]

    # ── Anonymous question operations ─────────────────────────────

    def post_question(
        self, course_id: str, *, text: str, student_id: int
    ) -> AnonQuestion:
        """Post an anonymous question.

        Raises:
            ValueError: If text is empty.
        """
        text = text.strip()
        if not text:
            raise ValueError("Question text cannot be empty")

        qid = f"aq_{uuid.uuid4().hex[:12]}"
        q = AnonQuestion(
            question_id=qid,
            course_id=course_id,
            student_id=student_id,
            text=text,
        )
        self._questions[qid] = q
        return q

    def upvote_question(self, question_id: str, *, student_id: int) -> int:
        """Upvote a question. Returns new upvote count.

        Each student can upvote once; duplicate upvotes are ignored.

        Raises:
            KeyError: If question not found.
        """
        q = self._get_question(question_id)
        q.upvoters.add(student_id)
        return q.upvote_count

    def resolve_question(self, question_id: str) -> AnonQuestion:
        """Mark a question as resolved (teacher action).

        Raises:
            KeyError: If question not found.
        """
        q = self._get_question(question_id)
        q.resolved = True
        return q

    def list_questions(
        self, course_id: str, *, include_resolved: bool = True
    ) -> list[AnonQuestion]:
        """List questions for a course, sorted by upvotes (desc) then time (desc)."""
        questions = [q for q in self._questions.values() if q.course_id == course_id]
        if not include_resolved:
            questions = [q for q in questions if not q.resolved]
        return sorted(
            questions,
            key=lambda q: (q.upvote_count, q.created_at),
            reverse=True,
        )

    def _get_question(self, question_id: str) -> AnonQuestion:
        if question_id not in self._questions:
            raise KeyError(f"Question '{question_id}' not found")
        return self._questions[question_id]

    # ── Danmaku (text wall) operations ────────────────────────────

    def post_danmaku(
        self, course_id: str, *, text: str, student_id: int
    ) -> DanmakuMessage:
        """Post a danmaku message.

        Raises:
            ValueError: If text is empty or exceeds 100 characters.
        """
        text = text.strip()
        if not text:
            raise ValueError("Danmaku text cannot be empty")
        if len(text) > 100:
            raise ValueError("Danmaku text cannot exceed 100 characters")

        mid = f"dm_{uuid.uuid4().hex[:12]}"
        msg = DanmakuMessage(
            message_id=mid,
            course_id=course_id,
            student_id=student_id,
            text=text,
        )
        self._danmaku.setdefault(course_id, []).append(msg)
        return msg

    def get_danmaku(
        self,
        course_id: str,
        *,
        limit: int = 50,
        since: float | None = None,
    ) -> list[DanmakuMessage]:
        """Get recent danmaku messages for a course.

        Args:
            course_id: Course identifier.
            limit: Max messages to return.
            since: If provided, only return messages after this timestamp.

        Returns:
            Messages sorted newest-first.
        """
        messages = self._danmaku.get(course_id, [])
        if since is not None:
            messages = [m for m in messages if m.created_at > since]
        return sorted(messages, key=lambda m: m.created_at, reverse=True)[:limit]

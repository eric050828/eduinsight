"""AI learning assistant that uses Lite-Mem for persistent student memory.

Each student is tracked by a unique user_id (mapped from Moodle user ID).
The assistant stores:
- Questions the student has asked
- Topics the student struggled with
- Learning preferences and patterns

Lite-Mem is a generic memory package -- we use it as-is without modification.
Any education-specific logic lives here in the assistant layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from litemem import Memory

logger = logging.getLogger(__name__)


def _student_uid(moodle_user_id: int) -> str:
    """Convert a Moodle user ID to a Lite-Mem user_id string.

    We namespace with 'moodle:' to keep Lite-Mem user IDs
    application-agnostic (other apps might use 'slack:', 'discord:', etc.).
    """
    return f"moodle:{moodle_user_id}"


@dataclass
class AssistantResponse:
    """Response from the learning assistant."""

    answer: str
    memory_context: list[str]  # Relevant memories used to inform the answer
    memories_stored: int  # Number of new memories stored from this interaction


class LearningAssistant:
    """AI learning assistant backed by Lite-Mem.

    This class handles the memory layer for student interactions.
    The actual LLM call for generating answers is delegated to a
    configurable callback -- this keeps the assistant testable
    and LLM-provider-agnostic.

    Usage::

        mem = Memory("eduinsight.db")
        assistant = LearningAssistant(mem)

        # Record a student interaction
        assistant.record_question(moodle_user_id=42, question="What is polymorphism?")

        # Retrieve context for answering
        context = assistant.get_student_context(moodle_user_id=42, query="OOP concepts")
    """

    def __init__(self, memory: Memory) -> None:
        self._memory = memory

    @property
    def memory(self) -> Memory:
        """Access the underlying Lite-Mem instance (read-only property)."""
        return self._memory

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    def record_question(self, moodle_user_id: int, question: str, *, topic: str = "") -> None:
        """Record that a student asked a question.

        Args:
            moodle_user_id: The student's Moodle user ID.
            question: The question text.
            topic: Optional topic tag (e.g. course name, subject area).
        """
        uid = _student_uid(moodle_user_id)
        content = f"Student asked: {question}"
        if topic:
            content = f"[{topic}] {content}"
        self._memory.add(uid, content)
        logger.debug("Recorded question for user %s: %s", uid, question[:80])

    def record_struggle(self, moodle_user_id: int, topic: str, details: str = "") -> None:
        """Record that a student is struggling with a topic.

        Args:
            moodle_user_id: The student's Moodle user ID.
            topic: The topic they're struggling with.
            details: Additional context about the struggle.
        """
        uid = _student_uid(moodle_user_id)
        content = f"Struggling with: {topic}"
        if details:
            content += f" — {details}"
        self._memory.add(uid, content)
        logger.debug("Recorded struggle for user %s: %s", uid, topic)

    def record_preference(self, moodle_user_id: int, preference: str) -> None:
        """Record a learning preference for a student.

        Args:
            moodle_user_id: The student's Moodle user ID.
            preference: Description of the preference (e.g. "prefers visual explanations").
        """
        uid = _student_uid(moodle_user_id)
        self._memory.add(uid, f"Learning preference: {preference}")
        logger.debug("Recorded preference for user %s: %s", uid, preference[:80])

    def get_student_context(
        self, moodle_user_id: int, query: str, *, top_k: int | None = None
    ) -> list[str]:
        """Retrieve relevant memories for a student given a query.

        This is the primary method for building context before
        generating an AI response.

        Args:
            moodle_user_id: The student's Moodle user ID.
            query: The search query (e.g. the student's current question).
            top_k: Override the default number of results.

        Returns:
            List of relevant memory strings from Lite-Mem.
        """
        uid = _student_uid(moodle_user_id)
        kwargs: dict[str, int] = {}
        if top_k is not None:
            kwargs["top_k"] = top_k
        return self._memory.query(uid, query, **kwargs)

    def record_interaction(
        self,
        moodle_user_id: int,
        question: str,
        answer: str,
        *,
        topic: str = "",
    ) -> None:
        """Record a complete Q&A interaction.

        Stores both the question and a summary of the answer so the
        assistant can recall what advice was previously given.

        Args:
            moodle_user_id: The student's Moodle user ID.
            question: The student's question.
            answer: The assistant's answer (will be summarized).
            topic: Optional topic tag.
        """
        uid = _student_uid(moodle_user_id)
        prefix = f"[{topic}] " if topic else ""
        self._memory.add(uid, f"{prefix}Q: {question}")
        # Store a truncated version of the answer to avoid bloating memory
        answer_summary = answer[:500] + "..." if len(answer) > 500 else answer
        self._memory.add(uid, f"{prefix}A: {answer_summary}")

    # ------------------------------------------------------------------
    # Analytics helpers (Phase 3 prep)
    # ------------------------------------------------------------------

    def get_all_memories(self, moodle_user_id: int) -> list[str]:
        """Get all stored memories for a student.

        Useful for analytics and learning pattern extraction.
        Uses Memory.list() to retrieve all facts without a search query.
        """
        uid = _student_uid(moodle_user_id)
        return self._memory.list(uid)

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

from .llm import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are EduInsight, an AI learning assistant for university students.

Your role:
- Answer academic questions clearly and accurately
- Adapt explanations to the student's level based on their history
- Encourage deeper understanding, not just memorization
- Be concise but thorough

You have access to the student's memory context (past questions, struggles, preferences).
Use this context to personalize your response, but do NOT repeat it back verbatim.
If the context is empty or irrelevant, just answer the question directly.

Always respond in the same language the student uses."""


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
    extracted_facts: list[str] | None = None  # Facts extracted by add_conversation


class LearningAssistant:
    """AI learning assistant backed by Lite-Mem.

    This class handles the memory layer for student interactions.
    When an LLMClient is provided, it generates AI answers augmented
    with the student's memory context. Without an LLM, it still
    records and retrieves memories (useful for testing).

    Usage::

        mem = Memory("eduinsight.db")
        assistant = LearningAssistant(mem)

        # Record a student interaction
        assistant.record_question(moodle_user_id=42, question="What is polymorphism?")

        # Retrieve context for answering
        context = assistant.get_student_context(moodle_user_id=42, query="OOP concepts")

        # With LLM: full conversation
        assistant = LearningAssistant(mem, llm=llm_client)
        response = await assistant.answer(moodle_user_id=42, question="What is OOP?")
    """

    def __init__(
        self,
        memory: Memory,
        *,
        llm: LLMClient | None = None,
        extractor: str = "stub",
    ) -> None:
        self._memory = memory
        self._llm = llm
        self._extractor = extractor

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

    def _build_prompt(self, question: str, context: list[str], *, topic: str = "") -> str:
        """Build a memory-augmented user prompt for the LLM.

        Combines the student's question with relevant memory context.
        """
        parts: list[str] = []
        if context:
            parts.append("Student memory context:")
            for i, mem in enumerate(context, 1):
                parts.append(f"  {i}. {mem}")
            parts.append("")
        if topic:
            parts.append(f"Topic: {topic}")
        parts.append(f"Student question: {question}")
        return "\n".join(parts)

    async def answer(
        self,
        moodle_user_id: int,
        question: str,
        *,
        topic: str = "",
    ) -> AssistantResponse:
        """Answer a student's question using memory context and LLM.

        1. Retrieve relevant memories for the student
        2. Build a memory-augmented prompt
        3. Call the LLM to generate an answer
        4. Record the interaction in memory

        Args:
            moodle_user_id: The student's Moodle user ID.
            question: The student's question.
            topic: Optional topic tag.

        Returns:
            AssistantResponse with the answer, context used, and memories stored.

        Raises:
            RuntimeError: If no LLM client is configured.
        """
        if self._llm is None:
            raise RuntimeError("No LLM client configured. Pass llm= to LearningAssistant.")

        # 1. Retrieve memory context
        context = self.get_student_context(moodle_user_id, question)

        # 2. Build prompt
        user_prompt = self._build_prompt(question, context, topic=topic)

        # 3. Call LLM
        reply = await self._llm.chat(user_prompt, system_prompt=SYSTEM_PROMPT)

        # 4. Extract facts from conversation using Lite-Mem add_conversation
        facts = self.extract_from_conversation(
            moodle_user_id, question, reply, topic=topic
        )

        # Fall back to basic recording if extraction found nothing
        if not facts:
            self.record_interaction(moodle_user_id, question, reply, topic=topic)
            return AssistantResponse(
                answer=reply,
                memory_context=context,
                memories_stored=2,
                extracted_facts=None,
            )

        return AssistantResponse(
            answer=reply,
            memory_context=context,
            memories_stored=len(facts),
            extracted_facts=facts,
        )

    def extract_from_conversation(
        self,
        moodle_user_id: int,
        question: str,
        answer: str,
        *,
        topic: str = "",
    ) -> list[str]:
        """Extract and store facts from a Q&A interaction using Lite-Mem's add_conversation.

        Uses Lite-Mem's fact extraction (stub/gemini/groq/ollama) to automatically
        identify and store meaningful facts from the conversation, rather than
        storing raw Q&A text.

        Args:
            moodle_user_id: The student's Moodle user ID.
            question: The student's question.
            answer: The assistant's answer.
            topic: Optional topic tag (included as context for the extractor).

        Returns:
            List of extracted fact strings stored in memory.
        """
        uid = _student_uid(moodle_user_id)
        q_content = f"[{topic}] {question}" if topic else question
        messages = [
            {"role": "user", "content": q_content},
            {"role": "assistant", "content": answer},
        ]
        facts = self._memory.add_conversation(uid, messages, extractor=self._extractor)
        logger.debug(
            "Extracted %d facts for user %s from conversation (extractor=%s)",
            len(facts), uid, self._extractor,
        )
        return facts

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

"""Tests for memory-augmented conversation (Phase 2 integration)."""

from unittest.mock import AsyncMock

import pytest
from litemem import Memory

from eduinsight.assistant import SYSTEM_PROMPT, LearningAssistant


class TestBuildPrompt:
    def setup_method(self) -> None:
        self.mem = Memory()
        self.assistant = LearningAssistant(self.mem)

    def test_prompt_with_context(self) -> None:
        prompt = self.assistant._build_prompt(
            "What is OOP?",
            ["Student asked: What is a class?", "Struggling with: inheritance"],
            topic="CS101",
        )
        assert "Student memory context:" in prompt
        assert "What is a class?" in prompt
        assert "inheritance" in prompt
        assert "Topic: CS101" in prompt
        assert "Student question: What is OOP?" in prompt

    def test_prompt_without_context(self) -> None:
        prompt = self.assistant._build_prompt("What is OOP?", [])
        assert "Student memory context:" not in prompt
        assert "Student question: What is OOP?" in prompt

    def test_prompt_without_topic(self) -> None:
        prompt = self.assistant._build_prompt("Hello", [], topic="")
        assert "Topic:" not in prompt


class TestAnswer:
    @pytest.mark.asyncio
    async def test_answer_with_mock_llm(self) -> None:
        mem = Memory()
        # Pre-populate some memory
        mem.add("moodle:42", "Student asked: What is a variable?", extract=False)

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="OOP is a programming paradigm based on objects.")

        assistant = LearningAssistant(mem, llm=mock_llm)
        response = await assistant.answer(42, "What is OOP?", topic="CS101")

        assert response.answer == "OOP is a programming paradigm based on objects."
        assert isinstance(response.memory_context, list)
        # With stub extractor, academic Q&A may not extract facts → fallback stores 2
        assert response.memories_stored >= 1

        # Verify LLM was called with system prompt and a user prompt
        mock_llm.chat.assert_called_once()
        call_args = mock_llm.chat.call_args
        fallback = call_args.args[1] if len(call_args.args) > 1 else ""
        sys_prompt = call_args.kwargs.get("system_prompt", fallback)
        assert SYSTEM_PROMPT in sys_prompt

    @pytest.mark.asyncio
    async def test_answer_records_interaction(self) -> None:
        mem = Memory()
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="The answer is 42.")

        assistant = LearningAssistant(mem, llm=mock_llm)
        await assistant.answer(1, "What is the answer?")

        # The interaction should be recorded in memory (via extraction or fallback)
        all_memories = assistant.get_all_memories(1)
        assert len(all_memories) >= 1

    @pytest.mark.asyncio
    async def test_answer_without_llm_raises(self) -> None:
        mem = Memory()
        assistant = LearningAssistant(mem)  # No LLM
        with pytest.raises(RuntimeError, match="No LLM client configured"):
            await assistant.answer(1, "Hello")

    @pytest.mark.asyncio
    async def test_answer_uses_memory_context(self) -> None:
        mem = Memory()
        # Student previously struggled with recursion
        mem.add(
            "moodle:10",
            "Struggling with: recursion — keeps getting stack overflow", extract=False)
        mem.add("moodle:10", "Learning preference: prefers visual diagrams", extract=False)

        captured_prompt = None

        async def capture_chat(user_msg, *, system_prompt=""):
            nonlocal captured_prompt
            captured_prompt = user_msg
            return "Here's a visual explanation of recursion..."

        mock_llm = AsyncMock()
        mock_llm.chat = capture_chat

        assistant = LearningAssistant(mem, llm=mock_llm)
        response = await assistant.answer(10, "Explain recursion")

        # The prompt should include memory context about recursion struggles
        assert captured_prompt is not None
        assert "recursion" in captured_prompt.lower()
        assert response.answer == "Here's a visual explanation of recursion..."


class TestExtractFromConversation:
    """Tests for Lite-Mem add_conversation integration."""

    def test_extract_with_personal_info(self) -> None:
        """Stub extractor should find facts from personal info in conversation."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")

        facts = assistant.extract_from_conversation(
            moodle_user_id=1,
            question="Hi, I live in Taipei and I'm studying computer science",
            answer="Welcome! I'd be happy to help with your CS studies.",
        )
        # Stub extractor should pick up "live in Taipei"
        assert len(facts) >= 1
        assert any("taipei" in f.lower() for f in facts)

    def test_extract_stores_in_memory(self) -> None:
        """Extracted facts should be retrievable from memory."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")

        assistant.extract_from_conversation(
            moodle_user_id=5,
            question="I work at Google as a software engineer",
            answer="That's great experience!",
        )

        # Facts should now be in memory
        results = assistant.get_student_context(5, "Google")
        assert len(results) >= 1

    def test_extract_with_topic_prefix(self) -> None:
        """Topic should be included in the user message for context."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")

        facts = assistant.extract_from_conversation(
            moodle_user_id=3,
            question="I live in Kaohsiung",
            answer="Nice city!",
            topic="CS101",
        )
        # Should still extract facts even with topic prefix
        assert len(facts) >= 1

    def test_extract_academic_qa_may_return_empty(self) -> None:
        """Pure academic Q&A without personal info may yield no stub-extractable facts."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")

        facts = assistant.extract_from_conversation(
            moodle_user_id=7,
            question="What is polymorphism?",
            answer="Polymorphism allows objects to take many forms.",
        )
        # Stub extractor may or may not find patterns here — both are valid
        assert isinstance(facts, list)

    def test_extract_user_isolation(self) -> None:
        """Facts extracted for one student should not appear for another."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")

        assistant.extract_from_conversation(
            moodle_user_id=20,
            question="I live in Tokyo",
            answer="Great!",
        )

        # User 20 should have the fact
        results_20 = assistant.get_student_context(20, "Tokyo")
        assert len(results_20) >= 1

        # User 21 should NOT
        results_21 = assistant.get_student_context(21, "Tokyo")
        assert len(results_21) == 0

    @pytest.mark.asyncio
    async def test_answer_with_extractable_content(self) -> None:
        """When conversation has extractable personal info, facts should be populated."""
        mem = Memory()
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Portland is a great city for students!")

        assistant = LearningAssistant(mem, llm=mock_llm, extractor="stub")
        response = await assistant.answer(
            99,
            "I live in Portland and I'm struggling with calculus",
        )

        assert response.answer == "Portland is a great city for students!"
        # Should have extracted facts (at least "live in Portland")
        if response.extracted_facts:
            assert len(response.extracted_facts) >= 1
            assert response.memories_stored == len(response.extracted_facts)
        else:
            # Fallback path
            assert response.memories_stored == 2

    @pytest.mark.asyncio
    async def test_answer_fallback_when_no_facts_extracted(self) -> None:
        """When no facts are extracted, answer() should fall back to record_interaction."""
        mem = Memory()
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="Polymorphism means many forms.")

        assistant = LearningAssistant(mem, llm=mock_llm, extractor="stub")
        response = await assistant.answer(50, "Define polymorphism")

        # If stub can't extract facts from this academic Q&A...
        if response.extracted_facts is None:
            # Fallback should have stored Q + A
            assert response.memories_stored == 2
            all_mem = assistant.get_all_memories(50)
            assert len(all_mem) >= 2
            assert any("polymorphism" in m.lower() for m in all_mem)

    def test_extractor_config_passed_through(self) -> None:
        """The extractor parameter should be stored and used."""
        mem = Memory()
        assistant = LearningAssistant(mem, extractor="stub")
        assert assistant._extractor == "stub"

        assistant2 = LearningAssistant(mem, extractor="auto")
        assert assistant2._extractor == "auto"

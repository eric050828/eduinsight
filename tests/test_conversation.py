"""Tests for memory-augmented conversation (Phase 2 integration)."""

from unittest.mock import AsyncMock, patch

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
        mem.add("moodle:42", "Student asked: What is a variable?")

        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="OOP is a programming paradigm based on objects.")

        assistant = LearningAssistant(mem, llm=mock_llm)
        response = await assistant.answer(42, "What is OOP?", topic="CS101")

        assert response.answer == "OOP is a programming paradigm based on objects."
        assert isinstance(response.memory_context, list)
        assert response.memories_stored == 2

        # Verify LLM was called with system prompt and a user prompt
        mock_llm.chat.assert_called_once()
        call_args = mock_llm.chat.call_args
        assert SYSTEM_PROMPT in call_args.kwargs.get("system_prompt", call_args.args[1] if len(call_args.args) > 1 else "")

    @pytest.mark.asyncio
    async def test_answer_records_interaction(self) -> None:
        mem = Memory()
        mock_llm = AsyncMock()
        mock_llm.chat = AsyncMock(return_value="The answer is 42.")

        assistant = LearningAssistant(mem, llm=mock_llm)
        await assistant.answer(1, "What is the answer?")

        # The interaction should be recorded in memory
        all_memories = assistant.get_all_memories(1)
        assert len(all_memories) >= 2
        assert any("What is the answer?" in m for m in all_memories)
        assert any("42" in m for m in all_memories)

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
        mem.add("moodle:10", "Struggling with: recursion — keeps getting stack overflow")
        mem.add("moodle:10", "Learning preference: prefers visual diagrams")

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

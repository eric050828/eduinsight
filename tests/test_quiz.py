"""Tests for AI quiz generation module."""

from __future__ import annotations

import json

import pytest
from litemem import Memory

from eduinsight.documents import DocumentChunk, ParsedDocument
from eduinsight.quiz import QuizGenerator, QuizQuestion, QuizResult, _parse_quiz_response
from eduinsight.rag import CourseRAG

# ------------------------------------------------------------------
# _parse_quiz_response tests
# ------------------------------------------------------------------


class TestParseQuizResponse:
    def test_valid_json_array(self):
        raw = json.dumps([
            {
                "question": "What is binary search?",
                "options": {
                    "A": "Linear scan", "B": "Divide and conquer",
                    "C": "Hashing", "D": "Sorting",
                },
                "answer": "B",
                "explanation": "Binary search divides the array in half.",
                "source": "lecture01.pdf p.1",
            }
        ])
        questions = _parse_quiz_response(raw)
        assert len(questions) == 1
        assert questions[0].question == "What is binary search?"
        assert questions[0].answer == "B"
        assert questions[0].options["B"] == "Divide and conquer"

    def test_markdown_fenced_json(self):
        raw = '```json\n' + json.dumps([
            {
                "question": "Q1?",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "A",
                "explanation": "Because A.",
            }
        ]) + '\n```'
        questions = _parse_quiz_response(raw)
        assert len(questions) == 1
        assert questions[0].answer == "A"

    def test_trailing_comma_cleanup(self):
        raw = """[
            {
                "question": "Q?",
                "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "answer": "C",
                "explanation": "reason",
            },
        ]"""
        questions = _parse_quiz_response(raw)
        assert len(questions) == 1

    def test_skips_malformed_questions(self):
        raw = json.dumps([
            {
                "question": "Good question?",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "A",
                "explanation": "ok",
            },
            {
                "question": "Bad - only 2 options",
                "options": {"A": "a", "B": "b"},
                "answer": "A",
                "explanation": "ok",
            },
            {
                "question": "Bad - answer not in options",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "E",
                "explanation": "ok",
            },
        ])
        questions = _parse_quiz_response(raw)
        assert len(questions) == 1
        assert questions[0].question == "Good question?"

    def test_empty_response(self):
        assert _parse_quiz_response("") == []

    def test_non_json_response(self):
        assert _parse_quiz_response("I cannot generate questions.") == []

    def test_json_with_surrounding_text(self):
        raw = 'Here are the questions:\n' + json.dumps([
            {
                "question": "Q?",
                "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "answer": "D",
                "explanation": "reason",
            }
        ]) + '\nHope these help!'
        questions = _parse_quiz_response(raw)
        assert len(questions) == 1
        assert questions[0].answer == "D"

    def test_multiple_questions(self):
        raw = json.dumps([
            {
                "question": f"Question {i}?",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "A",
                "explanation": f"Explanation {i}",
                "source": f"doc.pdf p.{i}",
            }
            for i in range(5)
        ])
        questions = _parse_quiz_response(raw)
        assert len(questions) == 5
        assert questions[2].source == "doc.pdf p.2"


# ------------------------------------------------------------------
# QuizQuestion dataclass tests
# ------------------------------------------------------------------


class TestQuizQuestion:
    def test_defaults(self):
        q = QuizQuestion(
            question="Q?",
            options={"A": "1", "B": "2", "C": "3", "D": "4"},
            answer="A",
            explanation="Because.",
        )
        assert q.source == ""

    def test_with_source(self):
        q = QuizQuestion(
            question="Q?",
            options={"A": "1", "B": "2", "C": "3", "D": "4"},
            answer="B",
            explanation="Because.",
            source="lecture.pdf p.3",
        )
        assert q.source == "lecture.pdf p.3"


# ------------------------------------------------------------------
# QuizGenerator tests (with mock LLM)
# ------------------------------------------------------------------


class MockLLM:
    """Mock LLM that returns a predefined quiz JSON response."""

    def __init__(self, response: str = "") -> None:
        self._response = response
        self.last_user_message: str = ""
        self.last_system_prompt: str = ""

    async def chat(
        self,
        user_message: str,
        *,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        self.last_user_message = user_message
        self.last_system_prompt = system_prompt
        return self._response


def _make_sample_doc() -> ParsedDocument:
    return ParsedDocument(
        filename="lecture01.pdf",
        total_pages=2,
        chunks=[
            DocumentChunk(
                text=(
                    "Binary search is a divide-and-conquer algorithm "
                    "that finds an element in O(log n) time."
                ),
                source="lecture01.pdf",
                page=1,
                chunk_index=0,
            ),
            DocumentChunk(
                text="Linear search checks each element sequentially with O(n) time complexity.",
                source="lecture01.pdf",
                page=2,
                chunk_index=1,
            ),
        ],
    )


def _valid_quiz_json(n: int = 2) -> str:
    return json.dumps([
        {
            "question": f"Question {i+1}?",
            "options": {
                "A": f"Option A{i}", "B": f"Option B{i}",
                "C": f"Option C{i}", "D": f"Option D{i}",
            },
            "answer": "B",
            "explanation": f"Explanation {i+1}",
            "source": f"lecture01.pdf p.{i+1}",
        }
        for i in range(n)
    ])


class TestQuizGenerator:
    @pytest.fixture
    def mem(self):
        return Memory(":memory:")

    @pytest.fixture
    def rag(self, mem):
        return CourseRAG(mem)

    @pytest.fixture
    def indexed_rag(self, rag):
        rag.index_document("CS101", _make_sample_doc())
        return rag

    @pytest.mark.asyncio
    async def test_generate_returns_questions(self, indexed_rag):
        llm = MockLLM(_valid_quiz_json(3))
        gen = QuizGenerator(indexed_rag, llm)
        result = await gen.generate("CS101", num_questions=3)
        assert isinstance(result, QuizResult)
        assert len(result.questions) == 3
        assert result.course_id == "CS101"
        assert result.chunks_used > 0

    @pytest.mark.asyncio
    async def test_generate_with_topic(self, indexed_rag):
        llm = MockLLM(_valid_quiz_json(2))
        gen = QuizGenerator(indexed_rag, llm)
        result = await gen.generate("CS101", topic="binary search", num_questions=2)
        assert result.topic == "binary search"
        assert "binary search" in llm.last_user_message.lower()

    @pytest.mark.asyncio
    async def test_generate_no_materials_raises(self, rag):
        llm = MockLLM(_valid_quiz_json())
        gen = QuizGenerator(rag, llm)
        with pytest.raises(ValueError, match="No materials found"):
            await gen.generate("EMPTY")

    @pytest.mark.asyncio
    async def test_generate_clamps_num_questions(self, indexed_rag):
        llm = MockLLM(_valid_quiz_json(5))
        gen = QuizGenerator(indexed_rag, llm)
        # num_questions > 20 should be clamped
        await gen.generate("CS101", num_questions=50)
        # The prompt should ask for 20 (clamped)
        assert "20" in llm.last_user_message

    @pytest.mark.asyncio
    async def test_generate_handles_llm_garbage(self, indexed_rag):
        llm = MockLLM("Sorry, I can't generate questions right now.")
        gen = QuizGenerator(indexed_rag, llm)
        result = await gen.generate("CS101", num_questions=3)
        assert result.questions == []
        assert result.chunks_used > 0

    @pytest.mark.asyncio
    async def test_generate_prompt_includes_material(self, indexed_rag):
        llm = MockLLM(_valid_quiz_json())
        gen = QuizGenerator(indexed_rag, llm)
        await gen.generate("CS101")
        # The user message should contain material text
        assert "binary search" in llm.last_user_message.lower()
        assert "lecture01.pdf" in llm.last_user_message

    @pytest.mark.asyncio
    async def test_system_prompt_is_quiz_focused(self, indexed_rag):
        llm = MockLLM(_valid_quiz_json())
        gen = QuizGenerator(indexed_rag, llm)
        await gen.generate("CS101")
        assert "multiple-choice" in llm.last_system_prompt.lower()
        assert "JSON" in llm.last_system_prompt


# ------------------------------------------------------------------
# Quiz API endpoint tests
# ------------------------------------------------------------------


class TestQuizAPI:
    @pytest.fixture
    def client(self):
        """Create a test client with mocked LLM for quiz generation."""

        from fastapi.testclient import TestClient

        from eduinsight import app as app_module

        mem = Memory(":memory:")
        rag = CourseRAG(mem)
        # Index sample materials
        rag.index_document("CS101", _make_sample_doc())

        mock_llm = MockLLM(_valid_quiz_json(3))
        quiz_gen = QuizGenerator(rag, mock_llm)

        with TestClient(app_module.app) as c:
            # Save originals created by lifespan, override for test
            orig_llm = app_module._llm
            app_module._memory = mem
            app_module._assistant = app_module.LearningAssistant(mem)
            app_module._rag = rag
            app_module._quiz = quiz_gen
            app_module._llm = mock_llm
            yield c
            # Restore original _llm so lifespan cleanup (__aexit__) works
            app_module._llm = orig_llm

    def test_generate_quiz_endpoint(self, client):
        resp = client.post("/courses/CS101/quiz/generate", json={"num_questions": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "CS101"
        assert len(data["questions"]) == 3
        assert data["chunks_used"] > 0
        # Verify question structure
        q = data["questions"][0]
        assert "question" in q
        assert "options" in q
        assert "answer" in q
        assert "explanation" in q

    def test_generate_quiz_with_topic(self, client):
        resp = client.post(
            "/courses/CS101/quiz/generate",
            json={"topic": "search algorithms", "num_questions": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "search algorithms"

    def test_generate_quiz_no_materials(self, client):
        resp = client.post("/courses/EMPTY/quiz/generate", json={"num_questions": 3})
        assert resp.status_code == 404
        assert "No materials found" in resp.json()["detail"]

    def test_generate_quiz_default_params(self, client):
        resp = client.post("/courses/CS101/quiz/generate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == ""

    @pytest.fixture
    def client_no_llm(self):
        """Test client without LLM (quiz disabled)."""
        from fastapi.testclient import TestClient

        from eduinsight import app as app_module

        mem = Memory(":memory:")

        with TestClient(app_module.app) as c:
            # Save originals created by lifespan, override for test
            orig_llm = app_module._llm
            app_module._memory = mem
            app_module._assistant = app_module.LearningAssistant(mem)
            app_module._rag = CourseRAG(mem)
            app_module._quiz = None
            app_module._llm = None
            yield c
            # Restore original _llm so lifespan cleanup (__aexit__) works
            app_module._llm = orig_llm

    def test_generate_quiz_no_llm_returns_503(self, client_no_llm):
        resp = client_no_llm.post("/courses/CS101/quiz/generate", json={})
        assert resp.status_code == 503
        assert "LLM" in resp.json()["detail"]

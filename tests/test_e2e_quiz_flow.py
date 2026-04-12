"""End-to-end integration test: RAG upload → AI quiz → live session → student answer → stats.

This tests the full "教材→AI→互動→分析" pipeline that is the core demo flow.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight.quiz import QuizGenerator
from eduinsight.rag import CourseRAG

# ------------------------------------------------------------------
# Mock LLM that returns valid quiz JSON
# ------------------------------------------------------------------


class _MockQuizLLM:
    """Returns quiz questions matching uploaded content."""

    async def chat(self, user_message: str, **kwargs) -> str:
        return json.dumps([
            {
                "question": "What time complexity does binary search have?",
                "options": {
                    "A": "O(n)",
                    "B": "O(log n)",
                    "C": "O(n²)",
                    "D": "O(1)",
                },
                "answer": "B",
                "explanation": "Binary search divides the search space in half each step.",
                "source": "test_material.pdf p.1",
            },
            {
                "question": "Which data structure does binary search require?",
                "options": {
                    "A": "Linked list",
                    "B": "Hash table",
                    "C": "Sorted array",
                    "D": "Stack",
                },
                "answer": "C",
                "explanation": "Binary search requires random access and sorted data.",
                "source": "test_material.pdf p.1",
            },
            {
                "question": "What is the worst case of linear search?",
                "options": {
                    "A": "O(1)",
                    "B": "O(log n)",
                    "C": "O(n log n)",
                    "D": "O(n)",
                },
                "answer": "D",
                "explanation": "Linear search may check every element.",
                "source": "test_material.pdf p.2",
            },
        ])


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_test_pdf() -> bytes:
    """Create a PDF with course material about search algorithms."""
    import fitz

    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text(
        (72, 72),
        "Binary search is a divide-and-conquer algorithm with O(log n) time complexity. "
        "It requires a sorted array and works by repeatedly dividing the search interval in half.",
    )
    p2 = doc.new_page()
    p2.insert_text(
        (72, 72),
        "Linear search checks each element sequentially with O(n) time complexity. "
        "It works on unsorted arrays but is slower than binary search for large inputs.",
    )
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def client():
    """Test client with RAG + mock LLM for the full pipeline."""
    mem = Memory(":memory:")
    rag = CourseRAG(mem)
    mock_llm = _MockQuizLLM()
    quiz_gen = QuizGenerator(rag, mock_llm)

    with TestClient(app_module.app) as c:
        orig_llm = app_module._llm
        app_module._memory = mem
        app_module._assistant = app_module.LearningAssistant(mem)
        app_module._rag = rag
        app_module._quiz = quiz_gen
        app_module._llm = mock_llm
        yield c
        app_module._llm = orig_llm


# ------------------------------------------------------------------
# End-to-end flow test
# ------------------------------------------------------------------


class TestE2EQuizFlow:
    """Full pipeline: upload material → generate quiz → live session → answer → stats."""

    def test_full_pipeline(self, client: TestClient):
        # ── Step 1: Upload course material (PDF) ──
        pdf_bytes = _make_test_pdf()
        resp = client.post(
            "/courses/ds101/materials",
            files={"file": ("search_algorithms.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        upload = resp.json()
        assert upload["status"] == "indexed"
        assert upload["chunks_indexed"] > 0
        assert upload["total_pages"] == 2

        # Verify material is listed
        resp = client.get("/courses/ds101/materials")
        assert resp.status_code == 200
        assert "search_algorithms.pdf" in resp.json()["documents"]

        # ── Step 2: Generate quiz from material ──
        resp = client.post(
            "/courses/ds101/quiz/generate",
            json={"topic": "search algorithms", "num_questions": 3},
        )
        assert resp.status_code == 200, f"Quiz gen failed: {resp.text}"
        quiz = resp.json()
        assert quiz["course_id"] == "ds101"
        assert len(quiz["questions"]) == 3
        assert quiz["chunks_used"] > 0
        questions = quiz["questions"]

        # ── Step 3: Create live quiz session from generated questions ──
        resp = client.post(
            "/quiz/sessions",
            json={
                "course_id": "ds101",
                "questions": questions,
                "title": "Search Algorithms Quiz",
            },
        )
        assert resp.status_code == 200, f"Create session failed: {resp.text}"
        session = resp.json()
        session_id = session["session_id"]
        assert session["status"] == "waiting"
        assert session["question_count"] == 3

        # ── Step 4: Activate session ──
        resp = client.post(f"/quiz/sessions/{session_id}/activate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

        # ── Step 5: Student gets questions (without answers) ──
        resp = client.get(f"/quiz/sessions/{session_id}/questions")
        assert resp.status_code == 200
        student_qs = resp.json()
        assert len(student_qs) == 3

        # ── Step 6: Students answer questions ──
        # Student 1001 answers all 3 correctly
        for i, q in enumerate(questions):
            resp = client.post(
                f"/quiz/sessions/{session_id}/answer",
                json={
                    "student_id": 1001,
                    "question_idx": i,
                    "selected": q["answer"],
                },
            )
            assert resp.status_code == 200
            assert resp.json()["is_correct"] is True

        # Student 1002 answers Q1 wrong, Q2 correct, Q3 wrong
        wrong_answers = {"B": "A", "C": "D", "D": "A"}  # maps correct → wrong
        student2_answers = [
            wrong_answers.get(questions[0]["answer"], "A"),  # wrong
            questions[1]["answer"],  # correct
            wrong_answers.get(questions[2]["answer"], "A"),  # wrong
        ]
        for i, ans in enumerate(student2_answers):
            resp = client.post(
                f"/quiz/sessions/{session_id}/answer",
                json={
                    "student_id": 1002,
                    "question_idx": i,
                    "selected": ans,
                },
            )
            assert resp.status_code == 200

        # ── Step 7: Check real-time stats ──
        resp = client.get(f"/quiz/sessions/{session_id}/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_students"] == 2
        assert stats["total_questions"] == 3
        # Overall correct rate: student1 got 3/3, student2 got 1/3 → 4/6 ≈ 66.7%
        assert 0.6 < stats["overall_correct_rate"] < 0.7

        # Per-question stats
        assert len(stats["questions"]) == 3
        # Q1: 1001 correct, 1002 wrong → 50%
        assert stats["questions"][0]["correct_rate"] == pytest.approx(0.5)
        # Q2: both correct → 100%
        assert stats["questions"][1]["correct_rate"] == pytest.approx(1.0)
        # Q3: 1001 correct, 1002 wrong → 50%
        assert stats["questions"][2]["correct_rate"] == pytest.approx(0.5)

        # ── Step 8: Close session ──
        resp = client.post(f"/quiz/sessions/{session_id}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

        # Verify no more answers accepted
        resp = client.post(
            f"/quiz/sessions/{session_id}/answer",
            json={"student_id": 1003, "question_idx": 0, "selected": "A"},
        )
        assert resp.status_code == 400

    def test_chat_with_rag_context(self, client: TestClient):
        """Verify that chat can reference uploaded course materials."""
        # Upload material first
        pdf_bytes = _make_test_pdf()
        client.post(
            "/courses/ds101/materials",
            files={"file": ("algo.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

        # Chat with course_id should include material context
        resp = client.post(
            "/chat",
            json={
                "moodle_user_id": 1001,
                "message": "What is binary search?",
                "course_id": "ds101",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # material_context should be populated (RAG found relevant chunks)
        assert data.get("material_context") is not None
        assert len(data["material_context"]) > 0

    def test_material_delete_removes_from_rag(self, client: TestClient):
        """Verify deleting material removes it from RAG search."""
        pdf_bytes = _make_test_pdf()
        client.post(
            "/courses/ds101/materials",
            files={"file": ("removeme.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

        # Confirm it's indexed
        resp = client.get("/courses/ds101/materials")
        assert "removeme.pdf" in resp.json()["documents"]

        # Delete it
        resp = client.delete("/courses/ds101/materials/removeme.pdf")
        assert resp.status_code == 200
        assert resp.json()["chunks_removed"] > 0

        # Confirm it's gone
        resp = client.get("/courses/ds101/materials")
        assert "removeme.pdf" not in resp.json()["documents"]

    def test_quiz_session_list(self, client: TestClient):
        """Verify listing quiz sessions works."""
        # Create a session with inline questions
        questions = [
            {
                "question": "Test Q?",
                "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "A",
                "explanation": "A is correct",
            }
        ]
        client.post(
            "/quiz/sessions",
            json={"course_id": "ds101", "questions": questions},
        )

        resp = client.get("/quiz/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 1
        assert sessions[0]["course_id"] == "ds101"

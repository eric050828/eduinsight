"""Tests for live quiz session management."""

from __future__ import annotations

import pytest

from eduinsight.live_quiz import (
    QuizSessionManager,
    QuizSessionQuestion,
    SessionStatus,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _sample_questions(n: int = 3) -> list[QuizSessionQuestion]:
    """Create n sample quiz questions."""
    questions = []
    for i in range(n):
        questions.append(
            QuizSessionQuestion(
                question=f"Question {i + 1}?",
                options={"A": f"A{i}", "B": f"B{i}", "C": f"C{i}", "D": f"D{i}"},
                answer="B",
                explanation=f"B is correct for Q{i + 1}",
                source=f"test.pdf p.{i + 1}",
            )
        )
    return questions


@pytest.fixture
def manager() -> QuizSessionManager:
    return QuizSessionManager()


@pytest.fixture
def active_session(manager: QuizSessionManager):
    """Create and activate a session with 3 questions."""
    session = manager.create_session(
        "CS101", _sample_questions(3), teacher_id=1001, title="Week 5 Quiz"
    )
    manager.activate_session(session.session_id)
    return session


# ------------------------------------------------------------------
# Session lifecycle tests
# ------------------------------------------------------------------


class TestSessionLifecycle:
    def test_create_session(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(2), teacher_id=1001
        )
        assert session.session_id.startswith("qs_")
        assert session.course_id == "CS101"
        assert session.status == SessionStatus.WAITING
        assert len(session.questions) == 2

    def test_create_with_title(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(1), teacher_id=1001, title="Midterm Quiz"
        )
        assert session.title == "Midterm Quiz"

    def test_create_empty_questions_raises(self, manager: QuizSessionManager):
        with pytest.raises(ValueError, match="no questions"):
            manager.create_session("CS101", [], teacher_id=1001)

    def test_activate_session(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(1), teacher_id=1001
        )
        activated = manager.activate_session(session.session_id)
        assert activated.status == SessionStatus.ACTIVE

    def test_close_session(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(1), teacher_id=1001
        )
        manager.activate_session(session.session_id)
        closed = manager.close_session(session.session_id)
        assert closed.status == SessionStatus.CLOSED

    def test_activate_closed_raises(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(1), teacher_id=1001
        )
        manager.activate_session(session.session_id)
        manager.close_session(session.session_id)
        with pytest.raises(ValueError, match="closed"):
            manager.activate_session(session.session_id)

    def test_get_session_not_found(self, manager: QuizSessionManager):
        with pytest.raises(KeyError):
            manager.get_session("nonexistent")

    def test_list_sessions(self, manager: QuizSessionManager):
        manager.create_session("CS101", _sample_questions(1), teacher_id=1001)
        manager.create_session("CS202", _sample_questions(1), teacher_id=1001)
        assert len(manager.list_sessions()) == 2
        assert len(manager.list_sessions(course_id="CS101")) == 1

    def test_list_sessions_sorted_newest_first(self, manager: QuizSessionManager):
        manager.create_session("CS101", _sample_questions(1), teacher_id=1001)
        s2 = manager.create_session("CS101", _sample_questions(1), teacher_id=1001)
        sessions = manager.list_sessions()
        assert sessions[0].session_id == s2.session_id


# ------------------------------------------------------------------
# Answer submission tests
# ------------------------------------------------------------------


class TestSubmitAnswer:
    def test_submit_correct_answer(self, manager: QuizSessionManager, active_session):
        answer = manager.submit_answer(
            active_session.session_id,
            student_id=2001,
            question_idx=0,
            selected="B",
        )
        assert answer.is_correct is True
        assert answer.selected == "B"

    def test_submit_wrong_answer(self, manager: QuizSessionManager, active_session):
        answer = manager.submit_answer(
            active_session.session_id,
            student_id=2001,
            question_idx=0,
            selected="A",
        )
        assert answer.is_correct is False

    def test_submit_to_waiting_session_raises(self, manager: QuizSessionManager):
        session = manager.create_session(
            "CS101", _sample_questions(1), teacher_id=1001
        )
        with pytest.raises(ValueError, match="not accepting"):
            manager.submit_answer(
                session.session_id, student_id=2001, question_idx=0, selected="A"
            )

    def test_submit_to_closed_session_raises(
        self, manager: QuizSessionManager, active_session
    ):
        manager.close_session(active_session.session_id)
        with pytest.raises(ValueError, match="not accepting"):
            manager.submit_answer(
                active_session.session_id,
                student_id=2001,
                question_idx=0,
                selected="A",
            )

    def test_invalid_question_idx_raises(
        self, manager: QuizSessionManager, active_session
    ):
        with pytest.raises(ValueError, match="Invalid question index"):
            manager.submit_answer(
                active_session.session_id,
                student_id=2001,
                question_idx=99,
                selected="A",
            )

    def test_invalid_option_raises(self, manager: QuizSessionManager, active_session):
        with pytest.raises(ValueError, match="Invalid option"):
            manager.submit_answer(
                active_session.session_id,
                student_id=2001,
                question_idx=0,
                selected="X",
            )

    def test_duplicate_answer_replaces(
        self, manager: QuizSessionManager, active_session
    ):
        manager.submit_answer(
            active_session.session_id,
            student_id=2001,
            question_idx=0,
            selected="A",
        )
        manager.submit_answer(
            active_session.session_id,
            student_id=2001,
            question_idx=0,
            selected="B",
        )
        results = manager.get_student_results(active_session.session_id, 2001)
        q0_answers = [r for r in results if r.question_idx == 0]
        assert len(q0_answers) == 1
        assert q0_answers[0].selected == "B"

    def test_case_insensitive_option(
        self, manager: QuizSessionManager, active_session
    ):
        answer = manager.submit_answer(
            active_session.session_id,
            student_id=2001,
            question_idx=0,
            selected="b",
        )
        assert answer.selected == "B"
        assert answer.is_correct is True


# ------------------------------------------------------------------
# Statistics tests
# ------------------------------------------------------------------


class TestStats:
    def test_empty_stats(self, manager: QuizSessionManager, active_session):
        stats = manager.get_stats(active_session.session_id)
        assert stats.total_students == 0
        assert stats.total_questions == 3
        assert stats.overall_correct_rate == 0.0
        assert all(q.total_answers == 0 for q in stats.questions)

    def test_stats_after_answers(self, manager: QuizSessionManager, active_session):
        sid = active_session.session_id
        # 3 students answer Q0: 2 correct, 1 wrong
        manager.submit_answer(sid, student_id=2001, question_idx=0, selected="B")
        manager.submit_answer(sid, student_id=2002, question_idx=0, selected="B")
        manager.submit_answer(sid, student_id=2003, question_idx=0, selected="A")

        stats = manager.get_stats(sid)
        assert stats.total_students == 3
        q0 = stats.questions[0]
        assert q0.total_answers == 3
        assert q0.correct_count == 2
        assert abs(q0.correct_rate - 2 / 3) < 0.01

    def test_option_distribution(self, manager: QuizSessionManager, active_session):
        sid = active_session.session_id
        manager.submit_answer(sid, student_id=2001, question_idx=0, selected="A")
        manager.submit_answer(sid, student_id=2002, question_idx=0, selected="A")
        manager.submit_answer(sid, student_id=2003, question_idx=0, selected="C")

        stats = manager.get_stats(sid)
        dist = stats.questions[0].option_distribution
        assert dist["A"] == 2
        assert dist["C"] == 1
        assert dist["B"] == 0
        assert dist["D"] == 0

    def test_overall_correct_rate(self, manager: QuizSessionManager, active_session):
        sid = active_session.session_id
        # Q0: 1/2 correct, Q1: 2/2 correct
        manager.submit_answer(sid, student_id=2001, question_idx=0, selected="B")
        manager.submit_answer(sid, student_id=2002, question_idx=0, selected="A")
        manager.submit_answer(sid, student_id=2001, question_idx=1, selected="B")
        manager.submit_answer(sid, student_id=2002, question_idx=1, selected="B")

        stats = manager.get_stats(sid)
        # Q0 rate = 0.5, Q1 rate = 1.0; overall = (0.5 + 1.0) / 2 = 0.75
        assert abs(stats.overall_correct_rate - 0.75) < 0.01

    def test_student_results(self, manager: QuizSessionManager, active_session):
        sid = active_session.session_id
        manager.submit_answer(sid, student_id=2001, question_idx=0, selected="B")
        manager.submit_answer(sid, student_id=2001, question_idx=1, selected="A")

        results = manager.get_student_results(sid, 2001)
        assert len(results) == 2
        assert results[0].is_correct is True
        assert results[1].is_correct is False


# ------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ------------------------------------------------------------------


@pytest.fixture
def client():
    """Create test client with app."""
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestLiveQuizAPI:
    def _create_and_activate(self, client) -> str:
        """Helper: create session and activate it, return session_id."""
        payload = {
            "course_id": "CS101",
            "title": "API Test Quiz",
            "questions": [
                {
                    "question": "What is 1+1?",
                    "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                    "answer": "B",
                    "explanation": "Basic math",
                    "source": "",
                },
                {
                    "question": "What is 2+2?",
                    "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
                    "answer": "B",
                    "explanation": "Basic math",
                    "source": "",
                },
            ],
        }
        resp = client.post("/quiz/sessions", json=payload)
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        resp = client.post(f"/quiz/sessions/{session_id}/activate")
        assert resp.status_code == 200
        return session_id

    def test_create_session(self, client):
        payload = {
            "course_id": "CS101",
            "title": "Test",
            "questions": [
                {
                    "question": "Q?",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "answer": "A",
                    "explanation": "e",
                    "source": "",
                }
            ],
        }
        resp = client.post("/quiz/sessions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["question_count"] == 1

    def test_activate_and_close(self, client):
        session_id = self._create_and_activate(client)
        resp = client.get(f"/quiz/sessions/{session_id}")
        assert resp.json()["status"] == "active"

        resp = client.post(f"/quiz/sessions/{session_id}/close")
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

    def test_get_questions_hides_answers(self, client):
        session_id = self._create_and_activate(client)
        resp = client.get(f"/quiz/sessions/{session_id}/questions")
        assert resp.status_code == 200
        questions = resp.json()
        assert len(questions) == 2
        # Should NOT include 'answer' field
        assert "answer" not in questions[0]
        assert "question" in questions[0]
        assert "options" in questions[0]

    def test_get_questions_before_active_403(self, client):
        payload = {
            "course_id": "CS101",
            "questions": [
                {
                    "question": "Q?",
                    "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                    "answer": "A",
                    "explanation": "e",
                    "source": "",
                }
            ],
        }
        resp = client.post("/quiz/sessions", json=payload)
        session_id = resp.json()["session_id"]
        resp = client.get(f"/quiz/sessions/{session_id}/questions")
        assert resp.status_code == 403

    def test_submit_answer_and_stats(self, client):
        session_id = self._create_and_activate(client)

        # Student 2001 answers Q0 correctly
        resp = client.post(
            f"/quiz/sessions/{session_id}/answer",
            json={"student_id": 2001, "question_idx": 0, "selected": "B"},
        )
        assert resp.status_code == 200
        assert resp.json()["is_correct"] is True
        assert resp.json()["correct_answer"] == "B"

        # Student 2002 answers Q0 incorrectly
        resp = client.post(
            f"/quiz/sessions/{session_id}/answer",
            json={"student_id": 2002, "question_idx": 0, "selected": "A"},
        )
        assert resp.json()["is_correct"] is False

        # Check stats
        resp = client.get(f"/quiz/sessions/{session_id}/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_students"] == 2
        assert stats["questions"][0]["correct_count"] == 1
        assert stats["questions"][0]["total_answers"] == 2
        assert abs(stats["questions"][0]["correct_rate"] - 0.5) < 0.01

    def test_list_sessions(self, client):
        self._create_and_activate(client)
        resp = client.get("/quiz/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) >= 1

    def test_session_not_found(self, client):
        resp = client.get("/quiz/sessions/nonexistent")
        assert resp.status_code == 404

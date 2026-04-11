"""Tests for classroom interaction: polls, anonymous questions, danmaku."""

from __future__ import annotations

import time

import pytest

from eduinsight.interaction import InteractionManager, PollStatus

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mgr() -> InteractionManager:
    return InteractionManager()


# ------------------------------------------------------------------
# Poll unit tests
# ------------------------------------------------------------------


class TestPollLifecycle:
    def test_create_poll(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="理解度", options=["懂了", "不太懂", "完全不懂"]
        )
        assert poll.poll_id.startswith("poll_")
        assert poll.status == PollStatus.WAITING
        assert poll.title == "理解度"
        assert len(poll.options) == 3

    def test_create_poll_too_few_options(self, mgr: InteractionManager):
        with pytest.raises(ValueError, match="at least 2"):
            mgr.create_poll("CS101", teacher_id=1001, title="Bad", options=["only one"])

    def test_activate_and_close(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B"]
        )
        mgr.activate_poll(poll.poll_id)
        assert mgr.get_poll(poll.poll_id).status == PollStatus.ACTIVE

        mgr.close_poll(poll.poll_id)
        assert mgr.get_poll(poll.poll_id).status == PollStatus.CLOSED

    def test_activate_closed_raises(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B"]
        )
        mgr.activate_poll(poll.poll_id)
        mgr.close_poll(poll.poll_id)
        with pytest.raises(ValueError, match="Cannot activate a closed poll"):
            mgr.activate_poll(poll.poll_id)

    def test_get_nonexistent_poll(self, mgr: InteractionManager):
        with pytest.raises(KeyError):
            mgr.get_poll("poll_nonexistent")

    def test_list_polls(self, mgr: InteractionManager):
        mgr.create_poll("CS101", teacher_id=1001, title="P1", options=["A", "B"])
        mgr.create_poll("CS102", teacher_id=1001, title="P2", options=["A", "B"])
        assert len(mgr.list_polls()) == 2
        assert len(mgr.list_polls("CS101")) == 1

    def test_list_polls_empty(self, mgr: InteractionManager):
        assert mgr.list_polls() == []


class TestVoting:
    def test_vote(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B", "C"]
        )
        mgr.activate_poll(poll.poll_id)
        mgr.vote(poll.poll_id, student_id=2001, option_idx=0)
        stats = mgr.poll_stats(poll.poll_id)
        assert stats.total_votes == 1
        assert stats.distribution == [1, 0, 0]

    def test_vote_inactive_raises(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B"]
        )
        with pytest.raises(ValueError, match="not accepting votes"):
            mgr.vote(poll.poll_id, student_id=2001, option_idx=0)

    def test_vote_invalid_option(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B"]
        )
        mgr.activate_poll(poll.poll_id)
        with pytest.raises(ValueError, match="Invalid option index"):
            mgr.vote(poll.poll_id, student_id=2001, option_idx=5)

    def test_vote_replaces_previous(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["A", "B"]
        )
        mgr.activate_poll(poll.poll_id)
        mgr.vote(poll.poll_id, student_id=2001, option_idx=0)
        mgr.vote(poll.poll_id, student_id=2001, option_idx=1)
        stats = mgr.poll_stats(poll.poll_id)
        assert stats.total_votes == 1
        assert stats.distribution == [0, 1]

    def test_multiple_voters(self, mgr: InteractionManager):
        poll = mgr.create_poll(
            "CS101", teacher_id=1001, title="Test", options=["Yes", "No"]
        )
        mgr.activate_poll(poll.poll_id)
        mgr.vote(poll.poll_id, student_id=2001, option_idx=0)
        mgr.vote(poll.poll_id, student_id=2002, option_idx=0)
        mgr.vote(poll.poll_id, student_id=2003, option_idx=1)
        stats = mgr.poll_stats(poll.poll_id)
        assert stats.total_votes == 3
        assert stats.distribution == [2, 1]


# ------------------------------------------------------------------
# Anonymous question unit tests
# ------------------------------------------------------------------


class TestAnonQuestions:
    def test_post_question(self, mgr: InteractionManager):
        q = mgr.post_question("CS101", text="什麼是 binary search?", student_id=2001)
        assert q.question_id.startswith("aq_")
        assert q.text == "什麼是 binary search?"
        assert q.upvote_count == 0
        assert q.resolved is False

    def test_empty_question_raises(self, mgr: InteractionManager):
        with pytest.raises(ValueError, match="cannot be empty"):
            mgr.post_question("CS101", text="", student_id=2001)

    def test_whitespace_only_raises(self, mgr: InteractionManager):
        with pytest.raises(ValueError, match="cannot be empty"):
            mgr.post_question("CS101", text="   ", student_id=2001)

    def test_upvote(self, mgr: InteractionManager):
        q = mgr.post_question("CS101", text="Help?", student_id=2001)
        count = mgr.upvote_question(q.question_id, student_id=2002)
        assert count == 1
        count = mgr.upvote_question(q.question_id, student_id=2003)
        assert count == 2

    def test_upvote_idempotent(self, mgr: InteractionManager):
        q = mgr.post_question("CS101", text="Help?", student_id=2001)
        mgr.upvote_question(q.question_id, student_id=2002)
        mgr.upvote_question(q.question_id, student_id=2002)
        assert q.upvote_count == 1

    def test_upvote_nonexistent_raises(self, mgr: InteractionManager):
        with pytest.raises(KeyError):
            mgr.upvote_question("aq_nonexistent", student_id=2001)

    def test_resolve(self, mgr: InteractionManager):
        q = mgr.post_question("CS101", text="Help?", student_id=2001)
        resolved = mgr.resolve_question(q.question_id)
        assert resolved.resolved is True

    def test_list_sorted_by_upvotes(self, mgr: InteractionManager):
        q1 = mgr.post_question("CS101", text="Q1", student_id=2001)
        q2 = mgr.post_question("CS101", text="Q2", student_id=2002)
        mgr.upvote_question(q2.question_id, student_id=2003)
        mgr.upvote_question(q2.question_id, student_id=2004)
        mgr.upvote_question(q1.question_id, student_id=2003)

        questions = mgr.list_questions("CS101")
        assert questions[0].question_id == q2.question_id  # 2 upvotes
        assert questions[1].question_id == q1.question_id  # 1 upvote

    def test_list_exclude_resolved(self, mgr: InteractionManager):
        q1 = mgr.post_question("CS101", text="Q1", student_id=2001)
        mgr.post_question("CS101", text="Q2", student_id=2002)
        mgr.resolve_question(q1.question_id)

        all_q = mgr.list_questions("CS101", include_resolved=True)
        assert len(all_q) == 2
        unresolved = mgr.list_questions("CS101", include_resolved=False)
        assert len(unresolved) == 1

    def test_list_empty_course(self, mgr: InteractionManager):
        assert mgr.list_questions("EMPTY") == []


# ------------------------------------------------------------------
# Danmaku unit tests
# ------------------------------------------------------------------


class TestDanmaku:
    def test_post_danmaku(self, mgr: InteractionManager):
        msg = mgr.post_danmaku("CS101", text="聽不懂+1", student_id=2001)
        assert msg.message_id.startswith("dm_")
        assert msg.text == "聽不懂+1"

    def test_empty_danmaku_raises(self, mgr: InteractionManager):
        with pytest.raises(ValueError, match="cannot be empty"):
            mgr.post_danmaku("CS101", text="", student_id=2001)

    def test_too_long_danmaku_raises(self, mgr: InteractionManager):
        with pytest.raises(ValueError, match="cannot exceed 100"):
            mgr.post_danmaku("CS101", text="x" * 101, student_id=2001)

    def test_get_danmaku_newest_first(self, mgr: InteractionManager):
        mgr.post_danmaku("CS101", text="msg1", student_id=2001)
        mgr.post_danmaku("CS101", text="msg2", student_id=2002)
        messages = mgr.get_danmaku("CS101")
        assert len(messages) == 2
        assert messages[0].created_at >= messages[1].created_at

    def test_get_danmaku_limit(self, mgr: InteractionManager):
        for i in range(10):
            mgr.post_danmaku("CS101", text=f"msg{i}", student_id=2001)
        messages = mgr.get_danmaku("CS101", limit=3)
        assert len(messages) == 3

    def test_get_danmaku_since(self, mgr: InteractionManager):
        mgr.post_danmaku("CS101", text="old", student_id=2001)
        cutoff = time.time()
        mgr.post_danmaku("CS101", text="new", student_id=2002)
        messages = mgr.get_danmaku("CS101", since=cutoff)
        assert len(messages) == 1
        assert messages[0].text == "new"

    def test_get_danmaku_empty_course(self, mgr: InteractionManager):
        assert mgr.get_danmaku("EMPTY") == []

    def test_danmaku_isolated_per_course(self, mgr: InteractionManager):
        mgr.post_danmaku("CS101", text="a", student_id=2001)
        mgr.post_danmaku("CS102", text="b", student_id=2001)
        assert len(mgr.get_danmaku("CS101")) == 1
        assert len(mgr.get_danmaku("CS102")) == 1


# ------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestPollAPI:
    def _create_active_poll(self, client) -> str:
        resp = client.post(
            "/interaction/polls",
            json={"course_id": "CS101", "title": "理解度", "options": ["懂", "不懂"]},
        )
        assert resp.status_code == 200
        poll_id = resp.json()["poll_id"]
        client.post(f"/interaction/polls/{poll_id}/activate")
        return poll_id

    def test_create_poll(self, client):
        resp = client.post(
            "/interaction/polls",
            json={"course_id": "CS101", "title": "Test", "options": ["A", "B", "C"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["options"] == ["A", "B", "C"]

    def test_poll_lifecycle(self, client):
        poll_id = self._create_active_poll(client)
        resp = client.get(f"/interaction/polls/{poll_id}/stats")
        assert resp.json()["status"] == "active"

        client.post(f"/interaction/polls/{poll_id}/close")
        resp = client.get(f"/interaction/polls/{poll_id}/stats")
        assert resp.json()["status"] == "closed"

    def test_vote_and_stats(self, client):
        poll_id = self._create_active_poll(client)
        client.post(
            f"/interaction/polls/{poll_id}/vote",
            json={"student_id": 2001, "option_idx": 0},
        )
        client.post(
            f"/interaction/polls/{poll_id}/vote",
            json={"student_id": 2002, "option_idx": 1},
        )
        resp = client.get(f"/interaction/polls/{poll_id}/stats")
        stats = resp.json()
        assert stats["total_votes"] == 2
        assert stats["distribution"] == [1, 1]

    def test_list_polls(self, client):
        self._create_active_poll(client)
        resp = client.get("/interaction/polls")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_poll_not_found(self, client):
        resp = client.post("/interaction/polls/nonexistent/activate")
        assert resp.status_code == 404


class TestQuestionAPI:
    def test_post_and_list(self, client):
        resp = client.post(
            "/interaction/questions",
            json={"course_id": "CS101", "student_id": 2001, "text": "什麼是 recursion?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "什麼是 recursion?"
        assert data["upvote_count"] == 0
        assert data["resolved"] is False

        resp = client.get("/interaction/questions", params={"course_id": "CS101"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_upvote(self, client):
        resp = client.post(
            "/interaction/questions",
            json={"course_id": "CS101", "student_id": 2001, "text": "Help?"},
        )
        qid = resp.json()["question_id"]
        resp = client.post(
            f"/interaction/questions/{qid}/upvote",
            json={"student_id": 2002},
        )
        assert resp.status_code == 200
        assert resp.json()["upvote_count"] == 1

    def test_resolve(self, client):
        resp = client.post(
            "/interaction/questions",
            json={"course_id": "CS101", "student_id": 2001, "text": "Q?"},
        )
        qid = resp.json()["question_id"]
        resp = client.post(f"/interaction/questions/{qid}/resolve")
        assert resp.status_code == 200
        assert resp.json()["resolved"] is True

    def test_question_not_found(self, client):
        resp = client.post(
            "/interaction/questions/nonexistent/upvote",
            json={"student_id": 2001},
        )
        assert resp.status_code == 404


class TestDanmakuAPI:
    def test_post_and_get(self, client):
        resp = client.post(
            "/interaction/danmaku",
            json={"course_id": "CS101", "student_id": 2001, "text": "+1"},
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "+1"

        resp = client.get("/interaction/danmaku", params={"course_id": "CS101"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_danmaku_limit(self, client):
        for i in range(5):
            client.post(
                "/interaction/danmaku",
                json={"course_id": "CS101", "student_id": 2001, "text": f"m{i}"},
            )
        resp = client.get(
            "/interaction/danmaku", params={"course_id": "CS101", "limit": 2}
        )
        assert len(resp.json()) == 2

    def test_empty_danmaku_rejected(self, client):
        resp = client.post(
            "/interaction/danmaku",
            json={"course_id": "CS101", "student_id": 2001, "text": ""},
        )
        assert resp.status_code == 400

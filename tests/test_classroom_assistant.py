"""Tests for the AI Classroom Assistant real-time insight engine."""

from __future__ import annotations

import time

import pytest

from eduinsight.attendance import AttendanceManager
from eduinsight.classroom_assistant import (
    ClassroomAssistant,
    ClassroomSnapshot,
)
from eduinsight.interaction import InteractionManager
from eduinsight.live_quiz import QuizSessionManager, QuizSessionQuestion

# ── Helpers ──────────────────────────────────────────────────────────

def _make_questions(n: int = 3) -> list[QuizSessionQuestion]:
    """Create n quiz questions with answer 'A'."""
    return [
        QuizSessionQuestion(
            question=f"Question {i + 1}: What is concept {i}?",
            options={"A": "Correct", "B": "Wrong1", "C": "Wrong2", "D": "Wrong3"},
            answer="A",
        )
        for i in range(n)
    ]


# ── Basic snapshot ───────────────────────────────────────────────────


class TestBasicSnapshot:
    def test_empty_snapshot_no_managers(self):
        """Snapshot with no managers = no alerts, positive message."""
        assistant = ClassroomAssistant()
        snap = assistant.get_snapshot("CS101")
        assert isinstance(snap, ClassroomSnapshot)
        assert snap.course_id == "CS101"
        assert snap.alert_count == 0
        assert snap.critical_count == 0
        assert len(snap.suggestions) == 1
        assert "良好" in snap.suggestions[0].text

    def test_empty_snapshot_with_managers(self):
        """Managers exist but no data → no alerts."""
        assistant = ClassroomAssistant(
            quiz_mgr=QuizSessionManager(),
            interaction_mgr=InteractionManager(),
            attendance_mgr=AttendanceManager(),
        )
        snap = assistant.get_snapshot("CS101")
        assert snap.alert_count == 0
        assert "良好" in snap.suggestions[0].text


# ── Quiz alerts ──────────────────────────────────────────────────────


class TestQuizAlerts:
    def test_low_correct_rate_warning(self):
        """Question with <50% correct rate triggers warning."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(2), teacher_id=1)
        qm.activate_session(session.session_id)
        # Q0: 1/3 correct (33%)
        qm.submit_answer(session.session_id, student_id=1, question_idx=0, selected="A")
        qm.submit_answer(session.session_id, student_id=2, question_idx=0, selected="B")
        qm.submit_answer(session.session_id, student_id=3, question_idx=0, selected="C")
        # Q1: 3/3 correct (100%)
        qm.submit_answer(session.session_id, student_id=1, question_idx=1, selected="A")
        qm.submit_answer(session.session_id, student_id=2, question_idx=1, selected="A")
        qm.submit_answer(session.session_id, student_id=3, question_idx=1, selected="A")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=3)
        snap = assistant.get_snapshot("CS101")

        quiz_alerts = [a for a in snap.alerts if a.source == "quiz"]
        assert len(quiz_alerts) >= 1
        assert any("第 1 題" in a.message for a in quiz_alerts)

    def test_critical_correct_rate(self):
        """Question with <30% correct rate triggers critical alert."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        # 0/4 correct (0%)
        for sid in range(1, 5):
            qm.submit_answer(session.session_id, student_id=sid, question_idx=0, selected="B")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=4)
        snap = assistant.get_snapshot("CS101")

        critical = [a for a in snap.alerts if a.level == "critical"]
        assert len(critical) >= 1
        assert critical[0].source == "quiz"

    def test_low_participation_alert(self):
        """<40% participation triggers warning."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        # Only 1 of 10 expected students answered
        qm.submit_answer(session.session_id, student_id=1, question_idx=0, selected="A")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=10)
        snap = assistant.get_snapshot("CS101")

        participation_alerts = [a for a in snap.alerts if "參與率" in a.message]
        assert len(participation_alerts) == 1

    def test_no_alert_on_good_results(self):
        """All correct → no quiz alerts."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(2), teacher_id=1)
        qm.activate_session(session.session_id)
        for sid in range(1, 6):
            for qi in range(2):
                qm.submit_answer(session.session_id, student_id=sid, question_idx=qi, selected="A")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=5)
        snap = assistant.get_snapshot("CS101")

        quiz_alerts = [a for a in snap.alerts if a.source == "quiz"]
        assert len(quiz_alerts) == 0

    def test_closed_session_still_analyzed(self):
        """Closed quiz session is still analyzed for insights."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        qm.submit_answer(session.session_id, student_id=1, question_idx=0, selected="B")
        qm.submit_answer(session.session_id, student_id=2, question_idx=0, selected="C")
        qm.close_session(session.session_id)

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=2)
        snap = assistant.get_snapshot("CS101")

        assert any(a.source == "quiz" for a in snap.alerts)


# ── Poll alerts ──────────────────────────────────────────────────────


class TestPollAlerts:
    def test_confusion_poll_alert(self):
        """≥30% voting confused → alert."""
        im = InteractionManager()
        poll = im.create_poll(
            "CS101", teacher_id=1, title="理解度",
            options=["懂了", "不太懂", "完全不懂"],
        )
        im.activate_poll(poll.poll_id)
        # 2 understand, 3 confused
        im.vote(poll.poll_id, student_id=1, option_idx=0)
        im.vote(poll.poll_id, student_id=2, option_idx=0)
        im.vote(poll.poll_id, student_id=3, option_idx=1)  # 不太懂
        im.vote(poll.poll_id, student_id=4, option_idx=2)  # 完全不懂
        im.vote(poll.poll_id, student_id=5, option_idx=2)  # 完全不懂

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        poll_alerts = [a for a in snap.alerts if a.source == "poll"]
        assert len(poll_alerts) == 1
        assert "60%" in poll_alerts[0].message
        assert snap.poll_active is True
        assert snap.poll_confusion == pytest.approx(0.6)

    def test_no_alert_when_understanding(self):
        """Majority understands → no poll alert."""
        im = InteractionManager()
        poll = im.create_poll("CS101", teacher_id=1, title="理解度", options=["懂了", "不太懂"])
        im.activate_poll(poll.poll_id)
        im.vote(poll.poll_id, student_id=1, option_idx=0)
        im.vote(poll.poll_id, student_id=2, option_idx=0)
        im.vote(poll.poll_id, student_id=3, option_idx=0)
        im.vote(poll.poll_id, student_id=4, option_idx=1)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        poll_alerts = [a for a in snap.alerts if a.source == "poll"]
        assert len(poll_alerts) == 0

    def test_non_confusion_poll_ignored(self):
        """Polls without confusion keywords don't generate confusion alerts."""
        im = InteractionManager()
        poll = im.create_poll(
            "CS101", teacher_id=1, title="喜歡的語言",
            options=["Python", "Java", "Go"],
        )
        im.activate_poll(poll.poll_id)
        im.vote(poll.poll_id, student_id=1, option_idx=0)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        poll_alerts = [a for a in snap.alerts if a.source == "poll"]
        assert len(poll_alerts) == 0

    def test_critical_confusion_above_50pct(self):
        """≥50% confused → critical level."""
        im = InteractionManager()
        poll = im.create_poll("CS101", teacher_id=1, title="check", options=["懂", "聽不懂"])
        im.activate_poll(poll.poll_id)
        im.vote(poll.poll_id, student_id=1, option_idx=1)
        im.vote(poll.poll_id, student_id=2, option_idx=1)
        im.vote(poll.poll_id, student_id=3, option_idx=0)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        poll_alerts = [a for a in snap.alerts if a.source == "poll"]
        assert len(poll_alerts) == 1
        assert poll_alerts[0].level == "critical"


# ── Anonymous question alerts ────────────────────────────────────────


class TestQuestionAlerts:
    def test_question_surge(self):
        """≥5 unresolved questions → alert."""
        im = InteractionManager()
        for i in range(6):
            im.post_question("CS101", text=f"Question {i}?", student_id=i + 1)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        assert snap.active_questions == 6
        q_alerts = [a for a in snap.alerts if a.source == "question" and "未解答" in a.message]
        assert len(q_alerts) == 1

    def test_high_upvote_alert(self):
        """Question with ≥3 upvotes → individual alert."""
        im = InteractionManager()
        q = im.post_question("CS101", text="What is recursion?", student_id=1)
        im.upvote_question(q.question_id, student_id=2)
        im.upvote_question(q.question_id, student_id=3)
        im.upvote_question(q.question_id, student_id=4)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")

        upvote_alerts = [a for a in snap.alerts if "附議" in a.message]
        assert len(upvote_alerts) == 1
        assert "3" in upvote_alerts[0].message

    def test_resolved_questions_not_counted(self):
        """Resolved questions don't count as active."""
        im = InteractionManager()
        for i in range(6):
            q = im.post_question("CS101", text=f"Q{i}", student_id=i + 1)
            im.resolve_question(q.question_id)

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101")
        assert snap.active_questions == 0


# ── Attendance alerts ────────────────────────────────────────────────


class TestAttendanceAlerts:
    def test_high_late_ratio(self):
        """≥25% late → alert."""
        am = AttendanceManager()
        session = am.create_session("CS101", teacher_id=1, title="Week 5")
        # Close this session — we'll create one with a short threshold
        am.close_session(session.session_id)

        # Create new session with very short threshold
        session2 = am.create_session("CS101", teacher_id=1, title="W5", late_threshold_sec=1)
        code2 = session2.checkin_code

        # Immediate checkins = present
        am.checkin(session2.session_id, student_id=1, code=code2)
        am.checkin(session2.session_id, student_id=2, code=code2)

        # Wait to make next students late
        import time as _time
        _time.sleep(1.1)

        am.checkin(session2.session_id, student_id=3, code=code2)

        assistant = ClassroomAssistant(attendance_mgr=am)
        snap = assistant.get_snapshot("CS101")

        att_alerts = [a for a in snap.alerts if a.source == "attendance"]
        assert len(att_alerts) == 1
        assert "遲到" in att_alerts[0].message

    def test_no_alert_all_on_time(self):
        """All students on time → no attendance alert."""
        am = AttendanceManager()
        session = am.create_session("CS101", teacher_id=1, late_threshold_sec=600)
        code = session.checkin_code

        for sid in range(1, 5):
            am.checkin(session.session_id, student_id=sid, code=code)

        assistant = ClassroomAssistant(attendance_mgr=am)
        snap = assistant.get_snapshot("CS101")

        att_alerts = [a for a in snap.alerts if a.source == "attendance"]
        assert len(att_alerts) == 0


# ── Danmaku alerts ───────────────────────────────────────────────────


class TestDanmakuAlerts:
    def test_confusion_burst(self):
        """≥3 confusion messages in 5 min → alert."""
        im = InteractionManager()
        now = time.time()
        # Post confusion messages with recent timestamps
        for i in range(4):
            msg = im.post_danmaku("CS101", text="聽不懂啦", student_id=i + 1)
            msg.created_at = now - 60  # 1 minute ago

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101", now=now)

        dmk_alerts = [a for a in snap.alerts if a.source == "danmaku"]
        assert len(dmk_alerts) == 1
        assert "4" in dmk_alerts[0].message

    def test_no_alert_normal_danmaku(self):
        """Normal (non-confusion) danmaku → no alert."""
        im = InteractionManager()
        now = time.time()
        for i in range(5):
            msg = im.post_danmaku("CS101", text="好酷！", student_id=i + 1)
            msg.created_at = now - 30

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101", now=now)

        dmk_alerts = [a for a in snap.alerts if a.source == "danmaku"]
        assert len(dmk_alerts) == 0

    def test_old_danmaku_ignored(self):
        """Confusion danmaku older than 5 min → ignored."""
        im = InteractionManager()
        now = time.time()
        for i in range(5):
            msg = im.post_danmaku("CS101", text="聽不懂", student_id=i + 1)
            msg.created_at = now - 400  # 6+ minutes ago

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101", now=now)

        dmk_alerts = [a for a in snap.alerts if a.source == "danmaku"]
        assert len(dmk_alerts) == 0

    def test_danmaku_rate_calculation(self):
        """Danmaku rate = messages per minute in window."""
        im = InteractionManager()
        now = time.time()
        for i in range(10):
            msg = im.post_danmaku("CS101", text=f"msg {i}", student_id=i + 1)
            msg.created_at = now - 120  # 2 min ago

        assistant = ClassroomAssistant(interaction_mgr=im)
        snap = assistant.get_snapshot("CS101", now=now)

        # 10 messages in 5-min window = 2.0 per minute
        assert snap.danmaku_rate == pytest.approx(2.0)


# ── Suggestions ──────────────────────────────────────────────────────


class TestSuggestions:
    def test_critical_quiz_generates_stop_suggestion(self):
        """Critical quiz alert → 'stop and re-explain' suggestion."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        for sid in range(1, 6):
            qm.submit_answer(session.session_id, student_id=sid, question_idx=0, selected="B")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=5)
        snap = assistant.get_snapshot("CS101")

        assert any("停下來" in s.text or "重新講解" in s.text for s in snap.suggestions)

    def test_multiple_sources_multiple_suggestions(self):
        """Alerts from different sources → multiple suggestions."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        qm.submit_answer(session.session_id, student_id=1, question_idx=0, selected="B")
        qm.submit_answer(session.session_id, student_id=2, question_idx=0, selected="C")

        im = InteractionManager()
        for i in range(6):
            im.post_question("CS101", text=f"Q{i}?", student_id=i + 1)

        assistant = ClassroomAssistant(quiz_mgr=qm, interaction_mgr=im, expected_students=2)
        snap = assistant.get_snapshot("CS101")

        assert len(snap.suggestions) >= 2

    def test_suggestions_sorted_by_priority(self):
        """Suggestions are sorted highest priority first."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        # 0% correct → critical
        for sid in range(1, 6):
            qm.submit_answer(session.session_id, student_id=sid, question_idx=0, selected="B")

        im = InteractionManager()
        for i in range(6):
            im.post_question("CS101", text=f"Q{i}?", student_id=i + 1)

        assistant = ClassroomAssistant(quiz_mgr=qm, interaction_mgr=im, expected_students=5)
        snap = assistant.get_snapshot("CS101")

        priorities = [s.priority for s in snap.suggestions]
        assert priorities == sorted(priorities, reverse=True)

    def test_alerts_sorted_critical_first(self):
        """Critical alerts come before warnings."""
        qm = QuizSessionManager()
        qs = _make_questions(3)
        session = qm.create_session("CS101", qs, teacher_id=1)
        qm.activate_session(session.session_id)
        # Q0: 0% correct (critical), Q1: 40% (warning), Q2: 100% (ok)
        for sid in range(1, 6):
            qm.submit_answer(session.session_id, student_id=sid, question_idx=0, selected="B")
        for sid in range(1, 6):
            sel = "A" if sid <= 2 else "B"
            qm.submit_answer(session.session_id, student_id=sid, question_idx=1, selected=sel)
        for sid in range(1, 6):
            qm.submit_answer(session.session_id, student_id=sid, question_idx=2, selected="A")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=5)
        snap = assistant.get_snapshot("CS101")

        levels = [a.level for a in snap.alerts]
        critical_indices = [i for i, lv in enumerate(levels) if lv == "critical"]
        warning_indices = [i for i, lv in enumerate(levels) if lv == "warning"]
        if critical_indices and warning_indices:
            assert max(critical_indices) < min(warning_indices)


# ── Course isolation ─────────────────────────────────────────────────


class TestCourseIsolation:
    def test_different_course_not_included(self):
        """Alerts from another course don't leak."""
        qm = QuizSessionManager()
        session = qm.create_session("CS102", _make_questions(1), teacher_id=1)
        qm.activate_session(session.session_id)
        qm.submit_answer(session.session_id, student_id=1, question_idx=0, selected="B")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=5)
        snap = assistant.get_snapshot("CS101")  # different course

        assert snap.alert_count == 0


# ── Snapshot properties ──────────────────────────────────────────────


class TestSnapshotProperties:
    def test_alert_count(self):
        snap = ClassroomSnapshot(course_id="CS101", timestamp=time.time())
        assert snap.alert_count == 0
        assert snap.critical_count == 0

    def test_quiz_metrics_populated(self):
        """Quiz participation and avg correct are populated."""
        qm = QuizSessionManager()
        session = qm.create_session("CS101", _make_questions(2), teacher_id=1)
        qm.activate_session(session.session_id)
        for qi in range(2):
            qm.submit_answer(session.session_id, student_id=1, question_idx=qi, selected="A")
            qm.submit_answer(session.session_id, student_id=2, question_idx=qi, selected="A")

        assistant = ClassroomAssistant(quiz_mgr=qm, expected_students=4)
        snap = assistant.get_snapshot("CS101")

        assert snap.quiz_participation == pytest.approx(0.5)
        assert snap.quiz_avg_correct == pytest.approx(1.0)


# ── API endpoint tests ───────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestClassroomAPI:
    def test_snapshot_empty(self, client):
        """GET /classroom/{course}/snapshot returns valid response with no data."""
        resp = client.get("/classroom/CS999/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "CS999"
        assert data["alert_count"] == 0
        assert "suggestions" in data
        assert "metrics" in data

    def test_snapshot_with_expected_students(self, client):
        """expected_students query param is accepted."""
        resp = client.get("/classroom/CS101/snapshot?expected_students=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "CS101"

    def test_snapshot_metrics_structure(self, client):
        """Metrics contain all expected fields."""
        resp = client.get("/classroom/CS101/snapshot")
        data = resp.json()
        m = data["metrics"]
        expected_keys = {
            "quiz_participation", "quiz_avg_correct", "active_questions",
            "attendance_present", "attendance_late", "attendance_total",
            "poll_active", "poll_confusion", "danmaku_rate",
        }
        assert expected_keys == set(m.keys())

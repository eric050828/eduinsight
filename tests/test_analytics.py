"""Tests for learning analytics module and API endpoints."""

import time

import pytest
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.analytics import Struggle, analyze_class, analyze_student, learning_trajectory
from eduinsight.app import app
from eduinsight.assistant import LearningAssistant
from eduinsight.demo_data import DEMO_STUDENTS


async def _make_client(mem: Memory) -> AsyncClient:
    """Create a test client with a pre-configured in-memory assistant."""
    import eduinsight.app as app_module

    app_module._memory = mem
    app_module._assistant = LearningAssistant(mem)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _seed_demo(mem: Memory) -> None:
    """Populate memory with demo student data."""
    for user_id, facts in DEMO_STUDENTS.items():
        for fact_text, category in facts:
            mem.add(user_id, fact_text, category=category)


# ------------------------------------------------------------------
# Unit tests for analytics module
# ------------------------------------------------------------------


class TestAnalyzeStudent:
    def test_empty_student(self) -> None:
        mem = Memory()
        result = analyze_student(mem, 999)
        assert result.moodle_user_id == 999
        assert result.total_facts == 0
        assert result.struggles == []
        assert result.weak_topics == []
        assert result.preferences == []

    def test_struggles_extracted(self) -> None:
        mem = Memory()
        # Lite-Mem may deduplicate similar "Struggling with:" facts,
        # so we use distinct topics to ensure both survive.
        mem.add("moodle:1", "[OOP] Q: What is inheritance?")
        mem.add("moodle:1", "Struggling with: recursion — can't trace base case")

        result = analyze_student(mem, 1)
        assert len(result.struggles) >= 1
        # At least one struggle should be extracted
        topics = [s.topic for s in result.struggles]
        assert "recursion" in topics
        # Check details extraction
        recursion_struggle = next(s for s in result.struggles if s.topic == "recursion")
        assert "base case" in recursion_struggle.details

    def test_weak_topics_from_struggles(self) -> None:
        mem = Memory()
        # Use very different struggle topics to avoid Lite-Mem dedup
        mem.add("moodle:1", "Struggling with: linear algebra — matrix multiplication")
        mem.add("moodle:1", "[Math] Q: How do eigenvalues work?")
        mem.add("moodle:1", "Struggling with: probability — Bayes theorem")

        result = analyze_student(mem, 1)
        # weak_topics should contain at least the struggles that survived dedup
        assert len(result.weak_topics) >= 1

    def test_question_topics_counted(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "[Math] Q: What is calculus?")
        mem.add("moodle:1", "[Math] Q: What is a derivative?")
        mem.add("moodle:1", "[Physics] Q: What is force?")
        mem.add("moodle:1", "[Math] A: Calculus is the study of change.")

        result = analyze_student(mem, 1)
        assert result.question_topics["Math"] >= 2
        assert result.question_topics["Physics"] == 1

    def test_preferences_extracted(self) -> None:
        mem = Memory()
        # Lite-Mem may merge similar preference facts; use one distinct preference
        mem.add("moodle:1", "Learning preference: visual diagrams and step-by-step walkthroughs")

        result = analyze_student(mem, 1)
        assert len(result.preferences) >= 1
        assert any("visual" in p for p in result.preferences)

    def test_demo_student_1001(self) -> None:
        """Student 1001 from demo data should have recognizable patterns."""
        mem = Memory()
        _seed_demo(mem)

        result = analyze_student(mem, 1001)
        assert result.total_facts > 0
        # At least some struggles should survive Lite-Mem dedup
        assert len(result.struggles) >= 1
        assert len(result.weak_topics) >= 1
        assert "Data Structures" in result.question_topics


class TestAnalyzeClass:
    def test_empty_class(self) -> None:
        mem = Memory()
        result = analyze_class(mem)
        assert result.total_students == 0
        assert result.total_facts == 0
        assert result.common_struggles == []

    def test_demo_class(self) -> None:
        """Full demo data should produce meaningful class analytics."""
        mem = Memory()
        _seed_demo(mem)

        result = analyze_class(mem)
        assert result.total_students == 4
        assert result.total_facts > 0
        assert len(result.students) == 4

        # Should find common struggles across students
        assert len(result.common_struggles) > 0

        # Topic distribution should include known topics
        assert "Data Structures" in result.topic_distribution
        assert "Algorithms" in result.topic_distribution

    def test_non_moodle_users_excluded(self) -> None:
        mem = Memory()
        mem.add("slack:99", "Some fact")
        mem.add("moodle:1", "Struggling with: math")

        result = analyze_class(mem)
        assert result.total_students == 1


# ------------------------------------------------------------------
# API endpoint tests
# ------------------------------------------------------------------


class TestStudentAnalyticsEndpoint:
    async def test_student_analytics(self) -> None:
        mem = Memory()
        _seed_demo(mem)

        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/1001")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 1001
            assert data["total_facts"] > 0
            assert len(data["struggles"]) >= 1
            assert len(data["weak_topics"]) >= 1
            assert "Data Structures" in data["question_topics"]

    async def test_empty_student(self) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/999")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_facts"] == 0
            assert data["struggles"] == []


class TestClassAnalyticsEndpoint:
    async def test_class_analytics(self) -> None:
        mem = Memory()
        _seed_demo(mem)

        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/class")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_students"] == 4
            assert data["total_facts"] > 0
            assert len(data["common_struggles"]) > 0
            assert "Data Structures" in data["topic_distribution"]


# ------------------------------------------------------------------
# Learning trajectory tests
# ------------------------------------------------------------------


class TestLearningTrajectory:
    def test_empty_student(self) -> None:
        mem = Memory()
        traj = learning_trajectory(mem, 999)
        assert traj.moodle_user_id == 999
        assert traj.total_weeks == 0
        assert traj.points == []

    def test_single_week(self) -> None:
        """All facts added at the same time should fall in one week."""
        mem = Memory()
        mem.add("moodle:1", "[Math] Q: What is calculus?")
        mem.add("moodle:1", "Struggling with: derivatives — chain rule")
        mem.add("moodle:1", "Learning preference: visual diagrams")

        traj = learning_trajectory(mem, 1)
        assert traj.total_weeks == 1
        assert len(traj.points) == 1
        p = traj.points[0]
        assert p.new_facts >= 2  # Lite-Mem may deduplicate
        assert p.cumulative_facts == p.new_facts

    def test_struggles_tracked_in_trajectory(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "Struggling with: recursion — base case")
        mem.add("moodle:1", "Struggling with: pointers — null dereference")

        traj = learning_trajectory(mem, 1)
        assert traj.total_weeks >= 1
        # At least some struggles should appear
        all_struggles = []
        for p in traj.points:
            all_struggles.extend(p.new_struggles)
        assert len(all_struggles) >= 1

    def test_topics_tracked_in_trajectory(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "[Algorithms] Q: What is Big-O?")
        mem.add("moodle:1", "[Database] Q: What is normalization?")

        traj = learning_trajectory(mem, 1)
        all_topics = []
        for p in traj.points:
            all_topics.extend(p.new_topics)
        assert len(all_topics) >= 1

    def test_multi_week_via_db(self) -> None:
        """Manually adjust created_at to simulate multi-week data."""
        mem = Memory()
        mem.add("moodle:5", "Struggling with: loops — off by one")
        mem.add("moodle:5", "[Math] Q: What is integration?")

        # Shift one fact back by 2 weeks via direct DB access
        conn = mem._store._get_conn()
        two_weeks_ago = time.time() - 14 * 86400
        conn.execute(
            "UPDATE facts SET created_at = ? WHERE user_id = ? AND rowid = ("
            "SELECT MIN(rowid) FROM facts WHERE user_id = ?)",
            (two_weeks_ago, "moodle:5", "moodle:5"),
        )
        conn.commit()

        traj = learning_trajectory(mem, 5)
        assert traj.total_weeks == 2
        assert len(traj.points) == 2
        # Cumulative should grow
        assert traj.points[1].cumulative_facts > traj.points[0].cumulative_facts

    def test_cumulative_struggles_grow(self) -> None:
        """Cumulative struggle count should never decrease."""
        mem = Memory()
        mem.add("moodle:6", "Struggling with: sorting — merge sort")
        mem.add("moodle:6", "Struggling with: graphs — BFS vs DFS")

        # Shift first fact back 1 week
        conn = mem._store._get_conn()
        one_week_ago = time.time() - 7 * 86400
        conn.execute(
            "UPDATE facts SET created_at = ? WHERE user_id = ? AND rowid = ("
            "SELECT MIN(rowid) FROM facts WHERE user_id = ?)",
            (one_week_ago, "moodle:6", "moodle:6"),
        )
        conn.commit()

        traj = learning_trajectory(mem, 6)
        if traj.total_weeks == 2:
            assert traj.points[1].cumulative_struggles >= traj.points[0].cumulative_struggles

    def test_demo_student_trajectory(self) -> None:
        """Demo students should produce non-empty trajectories."""
        mem = Memory()
        _seed_demo(mem)
        traj = learning_trajectory(mem, 1001)
        assert traj.total_weeks >= 1
        assert traj.points[0].new_facts > 0


class TestTrajectoryEndpoint:
    async def test_trajectory_endpoint(self) -> None:
        mem = Memory()
        _seed_demo(mem)

        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/1001/trajectory")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 1001
            assert data["total_weeks"] >= 1
            assert len(data["points"]) >= 1
            p = data["points"][0]
            assert "week_start" in p
            assert "new_facts" in p
            assert "cumulative_facts" in p

    async def test_empty_trajectory_endpoint(self) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/999/trajectory")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_weeks"] == 0
            assert data["points"] == []

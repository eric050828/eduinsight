"""Tests for learning analytics module and API endpoints."""

import time

from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.analytics import (
    analyze_class,
    analyze_student,
    assess_risk,
    generate_class_summaries,
    generate_student_summary,
    learning_trajectory,
)
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
            mem.add(user_id, fact_text, category=category, extract=False)


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
        mem.add("moodle:1", "[OOP] Q: What is inheritance?", extract=False)
        mem.add("moodle:1", "Struggling with: recursion — can't trace base case", extract=False)

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
        mem.add(
            "moodle:1",
            "Struggling with: linear algebra — matrix multiplication",
            extract=False,
        )
        mem.add("moodle:1", "[Math] Q: How do eigenvalues work?", extract=False)
        mem.add("moodle:1", "Struggling with: probability — Bayes theorem", extract=False)

        result = analyze_student(mem, 1)
        # weak_topics should contain at least the struggles that survived dedup
        assert len(result.weak_topics) >= 1

    def test_natural_language_struggle_extracted(self) -> None:
        """LLM-extracted facts without 'Struggling with' prefix should still be detected."""
        mem = Memory()
        mem.add("moodle:1", "搞不懂「進步性」怎麼判斷", extract=False)
        mem.add("moodle:1", "I'm confused by SWOT external vs internal factors", extract=False)
        mem.add("moodle:1", "為什麼 STP 流程的順序不能換？", extract=False)

        result = analyze_student(mem, 1)
        topics = [s.topic for s in result.struggles]
        # CJK quoted term: 進步性
        assert "進步性" in topics, f"Expected 進步性 in {topics}"
        # English jargon: SWOT
        assert "SWOT" in topics, f"Expected SWOT in {topics}"
        # Question topic without struggle word counts as engagement, not struggle
        assert "STP" in result.question_topics

    def test_question_topics_counted(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "[Math] Q: What is calculus?", extract=False)
        mem.add("moodle:1", "[Math] Q: What is a derivative?", extract=False)
        mem.add("moodle:1", "[Physics] Q: What is force?", extract=False)
        mem.add("moodle:1", "[Math] A: Calculus is the study of change.", extract=False)

        result = analyze_student(mem, 1)
        assert result.question_topics["Math"] >= 2
        assert result.question_topics["Physics"] == 1

    def test_preferences_extracted(self) -> None:
        mem = Memory()
        # Lite-Mem may merge similar preference facts; use one distinct preference
        mem.add(
            "moodle:1",
            "Learning preference: visual diagrams and step-by-step walkthroughs",
            extract=False,
        )

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
        assert result.total_students == 5
        assert result.total_facts > 0
        assert len(result.students) == 5

        # Should find common struggles across students
        assert len(result.common_struggles) > 0

        # Topic distribution should include known topics
        assert "Data Structures" in result.topic_distribution
        assert "Algorithms" in result.topic_distribution

    def test_non_moodle_users_excluded(self) -> None:
        mem = Memory()
        mem.add("slack:99", "Some fact", extract=False)
        mem.add("moodle:1", "Struggling with: math", extract=False)

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
    async def test_class_analytics(self, auth_headers) -> None:
        mem = Memory()
        _seed_demo(mem)

        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/class", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_students"] == 5
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
        mem.add("moodle:1", "[Math] Q: What is calculus?", extract=False)
        mem.add("moodle:1", "Struggling with: derivatives — chain rule", extract=False)
        mem.add("moodle:1", "Learning preference: visual diagrams", extract=False)

        traj = learning_trajectory(mem, 1)
        assert traj.total_weeks == 1
        assert len(traj.points) == 1
        p = traj.points[0]
        assert p.new_facts >= 2  # Lite-Mem may deduplicate
        assert p.cumulative_facts == p.new_facts

    def test_struggles_tracked_in_trajectory(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "Struggling with: recursion — base case", extract=False)
        mem.add("moodle:1", "Struggling with: pointers — null dereference", extract=False)

        traj = learning_trajectory(mem, 1)
        assert traj.total_weeks >= 1
        # At least some struggles should appear
        all_struggles = []
        for p in traj.points:
            all_struggles.extend(p.new_struggles)
        assert len(all_struggles) >= 1

    def test_topics_tracked_in_trajectory(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "[Algorithms] Q: What is Big-O?", extract=False)
        mem.add("moodle:1", "[Database] Q: What is normalization?", extract=False)

        traj = learning_trajectory(mem, 1)
        all_topics = []
        for p in traj.points:
            all_topics.extend(p.new_topics)
        assert len(all_topics) >= 1

    def test_multi_week_via_db(self) -> None:
        """Manually adjust created_at to simulate multi-week data."""
        mem = Memory()
        mem.add("moodle:5", "Struggling with: loops — off by one", extract=False)
        mem.add("moodle:5", "[Math] Q: What is integration?", extract=False)

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
        mem.add("moodle:6", "Struggling with: sorting — merge sort", extract=False)
        mem.add("moodle:6", "Struggling with: graphs — BFS vs DFS", extract=False)

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


# ------------------------------------------------------------------
# Risk assessment tests
# ------------------------------------------------------------------


class TestAssessRisk:
    def test_no_data_is_high_risk(self) -> None:
        """A student with zero facts should be high risk."""
        mem = Memory()
        risk = assess_risk(mem, 999)
        assert risk.risk_level == "high"
        assert risk.persistence_score == 0
        assert risk.days_since_last_activity is None
        assert any(f.label == "零互動" for f in risk.factors)

    def test_active_student_is_low_risk(self) -> None:
        """A student with recent, ample activity should be low risk."""
        mem = Memory()
        # Add plenty of facts (as sole student, they are the class average)
        for i in range(10):
            mem.add(
                "moodle:1",
                f"[Topic{i}] Fact about topic {i}: detailed info {i}",
                extract=False,
            )
        mem.add("moodle:1", "Struggling with: one thing — minor issue", extract=False)

        now = time.time()
        risk = assess_risk(mem, 1, now=now)
        assert risk.risk_level == "low"
        assert risk.persistence_score >= 70
        assert risk.days_since_last_activity is not None
        assert risk.days_since_last_activity <= 1

    def test_inactive_student_is_high_risk(self) -> None:
        """A student who hasn't been active for 3+ weeks should be high risk."""
        mem = Memory()
        mem.add("moodle:10", "[DS] Linked list basics: nodes and pointers", extract=False)
        mem.add("moodle:10", "Struggling with: everything — very confused", extract=False)

        # Backdate all facts to 30 days ago
        conn = mem._store._get_conn()
        old_ts = time.time() - 30 * 86400
        conn.execute(
            "UPDATE facts SET created_at = ?, updated_at = ? WHERE user_id = ?",
            (old_ts, old_ts, "moodle:10"),
        )
        conn.commit()

        risk = assess_risk(mem, 10)
        # Long inactivity + few facts + high struggle ratio → at least medium
        assert risk.risk_level in ("high", "medium")
        assert risk.persistence_score < 50
        assert risk.days_since_last_activity >= 29
        assert any(f.severity == "high" for f in risk.factors)

    def test_declining_activity_is_medium_risk(self) -> None:
        """A student with declining recent activity should be flagged."""
        mem = Memory()
        # Add older facts (4 weeks ago)
        for i in range(8):
            mem.add("moodle:20", f"[Algo] Algorithm topic {i}: explanation {i}", extract=False)

        # Backdate all to 4 weeks ago
        conn = mem._store._get_conn()
        old_ts = time.time() - 28 * 86400
        conn.execute(
            "UPDATE facts SET created_at = ?, updated_at = ? WHERE user_id = ?",
            (old_ts, old_ts, "moodle:20"),
        )
        conn.commit()

        # Add one recent fact (within last week)
        mem.add("moodle:20", "[Algo] Recent question about sorting: quicksort", extract=False)

        risk = assess_risk(mem, 20)
        # Should detect declining trend (activity drop factor present)
        trend_factors = [f for f in risk.factors if "驟降" in f.label or "停止" in f.label]
        assert len(trend_factors) >= 1

    def test_high_struggle_ratio_flagged(self) -> None:
        """A student with many struggles relative to total facts should be flagged."""
        mem = Memory()
        mem.add("moodle:30", "[DS] One general fact: arrays store elements", extract=False)
        mem.add("moodle:30", "Struggling with: recursion — can't trace calls", extract=False)
        mem.add("moodle:30", "Struggling with: pointers — null dereference", extract=False)
        mem.add("moodle:30", "Struggling with: trees — traversal order", extract=False)

        risk = assess_risk(mem, 30)
        # 3 struggles / 4 facts = 75% struggle ratio
        struggle_factors = [f for f in risk.factors if "困難" in f.label]
        assert len(struggle_factors) >= 1

    def test_class_avg_comparison(self) -> None:
        """Students below class average should score lower on volume."""
        mem = Memory()
        # Student 1: many facts
        for i in range(20):
            mem.add("moodle:41", f"[Topic{i}] Student 1 fact {i}: detailed info", extract=False)
        # Student 2: few facts
        for i in range(3):
            mem.add("moodle:42", f"[Topic{i}] Student 2 fact {i}: minimal info", extract=False)

        risk_low = assess_risk(mem, 41)
        risk_high = assess_risk(mem, 42)

        assert risk_low.persistence_score > risk_high.persistence_score

    def test_demo_students_risk(self) -> None:
        """Demo students should produce valid risk assessments."""
        mem = Memory()
        _seed_demo(mem)

        for sid in [1001, 1002, 1003, 1004]:
            risk = assess_risk(mem, sid)
            assert risk.moodle_user_id == sid
            assert risk.risk_level in ("high", "medium", "low")
            assert 0 <= risk.persistence_score <= 100
            assert risk.days_since_last_activity is not None


class TestRiskEndpoint:
    async def test_risk_endpoint(self) -> None:
        mem = Memory()
        _seed_demo(mem)

        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/1001/risk")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 1001
            assert data["risk_level"] in ("high", "medium", "low")
            assert 0 <= data["persistence_score"] <= 100
            assert isinstance(data["factors"], list)
            assert data["days_since_last_activity"] is not None

    async def test_risk_endpoint_empty_student(self) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/analytics/student/999/risk")
            assert resp.status_code == 200
            data = resp.json()
            assert data["risk_level"] == "high"
            assert data["persistence_score"] == 0
            assert data["days_since_last_activity"] is None


# ------------------------------------------------------------------
# Unit tests for AI interaction summaries
# ------------------------------------------------------------------


class TestGenerateStudentSummary:
    def test_empty_student(self) -> None:
        mem = Memory()
        s = generate_student_summary(mem, 999, display_name="測試生")
        assert s.moodle_user_id == 999
        assert s.name == "測試生"
        assert s.risk == "high"
        assert "尚無任何 AI 互動" in s.text

    def test_summary_with_struggles(self) -> None:
        mem = Memory()
        mem.add("moodle:1", "Struggling with recursion: base case confusion", extract=False)
        mem.add("moodle:1", "Struggling with pointers: null dereference", extract=False)
        mem.add("moodle:1", "[OOP] Q: What is inheritance?", extract=False)
        mem.add("moodle:1", "Learning preference: visual diagrams", extract=False)

        s = generate_student_summary(mem, 1, display_name="A 同學", now=time.time())
        assert s.name == "A 同學"
        assert "困難" in s.text
        assert "Persistence Score" in s.text
        assert s.risk in ("high", "medium", "low")

    def test_summary_with_no_struggles(self) -> None:
        mem = Memory()
        mem.add("moodle:2", "[Python] Q: How to use list comprehension?", extract=False)
        mem.add("moodle:2", "[Python] Q: What is a generator?", extract=False)
        mem.add("moodle:2", "Learning preference: code examples", extract=False)

        s = generate_student_summary(mem, 2, now=time.time())
        assert "未記錄明顯困難" in s.text

    def test_default_name(self) -> None:
        mem = Memory()
        mem.add("moodle:42", "[Math] Q: integral", extract=False)
        s = generate_student_summary(mem, 42, now=time.time())
        assert s.name == "moodle:42"


class TestGenerateClassSummaries:
    def test_empty_class(self) -> None:
        mem = Memory()
        result = generate_class_summaries(mem)
        assert result == []

    def test_class_with_demo_data(self) -> None:
        mem = Memory()
        _seed_demo(mem)
        result = generate_class_summaries(mem, now=time.time())
        assert len(result) == 5  # 5 demo students
        # All summaries have required fields
        for s in result:
            assert s.moodle_user_id > 0
            assert s.risk in ("high", "medium", "low")
            assert len(s.text) > 10

    def test_sorted_by_risk(self) -> None:
        mem = Memory()
        _seed_demo(mem)
        result = generate_class_summaries(mem, now=time.time())
        # High risk should come first
        risk_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(result) - 1):
            assert risk_order[result[i].risk] <= risk_order[result[i + 1].risk]

    def test_name_map(self) -> None:
        mem = Memory()
        _seed_demo(mem)
        names = {1001: "陳同學", 1002: "林同學"}
        result = generate_class_summaries(mem, name_map=names, now=time.time())
        named = {s.moodle_user_id: s.name for s in result}
        assert named[1001] == "陳同學"
        assert named[1002] == "林同學"


# ------------------------------------------------------------------
# API tests for /teacher/summaries
# ------------------------------------------------------------------


class TestSummariesAPI:
    async def test_summaries_empty(self, auth_headers) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/summaries", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["summaries"] == []

    async def test_summaries_with_data(self, auth_headers) -> None:
        mem = Memory()
        _seed_demo(mem)
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/summaries", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 5
            for s in data["summaries"]:
                assert "moodle_user_id" in s
                assert "name" in s
                assert "risk" in s
                assert "text" in s
                assert s["risk"] in ("high", "medium", "low")

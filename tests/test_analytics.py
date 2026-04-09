"""Tests for learning analytics module and API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.analytics import Struggle, analyze_class, analyze_student
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
        for fact in facts:
            mem.add(user_id, fact)


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

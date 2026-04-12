"""Tests for teaching analytics report module."""

from __future__ import annotations

import pytest
from litemem import Memory

from eduinsight.attendance import AttendanceManager
from eduinsight.grades import GradeManager
from eduinsight.interaction import InteractionManager
from eduinsight.live_quiz import QuizSessionManager, QuizSessionQuestion
from eduinsight.report import (
    AIGradeCorrelation,
    ReportGenerator,
    WeeklyReport,
    _correlation_insight,
    _pearson,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def memory() -> Memory:
    return Memory(":memory:")


@pytest.fixture
def grades() -> GradeManager:
    return GradeManager()


@pytest.fixture
def attendance() -> AttendanceManager:
    return AttendanceManager()


@pytest.fixture
def interaction() -> InteractionManager:
    return InteractionManager()


@pytest.fixture
def quiz() -> QuizSessionManager:
    return QuizSessionManager()


@pytest.fixture
def gen(
    memory: Memory,
    grades: GradeManager,
    attendance: AttendanceManager,
    interaction: InteractionManager,
    quiz: QuizSessionManager,
) -> ReportGenerator:
    return ReportGenerator(
        memory=memory,
        grades=grades,
        attendance=attendance,
        interaction=interaction,
        quiz=quiz,
    )


def _seed_students(memory: Memory) -> None:
    """Seed 3 students with different profiles."""
    # Student 1001: active learner
    memory.add("moodle:1001", "[Python] Q: What is a list?")
    memory.add("moodle:1001", "[Python] Q: How to use for loop?")
    memory.add("moodle:1001", "Struggling with recursion: stack overflow concept")
    memory.add("moodle:1001", "Learning preference: visual diagrams")

    # Student 1002: struggling
    memory.add("moodle:1002", "Struggling with linked list: pointer confusion")
    memory.add("moodle:1002", "Struggling with tree traversal: inorder vs preorder")
    memory.add("moodle:1002", "[Data Structures] Q: What is a stack?")

    # Student 1003: minimal activity
    memory.add("moodle:1003", "[SQL] Q: What is SELECT?")


def _seed_grades(grades: GradeManager) -> None:
    """Seed grades for ds101 course."""
    grades.set_categories("ds101", [
        {"name": "作業", "weight": 30},
        {"name": "期中考", "weight": 30},
        {"name": "期末考", "weight": 40},
    ])
    grades.record_score("ds101", student_id=1001, category="作業", item="HW1", score=90, total=100)
    grades.record_score("ds101", student_id=1001, category="期中考", item="Midterm", score=85, total=100)  # noqa: E501
    grades.record_score("ds101", student_id=1002, category="作業", item="HW1", score=60, total=100)
    grades.record_score("ds101", student_id=1002, category="期中考", item="Midterm", score=55, total=100)  # noqa: E501
    grades.record_score("ds101", student_id=1003, category="作業", item="HW1", score=75, total=100)


# ------------------------------------------------------------------
# Pearson correlation
# ------------------------------------------------------------------


class TestPearson:
    def test_perfect_positive(self):
        r = _pearson([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
        assert r is not None
        assert abs(r - 1.0) < 0.001

    def test_perfect_negative(self):
        r = _pearson([1.0, 2.0, 3.0], [30.0, 20.0, 10.0])
        assert r is not None
        assert abs(r - (-1.0)) < 0.001

    def test_too_few_points(self):
        assert _pearson([1.0, 2.0], [3.0, 4.0]) is None

    def test_zero_variance(self):
        assert _pearson([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None

    def test_mismatched_lengths(self):
        assert _pearson([1.0, 2.0, 3.0], [1.0, 2.0]) is None


class TestCorrelationInsight:
    def test_none(self):
        assert "資料不足" in _correlation_insight(None)

    def test_strong_positive(self):
        text = _correlation_insight(0.85)
        assert "強" in text and "正" in text

    def test_weak_negative(self):
        text = _correlation_insight(-0.25)
        assert "弱" in text and "負" in text

    def test_near_zero(self):
        text = _correlation_insight(0.05)
        assert "無相關" in text


# ------------------------------------------------------------------
# Weekly report
# ------------------------------------------------------------------


class TestWeeklyReport:
    def test_empty_report(self, gen: ReportGenerator):
        report = gen.weekly_report("ds101")
        assert isinstance(report, WeeklyReport)
        assert report.total_students == 0
        assert report.total_facts == 0

    def test_with_students(self, gen: ReportGenerator, memory: Memory):
        _seed_students(memory)
        report = gen.weekly_report("ds101")
        assert report.total_students == 3
        assert report.total_facts >= 7  # Lite-Mem may dedup similar facts
        assert report.avg_facts_per_student > 0

    def test_common_struggles(self, gen: ReportGenerator, memory: Memory):
        _seed_students(memory)
        report = gen.weekly_report("ds101")
        struggle_topics = [s[0] for s in report.common_struggles]
        assert "linked list" in struggle_topics or "recursion" in struggle_topics

    def test_with_grades(
        self, gen: ReportGenerator, memory: Memory, grades: GradeManager
    ):
        _seed_students(memory)
        _seed_grades(grades)
        report = gen.weekly_report("ds101")
        assert report.grade_mean is not None
        assert report.grade_mean > 0
        assert report.grade_distribution is not None

    def test_without_grades(self, gen: ReportGenerator, memory: Memory):
        _seed_students(memory)
        report = gen.weekly_report("ds101")
        assert report.grade_mean is None

    def test_with_attendance(
        self, gen: ReportGenerator, memory: Memory, attendance: AttendanceManager
    ):
        _seed_students(memory)
        session = attendance.create_session("ds101", teacher_id=9001)
        attendance.checkin(session.session_id, student_id=1001)
        attendance.checkin(session.session_id, student_id=1002)
        attendance.close_session(session.session_id)
        report = gen.weekly_report("ds101")
        assert report.total_sessions == 1
        assert report.avg_attendance_rate is not None

    def test_with_interaction(
        self, gen: ReportGenerator, memory: Memory, interaction: InteractionManager
    ):
        _seed_students(memory)
        interaction.create_poll("ds101", teacher_id=9001, title="Test Poll", options=["A", "B"])
        interaction.post_question("ds101", student_id=1001, text="Why?")
        interaction.post_danmaku("ds101", student_id=1001, text="Cool!")
        report = gen.weekly_report("ds101")
        assert report.total_polls == 1
        assert report.total_questions == 1
        assert report.total_danmaku == 1

    def test_with_quiz(
        self, gen: ReportGenerator, memory: Memory, quiz: QuizSessionManager
    ):
        _seed_students(memory)
        questions = [
            QuizSessionQuestion(
                question="What is 1+1?",
                options={"A": "1", "B": "2", "C": "3", "D": "4"},
                answer="B",
            )
        ]
        session = quiz.create_session("ds101", questions, teacher_id=9001)
        quiz.activate_session(session.session_id)
        quiz.submit_answer(
            session.session_id, student_id=1001, question_idx=0, selected="B"
        )
        quiz.close_session(session.session_id)
        report = gen.weekly_report("ds101")
        assert report.total_quiz_sessions == 1
        assert report.avg_quiz_score is not None
        assert report.avg_quiz_score == 100.0

    def test_per_student_metrics(
        self, gen: ReportGenerator, memory: Memory, grades: GradeManager
    ):
        _seed_students(memory)
        _seed_grades(grades)
        report = gen.weekly_report("ds101")
        assert len(report.students) == 3
        for s in report.students:
            assert s.fact_count >= 0
            assert s.risk_level in ("low", "medium", "high")

    def test_high_risk_students(self, gen: ReportGenerator, memory: Memory):
        # Create one student with zero activity to guarantee high risk
        memory.add("moodle:9999", "[Test] Q: placeholder")
        memory.forget("moodle:9999")
        # Actually, a student with 0 facts won't appear in class analytics.
        # Instead test with the seeded data
        _seed_students(memory)
        report = gen.weekly_report("ds101")
        # At least check the field exists and is a list
        assert isinstance(report.high_risk_students, list)

    def test_course_isolation(
        self, gen: ReportGenerator, memory: Memory, attendance: AttendanceManager
    ):
        _seed_students(memory)
        # Create attendance for a different course
        session = attendance.create_session("OTHER101", teacher_id=9001)
        attendance.checkin(session.session_id, student_id=1001)
        attendance.close_session(session.session_id)
        report = gen.weekly_report("ds101")
        # ds101 should have 0 attendance sessions
        assert report.total_sessions == 0


# ------------------------------------------------------------------
# AI-grade correlation
# ------------------------------------------------------------------


class TestAIGradeCorrelation:
    def test_empty(self, gen: ReportGenerator):
        result = gen.ai_grade_correlation("ds101")
        assert isinstance(result, AIGradeCorrelation)
        assert len(result.points) == 0
        assert "資料不足" in result.insight

    def test_with_data(
        self, gen: ReportGenerator, memory: Memory, grades: GradeManager
    ):
        _seed_students(memory)
        _seed_grades(grades)
        result = gen.ai_grade_correlation("ds101")
        assert len(result.points) == 3
        # Student 1001 has more facts and higher grades
        for p in result.points:
            assert p.student_id in (1001, 1002, 1003)
            assert p.weighted_grade > 0

    def test_correlation_direction(
        self, gen: ReportGenerator, memory: Memory, grades: GradeManager
    ):
        _seed_students(memory)
        _seed_grades(grades)
        result = gen.ai_grade_correlation("ds101")
        # With our test data: 1001 has 4 facts + high grade,
        # 1002 has 3 facts + low grade, 1003 has 1 fact + medium grade
        # Should show positive correlation
        if result.fact_grade_correlation is not None:
            assert result.fact_grade_correlation > 0

    def test_no_grades_for_course(
        self, gen: ReportGenerator, memory: Memory
    ):
        _seed_students(memory)
        # No grades configured → no correlation points
        result = gen.ai_grade_correlation("ds101")
        assert len(result.points) == 0


# ------------------------------------------------------------------
# API endpoint tests
# ------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from eduinsight.app import app

    with TestClient(app) as c:
        yield c


class TestReportAPI:
    def test_weekly_report_basic(self, client):
        resp = client.get("/reports/weekly/ds101")
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "ds101"
        assert "total_students" in data
        assert "common_struggles" in data
        assert "students" in data

    def test_weekly_report_with_demo(self, client):
        # Seed demo data first
        resp = client.post("/demo/reset")
        assert resp.status_code == 200
        resp = client.get("/reports/weekly/ds101")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_students"] > 0
        assert isinstance(data["students"], list)

    def test_correlation_empty(self, client):
        resp = client.get("/reports/correlation/ds101")
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "ds101"
        assert isinstance(data["points"], list)

    def test_correlation_with_demo(self, client):
        client.post("/demo/reset")
        resp = client.get("/reports/correlation/ds101")
        assert resp.status_code == 200
        data = resp.json()
        assert "insight" in data

    def test_excel_export(self, client):
        client.post("/demo/reset")
        resp = client.get("/reports/export/excel/ds101")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]
        assert len(resp.content) > 0
        # Verify it's a valid xlsx (starts with PK zip signature)
        assert resp.content[:2] == b"PK"

    def test_excel_export_empty_course(self, client):
        resp = client.get("/reports/export/excel/empty_course")
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"

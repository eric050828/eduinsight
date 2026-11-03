"""Regression coverage for authoritative enrollment and course isolation."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from litemem import Memory
from openpyxl import load_workbook

from eduinsight import app as api, auth, courses, sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.attendance import AttendanceManager
from eduinsight.grades import GradeManager
from eduinsight.interaction import InteractionManager
from eduinsight.live_quiz import QuizSessionManager, QuizSessionQuestion
from eduinsight.office_hours import OfficeHourManager
from eduinsight.report import ReportGenerator


@pytest.fixture
def client(auth_headers, monkeypatch):
    memory = Memory(":memory:", embedder=None)
    monkeypatch.setattr(api, "_memory", memory)
    monkeypatch.setattr(api, "_assistant", LearningAssistant(memory))
    monkeypatch.setattr(api, "_attendance", AttendanceManager())
    monkeypatch.setattr(api, "_interaction", InteractionManager())
    monkeypatch.setattr(api, "_quiz_manager", QuizSessionManager())
    monkeypatch.setattr(api, "_grades", GradeManager())
    monkeypatch.setattr(api, "_office_hours", OfficeHourManager())
    monkeypatch.setattr(api, "_llm", None)
    monkeypatch.setattr(api, "_rag", None)
    # ASGI requests only: no server and no lifespan demo seeds.
    return TestClient(api.app)


def test_session_and_chat_cannot_forge_enrollment(client, auth_headers):
    headers = auth_headers("student1001")
    assert client.post("/student/1001/courses/mk201/sessions", json={}, headers=headers).status_code == 403
    assert client.post("/chat", json={"moodle_user_id": 1001, "course_id": "mk201", "message": "Hi"}, headers=headers).status_code == 403
    forged = sessions.create_session(1001, "mk201")
    courses.init_enrollments()  # Migration is not re-run after table creation.
    assert not courses.is_enrolled("mk201", 1001)
    for path in ("/courses/mk201/participants", f"/sessions/{forged['session_id']}"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post("/chat", json={"moodle_user_id": 1001, "session_id": forged["session_id"], "message": "Hi"}, headers=headers).status_code == 403
    assert client.post("/student/1001/courses/general/sessions", json={}, headers=headers).status_code == 200
    courses.enroll("mk201", 1001)
    assert client.post("/student/1001/courses/mk201/sessions", json={}, headers=headers).status_code == 200


def test_teacher_assignment_is_db_authority(client, auth_headers):
    fresh = auth.create_user(auth.RegisterRequest(username="unmapped", password="testpass123", display_name="Fresh", role="teacher"))
    headers = {"Authorization": f"Bearer {auth.create_access_token(fresh)}"}
    for path in ("/teacher/students", "/courses/ds101/materials", "/export/all"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.patch("/admin/courses/ds101", json={"teacher_username": "unmapped"}, headers=auth_headers()).status_code == 200
    assert client.get("/courses/ds101/materials", headers=auth_headers("teacher")).status_code == 403
    assert client.get("/courses/ds101/info", headers=headers).status_code == 200
    assert client.get("/class-analytics/ds101/skills", headers=auth_headers("teacher")).status_code == 403
    assert client.get("/courses/ds101/forum/threads", headers=auth_headers("teacher")).status_code == 403


@pytest.mark.parametrize("actor", ["teacher", "student1001"])
def test_global_export_import_are_admin_only(client, auth_headers, actor):
    assert client.get("/export/all", headers=auth_headers(actor)).status_code == 403
    assert client.post("/import", files={"file": ("memory.json", b"{}", "application/json")}, headers=auth_headers(actor)).status_code == 403
    assert client.get("/export/all", headers=auth_headers()).status_code == 200


@pytest.mark.parametrize("path", [
    "/courses/mk201/materials", "/courses/mk201/materials/a.md/markdown",
    "/courses/mk201/materials/a.md/status", "/lectures/mk201",
    "/lectures/mk201/lecture/transcript", "/quiz/sessions?course_id=mk201",
    "/interaction/polls?course_id=mk201", "/interaction/questions?course_id=mk201",
    "/interaction/danmaku?course_id=mk201", "/attendance/sessions?course_id=mk201",
    "/office-hours/slots?course_id=mk201",
])
def test_legacy_path_and_query_guards(client, auth_headers, path):
    assert client.get(path, headers=auth_headers("student1001")).status_code == 403


def test_resource_lookup_body_guards_and_unfiltered_lists(client, auth_headers):
    headers = auth_headers("student1001")
    courses.enroll("ds101", 1001)
    question = QuizSessionQuestion("Q", {"A": "Yes", "B": "No"}, "A")
    quiz = api._quiz_manager.create_session("mk201", [question], teacher_id=1)
    api._quiz_manager.activate_session(quiz.session_id)
    poll = api._interaction.create_poll("mk201", teacher_id=1, title="Q", options=["A", "B"])
    api._interaction.activate_poll(poll.poll_id)
    anon = api._interaction.post_question("mk201", text="Q", student_id=1002)
    for path in (f"/quiz/sessions/{quiz.session_id}", f"/quiz/sessions/{quiz.session_id}/questions", f"/interaction/polls/{poll.poll_id}/stats"):
        assert client.get(path, headers=headers).status_code == 403
    for path, body in [
        (f"/quiz/sessions/{quiz.session_id}/answer", {"student_id": 1001, "question_idx": 0, "selected": "A"}),
        (f"/interaction/polls/{poll.poll_id}/vote", {"student_id": 1001, "option_idx": 0}),
        (f"/interaction/questions/{anon.question_id}/upvote", {"student_id": 1001}),
        ("/interaction/questions", {"course_id": "mk201", "student_id": 1001, "text": "Q"}),
        ("/interaction/danmaku", {"course_id": "mk201", "student_id": 1001, "text": "Hi"}),
    ]:
        assert client.post(path, json=body, headers=headers).status_code == 403
    own_att = api._attendance.create_session("ds101", teacher_id=1)
    api._attendance.create_session("mk201", teacher_id=1)
    assert client.get("/quiz/sessions", headers=headers).json() == []
    assert client.get("/interaction/polls", headers=headers).json() == []
    data = client.get("/attendance/sessions", headers=headers).json()
    assert [s["session_id"] for s in data] == [own_att.session_id]
    assert "checkin_code" not in data[0]


def test_attendance_requires_enrollment_and_code_without_leaking_it(client, auth_headers):
    courses.enroll("ds101", 1001)
    session = api._attendance.create_session("ds101", teacher_id=1)
    path = f"/attendance/sessions/{session.session_id}"
    student = auth_headers("student1001")
    assert "checkin_code" not in client.get(path, headers=student).json()
    assert client.get(path, headers=auth_headers("teacher")).json()["checkin_code"] == session.checkin_code
    for code in (None, "WRONG"):
        assert client.post(path + "/checkin", json={"student_id": 1001, "code": code}, headers=student).status_code == 400
    assert client.post(path + "/checkin", json={"student_id": 1001, "code": session.checkin_code}, headers=student).status_code == 200
    assert client.post(path + "/checkin", json={"student_id": 1002, "code": session.checkin_code}, headers=auth_headers("student1002")).status_code == 403
    assert client.post("/attendance/checkin-by-code", json={"student_id": 1002, "code": session.checkin_code}, headers=auth_headers("student1002")).status_code == 403
    session.checkin_code = ""
    assert client.post(path + "/checkin", json={"student_id": 1001}, headers=student).status_code == 200


def test_reports_exclude_unenrolled_memory_grades_and_excel_formulas(client, auth_headers):
    courses.enroll("ds101", 1001)
    memory = api.get_assistant().memory
    memory.add("moodle:1001", "Struggling with =HYPERLINK(abc)", extract=False)
    memory.add("moodle:1002", "Struggling with PRIVATE OUTSIDER", extract=False)
    api._grades.set_categories("ds101", [{"name": "Exam", "weight": 100}])
    for sid, score in [(1001, 80), (1002, 10)]:
        api._grades.record_score("ds101", student_id=sid, category="Exam", item="Exam", score=score)
    generator = ReportGenerator(memory=memory, grades=api._grades, attendance=api._attendance, interaction=api._interaction, quiz=api._quiz_manager)
    report = generator.weekly_report("ds101")
    assert [s.student_id for s in report.students] == [1001]
    assert report.total_students == 1 and report.total_facts == 1
    assert report.grade_mean == 80
    assert {s["student_id"] for s in report.high_risk_students} <= {1001}
    assert [p.student_id for p in generator.ai_grade_correlation("ds101").points] == [1001]
    # Put a formula-like untrusted topic into the report to test the actual exporter.
    from unittest.mock import patch
    report.common_struggles = [("=HYPERLINK(\"https://example.com\")", 1)]
    with patch.object(ReportGenerator, "weekly_report", return_value=report):
        result = client.get("/reports/export/excel/ds101", headers=auth_headers())
    assert result.status_code == 200
    workbook = load_workbook(BytesIO(result.content))
    cell = workbook.worksheets[2]["A2"]
    assert cell.value.startswith("=") and cell.data_type == "s"
    assert "1002" not in str([s.student_id for s in report.students])


@pytest.mark.parametrize("method,path", [("GET", "/demo"), ("GET", "/semester"), ("POST", "/demo/reset"), ("POST", "/demo/semester")])
def test_demo_admin_only_and_disabled_is_404(client, auth_headers, monkeypatch, method, path):
    for actor in ("teacher", "student1001"):
        assert client.request(method, path, headers=auth_headers(actor)).status_code == 403
    monkeypatch.setattr(api.config, "demo_enabled", lambda: False)
    assert client.request(method, path, headers=auth_headers()).status_code == 404


def test_one_time_session_backfill(monkeypatch, tmp_path):
    from eduinsight.config import settings
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "legacy-enrollment.db"))
    auth.init_db()
    sessions.init_sessions_table()
    sessions.create_session(1001, "ds101")
    courses.init_enrollments()
    assert courses.is_enrolled("ds101", 1001)
    sessions.create_session(1002, "ds101")
    courses.init_enrollments()
    assert not courses.is_enrolled("ds101", 1002)
    with sessions._db() as conn:
        assert conn.execute("SELECT source FROM course_enrollments").fetchone()[0] == "legacy_sessions"


def test_lifespan_validates_before_db_initialization(monkeypatch):
    from unittest.mock import Mock
    initialize = Mock()
    validator = Mock(side_effect=ValueError("unsafe production settings"))
    monkeypatch.setattr(api, "init_auth_db", initialize)
    monkeypatch.setattr(api.config, "validate_production_settings", validator)
    with pytest.raises(ValueError, match="unsafe production"):
        with TestClient(api.app):
            pass
    validator.assert_called_once_with()
    initialize.assert_not_called()


def test_lifespan_skips_all_demo_seeds_when_disabled(monkeypatch):
    from unittest.mock import Mock
    import shutil
    validator = Mock()
    monkeypatch.setattr(api.config, "validate_production_settings", validator)
    monkeypatch.setattr(api.config, "demo_enabled", lambda: False)
    monkeypatch.setattr(api.settings, "memory_embedder", "")
    for name in ("seed_demo_users", "seed_demo_notifications", "seed_demo_course_structure",
                 "seed_demo_audit", "seed_demo_admin_data"):
        monkeypatch.setattr(api, name, lambda: pytest.fail("Demo seed called while disabled"))
    monkeypatch.setattr(api, "resolve_llm_config", Mock(side_effect=ValueError("No LLM")))
    monkeypatch.setattr(shutil, "which", lambda command: None)
    with TestClient(api.app):
        validator.assert_called_once_with()


def test_missing_config_helpers_fail_closed_in_production(monkeypatch):
    monkeypatch.delattr(api.config, "demo_enabled")
    monkeypatch.delattr(api.config, "validate_production_settings")
    monkeypatch.setattr(api.settings, "env", "production")
    assert api._demo_enabled() is False
    with pytest.raises(RuntimeError, match="validator is unavailable"):
        with TestClient(api.app):
            pass

"""Authentication, role and ownership checks across the entire route inventory."""

import re

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight import sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.attendance import AttendanceManager
from eduinsight.grades import GradeManager
from eduinsight.interaction import InteractionManager
from eduinsight.live_quiz import QuizSessionManager
from eduinsight.office_hours import OfficeHourManager


PUBLIC = {"/", "/health", "/auth/register", "/auth/login", "/auth/lti-bridge"}
DATA_ROUTES = [
    (method, route.path)
    for route in app_module.app.routes
    if isinstance(route, APIRoute)
    and route.path not in PUBLIC
    and not route.path.startswith("/lti/")
    for method in sorted(route.methods)
]


@pytest.fixture
async def client(monkeypatch):
    mem = Memory()
    monkeypatch.setattr(app_module, "_memory", mem)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(mem))
    monkeypatch.setattr(app_module, "_grades", GradeManager())
    monkeypatch.setattr(app_module, "_attendance", AttendanceManager())
    monkeypatch.setattr(app_module, "_interaction", InteractionManager())
    monkeypatch.setattr(app_module, "_quiz_manager", QuizSessionManager())
    monkeypatch.setattr(app_module, "_office_hours", OfficeHourManager())
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test",
    ) as c:
        yield c


@pytest.mark.parametrize("method,path", DATA_ROUTES)
async def test_every_data_route_requires_authentication(client, method, path):
    path = re.sub(r"\{[^}]+\}", "1002", path)
    response = await client.request(method, path)
    assert response.status_code == 401, (method, path, response.text)


async def test_invalid_bearer_is_rejected(client):
    response = await client.get(
        "/student/1001/courses", headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


async def test_student_cannot_access_another_students_data(client, auth_headers):
    headers = auth_headers("student1001")
    for path in (
        "/courses/1002", "/moodle/grades/1/1002",
        "/student/1002/courses", "/student/1002/conversations",
        "/student/1002/courses/ds101/sessions",
        "/analytics/student/1002", "/analytics/student/1002/trajectory",
        "/analytics/student/1002/risk", "/export/student/1002",
        "/attendance/student/1002/history",
        "/grades/ds101/student/1002", "/grades/ds101/scores?student_id=1002",
        "/office-hours/students/1002/summary",
        "/office-hours/bookings?student_id=1002",
    ):
        response = await client.get(path, headers=headers)
        assert response.status_code == 403, (path, response.text)
    response = await client.post(
        "/student/1002/courses/ds101/sessions", json={"title": "Stolen"}, headers=headers,
    )
    assert response.status_code == 403


async def test_chat_session_ownership_for_reads_writes_and_chat(client, auth_headers):
    victim = sessions.create_session(1002, "ds101", "Private")
    sid = victim["session_id"]
    headers = auth_headers("student1001")
    for method, path, body in (
        ("GET", f"/sessions/{sid}", None),
        ("GET", f"/sessions/{sid}/messages", None),
        ("PATCH", f"/sessions/{sid}", {"title": "Stolen"}),
        ("DELETE", f"/sessions/{sid}", None),
        ("POST", "/chat", {"moodle_user_id": 1001, "message": "Hi", "session_id": sid}),
        ("POST", "/chat", {"moodle_user_id": 1002, "message": "Hi"}),
        ("POST", "/record-struggle", {"moodle_user_id": 1002, "topic": "Private"}),
    ):
        response = await client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, (method, path, response.text)
    assert sessions.get_session(sid)["title"] == "Private"
    owner = auth_headers("student1002")
    assert (await client.get(f"/sessions/{sid}", headers=owner)).status_code == 200
    assert (await client.get(f"/sessions/{sid}/messages", headers=owner)).status_code == 200
    assert (await client.patch(f"/sessions/{sid}", json={"title": "Mine"}, headers=owner)).status_code == 200
    assert (await client.delete(f"/sessions/{sid}", headers=owner)).status_code == 200


async def test_student_blocked_from_all_teacher_routes(client, auth_headers):
    headers = auth_headers("student1001")
    for method, path in DATA_ROUTES:
        if path == "/teacher" or path.startswith("/teacher/"):
            path = path.replace("{moodle_user_id}", "1001")
            response = await client.request(method, path, headers=headers)
            assert response.status_code == 403, path


async def test_teacher_allowed_and_scoped(client, auth_headers):
    sessions.create_session(1002, "ds101", "Class")
    session = sessions.create_session(1002, "mk201", "Other class")
    headers = auth_headers("teacher")
    for path in (
        "/teacher/students", "/teacher/students/1002/memories",
        "/teacher/summaries", "/teacher/me/course", "/analytics/class",
        "/student/1002/courses/ds101/sessions", "/analytics/student/1002",
    ):
        assert (await client.get(path, headers=headers)).status_code == 200, path
    for path in (
        "/teacher/students?course_id=mk201", "/teacher/me/course?username=teacher_huang",
        f"/sessions/{session['session_id']}/messages", "/grades/mk201/overview",
        "/reports/weekly/mk201", "/courses/mk201/materials",
    ):
        assert (await client.get(path, headers=headers)).status_code == 403, path
    response = await client.get("/student/1002/courses", headers=headers)
    assert {c["course_id"] for c in response.json()["courses"]} == {"ds101"}
    response = await client.post(
        "/attendance/sessions", json={"course_id": "ds101"}, headers=headers,
    )
    assert response.status_code == 200
    response = await client.post(
        "/attendance/sessions", json={"course_id": "mk201"}, headers=headers,
    )
    assert response.status_code == 403


async def test_student_score_and_booking_lists_are_filtered(client, auth_headers):
    gm = app_module._grades
    gm.set_categories("ds101", [{"name": "Quiz", "weight": 100}])
    for student_id in (1001, 1002):
        gm.record_score("ds101", student_id=student_id, category="Quiz", item="Q1", score=8, total=10)
        slot = app_module._office_hours.create_slot(
            "ds101", teacher_id=1, start_time=100 + student_id, end_time=200 + student_id,
        )
        app_module._office_hours.book_slot(slot.slot_id, student_id=student_id)
    headers = auth_headers("student1001")
    for path in ("/grades/ds101/scores", "/office-hours/bookings"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200
        assert {row["student_id"] for row in response.json()} == {1001}
    other = app_module._office_hours.list_bookings(student_id=1002)[0]
    for method, path in (
        ("GET", f"/office-hours/bookings/{other.booking_id}"),
        ("POST", f"/office-hours/bookings/{other.booking_id}/cancel"),
    ):
        assert (await client.request(method, path, headers=headers)).status_code == 403


async def test_student_body_ids_and_teacher_actions(client, auth_headers):
    headers = auth_headers("student1001")
    for path, body in (
        ("/quiz/sessions/missing/answer", {"student_id": 1002, "question_idx": 0, "selected": "A"}),
        ("/interaction/polls/missing/vote", {"student_id": 1002, "option_idx": 0}),
        ("/interaction/questions", {"course_id": "ds101", "student_id": 1002, "text": "Hi"}),
        ("/interaction/questions/missing/upvote", {"student_id": 1002}),
        ("/interaction/danmaku", {"course_id": "ds101", "student_id": 1002, "text": "Hi"}),
        ("/attendance/sessions/missing/checkin", {"student_id": 1002}),
        ("/attendance/checkin-by-code", {"student_id": 1002, "code": "123456"}),
        ("/office-hours/slots/missing/book", {"student_id": 1002}),
        ("/demo/reset", None), ("/demo/semester", None), ("/import", None),
        ("/grades/ds101/scores", {"student_id": 1001, "category": "Quiz", "item": "Q1", "score": 10}),
    ):
        response = await client.post(path, json=body, headers=headers)
        assert response.status_code == 403, (path, response.text)

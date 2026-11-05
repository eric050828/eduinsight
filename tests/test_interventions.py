"""Diagnosis -> targeted review assignment -> follow-up on completion and struggle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight import assignments, auth, class_analytics, diagnostics, interventions, sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.config import settings
from eduinsight.courses import enroll
from eduinsight.grades import GradeManager
from eduinsight.rag import CourseRAG


@pytest.fixture
async def client(monkeypatch, auth_headers):
    memory = Memory(settings.memory_db_path)
    monkeypatch.setattr(app_module, "_memory", memory)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(memory))
    monkeypatch.setattr(app_module, "_rag", CourseRAG(memory))
    monkeypatch.setattr(app_module, "_grades", GradeManager())
    for student_id in (1001, 1002, 1003):
        enroll("ds101", student_id, source="test")
        sessions.create_session(student_id, "ds101")
        auth_headers(f"student{student_id}")  # Creates the student account.
    for student_id in (1001, 1002):
        memory.add(
            f"moodle:{student_id}", "Struggling with JOIN: confused by NULL",
            category="struggling", extract=False,
        )
    app = FastAPI()
    for router in (auth.router, diagnostics.router, interventions.router, assignments.router,
                   class_analytics.router):
        app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.memory = memory
        yield client


async def dispatch(client, auth_headers, students=(1001, 1002), username="teacher"):
    return await client.post("/diagnostics/ds101/interventions", headers=auth_headers(username), json={
        "topic": "JOIN", "student_ids": list(students), "description": "重做 JOIN 練習",
        "due_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
    })


async def test_dispatch_creates_a_targeted_assignment(client, auth_headers):
    response = await dispatch(client, auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["topic"] == "JOIN" and body["assignment"]["title"] == "複習：JOIN"
    assert [m["moodle_user_id"] for m in body["members"]] == [1001, 1002]
    assert (body["member_count"], body["submitted_count"], body["completion_rate"]) == (2, 0, 0)
    assignment_id = body["assignment"]["id"]

    seen = (await client.get("/courses/ds101/assignments", headers=auth_headers("student1001"))).json()
    assert [a["id"] for a in seen if a["targeted"]] == [assignment_id]
    hidden = (await client.get("/courses/ds101/assignments", headers=auth_headers("student1003"))).json()
    assert assignment_id not in [a["id"] for a in hidden]
    detail = await client.get(f"/assignments/{assignment_id}", headers=auth_headers("student1003"))
    assert detail.status_code == 404
    submit = await client.put(
        f"/assignments/{assignment_id}/submission", headers=auth_headers("student1003"),
        json={"text": "x", "state": "submitted"},
    )
    assert submit.status_code == 404
    staff = (await client.get(f"/assignments/{assignment_id}", headers=auth_headers("teacher"))).json()
    assert staff["audience"] == [1001, 1002]


async def test_follow_up_tracks_completion_score_and_struggle(client, auth_headers):
    assignment_id = (await dispatch(client, auth_headers)).json()["assignment"]["id"]
    put = await client.put(
        f"/assignments/{assignment_id}/submission", headers=auth_headers("student1001"),
        json={"text": "LEFT JOIN 保留左表", "state": "submitted"},
    )
    assert put.status_code == 200, put.text
    graded = await client.post(
        f"/assignments/{assignment_id}/submissions/1001/grade", headers=auth_headers("teacher"),
        json={"score": 90},
    )
    assert graded.status_code == 200
    # Student 1001's struggle is resolved in memory; 1002 still struggles.
    memory = client.memory
    memory.forget("moodle:1001")
    memory.add("moodle:1001", "[SQL] Explains LEFT JOIN with NULL rows", extract=False)

    [item] = (await client.get(
        "/diagnostics/ds101/interventions", headers=auth_headers("teacher"),
    )).json()
    members = {m["moodle_user_id"]: m for m in item["members"]}
    assert members[1001]["status"] == "已評分" and members[1001]["score"] == 90
    assert members[1001]["still_struggling"] is False
    assert members[1002]["status"] == "未繳交" and members[1002]["still_struggling"] is True
    assert (item["submitted_count"], item["completion_rate"]) == (1, 0.5)
    assert (item["average_score"], item["still_struggling_count"]) == (90, 1)


async def test_targeted_work_stays_out_of_class_completion(client, auth_headers):
    await dispatch(client, auth_headers)
    completion = (await client.get(
        "/class-analytics/ds101/assignment-completion", headers=auth_headers("teacher"),
    )).json()
    assert "複習：JOIN" not in str(completion)


async def test_dispatch_validates_course_scope_and_enrollment(client, auth_headers):
    assert (await dispatch(client, auth_headers, username="teacher_huang")).status_code == 403
    assert (await dispatch(client, auth_headers, username="student1001")).status_code == 403
    assert (await dispatch(client, auth_headers, students=(1001, 1004))).status_code == 422
    response = await client.post("/diagnostics/ds101/interventions", json={})
    assert response.status_code == 401
    listed = await client.get("/diagnostics/ds101/interventions", headers=auth_headers("teacher_huang"))
    assert listed.status_code == 403


async def test_deleting_the_assignment_removes_the_intervention(client, auth_headers):
    assignment_id = (await dispatch(client, auth_headers)).json()["assignment"]["id"]
    deleted = await client.delete(f"/assignments/{assignment_id}", headers=auth_headers("teacher"))
    assert deleted.status_code == 204
    listed = await client.get("/diagnostics/ds101/interventions", headers=auth_headers("teacher"))
    assert listed.json() == []

"""Demo seeding respects teacher course membership and access restrictions."""

import pytest
from httpx import ASGITransport, AsyncClient

import eduinsight.app as app_module
from eduinsight.auth import TEACHER_COURSE_MAP
from eduinsight.sessions import list_sessions


@pytest.mark.parametrize("seed_semester", [False, True])
async def test_demo_teacher_scope(monkeypatch, auth_headers, seed_semester):
    monkeypatch.setattr(app_module, "_memory", None)
    monkeypatch.setattr(app_module, "_assistant", None)
    monkeypatch.setattr(app_module, "_rag", None)
    monkeypatch.setattr(app_module, "_quiz", None)
    expected_ids = set(range(1001, 1006))
    transport = ASGITransport(app=app_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Repeat seeding to ensure course sessions do not accumulate.
        for _ in range(2):
            response = await client.post("/demo/reset", headers=auth_headers())
            assert response.status_code == 200
            assert response.json()["total_memories"] == 54
            if seed_semester:
                response = await client.post("/demo/semester", headers=auth_headers())
                assert response.status_code == 200
                expected_ids.add(2001)

        for username, course_id in TEACHER_COURSE_MAP.items():
            response = await client.get("/teacher/students", headers=auth_headers(username))
            assert response.status_code == 200
            assert response.json()["total_students"] > 0
            assert {s["moodle_user_id"] for s in response.json()["students"]} == expected_ids
            for student_id in expected_ids:
                assert len(list_sessions(student_id, course_id)) == 1

        wang_headers = auth_headers("teacher_wang")
        for endpoint in ("/teacher/students", "/teacher/summaries", "/analytics/class"):
            response = await client.get(endpoint, headers=wang_headers)
            assert response.status_code == 200
            response = await client.get(
                endpoint, params={"course_id": TEACHER_COURSE_MAP["teacher"]},
                headers=wang_headers,
            )
            assert response.status_code == 403

        response = await client.get("/teacher/students/1001/memories", headers=wang_headers)
        assert response.status_code == 200
        assert response.json()["count"] > 0

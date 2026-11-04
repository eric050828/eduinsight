"""Opt-in course catalog: staff open a course, only then students can discover it."""

import pytest
from eduinsight import auth, courses, enrollment, sessions
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(auth_headers):
    auth.create_user(auth.RegisterRequest(
        username="outsider", password="test123", display_name="outsider", moodle_user_id=2001,
    ))
    courses.enroll("ds101", 1001, source="test")
    sessions.create_session(1001, "ds101")
    app = FastAPI()
    for router in (auth.router, courses.router, enrollment.router):
        app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def catalog(client, auth_headers, username="outsider"):
    response = await client.get("/enrollment/catalog", headers=auth_headers(username))
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


async def set_open(client, auth_headers, course_id="ds101", username="teacher", value=True):
    return await client.put(
        f"/courses/{course_id}/enrollment/open", json={"open": value},
        headers=auth_headers(username),
    )


async def test_courses_are_hidden_until_staff_open_them(client, auth_headers):
    assert await catalog(client, auth_headers) == []
    response = await set_open(client, auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"course_id": "ds101", "open": True}
    rows = (await client.get("/enrollment/catalog", headers=auth_headers("outsider"))).json()
    assert rows == [{"id": "ds101", "name": "資料結構", "teacher_name": "陳教授"}]
    state = await client.get("/courses/ds101/enrollment/open", headers=auth_headers("teacher"))
    assert state.json()["open"] is True

    assert (await set_open(client, auth_headers, value=False)).status_code == 200
    assert await catalog(client, auth_headers) == []


async def test_catalog_omits_enrolled_courses(client, auth_headers):
    await set_open(client, auth_headers)
    assert await catalog(client, auth_headers, "student1001") == []


async def test_catalog_does_not_grant_course_content(client, auth_headers):
    await set_open(client, auth_headers)
    info = await client.get("/courses/ds101/info", headers=auth_headers("outsider"))
    assert info.status_code == 403
    listed = await client.get("/courses", headers=auth_headers("outsider"))
    assert "ds101" not in [row["id"] for row in listed.json()]


async def test_only_course_staff_can_open_enrollment(client, auth_headers):
    assert (await set_open(client, auth_headers, username="teacher_huang")).status_code == 403
    assert (await set_open(client, auth_headers, username="outsider")).status_code == 403
    assert (await set_open(client, auth_headers, username="admin")).status_code == 200
    hidden = await client.get("/courses/ds101/enrollment/open", headers=auth_headers("teacher_huang"))
    assert hidden.status_code == 403


async def test_catalog_requires_a_student(client, auth_headers):
    assert (await client.get("/enrollment/catalog")).status_code == 401
    response = await client.get("/enrollment/catalog", headers=auth_headers("teacher"))
    assert response.status_code == 403

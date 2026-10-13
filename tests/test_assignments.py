"""Assignments use real JWT authentication and an isolated SQLite database."""

from eduinsight.courses import enroll

from datetime import UTC, datetime, timedelta

import pytest
from eduinsight import assignments, auth, sessions
from eduinsight.auth import TEACHER_COURSE_MAP
from eduinsight.config import settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(auth_headers):
    # Do not import the production app: this router can be integrated independently.
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(assignments.router)
    for student_id in range(1001, 1006):
        enroll("ds101", student_id, source="test")
        sessions.create_session(student_id, "ds101")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def assignment_body(**changes):
    return {
        "course_id": "ds101",
        "title": "Practice",
        "description": "Explain your solution",
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "max_score": 100,
        **changes,
    }


async def create(client, auth_headers, **changes):
    response = await client.post(
        "/assignments",
        json=assignment_body(**changes),
        headers=auth_headers("teacher"),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def submit(client, auth_headers, assignment_id, student="student1001", **changes):
    return await client.put(
        f"/assignments/{assignment_id}/submission",
        json={"text": "My solution", "state": "submitted", **changes},
        headers=auth_headers(student),
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/assignments", assignment_body()),
        ("GET", "/courses/ds101/assignments", None),
        ("GET", "/assignments/missing", None),
        ("PATCH", "/assignments/missing", {"title": "Update"}),
        ("DELETE", "/assignments/missing", None),
        ("GET", "/assignments/missing/submissions", None),
        ("PUT", "/assignments/missing/submission", {"state": "draft"}),
        ("POST", "/assignments/missing/submission/withdraw", None),
        ("POST", "/assignments/missing/submissions/1001/grade", {"score": 80}),
    ],
)
async def test_all_routes_require_authentication(client, method, path, body):
    response = await client.request(method, path, json=body)
    assert response.status_code == 401
    response = await client.request(
        method,
        path,
        json=body,
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/assignments", assignment_body()),
        ("PATCH", "/assignments/{id}", {"title": "Update"}),
        ("DELETE", "/assignments/{id}", None),
        ("GET", "/assignments/{id}/submissions", None),
        ("POST", "/assignments/{id}/submissions/1001/grade", {"score": 80}),
    ],
)
async def test_students_cannot_use_staff_routes(client, auth_headers, method, path, body):
    assignment = await create(client, auth_headers)
    response = await client.request(
        method,
        path.format(id=assignment["id"]),
        json=body,
        headers=auth_headers("student1001"),
    )
    assert response.status_code == 403


async def test_course_ownership_and_admin_access(client, auth_headers):
    assignment = await create(client, auth_headers)
    assignment_id = assignment["id"]
    for method, path, body in (
        ("POST", "/assignments", assignment_body()),
        ("GET", "/courses/ds101/assignments", None),
        ("GET", f"/assignments/{assignment_id}", None),
        ("PATCH", f"/assignments/{assignment_id}", {"title": "Stolen"}),
        ("DELETE", f"/assignments/{assignment_id}", None),
        ("GET", f"/assignments/{assignment_id}/submissions", None),
        ("POST", f"/assignments/{assignment_id}/submissions/1001/grade", {"score": 80}),
    ):
        response = await client.request(
            method, path, json=body, headers=auth_headers("teacher_huang")
        )
        assert response.status_code == 403, response.text
    response = await client.post(
        "/assignments",
        json=assignment_body(course_id="mk201"),
        headers=auth_headers(),
    )
    assert response.status_code == 201
    assert (
        await client.get("/courses/mk201/assignments", headers=auth_headers())
    ).status_code == 200
    assert (
        await client.patch(
            f"/assignments/{assignment_id}",
            json={"description": "Admin edit"},
            headers=auth_headers(),
        )
    ).status_code == 200
    auth.create_user(
        auth.RegisterRequest(
            username="unmapped",
            password="test123",
            display_name="Unmapped",
            role="teacher",
        )
    )
    response = await client.post(
        "/assignments",
        json=assignment_body(),
        headers=auth_headers("unmapped"),
    )
    assert response.status_code == 403


async def test_enrollment_and_identity(client, auth_headers):
    other = await client.post(
        "/assignments",
        json=assignment_body(course_id="mk201"),
        headers=auth_headers("teacher_huang"),
    )
    assignment_id = other.json()["id"]
    headers = auth_headers("student1001")
    for method, path, body in (
        ("GET", "/courses/mk201/assignments", None),
        ("GET", f"/assignments/{assignment_id}", None),
        ("PUT", f"/assignments/{assignment_id}/submission", {"state": "submitted"}),
        ("POST", f"/assignments/{assignment_id}/submission/withdraw", None),
    ):
        assert (await client.request(method, path, json=body, headers=headers)).status_code == 403
    enroll("mk201", 1001, source="test")
    sessions.create_session(1001, "mk201")
    assert (await client.get(f"/assignments/{assignment_id}", headers=headers)).status_code == 200
    auth.create_user(
        auth.RegisterRequest(
            username="no_moodle",
            password="test123",
            display_name="No identity",
            role="student",
            moodle_user_id=9999,
        )
    )
    assert (
        await client.get(
            "/courses/ds101/assignments",
            headers=auth_headers("no_moodle"),
        )
    ).status_code == 403
    with auth._db() as conn:
        conn.execute("UPDATE users SET moodle_user_id = NULL WHERE username = 'no_moodle'")
        conn.commit()
    assert (
        await client.get(
            "/courses/ds101/assignments",
            headers=auth_headers("no_moodle"),
        )
    ).status_code == 403


async def test_draft_submit_withdraw_and_private_views(client, auth_headers):
    assignment_id = (await create(client, auth_headers))["id"]
    path = f"/assignments/{assignment_id}"
    headers = auth_headers("student1001")
    initial = (await client.get(path, headers=headers)).json()
    assert initial["status"] == "未繳交"
    assert initial["submission"] is None
    draft = await submit(
        client,
        auth_headers,
        assignment_id,
        state="draft",
        text="Private draft",
        file_name="solution.pdf",
        file_metadata={"size": 123, "content_type": "application/pdf"},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "草稿"
    assert draft.json()["file_metadata"]["size"] == 123
    assert draft.json()["submitted_at"] is None
    submitted = await submit(client, auth_headers, assignment_id, text="Private final")
    assert submitted.json()["status"] == "已繳交"
    assert submitted.json()["submitted_at"] is not None
    assert submitted.json()["late"] is False
    assert (await submit(client, auth_headers, assignment_id, state="draft")).status_code == 409
    for url in (path, "/courses/ds101/assignments?student_id=1001"):
        view = (await client.get(url, headers=auth_headers("student1002"))).json()
        view = view[0] if isinstance(view, list) else view
        assert view["status"] == "未繳交"
        assert view["submission"] is None
        assert view["score"] is None and view["feedback"] is None
        assert "Private" not in str(view)
    assert (
        await submit(
            client,
            auth_headers,
            assignment_id,
            student_id=1002,
        )
    ).status_code == 422
    staff_rows = (await client.get(f"{path}/submissions", headers=auth_headers("teacher"))).json()
    assert [row["student_id"] for row in staff_rows] == [1001]
    # The JWT's auth row ID is distinct from the Moodle student ID.
    assert auth.get_user_by_username("student1001")["id"] != 1001
    withdrawn = await client.post(f"{path}/submission/withdraw", headers=headers)
    assert withdrawn.status_code == 200
    assert withdrawn.json()["state"] == "draft"
    assert withdrawn.json()["submitted_at"] is None
    assert (await submit(client, auth_headers, assignment_id)).status_code == 200


async def test_late_submission_policy(client, auth_headers):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assignment_id = (await create(client, auth_headers, due_at=past))["id"]
    path = f"/assignments/{assignment_id}"
    view = (await client.get(path, headers=auth_headers("student1001"))).json()
    assert view["status"] == "已逾期"
    draft = await submit(client, auth_headers, assignment_id, state="draft")
    assert draft.status_code == 200
    assert draft.json()["state"] == "draft" and draft.json()["status"] == "已逾期"
    assert (await submit(client, auth_headers, assignment_id)).status_code == 409
    assert (await submit(client, auth_headers, assignment_id, allow_late=True)).status_code == 422
    enabled = await client.patch(path, json={"allow_late": True}, headers=auth_headers("teacher"))
    assert enabled.status_code == 200
    late = await submit(client, auth_headers, assignment_id)
    assert late.status_code == 200
    assert late.json()["late"] is True and late.json()["status"] == "已繳交"
    graded = await client.post(
        f"{path}/submissions/1001/grade",
        json={"score": 70},
        headers=auth_headers("teacher"),
    )
    assert graded.json()["late"] is True and graded.json()["status"] == "已評分"


async def test_timezone_and_exact_deadline(client, auth_headers, monkeypatch):
    deadline = datetime(2030, 1, 1, 12, tzinfo=UTC).timestamp()
    assignment = await create(client, auth_headers, due_at="2030-01-01T20:00:00+08:00")
    assert assignment["due_at"] == "2030-01-01T12:00:00+00:00"
    monkeypatch.setattr(assignments.time, "time", lambda: deadline)
    assert (await submit(client, auth_headers, assignment["id"])).json()["late"] is False
    monkeypatch.setattr(assignments.time, "time", lambda: deadline + 0.001)
    assert (
        await submit(client, auth_headers, assignment["id"], student="student1002")
    ).status_code == 409


async def test_grading_validation_and_locks(client, auth_headers):
    assignment_id = (await create(client, auth_headers, max_score=10))["id"]
    path = f"/assignments/{assignment_id}"
    grade_path = f"{path}/submissions/1001/grade"
    staff = auth_headers("teacher")
    assert (await client.post(grade_path, json={"score": 8}, headers=staff)).status_code == 404
    assert (
        await client.post(
            f"{path}/submissions/9999/grade",
            json={"score": 8},
            headers=staff,
        )
    ).status_code == 403
    assert (await submit(client, auth_headers, assignment_id, state="draft")).status_code == 200
    assert (await client.post(grade_path, json={"score": 8}, headers=staff)).status_code == 409
    assert (await submit(client, auth_headers, assignment_id)).status_code == 200
    for score in (-1, 11):
        assert (
            await client.post(grade_path, json={"score": score}, headers=staff)
        ).status_code == 422
    grade = await client.post(
        grade_path, json={"score": 8, "feedback": "Private feedback"}, headers=staff
    )
    assert grade.status_code == 200
    assert grade.json()["status"] == "已評分"
    assert grade.json()["graded_at"] is not None
    for url in (path, "/courses/ds101/assignments"):
        result = (await client.get(url, headers=auth_headers("student1001"))).json()
        view = result[0] if isinstance(result, list) else result
        assert view["score"] == 8 and view["feedback"] == "Private feedback"
        other = (await client.get(url, headers=auth_headers("student1002"))).json()
        assert "Private feedback" not in str(other)
    assert (await submit(client, auth_headers, assignment_id)).status_code == 409
    assert (
        await client.post(
            f"{path}/submission/withdraw",
            headers=auth_headers("student1001"),
        )
    ).status_code == 409
    assert (await client.patch(path, json={"max_score": 7}, headers=staff)).status_code == 409
    regrade = await client.post(
        grade_path, json={"score": 0, "feedback": "Revised"}, headers=auth_headers()
    )
    assert regrade.status_code == 200 and regrade.json()["score"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"title": "  "},
        {"max_score": 0},
        {"max_score": -1},
        {"due_at": "not-a-date"},
        {"due_at": "2030-01-01T12:00:00"},
        {"course_id": "ds101", "student_id": 1002},
    ],
)
async def test_invalid_create(client, auth_headers, body):
    response = await client.post(
        "/assignments", json=assignment_body(**body), headers=auth_headers("teacher")
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"title": None},
        {"title": " "},
        {"max_score": 0},
        {"allow_late": None},
        {"description": None},
        {"due_at": None},
        {"course_id": "mk201"},
    ],
)
async def test_invalid_patch(client, auth_headers, patch):
    assignment_id = (await create(client, auth_headers))["id"]
    response = await client.patch(
        f"/assignments/{assignment_id}",
        json=patch,
        headers=auth_headers("teacher"),
    )
    assert response.status_code == 422


async def test_update_delete_persistence_and_missing_resources(client, auth_headers, tmp_path):
    assignment_id = (await create(client, auth_headers))["id"]
    path = f"/assignments/{assignment_id}"
    assert (await submit(client, auth_headers, assignment_id)).status_code == 200
    assert settings.auth_db_path == str(tmp_path / "auth.db")
    app = FastAPI()
    app.include_router(assignments.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as restarted:
        persisted = await restarted.get(path, headers=auth_headers("student1001"))
        assert persisted.json()["submission"]["text"] == "My solution"
    patch = {"title": " Updated ", "description": "", "max_score": 50, "allow_late": True}
    updated = await client.patch(path, json=patch, headers=auth_headers("teacher"))
    assert updated.status_code == 200 and updated.json()["title"] == "Updated"
    assert updated.json()["description"] == ""
    assert (await client.delete(path, headers=auth_headers())).status_code == 204
    with assignments._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assignment_submissions").fetchone()[0] == 0
    for method, url, body in (
        ("GET", path, None),
        ("DELETE", path, None),
        ("PATCH", path, {"title": "x"}),
        ("GET", f"{path}/submissions", None),
        ("POST", f"{path}/submissions/1001/grade", {"score": 1}),
    ):
        assert (
            await client.request(method, url, json=body, headers=auth_headers())
        ).status_code == 404
    assert (await submit(client, auth_headers, assignment_id)).status_code == 404
    assert (
        await client.post(
            f"{path}/submission/withdraw",
            headers=auth_headers("student1001"),
        )
    ).status_code == 404
    assert (
        await client.get("/courses/unknown/assignments", headers=auth_headers())
    ).status_code == 404
    assert (
        await client.post(
            "/assignments",
            json=assignment_body(course_id="unknown"),
            headers=auth_headers(),
        )
    ).status_code == 404


async def test_staff_cannot_impersonate_students(client, auth_headers):
    assignment_id = (await create(client, auth_headers))["id"]
    for user in ("teacher", "admin"):
        assert (await submit(client, auth_headers, assignment_id, student=user)).status_code == 403
        assert (
            await client.post(
                f"/assignments/{assignment_id}/submission/withdraw",
                headers=auth_headers(user),
            )
        ).status_code == 403
    assert (
        await client.post(
            f"/assignments/{assignment_id}/submission/withdraw",
            headers=auth_headers("student1001"),
        )
    ).status_code == 404


async def test_seed_idempotency_and_preserves_existing_work(client, auth_headers):
    for course_id in set(TEACHER_COURSE_MAP.values()) - {"ds101"}:
        for student_id in range(1001, 1006):
            enroll(course_id, student_id, source="test")
            sessions.create_session(student_id, course_id)
    first = assignments.seed_demo_assignments()
    assert first == {
        "assignments_created": 3 * len(set(TEACHER_COURSE_MAP.values())),
        "submissions_created": 9 * len(set(TEACHER_COURSE_MAP.values())),
    }
    with assignments._db() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM assignments ORDER BY id")]
        assert {
            row[0] for row in conn.execute("SELECT DISTINCT student_id FROM assignment_submissions")
        } == set(range(1001, 1006))
    assert assignments.seed_demo_assignments() == {
        "assignments_created": 0,
        "submissions_created": 0,
    }
    with assignments._db() as conn:
        assert [
            tuple(row) for row in conn.execute("SELECT * FROM assignments ORDER BY id")
        ] == before
    assignment_id = "demo-assignment-ds101-2"
    assert (await submit(client, auth_headers, assignment_id, text="Real work")).status_code == 200
    assert (
        await client.patch(
            f"/assignments/{assignment_id}",
            json={"title": "Teacher edit"},
            headers=auth_headers("teacher"),
        )
    ).status_code == 200
    assignments.seed_demo_assignments()
    view = (
        await client.get(f"/assignments/{assignment_id}", headers=auth_headers("student1001"))
    ).json()
    assert view["title"] == "Teacher edit" and view["submission"]["text"] == "Real work"
    for username, course_id in TEACHER_COURSE_MAP.items():
        listing = await client.get(
            f"/courses/{course_id}/assignments", headers=auth_headers(username)
        )
        assert listing.status_code == 200 and len(listing.json()) == 3


async def test_seed_does_not_enroll_students(client):
    assignments.seed_demo_assignments()
    with assignments._db() as conn:
        assert (
            conn.execute("SELECT COUNT(DISTINCT course_id) FROM chat_sessions").fetchone()[0] == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM assignment_submissions s JOIN assignments a "
                "ON a.id = s.assignment_id WHERE a.course_id != 'ds101'",
            ).fetchone()[0]
            == 0
        )


async def test_invalid_submission_fields(client, auth_headers):
    assignment_id = (await create(client, auth_headers))["id"]
    for changes in ({"state": "graded"}, {"score": 100}, {"file_metadata": {"data": "x" * 20001}}):
        assert (await submit(client, auth_headers, assignment_id, **changes)).status_code == 422

"""Real JWT management, disabled accounts, catalog, structure and preferences."""

from eduinsight.courses import enroll

import json
import sqlite3
from types import SimpleNamespace

import pytest
from eduinsight import (
    admin_manage,
    assignments,
    auth,
    course_structure,
    courses,
    platform_admin,
    preferences,
    sessions,
)
from eduinsight.config import settings
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "login_throttle_enabled", False)
    app = FastAPI()
    for module in (auth, courses, admin_manage, course_structure, preferences, platform_admin):
        app.include_router(module.router)
    with TestClient(app) as client:
        yield client


PROTECTED = [
    ("GET", "/admin/users", None),
    (
        "POST",
        "/admin/users",
        {
            "username": "new-user",
            "password": "pass123",
            "display_name": "New user",
            "role": "student",
        },
    ),
    ("PATCH", "/admin/users/1", {"display_name": "New name"}),
    ("POST", "/admin/users/1/reset-password", {}),
    ("POST", "/admin/courses", {"id": "new-course", "name": "Course"}),
    ("PATCH", "/admin/courses/ds101", {"description": "Description"}),
    ("POST", "/course-structure/ds101/sections", {"week": 1, "title": "Week"}),
    ("PATCH", "/course-structure/sections/missing", {"title": "Week"}),
    ("DELETE", "/course-structure/sections/missing", None),
    (
        "POST",
        "/course-structure/ds101/sections/missing/activities",
        {"type": "quiz", "title": "Quiz"},
    ),
    ("PATCH", "/course-structure/activities/missing", {"title": "Quiz"}),
    ("DELETE", "/course-structure/activities/missing", None),
    ("GET", "/me/preferences", None),
    ("PUT", "/me/preferences", {"theme": "dark"}),
    ("GET", "/admin/settings", None),
    ("PUT", "/admin/settings", {"site_name": "School"}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_new_routes_require_authentication(client, method, path, body, headers):
    assert client.request(method, path, json=body, headers=headers).status_code == 401


@pytest.mark.parametrize(
    "method,path,body", [entry for entry in PROTECTED if not entry[1].startswith("/me/")]
)
def test_students_cannot_manage(client, auth_headers, method, path, body):
    assert (
        client.request(method, path, json=body, headers=auth_headers("student1001")).status_code
        == 403
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        entry
        for entry in PROTECTED
        if entry[1].startswith("/admin/") and entry[1] != "/admin/courses/ds101"
    ],
)
def test_teachers_cannot_administer(client, auth_headers, method, path, body):
    assert (
        client.request(method, path, json=body, headers=auth_headers("teacher")).status_code == 403
    )


def test_user_listing_filter_pagination_no_secrets(client, auth_headers):
    headers = auth_headers()
    result = client.get("/admin/users?role=student&q=STUDENT100&limit=2&offset=1", headers=headers)
    assert result.status_code == 200
    data = result.json()
    assert data["total"] == 5 and data["limit"] == 2 and data["offset"] == 1
    assert [u["username"] for u in data["users"]] == ["student1002", "student1003"]
    assert all(u["active"] is True for u in data["users"])
    assert "password" not in result.text and "hash" not in result.text
    for query in ("role=owner", "limit=0", "limit=501", "offset=-1"):
        assert client.get(f"/admin/users?{query}", headers=headers).status_code == 422


def test_create_update_reset_password_audited(client, auth_headers):
    headers = auth_headers()
    body = {
        "username": "new-student",
        "password": "first123",
        "display_name": "New",
        "role": "student",
        "moodle_user_id": 2222,
    }
    response = client.post("/admin/users", json=body, headers=headers)
    assert response.status_code == 201
    created = response.json()
    assert created["active"] and created["moodle_user_id"] == 2222
    assert "password" not in response.text
    user_id = created["id"]
    assert client.post("/admin/users", json=body, headers=headers).status_code == 409
    updated = client.patch(
        f"/admin/users/{user_id}",
        json={"display_name": "Updated", "role": "teacher"},
        headers=headers,
    )
    assert updated.json()["display_name"] == "Updated"
    assert updated.json()["role"] == "teacher"
    reset = client.post(f"/admin/users/{user_id}/reset-password", headers=headers)
    assert reset.status_code == 200
    generated = reset.json()["password"]
    assert len(generated) >= 20
    assert (
        client.post(
            "/auth/login", json={"username": body["username"], "password": "first123"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"username": body["username"], "password": generated}
        ).status_code
        == 200
    )
    given = client.post(
        f"/admin/users/{user_id}/reset-password", json={"password": "second123"}, headers=headers
    )
    assert given.json() == {"user_id": user_id, "reset": True}
    assert (
        client.post(
            "/auth/login", json={"username": body["username"], "password": "second123"}
        ).status_code
        == 200
    )
    audit = client.get("/platform/audit-log", headers=headers)
    assert audit.json()["total"] == 4
    assert generated not in audit.text and "second123" not in audit.text
    assert {e["action"] for e in audit.json()["entries"]} == {
        "user.created",
        "user.updated",
        "user.password_reset",
    }


def test_disable_blocks_login_and_existing_token_and_reenable(client, auth_headers):
    headers, token = auth_headers(), auth_headers("student1001")
    user_id = auth.get_user_by_username("student1001")["id"]
    assert client.get("/auth/me", headers=token).status_code == 200
    assert (
        client.patch(f"/admin/users/{user_id}", json={"active": False}, headers=headers).json()[
            "active"
        ]
        is False
    )
    assert (
        client.post(
            "/auth/login", json={"username": "student1001", "password": "student123"}
        ).status_code
        == 401
    )
    assert client.get("/auth/me", headers=token).status_code == 401
    assert client.get("/me/preferences", headers=token).status_code == 401
    client.patch(f"/admin/users/{user_id}", json={"active": True}, headers=headers)
    assert client.get("/auth/me", headers=token).status_code == 401
    assert (
        client.post(
            "/auth/login", json={"username": "student1001", "password": "student123"}
        ).status_code
        == 200
    )


def test_disabled_lti_bridge_identity_is_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr(auth.settings, "enable_lti_bridge", True)
    bridge = client.post("/auth/lti-bridge", json={"moodle_user_id": 5555}).json()
    client.patch(
        f"/admin/users/{bridge['user']['id']}", json={"active": False}, headers=auth_headers()
    )
    assert client.post("/auth/lti-bridge", json={"moodle_user_id": 5555}).status_code == 409
    assert (
        client.get(
            "/auth/me",
            headers={
                "Authorization": f"Bearer {bridge['access_token']}",
            },
        ).status_code
        == 401
    )


def test_role_change_revokes_existing_token(client, auth_headers):
    user = auth.create_user(
        auth.RegisterRequest(
            username="other-admin", password="pass123", display_name="Admin", role="admin"
        )
    )
    token = {"Authorization": f"Bearer {auth.create_access_token(user)}"}
    assert client.get("/admin/users", headers=token).status_code == 200
    client.patch(f"/admin/users/{user.id}", json={"role": "student"}, headers=auth_headers())
    assert client.get("/admin/users", headers=token).status_code == 401


@pytest.mark.parametrize("body", [{"active": False}, {"role": "student"}, {"role": "teacher"}])
def test_admin_cannot_disable_or_demote_self(client, auth_headers, body):
    user_id = auth.get_user_by_username("admin")["id"]
    assert (
        client.patch(f"/admin/users/{user_id}", json=body, headers=auth_headers()).status_code
        == 403
    )
    row = auth.get_user_by_id(user_id)
    assert row["active"] == 1 and row["role"] == "admin"
    assert client.get("/platform/audit-log", headers=auth_headers()).json()["total"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"role": "admin"},
        {"active": "false"},
        {"active": None},
        {"display_name": " "},
        {"password": "oops"},
    ],
)
def test_user_patch_validation(client, auth_headers, body):
    user_id = auth.get_user_by_username("student1001")["id"]
    assert (
        client.patch(f"/admin/users/{user_id}", json=body, headers=auth_headers()).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "admin"),
        ("password", "x"),
        ("password", "密" * 25),
        ("moodle_user_id", 0),
        ("display_name", " "),
        ("extra", True),
    ],
)
def test_user_create_validation(client, auth_headers, field, value):
    body = {"username": "new-user", "password": "pass123", "display_name": "New"}
    body[field] = value
    assert client.post("/admin/users", json=body, headers=auth_headers()).status_code == 422


def test_missing_users_and_password_validation(client, auth_headers):
    headers = auth_headers()
    assert (
        client.patch("/admin/users/99999", json={"active": False}, headers=headers).status_code
        == 404
    )
    assert client.post("/admin/users/99999/reset-password", headers=headers).status_code == 404
    for password in (None, "x", "a" * 73):
        assert (
            client.post(
                "/admin/users/1/reset-password", json={"password": password}, headers=headers
            ).status_code
            == 422
        )


def test_legacy_active_migration_idempotent(client, auth_headers, tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.db"
    row = auth.get_user_by_username("student1001")
    with sqlite3.connect(legacy) as conn:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, "
            "password_hash TEXT, display_name TEXT, role TEXT, moodle_user_id INTEGER, "
            "created_at REAL)"
        )
        conn.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row[k]
                for k in (
                    "id",
                    "username",
                    "password_hash",
                    "display_name",
                    "role",
                    "moodle_user_id",
                    "created_at",
                )
            ],
        )
    monkeypatch.setattr(settings, "auth_db_path", str(legacy))
    assert auth.get_user_by_id(row["id"])["active"] == 1
    auth.init_db()
    auth.init_db()
    assert (
        client.post(
            "/auth/login", json={"username": row["username"], "password": "student123"}
        ).status_code
        == 200
    )
    with auth._db() as conn:
        assert (
            len([c for c in conn.execute("PRAGMA table_info(users)") if c["name"] == "active"]) == 1
        )


def test_catalog_create_update_archive_persistence_and_assignment(client, auth_headers):
    admin = auth_headers()
    teacher = auth.create_user(
        auth.RegisterRequest(
            username="new-teacher", password="pass123", display_name="New teacher", role="teacher"
        )
    )
    teacher_headers = {"Authorization": f"Bearer {auth.create_access_token(teacher)}"}
    body = {"id": "new-course", "name": "New course", "teacher_username": teacher.username}
    assert client.post("/admin/courses", json=body, headers=admin).status_code == 201
    assert client.post("/admin/courses", json=body, headers=admin).status_code == 409
    listed = client.get("/courses", headers=teacher_headers).json()
    assert [c["id"] for c in listed] == ["new-course"]
    assert listed[0]["teacher_name"] == "New teacher"
    updated = client.patch(
        "/admin/courses/new-course",
        json={"name": "Renamed", "description": "Intro", "archived": True},
        headers=admin,
    ).json()
    assert updated["name"] == "Renamed" and updated["archived"]
    assert updated["description"] == "Intro"
    assert client.get("/courses/new-course/info", headers=teacher_headers).json() == updated
    assert (
        client.get("/courses/new-course/info", headers=auth_headers("student1001")).status_code
        == 403
    )
    enroll("new-course", 1001, source="test")
    sessions.create_session(1001, "new-course")
    assert (
        client.get("/courses/new-course/info", headers=auth_headers("student1001")).status_code
        == 200
    )
    assert (
        client.patch(
            "/admin/courses/new-course",
            json={"description": "Teacher intro"},
            headers=teacher_headers,
        ).status_code
        == 200
    )
    for changes in ({"name": "No"}, {"archived": False}, {"teacher_username": "teacher"}):
        assert (
            client.patch(
                "/admin/courses/new-course", json=changes, headers=teacher_headers
            ).status_code
            == 403
        )
    assert (
        client.patch(
            "/admin/courses/new-course", json={"description": "No"}, headers=auth_headers("teacher")
        ).status_code
        == 403
    )
    client.patch("/admin/courses/new-course", json={"teacher_username": "teacher"}, headers=admin)
    assert client.get("/courses/new-course/info", headers=teacher_headers).status_code == 403
    assert {c["id"] for c in client.get("/courses", headers=auth_headers("teacher")).json()} == {
        "ds101",
        "new-course",
    }
    client.patch("/admin/courses/new-course", json={"teacher_username": None}, headers=admin)
    assert client.get("/courses/new-course/info", headers=admin).json()["teacher_name"] is None
    seed = admin_manage.seed_demo_admin_data()
    assert admin_manage.seed_demo_admin_data() == seed
    assert client.get("/courses/new-course/info", headers=admin).json()["name"] == "Renamed"


def test_seeded_catalog_updates_survive_reseed_and_reassignment(client, auth_headers):
    admin = auth_headers()
    client.patch(
        "/admin/courses/ds101",
        json={"name": "Updated", "teacher_username": "teacher_lin"},
        headers=admin,
    )
    admin_manage.seed_demo_admin_data()
    assert client.get("/courses/ds101/info", headers=admin).json()["name"] == "Updated"
    assert client.get("/courses/ds101/info", headers=auth_headers("teacher")).status_code == 403
    assert client.get("/courses/ds101/info", headers=auth_headers("teacher_lin")).status_code == 200


@pytest.mark.parametrize("seed_catalog", [False, True])
def test_course_authorization_inside_existing_write_transaction(auth_headers, seed_catalog):
    if seed_catalog:
        admin_manage.seed_demo_admin_data()
    user = auth._row_to_user(auth.get_user_by_username("teacher"))
    with assignments._db(write=True) as conn:
        conn.execute(
            "INSERT INTO assignments VALUES " "('lock-test', 'ds101', 'Title', '', 1, 100, 0, 1, 1)"
        )
        courses._check_course_access(user, "ds101")
        assert assignments._assignment(conn, "lock-test", user)["course_id"] == "ds101"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"name": " "},
        {"archived": "false"},
        {"teacher_username": "student1001"},
        {"teacher_username": "missing"},
        {"extra": 1},
    ],
)
def test_catalog_patch_validation(client, auth_headers, body):
    assert (
        client.patch("/admin/courses/ds101", json=body, headers=auth_headers()).status_code == 422
    )


def test_catalog_invalid_slug_missing_course_disabled_teacher(client, auth_headers):
    admin = auth_headers()
    assert (
        client.post(
            "/admin/courses", json={"id": "../bad", "name": "Bad"}, headers=admin
        ).status_code
        == 422
    )
    assert (
        client.patch("/admin/courses/missing", json={"name": "Name"}, headers=admin).status_code
        == 404
    )
    teacher_id = auth.get_user_by_username("teacher")["id"]
    client.patch(f"/admin/users/{teacher_id}", json={"active": False}, headers=admin)
    assert (
        client.post(
            "/admin/courses",
            json={"id": "new-course", "name": "Name", "teacher_username": "teacher"},
            headers=admin,
        ).status_code
        == 422
    )


def test_participants_have_auth_and_moodle_ids_no_secrets(client, auth_headers, monkeypatch):
    from eduinsight import app as app_module

    memory = sqlite3.connect(":memory:", check_same_thread=False)
    memory.executescript(
        "CREATE TABLE facts (user_id TEXT, created_at REAL, updated_at REAL); "
        "CREATE TABLE messages (user_id TEXT, created_at REAL);"
    )
    monkeypatch.setattr(
        app_module,
        "get_assistant",
        lambda: SimpleNamespace(
            memory=SimpleNamespace(_store=SimpleNamespace(_get_conn=lambda: memory)),
        ),
    )
    try:
        enroll("ds101", 1001, source="test")
        sessions.create_session(1001, "ds101")
        result = client.get("/courses/ds101/participants", headers=auth_headers()).json()
        by_name = {p["username"]: p for p in result}
        assert by_name["teacher"]["user_id"] == auth.get_user_by_username("teacher")["id"]
        assert by_name["teacher"]["moodle_user_id"] is None
        assert by_name["student1001"]["user_id"] == auth.get_user_by_username("student1001")["id"]
        assert by_name["student1001"]["moodle_user_id"] == 1001
        assert all("password_hash" not in p for p in result)
    finally:
        memory.close()


def _section(client, headers, course="ds101", week=1):
    result = client.post(
        f"/course-structure/{course}/sections",
        json={"week": week, "title": "Week"},
        headers=headers,
    )
    assert result.status_code == 201
    return result.json()["id"]


def _activity(client, headers, section_id, course="ds101", **changes):
    result = client.post(
        f"/course-structure/{course}/sections/{section_id}/activities",
        json={"type": "quiz", "title": "Quiz", **changes},
        headers=headers,
    )
    assert result.status_code == 201
    return result.json()["id"]


@pytest.mark.parametrize("delete_parent", [False, True])
def test_structure_editing_persistence_cascade_and_audit(client, auth_headers, delete_parent):
    headers = auth_headers("teacher")
    section_id = _section(client, headers)
    activity_id = _activity(client, headers, section_id)
    assert (
        client.patch(
            f"/course-structure/sections/{section_id}",
            json={"week": 2, "title": "Changed"},
            headers=headers,
        ).status_code
        == 200
    )
    updated = client.patch(
        f"/course-structure/activities/{activity_id}",
        json={"title": "Video", "type": "video"},
        headers=headers,
    )
    assert updated.json()["type"] == "video"
    sections = client.get("/course-structure/ds101", headers=headers).json()["sections"]
    assert sections[0]["week"] == 2 and sections[0]["activities"][0]["title"] == "Video"
    enroll("ds101", 1001, source="test")
    sessions.create_session(1001, "ds101")
    assert (
        client.put(
            f"/course-structure/ds101/activities/{activity_id}/complete",
            headers=auth_headers("student1001"),
        ).status_code
        == 200
    )
    path = (
        f"/course-structure/sections/{section_id}"
        if delete_parent
        else f"/course-structure/activities/{activity_id}"
    )
    assert client.delete(path, headers=headers).status_code == 200
    with course_structure._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM course_activity_completions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM course_activities").fetchone()[0] == 0
    assert client.delete(path, headers=headers).status_code == 404
    audit = client.get("/platform/audit-log", headers=auth_headers()).json()
    assert audit["total"] == 5
    assert all(e["actor"] == "teacher" for e in audit["entries"])


def test_structure_rejects_other_teacher_and_wrong_course(client, auth_headers):
    teacher, other = auth_headers("teacher"), auth_headers("teacher_huang")
    section_id = _section(client, teacher)
    activity_id = _activity(client, teacher, section_id)
    for method, path, body in [
        ("POST", "/course-structure/ds101/sections", {"week": 2, "title": "No"}),
        ("PATCH", f"/course-structure/sections/{section_id}", {"title": "No"}),
        ("DELETE", f"/course-structure/sections/{section_id}", None),
        (
            "POST",
            f"/course-structure/ds101/sections/{section_id}/activities",
            {"type": "quiz", "title": "No"},
        ),
        ("PATCH", f"/course-structure/activities/{activity_id}", {"title": "No"}),
        ("DELETE", f"/course-structure/activities/{activity_id}", None),
    ]:
        assert client.request(method, path, json=body, headers=other).status_code == 403
    assert (
        client.post(
            f"/course-structure/mk201/sections/{section_id}/activities",
            json={"type": "quiz", "title": "No"},
            headers=other,
        ).status_code
        == 404
    )


def test_structure_validation_unique_week_and_assignment_course(client, auth_headers):
    headers = auth_headers()
    assignments.seed_demo_assignments()
    section_id = _section(client, headers)
    second = _section(client, headers, week=2)
    assert (
        client.post(
            "/course-structure/ds101/sections", json={"week": 1, "title": "Dup"}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/course-structure/sections/{second}", json={"week": 1}, headers=headers
        ).status_code
        == 409
    )
    for body in ({"week": 0}, {"week": None}, {"title": " "}, {}, {"extra": 1}):
        assert (
            client.patch(
                f"/course-structure/sections/{section_id}", json=body, headers=headers
            ).status_code
            == 422
        )
    for body in (
        {"type": "invalid", "title": "Title"},
        {"type": "assignment", "title": "Title", "assignment_id": "missing"},
        {"type": "assignment", "title": "Title", "assignment_id": "demo-assignment-mk201-1"},
        {"type": "quiz", "title": "Title", "assignment_id": "demo-assignment-ds101-1"},
    ):
        assert (
            client.post(
                f"/course-structure/ds101/sections/{section_id}/activities",
                json=body,
                headers=headers,
            ).status_code
            == 422
        )
    activity_id = _activity(
        client, headers, section_id, type="assignment", assignment_id="demo-assignment-ds101-1"
    )
    for body in (
        {"type": None},
        {},
        {"assignment_id": "demo-assignment-mk201-1"},
        {"type": "video"},
    ):
        assert (
            client.patch(
                f"/course-structure/activities/{activity_id}", json=body, headers=headers
            ).status_code
            == 422
        )
    assert (
        client.patch(
            f"/course-structure/activities/{activity_id}",
            json={"type": "video", "assignment_id": None},
            headers=headers,
        ).status_code
        == 200
    )


def test_db_assigned_teacher_can_edit_new_course_structure(client, auth_headers):
    admin = auth_headers()
    client.post(
        "/admin/courses",
        json={"id": "new-course", "name": "Course", "teacher_username": "teacher"},
        headers=admin,
    )
    headers = auth_headers("teacher")
    section_id = _section(client, headers, course="new-course")
    _activity(client, headers, section_id, course="new-course", type="discussion")
    assert len(client.get("/course-structure/new-course", headers=headers).json()["sections"]) == 1


def test_structure_seeding_preserves_manual_sections_and_staff_deletions(client, auth_headers):
    headers = auth_headers()
    manual = _section(client, headers)
    course_structure.seed_demo_course_structure()
    body = client.get("/course-structure/ds101", headers=headers).json()
    assert body["sections"][0]["id"] == manual
    assert body["sections"][0]["activities"] == []
    activity = "demo-activity-ds101-2-reading"
    section = "demo-section-ds101-3"
    assert (
        client.delete(f"/course-structure/activities/{activity}", headers=headers).status_code
        == 200
    )
    assert (
        client.delete(f"/course-structure/sections/{section}", headers=headers).status_code == 200
    )
    course_structure.seed_demo_course_structure()
    with course_structure._db() as conn:
        assert (
            conn.execute("SELECT 1 FROM course_activities WHERE id = ?", (activity,)).fetchone()
            is None
        )
        assert (
            conn.execute("SELECT 1 FROM course_sections WHERE id = ?", (section,)).fetchone()
            is None
        )


def test_preferences_exact_serialized_size_boundary(client, auth_headers):
    headers = auth_headers("student1001")
    overhead = len(json.dumps({"dashboard_layout": [""]}).encode("utf-8"))
    body = {"dashboard_layout": ["x" * (16 * 1024 - overhead)]}
    assert client.put("/me/preferences", json=body, headers=headers).status_code == 200
    body["dashboard_layout"][0] += "x"
    assert client.put("/me/preferences", json=body, headers=headers).status_code == 422


def test_preferences_are_private_persistent_and_replace_json(client, auth_headers):
    first, second = auth_headers("student1001"), auth_headers("student1002")
    body = {
        "theme": "dark",
        "language": "en",
        "dashboard_layout": ["grades", "courses"],
        "notifications": {"email": False, "assignments": True},
    }
    assert client.get("/me/preferences", headers=first).json() == {}
    assert client.put("/me/preferences", json=body, headers=first).json() == body
    assert client.get("/me/preferences", headers=first).json() == body
    assert client.get("/me/preferences", headers=second).json() == {}
    assert client.put("/me/preferences", json={"theme": "light"}, headers=first).json() == {
        "theme": "light"
    }
    assert client.get("/me/preferences", headers=first).json() == {"theme": "light"}
    assert client.put("/me/preferences", json={}, headers=first).json() == {}


@pytest.mark.parametrize(
    "body",
    [
        {"unknown": True},
        {"theme": "blue"},
        {"language": "fr"},
        {"dashboard_layout": ["x"] * 31},
        {"dashboard_layout": [1]},
        {"theme": None},
        {"notifications": {"email": "false"}},
        {"dashboard_layout": ["x" * (16 * 1024)]},
        {"notifications": {"密" * 6000: True}},
    ],
)
def test_preferences_validation_and_size(client, auth_headers, body):
    headers = auth_headers("student1001")
    assert client.put("/me/preferences", json=body, headers=headers).status_code == 422
    assert client.get("/me/preferences", headers=headers).json() == {}


def test_preferences_accept_max_blocks_and_under_size(client, auth_headers):
    body = {
        "dashboard_layout": [f"block-{i}" for i in range(30)],
        "notifications": {"x" * 15000: True},
    }
    assert (
        client.put("/me/preferences", json=body, headers=auth_headers("teacher")).status_code == 200
    )


def test_settings_public_whitelist_validation_persistence_and_audit(client, auth_headers):
    admin = auth_headers()
    assert client.get("/public/settings").json() == {
        "site_name": "EduInsight",
        "maintenance_banner": "",
    }
    body = {"site_name": "School", "allow_self_register": False, "maintenance_banner": "Welcome"}
    assert client.put("/admin/settings", json=body, headers=admin).json() == body
    assert client.get("/admin/settings", headers=admin).json() == body
    assert client.get("/public/settings").json() == {
        "site_name": "School",
        "maintenance_banner": "Welcome",
    }
    admin_manage.seed_demo_admin_data()
    assert client.get("/admin/settings", headers=admin).json() == body
    for changes in (
        {"jwt_secret": "no"},
        {"site_name": " "},
        {"site_name": None},
        {"allow_self_register": "false"},
        {"maintenance_banner": "x" * 4001},
        {},
    ):
        assert client.put("/admin/settings", json=changes, headers=admin).status_code == 422
    assert (
        client.get("/platform/audit-log", headers=admin).json()["entries"][0]["action"]
        == "settings.updated"
    )

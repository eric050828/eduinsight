"""Real JWT authorization and persisted platform/course API coverage."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eduinsight import assignments, auth, course_structure, platform_admin, sessions
from eduinsight.config import settings
from eduinsight.courses import COURSE_CATALOG


@pytest.fixture
def client(auth_headers):
    app = FastAPI()
    app.include_router(platform_admin.router)
    app.include_router(course_structure.router)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def seeded(client):
    for student_id in (1001, 1002):
        sessions.create_session(student_id, "ds101")
    sessions.create_session(1001, "mk201")
    assignments.seed_demo_assignments()
    course_structure.seed_demo_course_structure()


ACTIVITY = "demo-activity-ds101-1-reading"
COMPLETION = f"/course-structure/ds101/activities/{ACTIVITY}/complete"
PROTECTED_ROUTES = [
    ("GET", "/platform/stats"), ("GET", "/platform/system"),
    ("GET", "/platform/audit-log"), ("GET", "/course-structure/ds101"),
    ("GET", "/course-structure/ds101/progress"), ("PUT", COMPLETION),
    ("DELETE", COMPLETION), ("GET", "/me/starred-courses"),
    ("PUT", "/me/starred-courses/ds101"), ("DELETE", "/me/starred-courses/ds101"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_routes_require_real_authentication(client, method, path, headers):
    assert client.request(method, path, headers=headers).status_code == 401


@pytest.mark.parametrize("actor", ["student1001", "teacher"])
@pytest.mark.parametrize("path", ["/platform/stats", "/platform/system", "/platform/audit-log"])
def test_platform_admin_only(client, auth_headers, actor, path):
    assert client.get(path, headers=auth_headers(actor)).status_code == 403


def test_platform_stats_counts_roles_sessions_activity_and_submissions(client, auth_headers):
    now = time.time()
    with sessions._db() as conn:
        conn.executemany("INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?, ?)", [
            ("recent", 1001, "ds101", "Recent", now, now),
            ("same-course", 1002, "ds101", "Recent", now, now),
            ("touched", 1001, "mk201", "Touched", now - 40 * 86400, now),
            ("inactive", 1001, "chm301", "Old", now - 31 * 86400, now - 31 * 86400),
        ])
        conn.commit()
    assignments.seed_demo_assignments()
    with assignments._db() as conn:
        assignment_count = conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]
        submission_count = conn.execute("SELECT COUNT(*) FROM assignment_submissions").fetchone()[0]
    response = client.get("/platform/stats", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {
        "registered_users": {"student": 5, "teacher": 5, "admin": 1}, "total_users": 11,
        "active_courses": 2, "total_chat_sessions": 4,
        "total_assignments": assignment_count, "total_submissions": submission_count,
    }
    assert assignment_count == 15 and submission_count > 0


def test_platform_stats_handles_uninitialized_optional_tables(client, auth_headers):
    body = client.get("/platform/stats", headers=auth_headers()).json()
    assert body["registered_users"] == {"student": 5, "teacher": 5, "admin": 1}
    assert body["active_courses"] == body["total_chat_sessions"] == 0
    assert body["total_assignments"] == body["total_submissions"] == 0


def test_platform_system_readonly_sizes_rows_uptime_and_missing_psutil(
    client, auth_headers, monkeypatch,
):
    monkeypatch.setitem(sys.modules, "psutil", None)
    with sqlite3.connect(settings.memory_db_path) as conn:
        conn.execute("CREATE TABLE facts (id INTEGER)")
        conn.executemany("INSERT INTO facts VALUES (?)", [(1,), (2,)])
    started = time.time() - 120
    monkeypatch.setattr(platform_admin, "_PROCESS_STARTED_AT", started)
    response = client.get("/platform/system", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert 120 <= body["uptime_seconds"] < 130
    assert body["python"].startswith("3.") and body["platform"]
    assert body["cpu"] is body["memory"] is None
    assert body["databases"]["auth"]["row_counts"]["users"] == 11
    assert body["databases"]["auth"]["row_counts"]["chat_sessions"] == 0
    assert body["databases"]["memory"]["row_counts"] == {"facts": 2}
    for name, path in (("auth", settings.auth_db_path), ("memory", settings.memory_db_path)):
        assert body["databases"][name]["size_bytes"] == Path(path).stat().st_size > 0
        assert body["databases"][name]["wal_size_bytes"] == 0


def test_platform_system_does_not_create_missing_memory_database(client, auth_headers):
    assert not Path(settings.memory_db_path).exists()
    body = client.get("/platform/system", headers=auth_headers()).json()
    assert body["databases"]["memory"] == {
        "size_bytes": 0, "wal_size_bytes": 0, "row_counts": {},
    }
    assert not Path(settings.memory_db_path).exists()


def test_platform_system_uses_already_installed_psutil(client, auth_headers, monkeypatch):
    fake = SimpleNamespace(
        cpu_percent=lambda interval: 12.5,
        getloadavg=lambda: (0.1, 0.2, 0.3),
        virtual_memory=lambda: SimpleNamespace(total=1000, available=600, used=400, percent=40),
        Process=lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=123)),
        Error=RuntimeError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake)
    body = client.get("/platform/system", headers=auth_headers()).json()
    assert body["cpu"] == {"percent": 12.5, "load_average": [0.1, 0.2, 0.3]}
    assert body["memory"] == {"total_bytes": 1000, "available_bytes": 600,
                              "used_bytes": 400, "percent": 40, "process_rss_bytes": 123}


def test_audit_lazy_creation_persistence_seed_and_pagination(client, auth_headers):
    headers = auth_headers()
    assert client.get("/platform/audit-log", headers=headers).json() == {
        "entries": [], "total": 0, "limit": 100, "offset": 0,
    }
    manual = platform_admin.record_audit("admin", "assignment.deleted", "assignment-123")
    assert manual["actor"] == "admin" and manual["action"] == "assignment.deleted"
    assert manual["target"] == "assignment-123" and manual["ts"] > 0
    assert platform_admin.seed_demo_audit() == 3
    before = client.get("/platform/audit-log", headers=headers).json()
    assert platform_admin.seed_demo_audit() == 0
    assert client.get("/platform/audit-log", headers=headers).json() == before
    with platform_admin._db() as conn:
        conn.execute("UPDATE platform_audit_log SET ts = 100")
    ordered = client.get("/platform/audit-log", headers=headers).json()
    assert ordered["total"] == 4
    assert [row["id"] for row in ordered["entries"]] == [4, 3, 2, 1]
    page = client.get("/platform/audit-log?limit=2&offset=1", headers=headers).json()
    assert page == {"entries": ordered["entries"][1:3], "total": 4, "limit": 2, "offset": 1}
    assert client.get("/platform/audit-log?offset=100", headers=headers).json()["entries"] == []
    for query in ("limit=0", "limit=501", "offset=-1", "limit=invalid"):
        assert client.get(f"/platform/audit-log?{query}", headers=headers).status_code == 422


def test_structure_seeds_all_catalog_courses_and_real_assignment_links(client, auth_headers, seeded):
    for course_id in COURSE_CATALOG:
        response = client.get(f"/course-structure/{course_id}", headers=auth_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["course_id"] == course_id
        assert [section["week"] for section in body["sections"]] == [1, 2, 3]
        for section in body["sections"]:
            assert section["title"].startswith(f"第 {section['week']} 週")
            assert {item["type"] for item in section["activities"]} == {
                "reading", "video", "quiz", "assignment", "discussion",
            }
            for item in section["activities"]:
                assert COURSE_CATALOG[course_id] in item["title"]
                assert "completed" not in item
                if (item["type"] == "assignment"
                        and course_id in auth.TEACHER_COURSE_MAP.values()):
                    with assignments._db() as conn:
                        row = conn.execute("SELECT course_id FROM assignments WHERE id = ?",
                                           (item["assignment_id"],)).fetchone()
                    assert row["course_id"] == course_id
                else:
                    assert item["assignment_id"] is None
    assert course_structure.seed_demo_course_structure() == {
        "sections_created": 0, "activities_created": 0, "assignment_links_updated": 0,
    }


def test_structure_seed_fills_links_when_assignments_arrive_later(client, auth_headers):
    first = course_structure.seed_demo_course_structure()
    assert first == {"sections_created": 3 * len(COURSE_CATALOG),
                     "activities_created": 15 * len(COURSE_CATALOG),
                     "assignment_links_updated": 0}
    assignments.seed_demo_assignments()
    second = course_structure.seed_demo_course_structure()
    assert second == {"sections_created": 0, "activities_created": 0,
                      "assignment_links_updated": 15}
    with assignments._db(write=True) as conn:
        conn.execute("DELETE FROM assignments WHERE id = 'demo-assignment-ds101-1'")
    with course_structure._db() as conn:
        assert conn.execute(
            "SELECT assignment_id FROM course_activities WHERE id = ?",
            ("demo-activity-ds101-1-assignment",),
        ).fetchone()[0] is None


@pytest.mark.parametrize("suffix", ["", "/progress"])
def test_course_reads_enforce_enrollment_and_teacher_ownership(
    client, auth_headers, seeded, suffix,
):
    path = f"/course-structure/ds101{suffix}"
    for actor in ("student1001", "student1002", "teacher", "admin"):
        assert client.get(path, headers=auth_headers(actor)).status_code == 200
    for actor in ("student1003", "teacher_huang"):
        assert client.get(path, headers=auth_headers(actor)).status_code == 403
    unmapped = auth.create_user(auth.RegisterRequest(
        username="new-teacher", password="pass123", display_name="Teacher", role="teacher",
    ))
    assert client.get(path, headers={
        "Authorization": f"Bearer {auth.create_access_token(unmapped)}",
    }).status_code == 403
    unknown = client.get(f"/course-structure/unknown{suffix}", headers=auth_headers())
    assert unknown.status_code == 404


def test_completion_is_persistent_private_idempotent_and_survives_reseed(
    client, auth_headers, seeded,
):
    a, b = auth_headers("student1001"), auth_headers("student1002")
    result = client.put(COMPLETION, headers=a)
    assert result.status_code == 200
    assert result.json()["completed"] is True
    assert client.put(COMPLETION, headers=a).json() == result.json()
    assert client.get("/course-structure/ds101", headers=a).json()["sections"][0][
        "activities"
    ][0]["completed"] is True
    assert client.get("/course-structure/ds101", headers=b).json()["sections"][0][
        "activities"
    ][0]["completed"] is False
    course_structure.seed_demo_course_structure()
    assert client.put(COMPLETION, headers=a).json() == result.json()
    assert client.get("/course-structure/ds101/progress", headers=a).json() == {
        "course_id": "ds101", "student_id": 1001, "completed": 1, "total": 15, "percent": 6.67,
    }
    assert client.get("/course-structure/ds101/progress", headers=b).json()["completed"] == 0
    assert client.delete(COMPLETION, headers=b).json()["completed"] is False
    assert client.get("/course-structure/ds101/progress", headers=a).json()["completed"] == 1
    with course_structure._db() as conn:
        persisted = conn.execute("SELECT student_id FROM course_activity_completions").fetchone()
        assert persisted[0] == 1001
    assert client.delete(COMPLETION, headers=a).json() == {
        "course_id": "ds101", "activity_id": ACTIVITY, "completed": False, "completed_at": None,
    }
    assert client.delete(COMPLETION, headers=a).status_code == 200
    assert client.get("/course-structure/ds101/progress", headers=a).json()["completed"] == 0


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_completion_write_guards_course_activity_and_roles(client, auth_headers, seeded, method):
    for actor in ("teacher", "admin", "teacher_huang", "student1003"):
        assert client.request(method, COMPLETION, headers=auth_headers(actor)).status_code == 403
    headers = auth_headers("student1001")
    for course, activity in (("ds101", "missing"), ("mk201", ACTIVITY)):
        path = f"/course-structure/{course}/activities/{activity}/complete"
        assert client.request(method, path, headers=headers).status_code == 404
    assert client.request(method, f"/course-structure/unknown/activities/{ACTIVITY}/complete",
                          headers=headers).status_code == 404
    with course_structure._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM course_activity_completions").fetchone()[0] == 0


def test_teacher_and_admin_progress_include_zero_progress_enrolled_students(
    client, auth_headers, seeded,
):
    client.put(COMPLETION, headers=auth_headers("student1001"))
    expected = {"course_id": "ds101", "total": 15, "students": [
        {"student_id": 1001, "completed": 1, "total": 15, "percent": 6.67},
        {"student_id": 1002, "completed": 0, "total": 15, "percent": 0.0},
    ]}
    for actor in ("teacher", "admin"):
        body = client.get("/course-structure/ds101/progress", headers=auth_headers(actor)).json()
        assert body == expected
    assert client.get("/course-structure/db101/progress", headers=auth_headers()).json() == {
        "course_id": "db101", "total": 15, "students": [],
    }


def test_unseeded_course_has_empty_structure_and_zero_progress(client, auth_headers):
    sessions.create_session(1001, "ds101")
    headers = auth_headers("student1001")
    assert client.get("/course-structure/ds101", headers=headers).json() == {
        "course_id": "ds101", "sections": [],
    }
    assert client.get("/course-structure/ds101/progress", headers=headers).json() == {
        "course_id": "ds101", "student_id": 1001, "completed": 0, "total": 0, "percent": 0.0,
    }


def test_stars_persist_are_private_and_idempotent(client, auth_headers, seeded):
    a, b = auth_headers("student1001"), auth_headers("student1002")
    assert client.get("/me/starred-courses", headers=a).json() == {"courses": []}
    for _ in range(2):
        assert client.put("/me/starred-courses/ds101", headers=a).json() == {
            "course_id": "ds101", "starred": True,
        }
    assert client.get("/me/starred-courses", headers=b).json() == {"courses": []}
    first = client.get("/me/starred-courses", headers=a).json()
    assert len(first["courses"]) == 1
    assert first["courses"][0]["course_id"] == "ds101"
    assert first["courses"][0]["name"] == "資料結構"
    assert first["courses"][0]["starred_at"] > 0
    assert client.put("/me/starred-courses/ds101", headers=a).status_code == 200
    assert client.get("/me/starred-courses", headers=a).json() == first
    assert client.delete("/me/starred-courses/ds101", headers=b).status_code == 200
    assert client.get("/me/starred-courses", headers=a).json() == first
    with course_structure._db() as conn:
        assert conn.execute("SELECT student_id FROM starred_courses").fetchone()[0] == 1001
    for _ in range(2):
        assert client.delete("/me/starred-courses/ds101", headers=a).json() == {
            "course_id": "ds101", "starred": False,
        }
    assert client.get("/me/starred-courses", headers=a).json() == {"courses": []}


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_star_writes_require_student_and_course_access(client, auth_headers, seeded, method):
    for actor in ("teacher", "admin", "student1003"):
        assert client.request(method, "/me/starred-courses/ds101",
                              headers=auth_headers(actor)).status_code == 403
    assert client.request(method, "/me/starred-courses/unknown",
                          headers=auth_headers("student1001")).status_code == 404
    for actor in ("teacher", "admin"):
        assert client.get("/me/starred-courses", headers=auth_headers(actor)).status_code == 403


def test_star_list_filters_courses_no_longer_enrolled(client, auth_headers, seeded):
    headers = auth_headers("student1001")
    client.put("/me/starred-courses/ds101", headers=headers)
    with sessions._db() as conn:
        conn.execute(
            "DELETE FROM chat_sessions WHERE moodle_user_id = 1001 AND course_id = 'ds101'"
        )
        conn.commit()
    assert client.get("/me/starred-courses", headers=headers).json() == {"courses": []}


def test_student_missing_moodle_identity_cannot_star(client, auth_headers):
    with auth._db() as conn:
        conn.execute("UPDATE users SET moodle_user_id = NULL WHERE username = 'student1001'")
        conn.commit()
    assert client.get("/me/starred-courses", headers=auth_headers("student1001")).status_code == 403


def test_progress_reaches_full_completion_and_keeps_courses_separate(
    client, auth_headers, seeded,
):
    headers = auth_headers("student1001")
    body = client.get("/course-structure/ds101", headers=headers).json()
    for section in body["sections"]:
        for activity in section["activities"]:
            path = f"/course-structure/ds101/activities/{activity['id']}/complete"
            assert client.put(path, headers=headers).status_code == 200
    assert client.get("/course-structure/ds101/progress", headers=headers).json() == {
        "course_id": "ds101", "student_id": 1001, "completed": 15,
        "total": 15, "percent": 100.0,
    }
    assert client.get("/course-structure/mk201/progress", headers=headers).json()["completed"] == 0
    other_path = "/course-structure/mk201/activities/demo-activity-mk201-1-reading/complete"
    assert client.put(other_path, headers=headers).status_code == 200
    assert client.get("/course-structure/ds101/progress", headers=headers).json()["completed"] == 15
    assert client.get("/course-structure/mk201/progress", headers=headers).json()["completed"] == 1

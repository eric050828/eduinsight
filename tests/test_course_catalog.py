"""Course catalog authorization, enrollment, and public participant fields."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight import auth, sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.grades import GradeManager
from eduinsight.live_quiz import QuizSessionManager

COURSE_IDS = {"general", "ds101", "py101", "db101", "mk201", "chm301", "eng201", "ipr101"}
COURSE_FIELDS = {"id", "name", "teacher_username", "teacher_name", "enrolled_count",
                 "description", "archived"}
PARTICIPANT_FIELDS = {"display_name", "role", "username", "last_active", "user_id", "moodle_user_id"}


@pytest.fixture
async def client(monkeypatch, auth_headers):
    monkeypatch.setattr(app_module.settings, "memory_embedder", "")
    memory = Memory(app_module.settings.memory_db_path)
    monkeypatch.setattr(app_module, "_memory", memory)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(memory))
    monkeypatch.setattr(app_module, "_llm", None)
    monkeypatch.setattr(app_module, "_rag", None)
    monkeypatch.setattr(app_module, "_quiz", None)
    monkeypatch.setattr(app_module, "_grades", GradeManager())
    monkeypatch.setattr(app_module, "_quiz_manager", QuizSessionManager())
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test",
    ) as client:
        reset = await client.post("/demo/reset", headers=auth_headers())
        assert reset.status_code == 200
        yield client


@pytest.mark.parametrize("path", [
    "/courses", "/courses/ds101/info", "/courses/ds101/participants",
])
async def test_authentication_required(client, path):
    assert (await client.get(path)).status_code == 401
    response = await client.get(path, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401


async def test_student_sees_only_enrolled_courses(client, auth_headers):
    # Demo reset enrolls all five students in every mapped teacher's course.
    with sessions._db() as conn:
        conn.execute(
            "DELETE FROM chat_sessions WHERE moodle_user_id = ? AND course_id != ?",
            (1001, "ds101"),
        )
        conn.commit()
    sessions.create_session(1001, "general")
    sessions.create_session(1002, "py101")
    sessions.create_session(1001, "outside-catalog")
    response = await client.get("/courses", headers=auth_headers("student1001"))
    assert response.status_code == 200
    entries = {course["id"]: course for course in response.json()}
    assert set(entries) == {"ds101", "general"}
    assert entries["ds101"]["enrolled_count"] == 5
    assert entries["general"]["enrolled_count"] == 1


async def test_student_without_enrollment_sees_empty_catalog(client, auth_headers):
    auth.create_user(auth.RegisterRequest(
        username="new_student", password="test123", display_name="新同學",
        role="student", moodle_user_id=2001,
    ))
    headers = auth_headers("new_student")
    assert (await client.get("/courses", headers=headers)).json() == []
    for suffix in ("info", "participants"):
        assert (await client.get(f"/courses/ds101/{suffix}", headers=headers)).status_code == 403


async def test_student_without_moodle_id_has_no_access(client, auth_headers):
    with auth._db() as conn:
        conn.execute("UPDATE users SET moodle_user_id = NULL WHERE username = 'student1001'")
        conn.commit()
    headers = auth_headers("student1001")
    assert (await client.get("/courses", headers=headers)).json() == []
    assert (await client.get("/courses/ds101/info", headers=headers)).status_code == 403


@pytest.mark.parametrize("username,course_id", list(auth.TEACHER_COURSE_MAP.items()))
async def test_teacher_is_scoped_to_mapping(client, auth_headers, username, course_id):
    headers = auth_headers(username)
    response = await client.get("/courses", headers=headers)
    assert response.status_code == 200
    assert [course["id"] for course in response.json()] == [course_id]
    assert (await client.get(f"/courses/{course_id}/info", headers=headers)).status_code == 200
    assert (await client.get(f"/courses/{course_id}/participants", headers=headers)).status_code == 200
    other = "mk201" if course_id == "ds101" else "ds101"
    for suffix in ("info", "participants"):
        assert (await client.get(f"/courses/{other}/{suffix}", headers=headers)).status_code == 403


async def test_unmapped_teacher_cannot_read_catalog_courses(client, auth_headers):
    auth.create_user(auth.RegisterRequest(
        username="unmapped_teacher", password="test123", display_name="未指派老師", role="teacher",
    ))
    headers = auth_headers("unmapped_teacher")
    assert (await client.get("/courses", headers=headers)).json() == []
    for course_id in ("general", "ds101", "py101", "db101"):
        for suffix in ("info", "participants"):
            response = await client.get(f"/courses/{course_id}/{suffix}", headers=headers)
            assert response.status_code == 403


async def test_admin_sees_complete_catalog_and_seeded_teacher_names(client, auth_headers):
    response = await client.get("/courses", headers=auth_headers())
    assert response.status_code == 200
    entries = {course["id"]: course for course in response.json()}
    assert set(entries) == COURSE_IDS
    for username, course_id in auth.TEACHER_COURSE_MAP.items():
        entry = entries[course_id]
        assert set(entry) == COURSE_FIELDS
        assert entry["teacher_username"] == username
        assert entry["teacher_name"] == auth.get_user_by_username(username)["display_name"]
        assert entry["enrolled_count"] == 5
    assert entries["ds101"]["name"] == "資料結構"
    assert entries["db101"]["name"] == "資料庫系統"


@pytest.mark.parametrize("course_id", ["general", "py101", "db101"])
async def test_unassigned_courses_have_null_teacher(client, auth_headers, course_id):
    sessions.create_session(1001, course_id)
    for username in ("admin", "student1001"):
        headers = auth_headers(username)
        response = await client.get(f"/courses/{course_id}/info", headers=headers)
        assert response.status_code == 200
        info = response.json()
        assert set(info) == COURSE_FIELDS
        assert info["teacher_username"] is None
        assert info["teacher_name"] is None
        assert info["enrolled_count"] == 1
        listed = (await client.get("/courses", headers=headers)).json()
        assert next(course for course in listed if course["id"] == course_id) == info
        response = await client.get(f"/courses/{course_id}/participants", headers=headers)
        assert response.status_code == 200
        assert [row["username"] for row in response.json()] == ["student1001"]
        assert response.json()[0]["role"] == "student"
    response = await client.get(f"/courses/{course_id}/info", headers=auth_headers("teacher"))
    assert response.status_code == 403


@pytest.mark.parametrize("username", ["student1001", "teacher", "admin"])
async def test_enrolled_users_can_read_participants_without_secrets(client, auth_headers, username):
    response = await client.get("/courses/ds101/participants", headers=auth_headers(username))
    assert response.status_code == 200
    participants = response.json()
    assert {row["username"] for row in participants} == {
        "teacher", "student1001", "student1002", "student1003", "student1004", "student1005",
    }
    assert len(participants) == 6
    for row in participants:
        assert set(row) == PARTICIPANT_FIELDS
        stored = auth.get_user_by_username(row["username"])
        assert row["display_name"] == stored["display_name"]
        assert row["role"] == stored["role"]
        assert stored["password_hash"] not in response.text
        assert "password" not in response.text
        assert "token" not in response.text
        assert "secret" not in response.text
        if row["role"] == "teacher":
            assert row["last_active"] is None
        else:
            assert isinstance(row["last_active"], (int, float))


async def test_non_enrolled_student_cannot_read_course_or_participants(client, auth_headers):
    for suffix in ("info", "participants"):
        response = await client.get(
            f"/courses/py101/{suffix}", headers=auth_headers("student1001"),
        )
        assert response.status_code == 403


@pytest.mark.parametrize("username", ["student1001", "teacher", "admin"])
@pytest.mark.parametrize("suffix", ["info", "participants"])
async def test_unknown_course_is_404(client, auth_headers, username, suffix):
    response = await client.get(f"/courses/missing/{suffix}", headers=auth_headers(username))
    assert response.status_code == 404


async def test_enrollment_counts_and_participants_are_deduplicated(client, auth_headers):
    with sessions._db() as conn:
        conn.execute(
            "INSERT INTO chat_sessions "
            "SELECT session_id || '-extra', moodle_user_id, course_id, title, created_at, last_msg_at "
            "FROM chat_sessions WHERE moodle_user_id = 1001 AND course_id = 'ds101'",
        )
        conn.commit()
    headers = auth_headers()
    info = (await client.get("/courses/ds101/info", headers=headers)).json()
    assert info["enrolled_count"] == 5
    participants = (await client.get("/courses/ds101/participants", headers=headers)).json()
    assert len(participants) == 6


@pytest.mark.parametrize("latest_source", ["session_created", "session_message", "fact", "message"])
async def test_last_active_uses_latest_session_or_memory_timestamp(
    client, auth_headers, latest_source,
):
    # Deterministic timestamps verify the maximum across all supported sources.
    with sessions._db() as conn:
        conn.execute(
            "UPDATE chat_sessions SET created_at = ?, last_msg_at = ? "
            "WHERE moodle_user_id = 1001 AND course_id = 'ds101'",
            (500 if latest_source == "session_created" else 100,
             500 if latest_source == "session_message" else 200),
        )
        conn.commit()
    conn = app_module._memory._store._get_conn()
    conn.execute(
        "UPDATE facts SET created_at = 100, updated_at = ? WHERE user_id = 'moodle:1001'",
        (500 if latest_source == "fact" else 300,),
    )
    conn.execute(
        "UPDATE messages SET created_at = ? WHERE user_id = 'moodle:1001'",
        (500 if latest_source == "message" else 400,),
    )
    conn.commit()
    response = await client.get("/courses/ds101/participants", headers=auth_headers())
    assert response.status_code == 200
    student = next(row for row in response.json() if row["username"] == "student1001")
    assert student["last_active"] == 500


async def test_existing_moodle_courses_route_is_preserved(client, auth_headers, monkeypatch):
    class MoodleClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get_user_courses(self, moodle_user_id):
            assert moodle_user_id == 1001
            return [SimpleNamespace(id=42, shortname="Moodle", fullname="Moodle 課程", summary="")]

    monkeypatch.setattr(app_module, "get_moodle_client", MoodleClient)
    response = await client.get("/courses/1001", headers=auth_headers("student1001"))
    assert response.status_code == 200
    assert response.json() == [{
        "id": 42, "shortname": "Moodle", "fullname": "Moodle 課程", "summary": "",
    }]

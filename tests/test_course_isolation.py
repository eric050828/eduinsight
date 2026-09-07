"""Course-level data isolation on teacher / class-wide endpoints (report ch.2 2.4.2)."""

from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import sessions as sessions_mod
from eduinsight.app import app
from eduinsight.assistant import LearningAssistant


async def _client(mem: Memory) -> AsyncClient:
    import eduinsight.app as app_module

    app_module._memory = mem
    app_module._assistant = LearningAssistant(mem)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _seed(mem: Memory) -> None:
    sessions_mod.init_sessions_table()
    a = LearningAssistant(mem)
    a.record_question(1001, "What is a BST?", topic="ds101")
    a.record_question(1002, "What is STP?", topic="mk201")
    sessions_mod.create_session(1001, "ds101", "bst")
    sessions_mod.create_session(1002, "mk201", "stp")


class TestTeacherScope:
    async def test_missing_token_is_401(self, auth_headers) -> None:
        async with await _client(Memory()) as c:
            assert (await c.get("/teacher/students")).status_code == 401

    async def test_teacher_sees_only_own_course(self, auth_headers) -> None:
        mem = Memory()
        _seed(mem)
        async with await _client(mem) as c:
            r = await c.get("/teacher/students", headers=auth_headers("teacher"))
            assert r.status_code == 200
            assert {s["moodle_user_id"] for s in r.json()["students"]} == {1001}

    async def test_teacher_cross_course_is_403(self, auth_headers) -> None:
        mem = Memory()
        _seed(mem)
        async with await _client(mem) as c:
            for path in ("/teacher/students", "/teacher/summaries", "/analytics/class"):
                r = await c.get(
                    path, params={"course_id": "ds101"}, headers=auth_headers("teacher_huang")
                )
                assert r.status_code == 403, path

    async def test_teacher_cross_course_student_memories_403(self, auth_headers) -> None:
        mem = Memory()
        _seed(mem)
        async with await _client(mem) as c:
            h = auth_headers("teacher_huang")
            assert (await c.get("/teacher/students/1001/memories", headers=h)).status_code == 403
            assert (await c.get("/teacher/students/1002/memories", headers=h)).status_code == 200

    async def test_student_only_own_course_and_self(self, auth_headers) -> None:
        mem = Memory()
        _seed(mem)
        async with await _client(mem) as c:
            h = auth_headers("student1001")
            assert (await c.get("/teacher/students", headers=h)).status_code == 403
            r = await c.get("/teacher/students", params={"course_id": "mk201"}, headers=h)
            assert r.status_code == 403
            r = await c.get("/teacher/students", params={"course_id": "ds101"}, headers=h)
            assert r.status_code == 200
            assert (await c.get("/teacher/students/1002/memories", headers=h)).status_code == 403
            assert (await c.get("/teacher/students/1001/memories", headers=h)).status_code == 200

    async def test_admin_unrestricted(self, auth_headers) -> None:
        mem = Memory()
        _seed(mem)
        async with await _client(mem) as c:
            r = await c.get("/teacher/students", headers=auth_headers("admin"))
            assert {s["moodle_user_id"] for s in r.json()["students"]} == {1001, 1002}

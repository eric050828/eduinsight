"""Tests for teacher dashboard API endpoints."""

from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.app import app
from eduinsight.assistant import LearningAssistant


async def _make_client(mem: Memory) -> AsyncClient:
    """Create a test client with a pre-configured in-memory assistant."""
    import eduinsight.app as app_module

    app_module._memory = mem
    app_module._assistant = LearningAssistant(mem)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestTeacherStudents:
    async def test_empty_dashboard(self, auth_headers) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/students", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_students"] == 0
            assert data["total_facts"] == 0
            assert data["students"] == []

    async def test_students_listed(self, auth_headers) -> None:
        mem = Memory()
        assistant = LearningAssistant(mem)
        assistant.record_question(1, "What is OOP?")
        assistant.record_question(2, "Explain recursion")
        assistant.record_struggle(2, "pointers", details="segfault when dereferencing")

        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/students", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_students"] == 2
            assert data["total_facts"] >= 3

            ids = {s["moodle_user_id"] for s in data["students"]}
            assert ids == {1, 2}

            # Student 2 has more facts
            student2 = next(s for s in data["students"] if s["moodle_user_id"] == 2)
            assert student2["fact_count"] >= 2

    async def test_non_moodle_users_excluded(self, auth_headers) -> None:
        """Users without 'moodle:' prefix should not appear."""
        mem = Memory()
        # Add a non-moodle user directly via Lite-Mem
        mem.add("slack:123", "some fact")
        # Add a moodle user via assistant
        assistant = LearningAssistant(mem)
        assistant.record_question(1, "What is OOP?")

        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/students", headers=auth_headers())
            data = resp.json()
            assert data["total_students"] == 1
            assert data["students"][0]["moodle_user_id"] == 1


class TestTeacherStudentMemories:
    async def test_get_memories(self, auth_headers) -> None:
        mem = Memory()
        assistant = LearningAssistant(mem)
        assistant.record_question(1, "What is a linked list?")
        assistant.record_struggle(1, "pointers")

        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/students/1/memories", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 1
            assert data["count"] >= 2
            assert len(data["memories"]) == data["count"]

    async def test_empty_memories(self, auth_headers) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher/students/999/memories", headers=auth_headers())
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 0
            assert data["memories"] == []

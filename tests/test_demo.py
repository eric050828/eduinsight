"""Tests for demo walkthrough endpoints."""

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


class TestDemoReset:
    async def test_demo_reset_seeds_data(self, tmp_path) -> None:
        """POST /demo/reset creates demo students in a fresh database."""
        import eduinsight.app as app_module

        db_path = str(tmp_path / "demo_test.db")
        app_module._memory = Memory(db_path)
        app_module._assistant = LearningAssistant(app_module._memory)

        # Override settings to use temp path
        original_path = app_module.settings.memory_db_path
        app_module.settings.memory_db_path = db_path
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/demo/reset")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "seeded"
                assert data["students_seeded"] == 4
                assert data["total_memories"] == 45

                # Verify teacher dashboard shows the seeded students
                resp2 = await client.get("/teacher/students")
                assert resp2.status_code == 200
                dashboard = resp2.json()
                assert dashboard["total_students"] == 4
        finally:
            app_module.settings.memory_db_path = original_path

    async def test_demo_page_served(self) -> None:
        """GET /demo serves the walkthrough page."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/demo")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

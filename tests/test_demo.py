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
                assert data["students_seeded"] == 5
                assert data["total_memories"] == 60

                # Verify teacher dashboard shows the seeded students
                resp2 = await client.get("/teacher/students")
                assert resp2.status_code == 200
                dashboard = resp2.json()
                assert dashboard["total_students"] == 5
        finally:
            app_module.settings.memory_db_path = original_path

    async def test_demo_reset_seeds_conversations(self, tmp_path) -> None:
        """POST /demo/reset also seeds conversation history."""
        import eduinsight.app as app_module

        db_path = str(tmp_path / "demo_conv.db")
        app_module._memory = Memory(db_path)
        app_module._assistant = LearningAssistant(app_module._memory)

        original_path = app_module.settings.memory_db_path
        app_module.settings.memory_db_path = db_path
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/demo/reset")
                # Check student 1001 has conversation history
                resp = await client.get("/student/1001/conversations")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_conversations"] >= 1
                assert len(data["conversations"][0]["messages"]) >= 2
        finally:
            app_module.settings.memory_db_path = original_path

    async def test_demo_reset_seeds_grades(self, tmp_path) -> None:
        """POST /demo/reset also seeds grade data for ds101."""
        import eduinsight.app as app_module

        db_path = str(tmp_path / "demo_grades.db")
        app_module._memory = Memory(db_path)
        app_module._assistant = LearningAssistant(app_module._memory)

        original_path = app_module.settings.memory_db_path
        app_module.settings.memory_db_path = db_path
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/demo/reset")
                # Check ds101 has categories
                resp = await client.get("/grades/ds101/categories")
                assert resp.status_code == 200
                cats = resp.json()
                assert len(cats) == 3
                # Check class overview has 5 students
                resp2 = await client.get("/grades/ds101/overview")
                assert resp2.status_code == 200
                overview = resp2.json()
                assert overview["total_students"] == 5
                assert overview["mean"] > 0
                # Check rankings
                assert len(overview["rankings"]) == 5
        finally:
            app_module.settings.memory_db_path = original_path

    async def test_demo_page_served(self) -> None:
        """GET /demo serves the walkthrough page."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/demo")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]


class TestPageRoutes:
    async def test_landing_page(self) -> None:
        """GET / serves the landing page."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    async def test_student_page(self) -> None:
        """GET /student serves the student dashboard."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/student")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    async def test_teacher_page(self) -> None:
        """GET /teacher serves the teacher dashboard."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    async def test_teacher_page_has_live_quiz_section(self) -> None:
        """Teacher dashboard includes live quiz management UI."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/teacher")
            text = resp.text
            assert "live-quiz-section" in text
            assert "即時測驗" in text
            assert "測驗 Sessions" in text
            assert "建立即時測驗" in text

    async def test_student_page_has_quiz_join(self) -> None:
        """Student dashboard includes quiz participation banner."""
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/student")
            text = resp.text
            assert "quizJoinBanner" in text
            assert "quizSessionInput" in text
            assert "課堂測驗" in text

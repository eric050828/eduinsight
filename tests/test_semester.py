"""Tests for semester demo feature."""

import pytest
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.app import app
from eduinsight.assistant import LearningAssistant
from eduinsight.semester_demo import SEMESTER_STUDENT_ID, SEMESTER_WEEKS


class TestSemesterData:
    """Tests for semester demo data integrity."""

    def test_has_18_weeks(self) -> None:
        assert len(SEMESTER_WEEKS) == 18

    def test_weeks_numbered_sequentially(self) -> None:
        for i, w in enumerate(SEMESTER_WEEKS, 1):
            assert w.week == i

    def test_every_week_has_facts(self) -> None:
        for w in SEMESTER_WEEKS:
            assert len(w.facts) >= 2, f"Week {w.week} has too few facts"

    def test_fact_categories_valid(self) -> None:
        valid = {"general", "struggling", "preference"}
        for w in SEMESTER_WEEKS:
            for text, cat in w.facts:
                assert cat in valid, f"Week {w.week}: invalid category '{cat}'"

    def test_unique_fact_prefixes_per_week(self) -> None:
        """Each fact within a week should have a unique prefix to avoid dedup."""
        for w in SEMESTER_WEEKS:
            prefixes = [t.split(":")[0] for t, _ in w.facts]
            assert len(prefixes) == len(set(prefixes)), (
                f"Week {w.week}: duplicate fact prefixes"
            )

    def test_total_facts_count(self) -> None:
        total = sum(len(w.facts) for w in SEMESTER_WEEKS)
        assert total >= 50  # at least 50 facts across the semester


class TestSemesterEndpoint:
    """Tests for POST /demo/semester."""

    @pytest.fixture
    async def client(self, tmp_path):
        import eduinsight.app as app_module

        db_path = str(tmp_path / "semester_test.db")
        app_module._memory = Memory(db_path)
        app_module._assistant = LearningAssistant(app_module._memory)

        original_path = app_module.settings.memory_db_path
        app_module.settings.memory_db_path = db_path
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
        finally:
            app_module.settings.memory_db_path = original_path

    async def test_semester_seeds_data(self, client) -> None:
        resp = await client.post("/demo/semester")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "seeded"
        assert data["student_id"] == SEMESTER_STUDENT_ID
        assert data["weeks_seeded"] == 18
        expected = sum(len(w.facts) for w in SEMESTER_WEEKS)
        assert data["total_memories"] == expected

    async def test_semester_timestamps_spread(self, client) -> None:
        """Verify facts have time-spread timestamps for trajectory."""
        import eduinsight.app as app_module

        await client.post("/demo/semester")

        mem = app_module._memory
        bundle = mem.export(SEMESTER_STUDENT_ID)
        timestamps = sorted(r.created_at for r in bundle.records)

        # First and last should be at least 17 weeks apart
        span_weeks = (timestamps[-1] - timestamps[0]) / (7 * 24 * 3600)
        assert span_weeks >= 16, f"Timestamp span is only {span_weeks:.1f} weeks"

    async def test_semester_trajectory_has_weeks(self, client) -> None:
        """After seeding, the trajectory API should return multiple weeks."""
        await client.post("/demo/semester")

        resp = await client.get("/analytics/student/2001/trajectory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_weeks"] >= 15  # some weeks may merge

    async def test_semester_analytics_has_struggles(self, client) -> None:
        """Student 2001 should have identifiable struggles after seeding."""
        await client.post("/demo/semester")

        resp = await client.get("/analytics/student/2001")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["struggles"]) >= 5
        assert len(data["weak_topics"]) >= 3

    async def test_semester_page_served(self, client) -> None:
        resp = await client.get("/semester")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

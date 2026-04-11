"""Tests for export/import memory endpoints."""

import json

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


class TestExportStudent:
    async def test_export_empty_student(self) -> None:
        """Exporting a student with no memories returns empty bundle."""
        mem = Memory(":memory:")
        async with await _make_client(mem) as client:
            resp = await client.get("/export/student/9999")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 9999
            assert data["record_count"] == 0
            assert data["bundle"]["user_id"] == "moodle:9999"
            assert data["bundle"]["records"] == []

    async def test_export_student_with_memories(self) -> None:
        """Exporting a student returns their memories as a MemoryBundle."""
        mem = Memory(":memory:")
        mem.add("moodle:101", "Struggling with recursion", category="struggling")
        mem.add("moodle:101", "Prefers visual explanations", category="preference")

        async with await _make_client(mem) as client:
            resp = await client.get("/export/student/101")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 101
            assert data["record_count"] == 2
            assert data["bundle"]["schema_version"] == "1.0"
            assert data["bundle"]["source_app"] == "LiteMem"
            texts = [r["text"] for r in data["bundle"]["records"]]
            assert "Struggling with recursion" in texts
            assert "Prefers visual explanations" in texts


class TestExportAll:
    async def test_export_all_empty(self) -> None:
        """Exporting all with no students returns empty list."""
        mem = Memory(":memory:")
        async with await _make_client(mem) as client:
            resp = await client.get("/export/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["students_exported"] == 0
            assert data["total_records"] == 0
            assert data["bundles"] == []

    async def test_export_all_multiple_students(self) -> None:
        """Exporting all returns bundles for each moodle student."""
        mem = Memory(":memory:")
        mem.add("moodle:201", "Fact A")
        mem.add("moodle:202", "Fact B")
        mem.add("moodle:202", "Fact C")

        async with await _make_client(mem) as client:
            resp = await client.get("/export/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["students_exported"] == 2
            assert data["total_records"] == 3
            assert len(data["bundles"]) == 2

    async def test_export_all_skips_non_moodle_users(self) -> None:
        """Non-moodle users are excluded from export."""
        mem = Memory(":memory:")
        mem.add("moodle:301", "Student fact")
        mem.add("internal:system", "System fact")

        async with await _make_client(mem) as client:
            resp = await client.get("/export/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["students_exported"] == 1
            user_ids = [b["user_id"] for b in data["bundles"]]
            assert "moodle:301" in user_ids
            assert "internal:system" not in user_ids


class TestImport:
    async def test_import_valid_bundle(self) -> None:
        """Importing a valid bundle adds memories to the database."""
        mem = Memory(":memory:")
        async with await _make_client(mem) as client:
            bundle = {
                "schema_version": "1.0",
                "user_id": "moodle:401",
                "exported_at": 1700000000.0,
                "source_app": "EduInsight",
                "metadata": {},
                "records": [
                    {
                        "text": "Likes Python",
                        "record_type": "preference",
                        "category": "preference",
                        "confidence": 1.0,
                        "created_at": 1700000000.0,
                        "updated_at": 1700000000.0,
                        "expires_at": None,
                        "source": "",
                        "tags": [],
                    },
                    {
                        "text": "Struggling with OOP",
                        "record_type": "permanent",
                        "category": "struggling",
                        "confidence": 1.0,
                        "created_at": 1700000000.0,
                        "updated_at": 1700000000.0,
                        "expires_at": None,
                        "source": "",
                        "tags": [],
                    },
                ],
            }
            content = json.dumps(bundle).encode()
            resp = await client.post(
                "/import",
                files={"file": ("bundle.json", content, "application/json")},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "imported"
            assert data["user_id"] == "moodle:401"
            assert data["records_imported"] == 2

            # Verify memories are in DB
            facts = mem.list("moodle:401")
            assert len(facts) == 2

    async def test_import_invalid_json(self) -> None:
        """Importing invalid JSON returns 400."""
        mem = Memory(":memory:")
        async with await _make_client(mem) as client:
            resp = await client.post(
                "/import",
                files={"file": ("bad.json", b"not json", "application/json")},
            )
            assert resp.status_code == 400

    async def test_import_missing_fields(self) -> None:
        """Importing JSON missing required fields returns 400."""
        mem = Memory(":memory:")
        async with await _make_client(mem) as client:
            content = json.dumps({"foo": "bar"}).encode()
            resp = await client.post(
                "/import",
                files={"file": ("incomplete.json", content, "application/json")},
            )
            assert resp.status_code == 400

    async def test_roundtrip_export_import(self) -> None:
        """Export then import produces identical memories."""
        mem = Memory(":memory:")
        mem.add("moodle:501", "Fact one", category="general")
        mem.add("moodle:501", "Fact two", category="struggling")

        async with await _make_client(mem) as client:
            # Export
            export_resp = await client.get("/export/student/501")
            assert export_resp.status_code == 200
            bundle_data = export_resp.json()["bundle"]

            # Clear and re-import
            mem.forget("moodle:501")
            assert len(mem.list("moodle:501")) == 0

            # Import
            content = json.dumps(bundle_data).encode()
            import_resp = await client.post(
                "/import",
                files={"file": ("roundtrip.json", content, "application/json")},
            )
            assert import_resp.status_code == 200
            assert import_resp.json()["records_imported"] == 2

            # Verify
            facts = mem.list("moodle:501")
            assert len(facts) == 2
            assert "Fact one" in facts
            assert "Fact two" in facts

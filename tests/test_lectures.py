"""Tests for lecture recording management module."""

from __future__ import annotations

import pytest
from litemem import Memory

from eduinsight.lectures import Lecture, LectureManager
from eduinsight.rag import CourseRAG
from eduinsight.transcribe import (
    StubTranscriber,
    TranscriptResult,
    TranscriptSegment,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def mem():
    return Memory(":memory:")


@pytest.fixture
def manager(mem):
    mgr = LectureManager(mem)
    mgr.set_transcriber(StubTranscriber(
        text="Today we discuss binary trees. A binary tree has at most two children per node.",
        language="en",
    ))
    return mgr


@pytest.fixture
def audio_file(tmp_path):
    """Create a fake audio file for testing."""
    f = tmp_path / "lecture_week3.mp3"
    f.write_bytes(b"\xff\xfb\x90" * 100)  # fake MP3 header bytes
    return f


# ------------------------------------------------------------------
# Lecture dataclass tests
# ------------------------------------------------------------------


class TestLecture:
    def test_to_dict(self):
        lec = Lecture(
            id="lec_abc123",
            course_id="CS101",
            title="Week 3: Trees",
            filename="lecture.mp3",
            transcript=TranscriptResult(
                text="Hello", language="en", duration=120.0, provider="stub",
            ),
            summary="About trees",
            chunks_indexed=5,
            created_at=1000000.0,
        )
        d = lec.to_dict()
        assert d["id"] == "lec_abc123"
        assert d["course_id"] == "CS101"
        assert d["duration"] == 120.0
        assert d["summary"] == "About trees"
        assert d["chunks_indexed"] == 5

    def test_transcript_with_timestamps(self):
        lec = Lecture(
            id="lec_1",
            course_id="CS101",
            title="Test",
            filename="test.mp3",
            transcript=TranscriptResult(
                text="First Second",
                language="en",
                duration=120.0,
                segments=[
                    TranscriptSegment(start=0.0, end=60.0, text="First"),
                    TranscriptSegment(start=60.0, end=120.0, text="Second"),
                ],
            ),
        )
        ts = lec.transcript_with_timestamps()
        assert "[00:00] First" in ts
        assert "[01:00] Second" in ts

    def test_transcript_without_segments_returns_text(self):
        lec = Lecture(
            id="lec_2",
            course_id="CS101",
            title="Test",
            filename="test.mp3",
            transcript=TranscriptResult(
                text="Plain transcript",
                language="en",
                duration=60.0,
                segments=[],
            ),
        )
        assert lec.transcript_with_timestamps() == "Plain transcript"


# ------------------------------------------------------------------
# LectureManager tests
# ------------------------------------------------------------------


class TestLectureManager:
    @pytest.mark.asyncio
    async def test_process_lecture(self, manager, audio_file):
        lec = await manager.process_lecture(
            "CS101", audio_file, "Week 3: Binary Trees",
            generate_summary=False,
        )
        assert lec.id.startswith("lec_")
        assert lec.course_id == "CS101"
        assert lec.title == "Week 3: Binary Trees"
        assert lec.transcript.provider == "stub"
        assert lec.chunks_indexed > 0

    @pytest.mark.asyncio
    async def test_list_lectures(self, manager, audio_file):
        await manager.process_lecture(
            "CS101", audio_file, "Lecture 1", generate_summary=False,
        )
        await manager.process_lecture(
            "CS101", audio_file, "Lecture 2", generate_summary=False,
        )
        await manager.process_lecture(
            "CS201", audio_file, "Other Course", generate_summary=False,
        )

        all_lectures = manager.list_lectures()
        assert len(all_lectures) == 3

        cs101 = manager.list_lectures("CS101")
        assert len(cs101) == 2

        cs201 = manager.list_lectures("CS201")
        assert len(cs201) == 1
        assert cs201[0].title == "Other Course"

    @pytest.mark.asyncio
    async def test_get_lecture(self, manager, audio_file):
        lec = await manager.process_lecture(
            "CS101", audio_file, "Test Lecture", generate_summary=False,
        )
        found = manager.get_lecture(lec.id)
        assert found is not None
        assert found.title == "Test Lecture"

    @pytest.mark.asyncio
    async def test_get_nonexistent_lecture(self, manager):
        assert manager.get_lecture("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete_lecture(self, manager, audio_file):
        lec = await manager.process_lecture(
            "CS101", audio_file, "To Delete", generate_summary=False,
        )
        assert manager.delete_lecture(lec.id) is True
        assert manager.get_lecture(lec.id) is None
        assert len(manager.list_lectures("CS101")) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, manager):
        assert manager.delete_lecture("nonexistent") is False

    @pytest.mark.asyncio
    async def test_transcript_indexed_in_rag(self, manager, mem, audio_file):
        await manager.process_lecture(
            "CS101", audio_file, "Week 3: Trees", generate_summary=False,
        )
        # The transcript should be searchable via RAG
        rag = CourseRAG(mem)
        results = rag.search("CS101", "binary trees")
        assert len(results) > 0
        # Should contain lecture content
        any_match = any("binary" in r.text.lower() for r in results)
        assert any_match

    @pytest.mark.asyncio
    async def test_lectures_sorted_by_time(self, manager, audio_file):
        await manager.process_lecture(
            "CS101", audio_file, "First", generate_summary=False,
        )
        await manager.process_lecture(
            "CS101", audio_file, "Second", generate_summary=False,
        )
        lectures = manager.list_lectures("CS101")
        # Most recent first
        assert lectures[0].title == "Second"
        assert lectures[1].title == "First"

    @pytest.mark.asyncio
    async def test_with_segments(self, manager, audio_file):
        """Test with a transcriber that returns segments."""
        class SegmentTranscriber:
            async def transcribe(self, path, *, language=None, prompt=None):
                return TranscriptResult(
                    text="Part one. Part two.",
                    language="en",
                    duration=120.0,
                    segments=[
                        TranscriptSegment(start=0.0, end=60.0, text="Part one."),
                        TranscriptSegment(start=60.0, end=120.0, text="Part two."),
                    ],
                    provider="test",
                )

        manager.set_transcriber(SegmentTranscriber())
        lec = await manager.process_lecture(
            "CS101", audio_file, "Segmented Lecture", generate_summary=False,
        )
        assert len(lec.transcript.segments) == 2
        assert lec.chunks_indexed > 0


# ------------------------------------------------------------------
# API endpoint tests
# ------------------------------------------------------------------


class TestLectureAPI:
    @pytest.fixture
    def client(self, mem):
        """Create a test client with lecture manager initialized."""
        from fastapi.testclient import TestClient

        import eduinsight.app as app_mod

        app_mod._memory = mem
        app_mod._lectures = LectureManager(mem)
        app_mod._lectures.set_transcriber(StubTranscriber(
            text="Test lecture about algorithms and data structures.",
            language="zh",
        ))
        app_mod._rag = CourseRAG(mem)

        client = TestClient(app_mod.app, raise_server_exceptions=False)
        yield client

        app_mod._memory = None
        app_mod._lectures = None
        app_mod._rag = None

    def test_upload_lecture(self, client, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 200)

        with open(audio, "rb") as f:
            resp = client.post(
                "/lectures/CS101/upload",
                data={"title": "Week 1 Intro", "language": "zh"},
                files={"file": ("test.mp3", f, "audio/mpeg")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == "CS101"
        assert data["title"] == "Week 1 Intro"
        assert data["chunks_indexed"] > 0

    def test_upload_unsupported_format(self, client, tmp_path):
        bad = tmp_path / "test.txt"
        bad.write_text("not audio")

        with open(bad, "rb") as f:
            resp = client.post(
                "/lectures/CS101/upload",
                files={"file": ("test.txt", f, "text/plain")},
            )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_list_lectures(self, client, tmp_path):
        # Upload two lectures
        for title in ["Lecture 1", "Lecture 2"]:
            audio = tmp_path / f"{title}.mp3"
            audio.write_bytes(b"\xff" * 200)
            with open(audio, "rb") as f:
                client.post(
                    "/lectures/CS101/upload",
                    data={"title": title},
                    files={"file": (f"{title}.mp3", f, "audio/mpeg")},
                )

        resp = client.get("/lectures/CS101")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_list_empty_course(self, client):
        resp = client.get("/lectures/EMPTY")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_transcript(self, client, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 200)

        with open(audio, "rb") as f:
            upload_resp = client.post(
                "/lectures/CS101/upload",
                data={"title": "Test Lecture"},
                files={"file": ("test.mp3", f, "audio/mpeg")},
            )
        lecture_id = upload_resp.json()["id"]

        resp = client.get(f"/lectures/CS101/{lecture_id}/transcript")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == lecture_id
        assert "algorithms" in data["text"].lower()
        assert len(data["segments"]) > 0

    def test_get_transcript_not_found(self, client):
        resp = client.get("/lectures/CS101/nonexistent/transcript")
        assert resp.status_code == 404

    def test_delete_lecture(self, client, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff" * 200)

        with open(audio, "rb") as f:
            upload_resp = client.post(
                "/lectures/CS101/upload",
                data={"title": "To Delete"},
                files={"file": ("test.mp3", f, "audio/mpeg")},
            )
        lecture_id = upload_resp.json()["id"]

        resp = client.delete(f"/lectures/CS101/{lecture_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        # Verify it's gone
        resp = client.get(f"/lectures/CS101/{lecture_id}/transcript")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/lectures/CS101/nonexistent")
        assert resp.status_code == 404

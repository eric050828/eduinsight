"""Material metadata, background indexing and persisted chat citations."""

from eduinsight.courses import enroll

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight import app as app_module, auth, sessions
from eduinsight.assistant import LearningAssistant
from eduinsight.config import settings
from eduinsight.documents import DocumentChunk, ParsedDocument
from eduinsight.material_metadata import MaterialMetadata
from eduinsight.rag import CourseRAG


@pytest.fixture
async def client(monkeypatch, tmp_path, auth_headers):
    monkeypatch.chdir(tmp_path)
    mem = Memory(settings.memory_db_path)
    monkeypatch.setattr(app_module, "_memory", mem)
    monkeypatch.setattr(app_module, "_assistant", LearningAssistant(mem))
    monkeypatch.setattr(app_module, "_rag", CourseRAG(mem))
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test",
        headers=auth_headers(),
    ) as c:
        yield c


async def upload(client, filename="notes.md", body=b"## Search\n\nBinary search halves the array.",
                 course="CS101", wait=False):
    return await client.post(
        f"/courses/{course}/materials" + ("?wait=true" if wait else ""),
        files={"file": (filename, body, "text/markdown")},
    )


async def test_metadata_persists_and_keeps_filename_list(client):
    body = b"## Search\n\nBinary search halves the array."
    response = await upload(client, body=body)
    assert response.status_code == 200
    assert response.json() == {
        "status": "indexing", "filename": "notes.md", "course_id": "CS101",
        "chunks_indexed": 0, "total_pages": 0,
    }
    data = (await client.get("/courses/CS101/materials")).json()
    assert data["documents"] == ["notes.md"]
    item = data["items"][0]
    assert item["size_bytes"] == len(body)
    assert item["content_type"] == "text/markdown"
    assert item["kind"] == "md"
    assert item["uploaded_at"] is not None
    assert item["uploaded_by"] == auth.get_user_by_username("admin")["id"]
    assert item["chunk_count"] == 1
    assert item["status"] == "done"
    assert item == MaterialMetadata().get("CS101", "notes.md")
    assert (await client.get("/courses/CS101/materials/notes.md/status")).json() == {
        "status": "done", "chunk_count": 1, "error": None,
    }
    assert (await client.get("/courses/CS202/materials")).json()["items"] == []
    assert (await client.get("/courses/CS202/materials/notes.md/status")).status_code == 404


async def test_response_is_sent_before_parser_finishes(client, monkeypatch):
    release = threading.Event()
    body_sent = asyncio.Event()
    sent_body = []
    original = app_module.to_markdown

    def blocked_parser(path):
        assert release.wait(timeout=10), "Test did not release background parser"
        return original(path)

    async def observe_response(scope, receive, send):
        async def observe(message):
            if message["type"] == "http.response.body" and not message.get("more_body"):
                sent_body.append(message["body"])
                body_sent.set()
            await send(message)
        await app_module.app(scope, receive, observe)

    monkeypatch.setattr(app_module, "to_markdown", blocked_parser)
    async with AsyncClient(
        transport=ASGITransport(app=observe_response), base_url="http://test",
        headers=client.headers,
    ) as observed:
        task = asyncio.create_task(upload(observed))
        try:
            await asyncio.wait_for(body_sent.wait(), timeout=3)
            assert json.loads(sent_body[0])["status"] == "indexing"
            assert not task.done()  # ASGITransport awaits the background callback.
            status = await client.get("/courses/CS101/materials/notes.md/status")
            assert status.json() == {"status": "indexing", "chunk_count": 0, "error": None}
            duplicate = await upload(client)
            assert duplicate.status_code == 409
            assert (await client.delete("/courses/CS101/materials/notes.md")).status_code == 409
        finally:
            release.set()
            await task
    assert (await client.get("/courses/CS101/materials/notes.md/status")).json()["status"] == "done"


async def test_backfill_legacy_rag_documents(client):
    rag = app_module._rag
    rag.index_document("CS101", ParsedDocument("legacy.pdf", 2, [
        DocumentChunk("Binary search", "legacy.pdf", page=1),
        DocumentChunk("Linked lists", "legacy.pdf", page=2, chunk_index=1),
    ]))
    # Status also backfills, without requiring a preceding list call.
    assert (await client.get("/courses/CS101/materials/legacy.pdf/status")).json() == {
        "status": "done", "chunk_count": 2, "error": None,
    }
    item = (await client.get("/courses/CS101/materials")).json()["items"][0]
    assert item["filename"] == "legacy.pdf"
    assert item["chunk_count"] == 2
    assert item["uploaded_at"] is None
    assert item["uploaded_by"] is None
    assert item["size_bytes"] is None
    assert item["content_type"] == "application/pdf"
    assert item["kind"] == "pdf"


async def test_status_remains_responsive_while_list_waits_for_index_lock(client, monkeypatch):
    release = threading.Event()
    indexing = threading.Event()
    listing = threading.Event()
    original_index = app_module._rag.index_markdown
    original_items = app_module._material_items

    def blocked_index(course_id, parsed):
        indexing.set()
        assert release.wait(timeout=10)
        return original_index(course_id, parsed)

    def waiting_list(*args):
        listing.set()
        return original_items(*args)

    monkeypatch.setattr(app_module._rag, "index_markdown", blocked_index)
    monkeypatch.setattr(app_module, "_material_items", waiting_list)
    upload_task = asyncio.create_task(upload(client))
    list_task = None
    try:
        assert await asyncio.to_thread(indexing.wait, 3)
        list_task = asyncio.create_task(client.get("/courses/CS101/materials"))
        assert await asyncio.to_thread(listing.wait, 3)
        response = await asyncio.wait_for(
            client.get("/courses/CS101/materials/notes.md/status"), timeout=3,
        )
        assert response.json()["status"] == "indexing"
        assert not list_task.done()
    finally:
        release.set()
        await upload_task
        if list_task is not None:
            await list_task


async def test_failed_background_job_records_error_and_cleans_temp_file(client, monkeypatch):
    paths = []

    def fail_parse(path):
        paths.append(path)
        raise ValueError("Cannot parse document")

    monkeypatch.setattr(app_module, "to_markdown", fail_parse)
    assert (await upload(client)).json()["status"] == "indexing"
    assert (await client.get("/courses/CS101/materials/notes.md/status")).json() == {
        "status": "failed", "chunk_count": 0, "error": "Cannot parse document",
    }
    assert all(not Path(path).exists() for path in paths)
    assert (await client.get("/courses/CS101/materials")).json()["items"][0]["status"] == "failed"
    assert (await client.delete("/courses/CS101/materials/notes.md")).json()["status"] == "removed"
    assert (await client.get("/courses/CS101/materials/notes.md/status")).status_code == 404


async def test_partial_index_failure_does_not_leave_chunks(client, monkeypatch):
    await upload(client, "other.md")
    rag = app_module._rag
    original = rag.index_markdown

    def fail_index(course_id, parsed):
        original(course_id, parsed)
        raise RuntimeError("Embedding unavailable")

    monkeypatch.setattr(rag, "index_markdown", fail_index)
    assert (await upload(client)).json()["status"] == "indexing"
    assert rag.list_documents("CS101") == ["other.md"]
    assert not Path("_materials_md/CS101/notes.md.md").exists()
    assert (await client.get("/courses/CS101/materials/notes.md/status")).json() == {
        "status": "failed", "chunk_count": 0, "error": "Embedding unavailable",
    }


async def test_wait_path_and_replacement_delete_metadata_and_markdown(client):
    first = await upload(client, wait=True)
    assert first.json()["status"] == "indexed"
    assert first.json()["chunks_indexed"] == 1
    second = await upload(client, body=b"## Sorting\n\nQuicksort sorts an array.", wait=True)
    assert second.json()["chunks_indexed"] == 1
    assert app_module._rag.document_counts("CS101") == {"notes.md": 1}
    assert "Search" not in (
        await client.get("/courses/CS101/materials/notes.md/markdown")
    ).json()["markdown"]
    assert (await client.delete("/courses/CS101/materials/notes.md")).json()["chunks_removed"] == 1
    assert (await client.get("/courses/CS101/materials")).json() == {
        "course_id": "CS101", "documents": [], "items": [],
    }
    assert (await client.get("/courses/CS101/materials/notes.md/markdown")).status_code == 404


async def test_sync_failure_remains_http_error(client, monkeypatch):
    def fail(path):
        raise ValueError("Invalid document")
    monkeypatch.setattr(app_module, "to_markdown", fail)
    response = await upload(client, wait=True)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid document"
    assert (
        await client.get("/courses/CS101/materials/notes.md/status")
    ).json()["status"] == "failed"


async def test_youtube_metadata(client):
    response = await client.post("/courses/CS101/materials/youtube", json={
        "url": "https://youtu.be/abcdefghijk", "title": "Search lesson",
    })
    assert response.status_code == 200
    item = (await client.get("/courses/CS101/materials")).json()["items"][0]
    assert item["kind"] == "youtube"
    assert item["status"] == "done"
    assert item["size_bytes"] > 0
    assert item["uploaded_at"] is not None


@pytest.mark.parametrize("with_llm", [False, True])
async def test_chat_persists_exact_citations_and_mentions(client, monkeypatch, with_llm):
    await upload(client, "selected.md", b"## Selected\n\nBinary search uses sorted arrays.")
    await upload(client, "other.md", b"## Other\n\nBinary search is efficient.")
    assistant = app_module._assistant
    if with_llm:
        monkeypatch.setattr(assistant, "_llm", object())
        monkeypatch.setattr(assistant, "answer", AsyncMock(return_value=SimpleNamespace(
            answer="Use binary search [1]", memory_context=[],
        )))
    response = await client.post("/chat", json={
        "moodle_user_id": 1001, "message": "binary search", "course_id": "CS101",
        "material_filenames": ["selected.md"], "mention_user_ids": [1002, 1003],
    })
    assert response.status_code == 200
    reply = response.json()
    citations = reply["material_context"]
    assert citations
    assert {c["filename"] for c in citations} == {"selected.md"}
    assert set(citations[0]) == {"id", "filename", "heading", "anchor_id", "text"}
    if with_llm:
        prompt_context = assistant.answer.call_args.kwargs["material_context"]
        assert "selected.md" in prompt_context
        assert "other.md" not in prompt_context
    # New Memory/RAG instance and removed materials must not alter old citations.
    app_module._rag.remove_document("CS101", "selected.md")
    monkeypatch.setattr(app_module, "_memory", Memory(settings.memory_db_path))
    history = (await client.get(f"/sessions/{reply['session_id']}/messages")).json()["messages"]
    assert len(history) == 2
    assert history[0]["mention_user_ids"] == [1002, 1003]
    assert history[1]["material_context"] == citations
    assert history[1]["content"] == reply["reply"]
    assert {"role", "content", "created_at"}.issubset(history[1])


async def test_legacy_messages_have_null_citations(client):
    enroll("CS101", 1001, source="test")
    sess = sessions.create_session(1001, "CS101", "Legacy")
    app_module._memory._store.store_message(
        "moodle:1001", "Old answer", session_id=sess["session_id"], role="assistant",
    )
    message = (await client.get(f"/sessions/{sess['session_id']}/messages")).json()["messages"][0]
    assert message["material_context"] is None
    assert message["mention_user_ids"] is None


async def test_selected_material_belongs_to_effective_session_course(client):
    await upload(client)
    await upload(client, "foreign.md", course="CS202")
    enroll("CS101", 1001, source="test")
    sess = sessions.create_session(1001, "CS101", "Chat")
    base = {"moodle_user_id": 1001, "message": "binary search", "session_id": sess["session_id"]}
    good = await client.post("/chat", json={**base, "material_filenames": ["notes.md"]})
    assert good.status_code == 200
    assert good.json()["material_context"]
    bad = await client.post("/chat", json={**base, "material_filenames": ["foreign.md"]})
    assert bad.status_code == 400
    no_course = await client.post("/chat", json={
        "moodle_user_id": 1001, "message": "hello", "material_filenames": ["notes.md"],
    })
    assert no_course.status_code == 400


async def test_empty_material_selection_disables_retrieval(client):
    await upload(client)
    response = await client.post("/chat", json={
        "moodle_user_id": 1001, "message": "binary search", "course_id": "CS101",
        "material_filenames": [],
    })
    assert response.json()["material_context"] == []
    history = (await client.get(f"/sessions/{response.json()['session_id']}/messages")).json()
    assert history["messages"][1]["material_context"] == []


async def test_filtered_search_finds_selected_file_beyond_top_five(client):
    rag = app_module._rag
    for i in range(8):
        filename = f"file{i}.pdf"
        rag.index_document("CS101", ParsedDocument(filename, 1, [
            DocumentChunk("Binary search uses sorted arrays.", filename, page=1),
        ]))
    all_results = rag.search("CS101", "binary search", top_k=8)
    selected = all_results[-1].source
    assert selected not in {r.source for r in all_results[:5]}
    filtered = rag.search("CS101", "binary search", material_filenames=[selected])
    assert [r.source for r in filtered] == [selected]


async def test_status_authentication_and_teacher_scope_unchanged(client, auth_headers):
    enroll("CS101", 1001, source="test")
    await upload(client)
    assert (await client.get("/courses/CS101/materials/notes.md/status", headers={
        "Authorization": "Bearer invalid",
    })).status_code == 401
    assert (await client.get(
        "/courses/CS101/materials/notes.md/status", headers=auth_headers("teacher"),
    )).status_code == 403
    assert (await client.get(
        "/courses/CS101/materials/notes.md/status", headers=auth_headers("student1001"),
    )).status_code == 200
    denied = await client.post("/courses/CS101/materials", headers=auth_headers("student1001"),
                               files={"file": ("student.md", b"## Notes", "text/markdown")})
    assert denied.status_code == 403
    assert MaterialMetadata().get("CS101", "student.md") is None


async def test_message_history_ownership_with_saved_citations(client, auth_headers):
    response = await client.post("/chat", json={"moodle_user_id": 1001, "message": "hello"})
    sid = response.json()["session_id"]
    assert (await client.get(
        f"/sessions/{sid}/messages", headers=auth_headers("student1002"),
    )).status_code == 403
    assert (await client.get(
        f"/sessions/{sid}/messages", headers=auth_headers("student1001"),
    )).status_code == 200
    assert (await client.delete(f"/sessions/{sid}")).status_code == 200
    assert sessions.get_message_metadata(sid) == {}


async def test_invalid_filename_does_not_create_metadata(client):
    response = await upload(client, "../escape.md")
    assert response.status_code == 400
    assert MaterialMetadata().list("CS101") == []

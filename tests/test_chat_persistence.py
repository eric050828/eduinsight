"""The student's question is saved before the AI answers, so a reload mid-answer keeps it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from litemem import Memory

from eduinsight import app as app_module
from eduinsight.rag import CourseRAG


@pytest.fixture
def client(auth_headers):
    mem = Memory(":memory:")
    with TestClient(app_module.app, raise_server_exceptions=False, headers=auth_headers()) as c:
        orig_llm = app_module._llm
        app_module._memory = mem
        app_module._assistant = app_module.LearningAssistant(mem)
        app_module._rag = CourseRAG(mem)
        app_module._quiz = None
        yield c
        app_module._llm = orig_llm


def _session_roles(session_id: str) -> list[str]:
    return [m["role"] for m in app_module._memory._store.get_messages("moodle:1001")
            if m.get("session_id") == session_id]


def test_question_is_stored_before_the_answer(client, monkeypatch):
    seen: dict[str, list[str]] = {}
    assistant = app_module._assistant
    monkeypatch.setattr(assistant, "_llm", object())

    async def answer(student_id, message, topic=None, material_context=""):
        # A reload at this moment reads the session: the question must already be there.
        session_id = next(m["session_id"] for m in app_module._memory._store.get_messages(
            "moodle:1001") if m["content"] == message)
        seen["roles"] = _session_roles(session_id)
        return SimpleNamespace(answer="合併排序在合併時保留相等元素的順序。", memory_context=[])

    monkeypatch.setattr(assistant, "answer", answer)
    response = client.post("/chat", json={"moodle_user_id": 1001, "message": "合併排序為什麼穩定？"})
    assert response.status_code == 200, response.text
    assert seen["roles"] == ["user"]
    assert _session_roles(response.json()["session_id"]) == ["user", "assistant"]


def test_failed_answer_keeps_the_question(client, monkeypatch):
    assistant = app_module._assistant
    monkeypatch.setattr(assistant, "_llm", object())

    async def answer(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(assistant, "answer", answer)
    response = client.post("/chat", json={"moodle_user_id": 1001, "message": "快速排序何時退化？"})
    assert response.status_code == 500
    messages = app_module._memory._store.get_messages("moodle:1001")
    assert [(m["role"], m["content"]) for m in messages] == [("user", "快速排序何時退化？")]

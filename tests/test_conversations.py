"""Tests for student conversations API endpoint."""

from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.app import app
from eduinsight.assistant import LearningAssistant


async def _make_client(mem: Memory) -> AsyncClient:
    import eduinsight.app as app_module

    app_module._memory = mem
    app_module._assistant = LearningAssistant(mem)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _store_msg(mem: Memory, uid: str, content: str, session_id: str = "", role: str = "user") -> None:
    """Insert a message via Lite-Mem's internal store."""
    mem._store.store_message(uid, content, session_id=session_id, role=role)


class TestStudentConversations:
    async def test_empty_conversations(self) -> None:
        mem = Memory()
        async with await _make_client(mem) as client:
            resp = await client.get("/student/1/conversations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["moodle_user_id"] == 1
            assert data["total_conversations"] == 0
            assert data["conversations"] == []

    async def test_conversations_returned(self) -> None:
        mem = Memory()
        _store_msg(mem, "moodle:1", "What is OOP?", session_id="s1", role="user")
        _store_msg(mem, "moodle:1", "OOP stands for Object-Oriented Programming.", session_id="s1", role="assistant")

        async with await _make_client(mem) as client:
            resp = await client.get("/student/1/conversations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_conversations"] == 1
            conv = data["conversations"][0]
            assert conv["session_id"] == "s1"
            assert len(conv["messages"]) == 2
            assert conv["messages"][0]["role"] == "user"
            assert conv["messages"][1]["role"] == "assistant"

    async def test_multiple_sessions(self) -> None:
        mem = Memory()
        _store_msg(mem, "moodle:2", "Q1", session_id="s1", role="user")
        _store_msg(mem, "moodle:2", "A1", session_id="s1", role="assistant")
        _store_msg(mem, "moodle:2", "Q2", session_id="s2", role="user")
        _store_msg(mem, "moodle:2", "A2", session_id="s2", role="assistant")

        async with await _make_client(mem) as client:
            resp = await client.get("/student/2/conversations")
            data = resp.json()
            assert data["total_conversations"] == 2
            sids = {c["session_id"] for c in data["conversations"]}
            assert sids == {"s1", "s2"}

    async def test_limit_param(self) -> None:
        mem = Memory()
        for i in range(5):
            _store_msg(mem, "moodle:3", f"msg{i}", session_id="s1", role="user")

        async with await _make_client(mem) as client:
            resp = await client.get("/student/3/conversations?limit=3")
            data = resp.json()
            total_msgs = sum(len(c["messages"]) for c in data["conversations"])
            assert total_msgs <= 3

    async def test_different_users_isolated(self) -> None:
        mem = Memory()
        _store_msg(mem, "moodle:10", "Hello", session_id="s1", role="user")
        _store_msg(mem, "moodle:20", "Hi", session_id="s2", role="user")

        async with await _make_client(mem) as client:
            resp = await client.get("/student/10/conversations")
            data = resp.json()
            assert data["total_conversations"] == 1
            assert data["conversations"][0]["messages"][0]["content"] == "Hello"

    async def test_chat_stores_messages_in_history(self) -> None:
        """POST /chat should store user+assistant messages so they appear in conversations API."""
        mem = Memory()
        async with await _make_client(mem) as client:
            # Send a chat message (no LLM configured → fallback reply)
            resp = await client.post("/chat", json={
                "moodle_user_id": 99,
                "message": "What is recursion?",
                "topic": "CS101",
            })
            assert resp.status_code == 200

            # Now check conversations endpoint
            resp2 = await client.get("/student/99/conversations")
            data = resp2.json()
            assert data["total_conversations"] == 1
            msgs = data["conversations"][0]["messages"]
            assert len(msgs) == 2
            assert msgs[0]["role"] == "user"
            assert "recursion" in msgs[0]["content"]
            assert msgs[1]["role"] == "assistant"

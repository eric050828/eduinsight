"""Real JWT authentication, course scoping and private direct-message behavior."""

from types import SimpleNamespace

import pytest
from eduinsight import auth, messaging, sessions
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def setup(auth_headers, monkeypatch):
    # conftest isolates SQLite and auth_headers creates users and genuine JWTs.
    for moodle_id in (1001, 1002, 1003):
        sessions.create_session(moodle_id, "ds101")
    sessions.create_session(1004, "mk201")
    users = {
        name: auth.get_user_by_username(name)["id"]
        for name in (*auth.TEACHER_COURSE_MAP, "admin", *(
            f"student{uid}" for uid in range(1001, 1006)
        ))
    }
    clock = SimpleNamespace(now=1_800_000_000.0)
    monkeypatch.setattr(messaging, "time", SimpleNamespace(time=lambda: clock.now))
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(messaging.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, headers=auth_headers, ids=users, clock=clock)


def _send(setup, sender, recipient, text="hello"):
    response = setup.client.post(
        f"/messages/conversations/{setup.ids[recipient]}",
        json={"text": text}, headers=setup.headers(sender),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _unread(setup, username):
    response = setup.client.get("/messages/unread-count", headers=setup.headers(username))
    assert response.status_code == 200
    return response.json()["unread_count"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/messages/conversations"),
    ("GET", "/messages/conversations/2"),
    ("POST", "/messages/conversations/2"),
    ("POST", "/messages/conversations/2/read"),
    ("DELETE", "/messages/1"),
    ("GET", "/messages/contacts"),
    ("GET", "/messages/unread-count"),
    ("POST", "/presence/heartbeat"),
    ("GET", "/presence?user_ids=1,2"),
    ("GET", "/presence/course/ds101"),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_all_routes_require_authentication(setup, method, path, headers):
    response = setup.client.request(method, path, headers=headers)
    assert response.status_code == 401, response.text


def test_contacts_scope_and_safe_fields(setup):
    expected = {
        "student1001": {"teacher", "student1002", "student1003"},
        "student1004": {"teacher_huang"},
        "student1005": set(),
        "teacher": {"student1001", "student1002", "student1003"},
        "teacher_huang": {"student1004"},
        "admin": {*auth.TEACHER_COURSE_MAP, "student1001", "student1002",
                  "student1003", "student1004"},
    }
    for username, names in expected.items():
        response = setup.client.get("/messages/contacts", headers=setup.headers(username))
        assert response.status_code == 200
        contacts = response.json()
        assert {contact["username"] for contact in contacts} == names
        assert all(set(contact) == {
            "user_id", "display_name", "role", "username", "moodle_user_id",
        } for contact in contacts)
        assert all(contact["user_id"] == setup.ids[contact["username"]] for contact in contacts)
    # Multiple enrollment sessions must not duplicate classmates; a second
    # course adds that course's teacher and students, not unrelated accounts.
    sessions.create_session(1001, "ds101", "another session")
    sessions.create_session(1001, "mk201")
    contacts = setup.client.get(
        "/messages/contacts", headers=setup.headers("student1001"),
    ).json()
    assert {contact["username"] for contact in contacts} == {
        "teacher", "teacher_huang", "student1002", "student1003", "student1004",
    }
    assert len(contacts) == 5


def test_unmapped_teacher_has_no_contacts(setup):
    auth.create_user(auth.RegisterRequest(
        username="unmapped", password="pass123", display_name="Unmapped", role="teacher",
    ))
    response = setup.client.get("/messages/contacts", headers=setup.headers("unmapped"))
    assert response.json() == []
    assert setup.client.get(
        "/presence/course/ds101", headers=setup.headers("unmapped"),
    ).status_code == 403


def test_send_creates_recipient_notification_and_unread(setup):
    message = _send(setup, "student1001", "teacher", "Could you explain the homework?")
    assert message == {
        "id": message["id"], "sender_id": setup.ids["student1001"],
        "recipient_id": setup.ids["teacher"], "text": "Could you explain the homework?",
        "created_at": setup.clock.now, "read_at": None, "deleted_at": None,
        "is_deleted": False,
    }
    assert _unread(setup, "teacher") == 1
    assert _unread(setup, "student1001") == 0
    assert _unread(setup, "student1002") == 0
    with auth._db() as conn:
        rows = conn.execute("SELECT * FROM notifications").fetchall()
    assert len(rows) == 1
    assert rows[0]["user_id"] == setup.ids["teacher"]
    assert rows[0]["kind"] == "direct_message"
    assert rows[0]["body"] == message["text"]
    assert rows[0]["link"] == f"/messages/conversations/{setup.ids['student1001']}"


def test_conversation_list_latest_sort_and_unread(setup):
    first = _send(setup, "student1002", "student1001", "first")
    setup.clock.now += 1
    _send(setup, "teacher", "student1001", "teacher's message")
    setup.clock.now += 1
    latest = _send(setup, "student1001", "student1002", "x" * 250)
    response = setup.client.get(
        "/messages/conversations", headers=setup.headers("student1001"),
    )
    assert response.status_code == 200
    conversations = response.json()
    assert [item["peer"]["user_id"] for item in conversations] == [
        setup.ids["student1002"], setup.ids["teacher"],
    ]
    assert conversations[0]["last_message_preview"] == "x" * 200
    assert conversations[0]["last_at"] == latest["created_at"] > first["created_at"]
    assert [item["unread_count"] for item in conversations] == [1, 1]
    assert _unread(setup, "student1001") == 2


def test_a_cannot_read_or_mark_bc_conversation(setup):
    secret = _send(setup, "student1002", "student1003", "B/C private")
    a_headers = setup.headers("student1001")
    for peer in ("student1002", "student1003"):
        path = f"/messages/conversations/{setup.ids[peer]}"
        response = setup.client.get(path, headers=a_headers)
        assert response.status_code == 200
        assert response.json()["messages"] == []
        assert response.json()["total"] == 0
        assert setup.client.post(path + "/read", headers=a_headers).json()["updated_count"] == 0
    assert setup.client.get("/messages/conversations", headers=a_headers).json() == []
    # Even the admin's history and conversation list are personal.
    assert setup.client.get(
        "/messages/conversations", headers=setup.headers("admin"),
    ).json() == []
    assert setup.client.get(
        f"/messages/conversations/{setup.ids['student1003']}",
        headers=setup.headers("admin"),
    ).json()["messages"] == []
    assert _unread(setup, "student1003") == 1
    assert setup.client.delete(f"/messages/{secret['id']}", headers=a_headers).status_code == 404
    history = setup.client.get(
        f"/messages/conversations/{setup.ids['student1002']}",
        headers=setup.headers("student1003"),
    ).json()
    assert [item["text"] for item in history["messages"]] == ["B/C private"]
    assert history["messages"][0]["read_at"] == setup.clock.now


def test_history_pagination_marks_incoming_and_preserves_outgoing_unread(setup):
    incoming = [_send(setup, "student1002", "student1001", str(i)) for i in range(4)]
    outgoing = _send(setup, "student1001", "student1002", "reply")
    path = f"/messages/conversations/{setup.ids['student1002']}"
    response = setup.client.get(path + "?limit=2", headers=setup.headers("student1001"))
    page = response.json()
    assert [item["id"] for item in page["messages"]] == [incoming[-1]["id"], outgoing["id"]]
    assert page["total"] == 5
    assert (page["limit"], page["offset"], page["has_more"]) == (2, 0, True)
    assert _unread(setup, "student1001") == 0
    assert _unread(setup, "student1002") == 1
    page = setup.client.get(path + "?limit=2&offset=4", headers=setup.headers("student1001"))
    assert [item["id"] for item in page.json()["messages"]] == [incoming[0]["id"]]
    assert page.json()["has_more"] is False
    assert setup.client.get(
        path + "?offset=99", headers=setup.headers("student1001"),
    ).json()["messages"] == []


def test_explicit_read_is_idempotent_and_only_incoming(setup):
    _send(setup, "student1002", "student1001")
    _send(setup, "student1002", "student1001")
    _send(setup, "student1001", "student1002")
    path = f"/messages/conversations/{setup.ids['student1002']}/read"
    headers = setup.headers("student1001")
    assert setup.client.post(path, headers=headers).json() == {
        "updated_count": 2, "unread_count": 0,
    }
    assert setup.client.post(path, headers=headers).json()["updated_count"] == 0
    assert _unread(setup, "student1002") == 1


def test_soft_delete_own_sent_only_and_tombstone(setup):
    message = _send(setup, "student1001", "student1002", "delete me")
    path = f"/messages/{message['id']}"
    for username in ("student1002", "student1003", "admin"):
        assert setup.client.delete(path, headers=setup.headers(username)).status_code == 404
    response = setup.client.delete(path, headers=setup.headers("student1001"))
    assert response.json() == {"deleted": True, "id": message["id"]}
    assert _unread(setup, "student1002") == 0
    with messaging._db() as conn:
        row = conn.execute(
            "SELECT * FROM direct_messages WHERE id = ?", (message["id"],),
        ).fetchone()
    assert row["text"] == ""
    assert row["deleted_at"] == setup.clock.now
    setup.clock.now += 10
    assert setup.client.delete(path, headers=setup.headers("student1001")).status_code == 200
    history = setup.client.get(
        f"/messages/conversations/{setup.ids['student1001']}",
        headers=setup.headers("student1002"),
    ).json()
    tombstone = history["messages"][0]
    assert tombstone["is_deleted"] is True
    assert tombstone["text"] == ""
    assert tombstone["deleted_at"] == message["created_at"]
    assert tombstone["read_at"] is None
    conversation = setup.client.get(
        "/messages/conversations", headers=setup.headers("student1002"),
    ).json()[0]
    assert conversation["last_message_preview"] == ""
    assert conversation["unread_count"] == 0
    assert setup.client.delete(
        "/messages/99999", headers=setup.headers("student1001"),
    ).status_code == 404


@pytest.mark.parametrize("body", [
    {}, {"text": ""}, {"text": " \n\t"}, {"text": "x" * 2001},
    {"text": None}, {"text": 123}, {"text": "hello", "sender_id": 999},
])
def test_text_validation(setup, body):
    response = setup.client.post(
        f"/messages/conversations/{setup.ids['student1002']}",
        json=body, headers=setup.headers("student1001"),
    )
    assert response.status_code == 422
    assert _unread(setup, "student1002") == 0


@pytest.mark.parametrize("text", ["好", "好" * 2000])
def test_text_boundaries(setup, text):
    assert _send(setup, "student1001", "student1002", text)["text"] == text


def test_peer_and_pagination_validation(setup):
    headers = setup.headers("student1001")
    for peer, status in (("student1001", 422), ("student1004", 403), ("student1005", 403)):
        path = f"/messages/conversations/{setup.ids[peer]}"
        for method, suffix in (("GET", ""), ("POST", ""), ("POST", "/read")):
            response = setup.client.request(
                method, path + suffix, json={"text": "hi"}, headers=headers,
            )
            assert response.status_code == status
    for peer_id in (0, -1, 99999):
        response = setup.client.post(
            f"/messages/conversations/{peer_id}", json={"text": "hi"}, headers=headers,
        )
        assert response.status_code == (404 if peer_id == 99999 else 422)
    for query in ("limit=0", "limit=101", "offset=-1", "limit=abc"):
        response = setup.client.get(
            f"/messages/conversations/{setup.ids['student1002']}?{query}", headers=headers,
        )
        assert response.status_code == 422
    assert setup.client.post(
        f"/messages/conversations/{setup.ids['student1004']}", json={"text": "hi"},
        headers=setup.headers("teacher"),
    ).status_code == 403


def test_existing_conversation_survives_enrollment_changes_but_cannot_send(setup):
    message = _send(setup, "student1001", "student1002")
    with sessions._db() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE moodle_user_id = 1001")
        conn.commit()
    path = f"/messages/conversations/{setup.ids['student1002']}"
    headers = setup.headers("student1001")
    assert setup.client.get(path, headers=headers).json()["messages"][0]["id"] == message["id"]
    assert setup.client.post(path, json={"text": "new"}, headers=headers).status_code == 403
    assert setup.client.post(path + "/read", headers=headers).status_code == 200


def test_presence_window_heartbeat_upsert_and_scope(setup):
    headers = setup.headers("student1001")
    ids = [setup.ids["student1001"], setup.ids["student1002"]]
    path = f"/presence?user_ids={ids[0]},{ids[1]},{ids[0]}"
    assert setup.client.get(path, headers=headers).json() == [
        {"user_id": uid, "last_seen": None, "online": False} for uid in ids
    ]
    response = setup.client.post("/presence/heartbeat", headers=headers)
    assert response.json() == {"user_id": ids[0], "last_seen": setup.clock.now, "online": True}
    setup.clock.now += 120
    assert setup.client.get(path, headers=headers).json()[0]["online"] is True
    setup.clock.now += 0.001
    assert setup.client.get(path, headers=headers).json()[0]["online"] is False
    assert setup.client.post("/presence/heartbeat", headers=headers).json()["online"] is True
    with messaging._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM message_presence").fetchone()[0] == 1
    course = setup.client.get("/presence/course/ds101", headers=headers).json()
    assert {item["user_id"] for item in course} == {
        setup.ids[name] for name in ("teacher", "student1001", "student1002", "student1003")
    }
    assert next(item for item in course if item["user_id"] == ids[0])["online"] is True
    assert setup.client.get("/presence/course/mk201", headers=headers).status_code == 403
    assert setup.client.get("/presence/course/unknown", headers=headers).status_code == 404
    assert setup.client.get(
        f"/presence?user_ids={setup.ids['student1004']}", headers=headers,
    ).status_code == 403
    assert setup.client.get(
        f"/presence?user_ids={ids[0]},99999", headers=headers,
    ).status_code == 403


@pytest.mark.parametrize("query", ["", "abc", "1,", "0", "-1", "1.5", ",1", "1,,2"])
def test_presence_validation(setup, query):
    assert setup.client.get(
        f"/presence?user_ids={query}", headers=setup.headers("student1001"),
    ).status_code == 422


def test_seed_idempotent_and_preserves_read_deleted_state(setup):
    # Four rows are eligible in ds101; student1003 is not enrolled in mk201.
    assert messaging.seed_demo_messages() == 4
    path = f"/messages/conversations/{setup.ids['teacher']}"
    headers = setup.headers("student1001")
    messages = setup.client.get(path, headers=headers).json()["messages"]
    own = next(item for item in messages if item["sender_id"] == setup.ids["student1001"])
    setup.client.delete(f"/messages/{own['id']}", headers=headers)
    with messaging._db() as conn:
        before = [dict(row) for row in conn.execute("SELECT * FROM direct_messages ORDER BY id")]
    setup.clock.now += 100
    assert messaging.seed_demo_messages() == 0
    with messaging._db() as conn:
        after = [dict(row) for row in conn.execute("SELECT * FROM direct_messages ORDER BY id")]
    assert before == after
    sessions.create_session(1003, "mk201")
    assert messaging.seed_demo_messages() == 1
    assert messaging.seed_demo_messages() == 0


def test_seed_without_demo_accounts_is_safe():
    assert messaging.seed_demo_messages() == 0
    with auth._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

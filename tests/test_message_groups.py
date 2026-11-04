"""Group conversations and starred messages: membership scoping and unread state."""

from types import SimpleNamespace

import pytest
from eduinsight import auth, message_groups, messaging, sessions
from eduinsight.courses import enroll
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def setup(auth_headers):
    for moodle_id in (1001, 1002, 1003):
        enroll("ds101", moodle_id, source="test")
        sessions.create_session(moodle_id, "ds101")
    enroll("mk201", 1004, source="test")
    sessions.create_session(1004, "mk201")
    ids = {
        name: auth.get_user_by_username(name)["id"]
        for name in ("teacher", "teacher_huang", *(f"student{uid}" for uid in range(1001, 1005)))
    }
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(messaging.router)
    app.include_router(message_groups.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, headers=auth_headers, ids=ids)


def _create(setup, owner="teacher", members=("student1001", "student1002"), name="排序讀書會"):
    response = setup.client.post("/message-groups", headers=setup.headers(owner), json={
        "name": name, "member_ids": [setup.ids[member] for member in members],
    })
    assert response.status_code == 201, response.text
    return response.json()


def _send(setup, group_id, sender, text="大家好"):
    response = setup.client.post(
        f"/message-groups/{group_id}/messages", headers=setup.headers(sender), json={"text": text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _unread(setup, username):
    return setup.client.get(
        "/messages/unread-count", headers=setup.headers(username),
    ).json()["unread_count"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/message-groups"),
    ("POST", "/message-groups"),
    ("GET", "/message-groups/1"),
    ("GET", "/message-groups/1/messages"),
    ("POST", "/message-groups/1/messages"),
    ("DELETE", "/message-groups/1/members/me"),
    ("PUT", "/messages/1/star"),
    ("GET", "/messages/starred"),
])
def test_requires_login(setup, method, path):
    assert setup.client.request(method, path).status_code == 401


def test_members_must_be_course_contacts(setup):
    response = setup.client.post("/message-groups", headers=setup.headers("student1001"), json={
        "name": "跨課", "member_ids": [setup.ids["student1004"]],
    })
    assert response.status_code == 403
    response = setup.client.post("/message-groups", headers=setup.headers("student1001"), json={
        "name": "只有自己", "member_ids": [setup.ids["student1001"]],
    })
    assert response.status_code == 422


def test_group_conversation_and_unread(setup):
    group = _create(setup)
    assert [m["username"] for m in group["members"]] == ["teacher", "student1001", "student1002"]
    _send(setup, group["id"], "teacher", "本週複習快速排序")
    assert _unread(setup, "student1001") == 1
    assert _unread(setup, "teacher") == 0

    [summary] = setup.client.get("/message-groups", headers=setup.headers("student1001")).json()
    assert (summary["name"], summary["unread_count"], summary["member_count"]) == ("排序讀書會", 1, 3)
    assert summary["last_message_preview"] == "本週複習快速排序"

    history = setup.client.get(
        f"/message-groups/{group['id']}/messages", headers=setup.headers("student1001"),
    ).json()
    assert [(m["sender_name"], m["text"]) for m in history["messages"]] == [("陳教授", "本週複習快速排序")]
    assert _unread(setup, "student1001") == 0
    assert _unread(setup, "student1002") == 1


def test_non_members_cannot_see_or_post(setup):
    group = _create(setup)
    for path in (f"/message-groups/{group['id']}", f"/message-groups/{group['id']}/messages"):
        assert setup.client.get(path, headers=setup.headers("student1003")).status_code == 404
    response = setup.client.post(
        f"/message-groups/{group['id']}/messages", headers=setup.headers("student1003"),
        json={"text": "偷看"},
    )
    assert response.status_code == 404
    assert setup.client.get("/message-groups", headers=setup.headers("student1003")).json() == []


def test_only_owner_adds_members_and_new_members_skip_old_unread(setup):
    group = _create(setup)
    _send(setup, group["id"], "student1001", "舊訊息")
    path = f"/message-groups/{group['id']}/members"
    body = {"user_ids": [setup.ids["student1003"]]}
    assert setup.client.post(path, headers=setup.headers("student1001"), json=body).status_code == 403
    added = setup.client.post(path, headers=setup.headers("teacher"), json=body)
    assert added.status_code == 200, added.text
    assert setup.ids["student1003"] in [m["user_id"] for m in added.json()["members"]]
    assert _unread(setup, "student1003") == 0
    outside = {"user_ids": [setup.ids["student1004"]]}
    assert setup.client.post(path, headers=setup.headers("teacher"), json=outside).status_code == 403


def test_leaving_removes_access_and_transfers_ownership(setup):
    group = _create(setup)
    left = setup.client.delete(
        f"/message-groups/{group['id']}/members/me", headers=setup.headers("teacher"),
    )
    assert left.status_code == 200
    assert setup.client.get(
        f"/message-groups/{group['id']}", headers=setup.headers("teacher"),
    ).status_code == 404
    detail = setup.client.get(
        f"/message-groups/{group['id']}", headers=setup.headers("student1001"),
    ).json()
    assert detail["owner_id"] == setup.ids["student1001"]


def test_delete_own_group_message_only(setup):
    group = _create(setup)
    message = _send(setup, group["id"], "student1001")
    path = f"/message-groups/{group['id']}/messages/{message['id']}"
    assert setup.client.delete(path, headers=setup.headers("student1002")).status_code == 404
    assert setup.client.delete(path, headers=setup.headers("student1001")).status_code == 200
    history = setup.client.get(
        f"/message-groups/{group['id']}/messages", headers=setup.headers("student1002"),
    ).json()
    assert history["messages"][0]["is_deleted"] is True and history["messages"][0]["text"] == ""
    assert _unread(setup, "student1002") == 0


def test_star_direct_and_group_messages(setup):
    direct = setup.client.post(
        f"/messages/conversations/{setup.ids['teacher']}", headers=setup.headers("student1001"),
        json={"text": "請問作業"},
    ).json()
    group = _create(setup)
    message = _send(setup, group["id"], "teacher", "考試範圍")

    assert setup.client.put(
        f"/messages/{direct['id']}/star", headers=setup.headers("student1002"),
    ).status_code == 404
    assert setup.client.put(
        f"/message-groups/{group['id']}/messages/{message['id']}/star",
        headers=setup.headers("student1003"),
    ).status_code == 404

    for path in (f"/messages/{direct['id']}/star",
                 f"/message-groups/{group['id']}/messages/{message['id']}/star"):
        response = setup.client.put(path, headers=setup.headers("student1001"))
        assert response.status_code == 200 and response.json()["starred"] is True
    starred = setup.client.get("/messages/starred", headers=setup.headers("student1001")).json()
    assert sorted((item["kind"], item["text"]) for item in starred) == [
        ("direct", "請問作業"), ("group", "考試範圍"),
    ]
    group_item = next(item for item in starred if item["kind"] == "group")
    assert group_item["group_name"] == "排序讀書會" and group_item["sender_name"] == "陳教授"
    direct_item = next(item for item in starred if item["kind"] == "direct")
    assert direct_item["peer"]["username"] == "teacher"
    assert setup.client.get("/messages/starred", headers=setup.headers("teacher")).json() == []

    assert setup.client.delete(
        f"/messages/{direct['id']}/star", headers=setup.headers("student1001"),
    ).status_code == 200
    setup.client.delete(f"/message-groups/{group['id']}/members/me", headers=setup.headers("student1001"))
    assert setup.client.get("/messages/starred", headers=setup.headers("student1001")).json() == []

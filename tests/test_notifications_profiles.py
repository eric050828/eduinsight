"""Real JWT authentication and isolated SQLite tests for the two new routers."""

from __future__ import annotations

import sqlite3

import pytest
from eduinsight import auth, notifications, profiles
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(auth_headers):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(notifications.router)
    app.include_router(profiles.router)
    with TestClient(app) as client:
        yield client


def user_id(username="student1001"):
    return auth.get_user_by_username(username)["id"]


def make_notification(username="student1001", title="Assignment due"):
    return notifications.create_notification(
        user_id(username), title, "Review your assignment.", "assignment_due", "/assignments",
    )


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/notifications", None),
    ("POST", "/notifications/1/read", None),
    ("POST", "/notifications/read-all", None),
    ("DELETE", "/notifications/1", None),
    ("GET", "/profile/me", None),
    ("PATCH", "/profile/me", {"bio": "Hello"}),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_requires_authentication(client, method, path, payload, headers):
    assert client.request(method, path, json=payload, headers=headers).status_code == 401


def test_notifications_order_counts_read_and_delete(client, auth_headers):
    headers = auth_headers("student1001")
    assert client.get("/notifications", headers=headers).json() == {
        "notifications": [], "unread_count": 0,
    }
    first = make_notification(title="First")
    second = make_notification(title="Second")
    # Make the tie breaker deterministic, independent of Windows clock precision.
    with notifications._db() as conn:
        conn.execute("UPDATE notifications SET created_at = 100")
        conn.commit()
    body = client.get("/notifications", headers=headers).json()
    assert [item["id"] for item in body["notifications"]] == [second["id"], first["id"]]
    assert body["unread_count"] == 2
    assert all(item["is_read"] is False for item in body["notifications"])
    for _ in range(2):
        response = client.post(f"/notifications/{first['id']}/read", headers=headers)
        assert response.status_code == 200
        assert response.json()["is_read"] is True
    assert client.get("/notifications", headers=headers).json()["unread_count"] == 1
    assert client.post("/notifications/read-all", headers=headers).json() == {
        "updated_count": 1, "unread_count": 0,
    }
    assert client.post("/notifications/read-all", headers=headers).json()["updated_count"] == 0
    assert client.delete(f"/notifications/{first['id']}", headers=headers).json() == {
        "deleted": True, "id": first["id"],
    }
    assert client.delete(f"/notifications/{first['id']}", headers=headers).status_code == 404
    assert client.post(f"/notifications/{first['id']}/read", headers=headers).status_code == 404
    third = make_notification(title="Unread")
    assert client.delete(f"/notifications/{third['id']}", headers=headers).status_code == 200
    remaining = client.get("/notifications", headers=headers).json()
    assert remaining["unread_count"] == 0
    assert [item["id"] for item in remaining["notifications"]] == [second["id"]]


@pytest.mark.parametrize("actor", ["student1001", "teacher", "admin"])
def test_notifications_are_private_for_every_role(client, auth_headers, actor):
    mine = make_notification(username=actor)
    theirs = make_notification(username="student1002")
    headers = auth_headers(actor)
    body = client.get("/notifications", headers=headers).json()
    assert [item["id"] for item in body["notifications"]] == [mine["id"]]
    for target in (theirs["id"], 999999):
        assert client.post(f"/notifications/{target}/read", headers=headers).status_code == 404
        assert client.delete(f"/notifications/{target}", headers=headers).status_code == 404
    assert client.post("/notifications/read-all", headers=headers).json()["updated_count"] == 1
    other = client.get("/notifications", headers=auth_headers("student1002")).json()
    assert other["unread_count"] == 1
    assert other["notifications"][0]["id"] == theirs["id"]
    assert other["notifications"][0]["is_read"] is False


def test_notification_helper_and_seed_idempotency(client, auth_headers):
    manual = make_notification(title="Custom")
    assert manual["user_id"] == user_id()
    assert manual["is_read"] is False
    assert notifications.seed_demo_notifications() == 30
    before = client.get("/notifications", headers=auth_headers("student1001")).json()
    seeded = next(item for item in before["notifications"] if item["title"] != "Custom")
    client.post(f"/notifications/{seeded['id']}/read", headers=auth_headers("student1001"))
    assert notifications.seed_demo_notifications() == 0
    after = client.get("/notifications", headers=auth_headers("student1001")).json()
    assert len(after["notifications"]) == 4
    assert after["unread_count"] == 3
    assert {item["id"] for item in before["notifications"]} == {
        item["id"] for item in after["notifications"]
    }
    for username in [*auth.TEACHER_COURSE_MAP, *(f"student{i}" for i in range(1002, 1006))]:
        body = client.get("/notifications", headers=auth_headers(username)).json()
        assert len(body["notifications"]) == body["unread_count"] == 3
        assert {item["kind"] for item in body["notifications"]} == {
            "assignment_due", "grade_released", "ai_tip",
        }
    assert client.get("/notifications", headers=auth_headers("admin")).json()["notifications"] == []
    with pytest.raises(sqlite3.IntegrityError):
        notifications.create_notification(999999, "Bad user", "Body", "tip")


def test_seed_without_existing_demo_users(auth_headers):
    with auth._db() as conn:
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()
    assert notifications.seed_demo_notifications() == 0
    assert auth.get_user_by_username("student1001") is None


def test_profiles_defaults_partial_updates_and_isolation(client, auth_headers):
    headers = auth_headers("student1001")
    original_user = auth.get_user_by_id(user_id())
    initial = client.get("/profile/me", headers=headers).json()
    assert initial == {
        "id": original_user["id"], "username": original_user["username"],
        "role": "student", "joined_at": original_user["created_at"],
        "display_name": original_user["display_name"], "email": None, "location": None,
        "bio": None, "social_links": {}, "avatar_url": None,
    }
    updates = {
        "display_name": "Alice", "email": "alice@example.com", "location": "Taipei",
        "bio": "Learning Python", "social_links": {"website": "https://example.com/alice"},
        "avatar_url": "http://example.com/avatar.png",
    }
    response = client.patch("/profile/me", headers=headers, json=updates)
    assert response.status_code == 200
    assert response.json() == initial | updates
    assert "password_hash" not in response.text
    assert auth.get_user_by_id(user_id()) == original_user
    assert client.get("/profile/me", headers=headers).json() == initial | updates
    assert client.patch("/profile/me", headers=headers, json={"bio": "New bio"}).json() == (
        initial | updates | {"bio": "New bio"}
    )
    cleared = client.patch("/profile/me", headers=headers, json={
        "email": None, "location": None, "bio": None, "avatar_url": None, "social_links": {},
    }).json()
    assert cleared == initial | {"display_name": "Alice"}
    assert client.patch("/profile/me", headers=headers, json={}).json() == cleared
    b_headers = auth_headers("student1002")
    client.patch("/profile/me", headers=b_headers, json={"display_name": "Bob", "bio": "Private"})
    assert client.get("/profile/me", headers=headers).json() == cleared
    assert client.get("/profile/me", headers=b_headers).json()["bio"] == "Private"


@pytest.mark.parametrize("updates", [
    {"display_name": ""}, {"display_name": "x" * 65}, {"display_name": None},
    {"email": "not-an-email"}, {"email": "x" * 250 + "@example.com"},
    {"location": "x" * 201}, {"bio": "x" * 2001},
    {"avatar_url": "javascript:alert(1)"}, {"avatar_url": "ftp://example.com/image"},
    {"avatar_url": "/avatar.png"}, {"avatar_url": "https://example.com/" + "a" * 2048},
    {"social_links": {"website": "javascript:alert(1)"}},
    {"social_links": {"website": "ftp://example.com"}},
    {"social_links": {"website": "/relative"}},
    {"social_links": {"website": "https://example.com/" + "a" * 2048}},
    {"social_links": {"": "https://example.com"}},
    {"social_links": {"x" * 65: "https://example.com"}},
    {"social_links": {str(i): "https://example.com" for i in range(21)}},
    {"social_links": {"website": 123}}, {"social_links": None},
    {"user_id": 2}, {"role": "admin"}, {"username": "other"}, {"password_hash": "secret"},
])
def test_profile_validation_is_atomic(client, auth_headers, updates):
    headers = auth_headers("student1001")
    before = client.get("/profile/me", headers=headers).json()
    response = client.patch("/profile/me", headers=headers, json={"bio": "Changed"} | updates)
    assert response.status_code == 422, response.text
    assert client.get("/profile/me", headers=headers).json() == before


@pytest.mark.parametrize("actor", ["teacher", "admin"])
def test_profile_role_is_from_users_and_remains_private(client, auth_headers, actor):
    headers = auth_headers(actor)
    response = client.patch("/profile/me", headers=headers, json={"bio": f"{actor}'s bio"})
    assert response.status_code == 200
    assert response.json()["role"] == actor
    assert response.json()["username"] == actor
    assert client.get("/profile/me", headers=auth_headers("student1001")).json()["bio"] is None

"""Tests for the standalone JWT auth module (Version A) + LTI bridge."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eduinsight import auth
from eduinsight.app import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "auth_test.db"
    monkeypatch.setattr(auth.settings, "auth_db_path", str(db_path))
    auth.init_db()
    with TestClient(app) as c:
        yield c


def test_register_creates_user_and_returns_token(client):
    r = client.post(
        "/auth/register",
        json={
            "username": "alice",
            "password": "secret123",
            "display_name": "Alice",
            "role": "student",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "student"
    assert body["user"]["moodle_user_id"] is not None  # auto-assigned
    assert body["access_token"]


def test_register_rejects_admin_role(client):
    r = client.post(
        "/auth/register",
        json={
            "username": "evil",
            "password": "secret123",
            "display_name": "evil",
            "role": "admin",
        },
    )
    assert r.status_code == 403


def test_login_with_correct_password(client):
    client.post(
        "/auth/register",
        json={
            "username": "bob",
            "password": "pw1234",
            "display_name": "Bob",
            "role": "student",
        },
    )
    r = client.post("/auth/login", json={"username": "bob", "password": "pw1234"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={
            "username": "carol",
            "password": "right",
            "display_name": "Carol",
            "role": "student",
        },
    )
    r = client.post("/auth/login", json={"username": "carol", "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_bearer(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_returns_current_user(client):
    reg = client.post(
        "/auth/register",
        json={
            "username": "dave",
            "password": "pw12345",
            "display_name": "Dave",
            "role": "teacher",
        },
    )
    token = reg.json()["access_token"]
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "dave"
    assert r.json()["role"] == "teacher"


def test_lti_bridge_creates_user_for_new_moodle_id(client):
    r = client.post(
        "/auth/lti-bridge",
        json={"moodle_user_id": 7777, "display_name": "LTI Test", "role": "student"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "lti_7777"
    assert body["user"]["moodle_user_id"] == 7777
    assert body["access_token"]


def test_lti_bridge_idempotent(client):
    r1 = client.post(
        "/auth/lti-bridge",
        json={"moodle_user_id": 8888, "display_name": "Repeat", "role": "student"},
    )
    r2 = client.post(
        "/auth/lti-bridge",
        json={"moodle_user_id": 8888, "display_name": "Repeat", "role": "student"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Same user id, different tokens (different iat)
    assert r1.json()["user"]["id"] == r2.json()["user"]["id"]


def test_seed_demo_users_idempotent(monkeypatch, tmp_path):
    db_path = tmp_path / "seed_test.db"
    monkeypatch.setattr(auth.settings, "auth_db_path", str(db_path))
    first = auth.seed_demo_users()
    second = auth.seed_demo_users()
    assert "teacher" in first
    assert all(v == "exists" for v in second.values())

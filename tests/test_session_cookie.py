"""Browser sessions: HttpOnly cookie, CSRF header on unsafe requests, logout."""

import pytest
from eduinsight import auth, preferences
from eduinsight.config import settings
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(auth_headers):
    auth_headers("student1001")  # Creates the demo student account.
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(preferences.router)
    with TestClient(app) as client:
        yield client


def _login(client):
    response = client.post("/auth/login", json={"username": "student1001", "password": "student123"})
    assert response.status_code == 200, response.text
    return response


def test_login_sets_an_httponly_lax_cookie(client):
    header = _login(client).headers["set-cookie"]
    assert header.startswith(f"{auth.SESSION_COOKIE}=")
    lowered = header.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered and "path=/" in lowered
    assert f"max-age={settings.jwt_expire_minutes * 60}" in lowered
    assert "secure" not in lowered  # development; production adds Secure


def test_cookie_secure_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    assert "secure" in _login(client).headers["set-cookie"].lower()


def test_cookie_authenticates_reads(client):
    _login(client)
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "student1001"


def test_cookie_writes_require_the_csrf_header(client):
    _login(client)
    body = {"theme": "dark"}
    assert client.put("/me/preferences", json=body).status_code == 403
    allowed = client.put("/me/preferences", json=body, headers={auth.CSRF_HEADER: "EduInsight"})
    assert allowed.status_code == 200, allowed.text


def test_bearer_header_needs_no_csrf_header(client, auth_headers):
    response = client.put("/me/preferences", json={"theme": "dark"}, headers=auth_headers("student1001"))
    assert response.status_code == 200


def test_logout_clears_the_cookie(client):
    _login(client)
    response = client.post("/auth/logout")
    assert response.status_code == 204
    assert 'max-age=0' in response.headers["set-cookie"].lower()
    assert client.get("/auth/me").status_code == 401


def test_bad_cookie_is_rejected(client):
    client.cookies.set(auth.SESSION_COOKIE, "not-a-jwt")
    assert client.get("/auth/me").status_code == 401

"""Admin security report: configuration checks without leaking secrets."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eduinsight import auth, platform_admin, security_center
from eduinsight.config import jwt_secret_is_strong, settings

STRONG = "k3J9-random-production-secret-value-0001"


@pytest.fixture
def client(auth_headers):
    app = FastAPI()
    app.include_router(security_center.router)
    app.include_router(platform_admin.router)
    with TestClient(app) as client:
        yield client


def _report(client, auth_headers):
    response = client.get("/platform/security", headers=auth_headers("admin"))
    assert response.status_code == 200, response.text
    return response.json()


def _status(report):
    return {check["id"]: check["status"] for check in report["checks"]}


def test_admin_only(client, auth_headers):
    assert client.get("/platform/security").status_code == 401
    for username in ("teacher", "student1001"):
        response = client.get("/platform/security", headers=auth_headers(username))
        assert response.status_code == 403


def test_development_defaults_are_flagged(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "jwt_secret", "dev-only-secret-change-me-in-production")
    report = _report(client, auth_headers)
    status = _status(report)
    assert status["environment"] == "warn" and status["jwt_secret"] == "warn"
    # The test admin uses the published demo password.
    assert status["default_admin_password"] == "fail"
    detail = next(c for c in report["checks"] if c["id"] == "default_admin_password")["detail"]
    assert "admin" in detail
    assert sum(report["summary"].values()) == len(report["checks"])


def test_hardened_production_passes(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "jwt_secret", STRONG)
    monkeypatch.setattr(settings, "cors_origins", "https://edu.example.org")
    auth.reset_user_password(auth.get_user_by_username("admin")["id"], "a-real-admin-password")
    report = _report(client, auth_headers)
    status = _status(report)
    for check in ("environment", "jwt_secret", "demo", "default_admin_password", "login_throttle",
                  "lti", "cors", "token_lifetime"):
        assert status[check] == "pass", (check, report["checks"])
    assert STRONG not in str(report)
    assert all("password_hash" not in admin for admin in report["admins"])


def test_cors_wildcard_and_plain_http(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "*")
    assert _status(_report(client, auth_headers))["cors"] == "fail"
    monkeypatch.setattr(settings, "cors_origins", "http://localhost:3000,http://edu.example.org")
    assert _status(_report(client, auth_headers))["cors"] == "warn"


def test_disabled_throttle_fails(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "login_throttle_enabled", False)
    assert _status(_report(client, auth_headers))["login_throttle"] == "fail"


def test_check_is_audited(client, auth_headers):
    _report(client, auth_headers)
    log = client.get("/platform/audit-log", headers=auth_headers("admin")).json()
    assert any(entry["action"] == "security.check" for entry in log["entries"])


def test_secret_strength_rule():
    assert jwt_secret_is_strong(STRONG)
    assert not jwt_secret_is_strong("short")
    assert not jwt_secret_is_strong("x" * 20 + "-change-me-" + "y" * 20)

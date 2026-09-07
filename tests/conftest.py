"""Shared fixtures: isolated auth DB + bearer headers for role-scoped endpoints."""

from __future__ import annotations

import pytest

from eduinsight import auth, sessions
from eduinsight.config import settings


@pytest.fixture(autouse=True)
def _isolate_databases(monkeypatch, tmp_path):
    """Never let a test touch the real demo / auth SQLite files.

    Several endpoint tests spin up the app lifespan (TestClient) which opens
    settings.memory_db_path; without this guard they silently wipe the demo
    data used for live walkthroughs.
    """
    monkeypatch.setattr(settings, "memory_db_path", str(tmp_path / "memory.db"))
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "auth.db"))
    auth.init_db()
    sessions.init_sessions_table()


@pytest.fixture
def auth_headers(monkeypatch, tmp_path):
    """Factory: auth_headers(username="admin") -> {"Authorization": "Bearer ..."}.

    Uses a temp auth DB seeded with the demo accounts plus an unscoped 'admin'
    user. Tests written before course-level isolation use the admin token.
    """
    monkeypatch.setattr(auth.settings, "auth_db_path", str(tmp_path / "auth.db"))
    auth.seed_demo_users()
    auth.create_user(auth.RegisterRequest(
        username="admin", password="admin123", display_name="Admin", role="admin",
    ))

    def _make(username: str = "admin") -> dict[str, str]:
        row = auth.get_user_by_username(username)
        assert row is not None, username
        user = auth._row_to_user(row)  # noqa: SLF001
        return {"Authorization": f"Bearer {auth.create_access_token(user)}"}

    return _make

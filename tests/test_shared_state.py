"""Login throttle and LTI state are shared by every worker that uses the same auth DB."""

import json
import subprocess
import sys
import textwrap
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eduinsight import auth, lti
from eduinsight.config import settings


@pytest.fixture(autouse=True)
def shared_settings(monkeypatch):
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "demo_mode", None)
    monkeypatch.setattr(settings, "enable_lti_bridge", False)
    monkeypatch.setattr(settings, "login_throttle_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", "a-test-signing-secret-of-at-least-32-characters")
    original_salt = auth.bcrypt.gensalt
    monkeypatch.setattr(auth.bcrypt, "gensalt", lambda: original_salt(rounds=4))
    monkeypatch.setattr(auth, "_DUMMY_HASH", auth.hash_password("dummy123"))
    auth._login_failures.clear()
    for store in (lti._sessions, lti._launch_cache, lti._exchange_codes):
        store.clear()
    yield
    auth._login_failures.clear()
    for store in (lti._sessions, lti._launch_cache, lti._exchange_codes):
        store.clear()


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(lti.router)
    return app


@pytest.fixture
def workers():
    """Two independent app instances, standing in for two Uvicorn workers."""
    with TestClient(make_app()) as first, TestClient(make_app()) as second:
        yield first, second


WRONG = {"username": "trusted-user", "password": "wrong-password"}


def provision():
    return auth.create_user(auth.RegisterRequest(
        username="trusted-user", password="student123", display_name="Trusted",
    ))


def test_login_failures_on_one_worker_lock_out_the_other(workers):
    provision()
    first, second = workers
    for _ in range(4):
        assert first.post("/auth/login", json=WRONG).status_code == 401
    locked = first.post("/auth/login", json=WRONG)
    assert locked.status_code == 429 and locked.headers["Retry-After"] == "30"
    on_other = second.post("/auth/login", json={**WRONG, "password": "student123"})
    assert on_other.status_code == 429 and on_other.headers["Retry-After"] in {"29", "30"}


def test_failures_alternating_between_workers_add_up(workers):
    provision()
    first, second = workers
    for index in range(4):
        worker = first if index % 2 else second
        assert worker.post("/auth/login", json=WRONG).status_code == 401
    assert first.post("/auth/login", json=WRONG).status_code == 429
    assert second.post("/auth/login", json=WRONG).status_code == 429


def test_success_on_one_worker_resets_the_shared_count(workers):
    provision()
    first, second = workers
    for _ in range(3):
        assert first.post("/auth/login", json=WRONG).status_code == 401
    assert second.post("/auth/login", json={**WRONG, "password": "student123"}).status_code == 200
    assert not auth._login_failures
    for _ in range(4):
        assert first.post("/auth/login", json=WRONG).status_code == 401


def test_throttle_switch_still_disables_shared_counting(workers, monkeypatch):
    monkeypatch.setattr(settings, "login_throttle_enabled", False)
    first, second = workers
    for worker in (first, second) * 4:
        assert worker.post("/auth/login", json=WRONG).status_code == 401
    assert not auth._login_failures


@pytest.fixture
def valid_launch(monkeypatch):
    class Launch:
        def __init__(self, *args):
            pass

        def validate(self):
            pass

        def get_launch_data(self):
            return {"sub": "7777", "name": "Learner"}

        def get_launch_id(self):
            return "verified-launch-id"

    monkeypatch.setattr(lti, "_get_tool_config", lambda: {})
    monkeypatch.setattr(lti, "FastAPIMessageLaunch", Launch)


def test_lti_exchange_code_cannot_be_replayed_on_another_worker(workers, valid_launch):
    first, second = workers
    response = first.post("/lti/launch", data={}, follow_redirects=False)
    assert response.status_code == 302
    code = parse_qs(urlsplit(response.headers["Location"]).query)["code"][0]
    assert lti._launch_cache["verified-launch-id"]["sub"] == "7777"
    exchanged = second.post("/lti/exchange", json={"code": code})
    assert exchanged.status_code == 200
    for worker in (first, second):
        replay = worker.post("/lti/exchange", json={"code": code})
        assert replay.status_code == 401 and replay.headers["Cache-Control"] == "no-store"


def test_lti_session_written_by_one_worker_is_read_by_another(workers, monkeypatch):
    issuer = "https://moodle.example"
    configuration = lti.ToolConfDict({issuer: [{
        "client_id": "registered-client", "auth_login_url": issuer + "/authorize",
        "auth_token_url": issuer + "/token", "key_set_url": issuer + "/jwks",
        "deployment_ids": ["deployment"],
    }]})
    monkeypatch.setattr(lti, "_get_tool_config", lambda: configuration)
    first, _ = workers
    response = first.post("/lti/login", data={
        "iss": issuer, "login_hint": "hint", "target_link_uri": "https://tool.example/lti/launch",
    }, follow_redirects=False)
    assert response.status_code == 302
    sid = response.cookies["lti_session_id"]
    nonce = parse_qs(urlsplit(response.headers["Location"]).query)["nonce"][0]
    # A fresh request object (as another worker would build) resumes the same session.
    resumed = lti.FastAPILTIRequest(_request_with_session(sid))
    assert resumed.session_id == sid
    assert resumed.session["lti1p3-nonce-" + nonce] is True


def _request_with_session(sid):
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "scheme": "https",
                    "path": "/lti/launch", "query_string": b"",
                    "headers": [(b"cookie", f"lti_session_id={sid}".encode())],
                    "server": ("test", 443)})


def test_state_is_shared_with_a_separate_worker_process(tmp_path):
    """A real second interpreter sees this process's lockout and consumes its code once."""
    for _ in range(4):
        auth._record_login_failure((("ip", "203.0.113.9"),))
    with pytest.raises(auth.HTTPException):
        auth._record_login_failure((("ip", "203.0.113.9"),))
    lti._exchange_codes["cross-process-code"] = (42, 3)
    script = textwrap.dedent("""
        import json, sys
        from eduinsight import auth, lti
        from eduinsight.config import settings
        settings.auth_db_path = sys.argv[1]
        settings.login_throttle_enabled = True
        try:
            auth._check_login_throttle((("ip", "203.0.113.9"),))
            locked = None
        except auth.HTTPException as exc:
            locked = exc.status_code
        first = lti._exchange_codes.pop("cross-process-code")
        second = lti._exchange_codes.pop("cross-process-code")
        print(json.dumps({"locked": locked, "first": first, "second": second}))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, settings.auth_db_path],
        capture_output=True, text=True, timeout=120, check=True, cwd=tmp_path,
    )
    outcome = json.loads(result.stdout.strip().splitlines()[-1])
    assert outcome == {"locked": 429, "first": [42, 3], "second": None}
    assert lti._exchange_codes.pop("cross-process-code") is None

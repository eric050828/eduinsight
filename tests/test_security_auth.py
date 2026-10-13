"""Regression coverage for deployment, identity, token, login and LTI hardening."""

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from eduinsight import admin_manage, auth, lti, preferences
from eduinsight.config import Settings, demo_enabled, settings, validate_production_settings
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from jwt.warnings import InsecureKeyLengthWarning
from pydantic import ValidationError
from starlette.requests import Request


@pytest.fixture(autouse=True)
def security_settings(monkeypatch):
    monkeypatch.setattr(settings, "env", "development")
    monkeypatch.setattr(settings, "demo_mode", None)
    monkeypatch.setattr(settings, "enable_lti_bridge", False)
    monkeypatch.setattr(settings, "login_throttle_enabled", False)
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


@pytest.fixture
def api():
    app = FastAPI()
    for module in (auth, lti, admin_manage, preferences):
        app.include_router(module.router)
    return app


@pytest.fixture
def client(api):
    with TestClient(api) as result:
        yield result


def register_body(**changes):
    return {"username": "new-student", "password": "student123",
            "display_name": "Student", **changes}


def provision(username="trusted-user", **changes):
    return auth.create_user(auth.RegisterRequest(
        username=username, password="student123", display_name="Trusted", **changes,
    ))


def bearer(user):
    return {"Authorization": f"Bearer {auth.create_access_token(user)}"}


@pytest.mark.parametrize("environment,override,enabled", [
    ("development", None, True), ("development", True, True),
    ("development", False, False), ("production", None, False),
    ("production", True, False), ("production", False, False),
])
def test_demo_mode_and_seed_gates(monkeypatch, environment, override, enabled):
    monkeypatch.setattr(settings, "env", environment)
    monkeypatch.setattr(settings, "demo_mode", override)
    assert demo_enabled() is enabled
    result = auth.seed_demo_users()
    assert bool(result) is enabled
    assert bool(auth.get_user_by_username("admin")) is enabled
    assert bool(auth.get_user_by_username("teacher")) is enabled


@pytest.mark.parametrize("secret", [
    "", " " * 40, "short", "a" * 31, Settings.model_fields["jwt_secret"].default,
    "placeholder" * 4, "replace-with-a-random-secret-32-characters",
    "change_me" * 5, "your_jwt_secret" * 3,
])
def test_production_rejects_unsafe_secrets(secret):
    with pytest.raises(ValidationError, match="EDUINSIGHT_JWT_SECRET"):
        Settings(_env_file=None, env="production", jwt_secret=secret)


def test_settings_environment_and_explicit_startup_validation(monkeypatch):
    monkeypatch.setenv("EDUINSIGHT_ENV", "production")
    monkeypatch.setenv("EDUINSIGHT_JWT_SECRET", "0f" * 32)
    configured = Settings(_env_file=None)
    assert configured.env == "production"
    validate_production_settings(configured)
    configured.jwt_secret = ""
    with pytest.raises(ValueError):
        validate_production_settings(configured)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="staging")


@pytest.mark.parametrize("environment,demo,bridge", [
    ("development", None, False), ("development", False, True),
    ("production", None, True), ("production", True, True),
])
def test_bridge_requires_development_demo_and_opt_in(client, monkeypatch,
                                                    environment, demo, bridge):
    monkeypatch.setattr(settings, "env", environment)
    monkeypatch.setattr(settings, "demo_mode", demo)
    monkeypatch.setattr(settings, "enable_lti_bridge", bridge)
    response = client.post("/auth/lti-bridge", json={"moodle_user_id": 7777})
    assert response.status_code == 404
    assert auth.get_user_by_username("lti_7777") is None


def test_bridge_rejects_admin_and_identity_reuse(client, monkeypatch):
    monkeypatch.setattr(settings, "enable_lti_bridge", True)
    assert client.post("/auth/lti-bridge", json={
        "moodle_user_id": 7777, "role": "admin",
    }).status_code == 403
    first = client.post("/auth/lti-bridge", json={"moodle_user_id": 7777})
    assert first.status_code == 200
    assert client.get("/auth/me", headers={
        "Authorization": f"Bearer {first.json()['access_token']}",
    }).status_code == 200
    repeated = client.post("/auth/lti-bridge", json={"moodle_user_id": 7777})
    assert repeated.status_code == 409 and "access_token" not in repeated.json()
    provision("other-name", moodle_user_id=8888)
    assert client.post("/auth/lti-bridge", json={"moodle_user_id": 8888}).status_code == 409
    provision("lti_9999", role="admin")
    assert client.post("/auth/lti-bridge", json={"moodle_user_id": 9999}).status_code == 409


@pytest.mark.parametrize("extra", [
    {"role": "admin"}, {"role": "teacher"}, {"role": "student"},
    {"moodle_user_id": 1001}, {"moodle_user_id": None},
])
def test_public_register_forbids_identity_fields(client, extra):
    assert client.post("/auth/register", json=register_body(**extra)).status_code == 422
    assert auth.get_user_by_username("new-student") is None


def test_public_register_assigns_unique_student_identity(client):
    provision("teacher-with-id", role="teacher", moodle_user_id=9000)
    first = client.post("/auth/register", json=register_body())
    second = client.post("/auth/register", json=register_body(username="second-student"))
    assert first.status_code == second.status_code == 200
    assert first.json()["user"]["role"] == "student"
    assert first.json()["user"]["moodle_user_id"] == 9001
    assert second.json()["user"]["moodle_user_id"] == 9002
    assert client.post("/auth/register", json=register_body()).status_code == 409


def test_concurrent_identity_allocation_and_unique_index():
    with ThreadPoolExecutor(max_workers=6) as pool:
        users = list(pool.map(lambda i: provision(f"parallel-{i}"), range(12)))
    assert len({user.moodle_user_id for user in users}) == 12
    with pytest.raises(HTTPException) as error:
        provision("collision", moodle_user_id=users[0].moodle_user_id)
    assert error.value.status_code == 409
    # Multiple non-student NULL identities are valid.
    provision("teacher-a", role="teacher")
    provision("teacher-b", role="teacher")


@pytest.mark.parametrize("environment,allowed", [("development", True), ("production", False)])
def test_registration_default_precedes_preferences_seed(client, monkeypatch, tmp_path,
                                                      environment, allowed):
    monkeypatch.setattr(settings, "env", environment)
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "fresh.db"))
    auth.init_db()
    preferences.seed_defaults()
    assert preferences._settings()["allow_self_register"] is allowed
    response = client.post("/auth/register", json=register_body())
    assert response.status_code == (200 if allowed else 403)


def test_registration_respects_admin_setting_in_both_modes(client, monkeypatch):
    admin = provision("trusted-admin", role="admin")
    headers = bearer(admin)
    for environment in ("development", "production"):
        monkeypatch.setattr(settings, "env", environment)
        for enabled in (False, True):
            assert client.put("/admin/settings", json={"allow_self_register": enabled},
                              headers=headers).status_code == 200
            response = client.post("/auth/register", json=register_body(
                username=f"{environment}-{enabled}",
            ))
            assert response.status_code == (200 if enabled else 403)


@pytest.mark.parametrize("environment,password,expected", [
    ("development", "abc", 422), ("development", "abcd", 200),
    ("development", "éé", 200), ("production", "1234567", 422),
    ("production", "12345678", 200), ("production", "éééé", 200),
    ("production", "你你", 422), ("production", "你" * 24, 200),
    ("development", "x" * 72, 200), ("production", "x" * 72, 200),
    ("development", "x" * 73, 422), ("production", "é" * 37, 422),
])
def test_password_policy_uses_utf8_bytes(client, monkeypatch, environment, password, expected):
    monkeypatch.setattr(settings, "env", environment)
    response = client.post("/auth/register", json=register_body(password=password))
    assert response.status_code == expected
    if expected == 200:
        assert client.post("/auth/login", json={
            "username": "new-student", "password": password,
        }).status_code == 200


def test_overlong_login_and_admin_reset_are_422(client):
    admin = provision("trusted-admin", role="admin")
    student = provision()
    assert client.post("/auth/login", json={
        "username": student.username, "password": "你" * 25,
    }).status_code == 422
    assert client.post(f"/admin/users/{student.id}/reset-password", headers=bearer(admin),
                       json={"password": "你" * 25}).status_code == 422
    with pytest.raises(HTTPException) as error:
        auth.hash_password("x" * 73)
    assert error.value.status_code == 422


def legacy_database(path, duplicate=False):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, "
                     "password_hash TEXT, display_name TEXT, role TEXT, moodle_user_id INTEGER, "
                     "created_at REAL)")
        for i in (1, 2):
            conn.execute("INSERT INTO users VALUES (?, ?, ?, ?, 'student', ?, 1)",
                         (i, f"old-{i}", auth.hash_password("student123"), "Old",
                          1001 if duplicate else 1000 + i))


def test_legacy_migration_is_idempotent_and_preserves_accounts(monkeypatch, tmp_path):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    monkeypatch.setattr(settings, "auth_db_path", str(path))
    for _ in range(2):
        auth.init_db()
    row = auth.get_user_by_id(1)
    assert row["token_version"] == 0 and row["active"] == 1
    assert row["moodle_user_id"] == 1001
    assert auth.verify_password("student123", row["password_hash"])
    with auth._db() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)")]
        assert columns.count("active") == columns.count("token_version") == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE users SET moodle_user_id=1001 WHERE id=2")


def test_duplicate_legacy_identities_fail_without_data_loss(monkeypatch, tmp_path):
    path = tmp_path / "duplicates.db"
    legacy_database(path, duplicate=True)
    monkeypatch.setattr(settings, "auth_db_path", str(path))
    with pytest.raises(RuntimeError, match="reconcile identities"):
        auth.init_db()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id, moodle_user_id FROM users ORDER BY id").fetchall() == [
            (1, 1001), (2, 1001),
        ]
        assert "token_version" not in [r[1] for r in conn.execute("PRAGMA table_info(users)")]


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "iss", "ver"])
def test_jwt_requires_claims(client, missing):
    user = provision()
    payload = auth.decode_token(auth.create_access_token(user))
    del payload[missing]
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("sub", ["0", "-1", "+1", "01", "abc", "1.0", "١", 1, None,
                                 "999999999999999999999999999999"])
def test_jwt_subject_must_be_positive_integer_string(client, sub):
    payload = auth.decode_token(auth.create_access_token(provision()))
    payload["sub"] = sub
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("change", [
    {"ver": "0"}, {"ver": False}, {"ver": -1}, {"ver": 999},
    {"iss": "someone-else"}, {"exp": 1}, {"iat": 9999999999},
    {"exp": []}, {"iat": {}},
])
def test_jwt_invalid_claims_and_version_are_rejected(client, change):
    payload = auth.decode_token(auth.create_access_token(provision()))
    payload.update(change)
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_jwt_algorithm_is_pinned_and_bump_revokes(client):
    user = provision()
    token = auth.create_access_token(user)
    payload = auth.decode_token(token)
    assert payload["ver"] == 0
    with pytest.warns(InsecureKeyLengthWarning):
        wrong_algorithm = jwt.encode(payload, settings.jwt_secret, algorithm="HS512")
    assert client.get("/auth/me", headers={
        "Authorization": f"Bearer {wrong_algorithm}",
    }).status_code == 401
    auth.bump_token_version(user.id)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/auth/me", headers=bearer(user)).status_code == 200


@pytest.mark.parametrize("mutation", ["password", "role", "disable"])
def test_admin_mutations_revoke_tokens_permanently(client, mutation):
    admin = provision("trusted-admin", role="admin")
    student = provision()
    old = bearer(student)
    headers = bearer(admin)
    if mutation == "password":
        result = client.post(f"/admin/users/{student.id}/reset-password", headers=headers,
                             json={"password": "new-password123"})
    else:
        changes = {"role": "teacher"} if mutation == "role" else {"active": False}
        result = client.patch(f"/admin/users/{student.id}", headers=headers, json=changes)
    assert result.status_code == 200
    assert auth.get_user_by_id(student.id)["token_version"] == 1
    assert client.get("/auth/me", headers=old).status_code == 401
    if mutation == "disable":
        client.patch(f"/admin/users/{student.id}", headers=headers, json={"active": True})
        assert client.get("/auth/me", headers=old).status_code == 401
    assert client.get("/auth/me", headers=bearer(student)).status_code == 200


def test_login_throttle_username_ip_backoff_and_success_reset(client, api, monkeypatch):
    provision()
    monkeypatch.setattr(settings, "login_throttle_enabled", True)
    clock = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    wrong = {"username": "trusted-user", "password": "wrong-password"}
    for _ in range(4):
        assert client.post("/auth/login", json=wrong).status_code == 401
    locked = client.post("/auth/login", json=wrong)
    assert locked.status_code == 429 and locked.headers["Retry-After"] == "30"
    # A different username from the same IP is locked as well.
    assert client.post("/auth/login", json={**wrong, "username": "different"}).status_code == 429
    # Moving to a different IP cannot bypass the username lock.
    async def from_other_ip():
        async with AsyncClient(transport=ASGITransport(app=api, client=("198.51.100.1", 1)),
                               base_url="http://test") as other:
            return await other.post("/auth/login", json=wrong)
    assert asyncio.run(from_other_ip()).status_code == 429
    for expected in (60, 120, 240, 480, 900, 900):
        clock[0] += 901
        locked = client.post("/auth/login", json=wrong)
        assert locked.status_code == 429 and locked.headers["Retry-After"] == str(expected)
    clock[0] += 901
    assert client.post("/auth/login", json={**wrong, "password": "student123"}).status_code == 200
    assert not auth._login_failures
    assert client.post("/auth/login", json=wrong).status_code == 401
    clock[0] += auth._THROTTLE_TTL + 1
    auth._check_login_throttle((("username", "trusted-user"),))
    assert not auth._login_failures


def test_throttle_is_bounded_and_switchable(client, monkeypatch):
    monkeypatch.setattr(settings, "login_throttle_enabled", True)
    monkeypatch.setattr(auth, "_THROTTLE_MAX", 3)
    for index in range(10):
        auth._record_login_failure((("username", f"user-{index}"),))
    assert len(auth._login_failures) == 3
    monkeypatch.setattr(settings, "login_throttle_enabled", False)
    for _ in range(6):
        assert client.post("/auth/login", json={
            "username": "missing", "password": "wrong-password",
        }).status_code == 401


async def test_bcrypt_runs_off_event_loop_and_unknown_uses_dummy(api, monkeypatch):
    user = provision()
    loop_thread = threading.get_ident()
    calls = []
    original = auth.verify_password
    def spy(password, hashed):
        calls.append((threading.get_ident(), hashed))
        return original(password, hashed)
    monkeypatch.setattr(auth, "verify_password", spy)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.post("/auth/login", json={
            "username": user.username, "password": "student123",
        })).status_code == 200
        assert (await client.post("/auth/login", json={
            "username": "missing", "password": "student123",
        })).status_code == 401
    assert len(calls) == 2 and all(thread != loop_thread for thread, _ in calls)
    assert calls[1][1] == auth._DUMMY_HASH


async def test_reset_during_password_verification_cannot_mint_new_version(api, monkeypatch):
    user = provision()
    original = auth.verify_password
    def reset_during_verification(password, hashed):
        verified = original(password, hashed)
        auth.reset_user_password(user.id, "replacement-password123")
        auth.bump_token_version(user.id)
        return verified
    monkeypatch.setattr(auth, "verify_password", reset_during_verification)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        result = await client.post("/auth/login", json={
            "username": user.username, "password": "student123",
        })
    assert result.status_code == 401 and "access_token" not in result.json()


@pytest.mark.parametrize("endpoint", ["login", "launch"])
def test_lti_errors_do_not_reflect_html(client, monkeypatch, endpoint):
    attack = '<img src=x onerror=alert(1)>'
    def invalid_config():
        raise ValueError(attack)
    monkeypatch.setattr(lti, "_get_tool_config", invalid_config)
    response = client.post(f"/lti/{endpoint}", data={"iss": attack})
    assert response.status_code == 400 and attack not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_lti_redirect_does_not_interpolate_url_in_html():
    location = 'https://moodle.example/login?hint=</script><img onerror="alert(1)">'
    response = lti.FastAPIRedirect(location).do_js_redirect()
    assert response.status_code == 302 and b"<img" not in response.body
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(ValueError):
        lti.FastAPIRedirect("javascript:alert(1)").do_js_redirect()


def test_real_oidc_login_persists_server_session_without_html(client, monkeypatch):
    issuer = "https://moodle.example"
    configuration = lti.ToolConfDict({issuer: [{
        "client_id": "registered-client", "auth_login_url": issuer + "/authorize",
        "auth_token_url": issuer + "/token", "key_set_url": issuer + "/jwks",
        "deployment_ids": ["deployment"],
    }]})
    monkeypatch.setattr(lti, "_get_tool_config", lambda: configuration)
    response = client.post("/lti/login", data={
        "iss": issuer, "login_hint": '<img onerror="alert(1)">',
        "target_link_uri": "https://tool.example/lti/launch",
    }, follow_redirects=False)
    assert response.status_code == 302 and b"<img" not in response.content
    params = parse_qs(urlsplit(response.headers["Location"]).query)
    sid = response.cookies["lti_session_id"]
    assert lti._sessions[sid]["lti1p3-nonce-" + params["nonce"][0]] is True
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("body", [{}, {"code": ""}, {"code": "x", "token": "secret"}])
def test_lti_exchange_validation_is_not_cached(client, body):
    response = client.post("/lti/exchange", json=body)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"


@pytest.fixture
def valid_launch(monkeypatch):
    class Launch:
        def __init__(self, *args):
            pass
        def validate(self):
            pass
        def get_launch_data(self):
            return {"sub": "7777", "name": '<img onerror="alert(1)">'}
        def get_launch_id(self):
            return "verified-launch-id"
    monkeypatch.setattr(lti, "_get_tool_config", lambda: {})
    monkeypatch.setattr(lti, "FastAPIMessageLaunch", Launch)


def launch_code(client):
    response = client.post("/lti/launch", data={}, follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    assert "token" not in query and "access_token" not in query
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    return query["code"][0]


def test_lti_exchange_code_is_single_use(client, valid_launch):
    code = launch_code(client)
    response = client.post("/lti/exchange", json={"code": code})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert client.get("/auth/me", headers={
        "Authorization": f"Bearer {response.json()['access_token']}",
    }).status_code == 200
    repeated = client.post("/lti/exchange", json={"code": code})
    assert repeated.status_code == 401 and repeated.headers["Cache-Control"] == "no-store"


def test_lti_exchange_code_expires_at_60_seconds(client, valid_launch, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(lti.time, "monotonic", lambda: clock[0])
    code = launch_code(client)
    clock[0] += 60
    response = client.post("/lti/exchange", json={"code": code})
    assert response.status_code == 401 and response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("mutation", ["disable", "version", "delete"])
def test_lti_exchange_rechecks_account(client, valid_launch, mutation):
    code = launch_code(client)
    row = auth.get_user_by_username("lti_7777")
    if mutation == "version":
        auth.bump_token_version(row["id"])
    else:
        with auth._db() as conn:
            sql = "UPDATE users SET active=0 WHERE id=?" if mutation == "disable" else (
                "DELETE FROM users WHERE id=?"
            )
            conn.execute(sql, (row["id"],))
            conn.commit()
    assert client.post("/lti/exchange", json={"code": code}).status_code == 401


def request_with_session(sid=None, scheme="https"):
    headers = [(b"cookie", f"lti_session_id={sid}".encode())] if sid else []
    return Request({"type": "http", "method": "POST", "scheme": scheme,
                    "path": "/lti/login", "query_string": b"", "headers": headers,
                    "server": ("test", 443)})


def test_lti_session_ids_are_server_generated_and_cookie_secure():
    attacker = "attacker-chosen-session"
    first = lti.FastAPILTIRequest(request_with_session(attacker))
    second = lti.FastAPILTIRequest(request_with_session(attacker))
    assert first.session_id != attacker and second.session_id != first.session_id
    assert len(first.session_id) >= 32 and attacker not in lti._sessions
    resumed = lti.FastAPILTIRequest(request_with_session(first.session_id))
    assert resumed.session_id == first.session_id
    first.session["nonce"] = "server-value"
    assert resumed.session["nonce"] == "server-value"
    response = lti.FastAPIRedirect("https://moodle.example",
                                  lti.FastAPICookieService(first)).do_redirect()
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie


@pytest.mark.parametrize("store_name", ["_sessions", "_launch_cache", "_exchange_codes"])
def test_lti_stores_have_ttl_and_max_size(monkeypatch, store_name):
    store = getattr(lti, store_name)
    clock = [1000.0]
    monkeypatch.setattr(lti.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(store, "max_size", 2)
    for key in ("first", "second", "third"):
        store[key] = {"value": key}
    assert len(store) == 2 and "first" not in store
    clock[0] += store.ttl
    assert store.get("third") is None and len(store) == 0
    if store_name == "_sessions":
        replaced = lti.FastAPILTIRequest(request_with_session("third"))
        assert replaced.session_id != "third"


def test_exchange_consume_is_atomic_across_threads():
    lti._exchange_codes["one-code"] = (1, 0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: lti._exchange_codes.pop("one-code", None), range(8)))
    assert results.count((1, 0)) == 1 and results.count(None) == 7

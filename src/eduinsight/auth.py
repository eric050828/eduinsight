"""Authentication module for EduInsight (Version A — standalone JWT).

Provides:
- SQLite-backed user table (users.db separate from memory.db)
- /auth/register, /auth/login, /auth/me endpoints
- Bearer token middleware via FastAPI dependency

Lite-Mem (memory_db_path) is NOT touched — this module owns its own DB.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .config import demo_enabled, settings

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- Schema

Role = Literal["student", "teacher", "admin"]


class AuthUser(BaseModel):
    id: int
    username: str
    display_name: str
    role: Role
    moodle_user_id: int | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=72, repr=False)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if not 1 <= len(value.encode("utf-8")) <= 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class PublicRegisterRequest(LoginRequest):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def registration_password(cls, value: str) -> str:
        minimum = 8 if settings.env == "production" else 4
        if not minimum <= len(value.encode("utf-8")) <= 72:
            raise ValueError(f"Password must be {minimum}..72 UTF-8 bytes")
        return value


class RegisterRequest(LoginRequest):
    """Trusted backend provisioning only; never used as a public request body."""
    display_name: str = Field(min_length=1, max_length=64)
    role: Role = "student"
    moodle_user_id: int | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser


# ---------------------------------------------------------------- DB


def _ensure_dir(path: str) -> None:
    p = Path(path).expanduser().resolve().parent
    p.mkdir(parents=True, exist_ok=True)


@contextmanager
def _db():
    _ensure_dir(settings.auth_db_path)
    conn = sqlite3.connect(settings.auth_db_path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_active_column(conn)
        yield conn
    finally:
        conn.close()


def _ensure_active_column(conn: sqlite3.Connection) -> None:
    """Upgrade legacy schemas atomically without reassigning account identities."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ux_users_moodle'"
    ).fetchone()
    if columns and (not {"active", "token_version"} <= columns or not index):
        conn.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        duplicate = conn.execute(
            "SELECT moodle_user_id FROM users WHERE moodle_user_id IS NOT NULL "
            "GROUP BY moodle_user_id HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            conn.rollback()
            raise RuntimeError(
                "Duplicate users.moodle_user_id; reconcile identities before startup"
            )
        if "active" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1 "
                         "CHECK(active IN (0, 1))")
        if "token_version" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_moodle "
                     "ON users(moodle_user_id) WHERE moodle_user_id IS NOT NULL")
        conn.commit()
    # Insert before preferences' development defaults, preserving explicit admin settings.
    conn.execute("CREATE TABLE IF NOT EXISTS platform_settings "
                 "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO platform_settings (key, value) VALUES (?, ?)",
                 ("allow_self_register", json.dumps(settings.env == "development")))
    conn.commit()


def init_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                display_name    TEXT NOT NULL,
                role            TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
                moodle_user_id  INTEGER,
                active          INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                token_version   INTEGER NOT NULL DEFAULT 0,
                created_at      REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS ix_users_moodle ON users(moodle_user_id);
            """
        )
        conn.commit()
        _ensure_active_column(conn)


# ---------------------------------------------------------------- Hashing


def hash_password(plain: str) -> str:
    minimum = 8 if settings.env == "production" else 4
    if not minimum <= len(plain.encode("utf-8")) <= 72:
        raise HTTPException(422, f"Password must be {minimum}..72 UTF-8 bytes")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- Tokens


def create_access_token(user: AuthUser, *, expected_version: int | None = None) -> str:
    row = get_user_by_id(user.id)
    if row is None or not row.get("active", 1):
        raise HTTPException(401, "User is unavailable")
    if expected_version is not None and row["token_version"] != expected_version:
        raise HTTPException(401, "Account credentials changed; log in again")
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "moodle_user_id": user.moodle_user_id,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.now(UTC),
        "iss": "eduinsight",
        "ver": row["token_version"],
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=["HS256"], issuer="eduinsight",
            options={"require": ["exp", "iat", "sub", "iss", "ver"]},
        )
        sub = payload["sub"]
        if (not isinstance(sub, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", sub)
                or int(sub) > 2**63 - 1):
            raise jwt.InvalidTokenError("Invalid subject")
        if (not isinstance(payload["ver"], int) or isinstance(payload["ver"], bool)
                or payload["ver"] < 0):
            raise jwt.InvalidTokenError("Invalid token version")
        return payload
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e


def bump_token_version(user_id: int) -> None:
    """Revoke all previously issued tokens for an account."""
    with _db() as conn:
        if conn.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?",
                        (user_id,)).rowcount == 0:
            raise HTTPException(404, "User not found")
        conn.commit()


# ---------------------------------------------------------------- DB ops


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    """Expose account metadata without password hashes or token material."""
    return _row_to_user(row).model_dump() | {"active": bool(row.get("active", 1))}


def list_managed_users(role: str | None, q: str | None, limit: int, offset: int) -> dict:
    clauses, params = [], []
    if role:
        clauses.append("role = ?")
        params.append(role)
    if q:
        clauses.append("(instr(lower(username), lower(?)) > 0 "
                       "OR instr(lower(display_name), lower(?)) > 0)")
        params.extend([q, q])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users" + where, params).fetchone()[0]
        rows = conn.execute("SELECT * FROM users" + where + " ORDER BY id LIMIT ? OFFSET ?",
                            [*params, limit, offset]).fetchall()
    return {"users": [public_user(dict(row)) for row in rows], "total": total,
            "limit": limit, "offset": offset}


def update_managed_user(user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    if set(changes) - {"display_name", "role", "active"}:
        raise ValueError("Unsupported user fields")
    with _db() as conn:
        if changes:
            conn.execute("UPDATE users SET " + ", ".join(f"{key} = ?" for key in changes)
                         + " WHERE id = ?", [*changes.values(), user_id])
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "User not found")
        conn.commit()
    return public_user(dict(row))


def reset_user_password(user_id: int, password: str) -> None:
    hashed = hash_password(password)
    with _db() as conn:
        if conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                        (hashed, user_id)).rowcount == 0:
            raise HTTPException(404, "User not found")
        conn.commit()


def create_user(req: RegisterRequest) -> AuthUser:
    hashed = hash_password(req.password)
    moodle_id = req.moodle_user_id
    with _db() as conn:
        # Serialize allocation and insertion; all roles share the same identity namespace.
        conn.execute("BEGIN IMMEDIATE")
        if moodle_id is None and req.role == "student":
            maximum = conn.execute("SELECT MAX(moodle_user_id) FROM users").fetchone()[0]
            moodle_id = max(1000, maximum or 0) + 1
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, "
                "moodle_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    req.username,
                    hashed,
                    req.display_name,
                    req.role,
                    moodle_id,
                    datetime.now(UTC).timestamp(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Username or Moodle identity already exists") from exc
        conn.commit()
        new_id = cur.lastrowid
    assert new_id is not None
    return AuthUser(
        id=new_id,
        username=req.username,
        display_name=req.display_name,
        role=req.role,
        moodle_user_id=moodle_id,
    )


def _row_to_user(row: dict[str, Any]) -> AuthUser:
    return AuthUser(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        moodle_user_id=row["moodle_user_id"],
    )


# ---------------------------------------------------------------- Dependencies


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = decode_token(creds.credentials)
    user_id = int(payload["sub"])
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if not row.get("active", 1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is disabled")
    if payload["ver"] != row["token_version"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token revoked")
    return _row_to_user(row)


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser | None:
    if creds is None or not creds.credentials:
        return None
    try:
        return await get_current_user(creds)
    except HTTPException:
        return None


def require_role(*roles: Role):
    async def _check(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Requires role: {','.join(roles)}"
            )
        return user

    return _check


# ---------------------------------------------------------------- Routes


_DUMMY_HASH = "$2b$12$l/MOpBPqNhpKl1M5zNd5BejRHcGNF9QPgluYnreL1nwULLK3/hLXG"
_THROTTLE_TTL = 1800
_THROTTLE_MAX = 10000
_login_failures: OrderedDict[tuple[str, str], tuple[int, float, float]] = OrderedDict()
_throttle_lock = threading.Lock()


def _prune_login_failures(now: float) -> None:
    for key, (_, _, expires) in list(_login_failures.items()):
        if expires <= now:
            _login_failures.pop(key, None)
    while len(_login_failures) > _THROTTLE_MAX:
        _login_failures.popitem(last=False)


def _locked_response(seconds: float) -> None:
    if seconds > 0:
        raise HTTPException(429, "Too many login attempts",
                            headers={"Retry-After": str(max(1, math.ceil(seconds)))})


def _check_login_throttle(keys: tuple[tuple[str, str], ...]) -> None:
    if not settings.login_throttle_enabled:
        return
    now = time.monotonic()
    with _throttle_lock:
        _prune_login_failures(now)
        remaining = max((_login_failures.get(key, (0, 0, 0))[1] - now for key in keys),
                        default=0)
    _locked_response(remaining)


def _record_login_failure(keys: tuple[tuple[str, str], ...]) -> None:
    if not settings.login_throttle_enabled:
        return
    now = time.monotonic()
    delay = 0
    with _throttle_lock:
        _prune_login_failures(now)
        for key in keys:
            count = _login_failures.get(key, (0, 0, 0))[0] + 1
            lockout = min(900, 30 * 2 ** min(count - 5, 5)) if count >= 5 else 0
            _login_failures[key] = (count, now + lockout, now + _THROTTLE_TTL)
            _login_failures.move_to_end(key)
            delay = max(delay, lockout)
        _prune_login_failures(now)
    _locked_response(delay)


@router.post("/register", response_model=TokenResponse)
async def register(req: PublicRegisterRequest) -> TokenResponse:
    with _db() as conn:
        value = conn.execute("SELECT value FROM platform_settings WHERE key = ?",
                             ("allow_self_register",)).fetchone()[0]
    if value != "true":
        raise HTTPException(403, "Self registration is disabled")
    user = await run_in_threadpool(create_user, RegisterRequest(**req.model_dump()))
    return TokenResponse(access_token=create_access_token(user), user=user)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request) -> TokenResponse:
    keys = (("username", req.username),
            ("ip", request.client.host if request.client else "unknown"))
    _check_login_throttle(keys)
    row = get_user_by_username(req.username)
    valid = await run_in_threadpool(
        verify_password, req.password, row["password_hash"] if row else _DUMMY_HASH,
    )
    if not valid or row is None or not row.get("active", 1):
        _record_login_failure(keys)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if settings.login_throttle_enabled:
        with _throttle_lock:
            for key in keys:
                _login_failures.pop(key, None)
    user = _row_to_user(row)
    return TokenResponse(
        access_token=create_access_token(user, expected_version=row["token_version"]), user=user,
    )


@router.get("/me", response_model=AuthUser)
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user


class LTIBridgeRequest(BaseModel):
    moodle_user_id: int = Field(ge=1)
    display_name: str = Field(default="", max_length=64)
    role: Role = "student"


@router.post("/lti-bridge", response_model=TokenResponse)
async def lti_bridge_dev(req: LTIBridgeRequest) -> TokenResponse:
    """Dev-only: simulate an LTI launch by issuing a JWT for an arbitrary moodle_user_id.

    Explicit development opt-in only; existing identities can never be impersonated.
    """
    if not demo_enabled() or not settings.enable_lti_bridge:
        raise HTTPException(404, "LTI development bridge is disabled")
    if req.role == "admin":
        raise HTTPException(403, "Admin role is not allowed")
    username = f"lti_{req.moodle_user_id}"
    with _db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? OR moodle_user_id = ?",
            (username, req.moodle_user_id),
        ).fetchone()
    if existing:
        raise HTTPException(409, "Account already exists; use authenticated login")
    user = await run_in_threadpool(
        create_user,
        RegisterRequest(
            username=username,
            password=secrets.token_hex(16),
            display_name=req.display_name or username,
            role=req.role,
            moodle_user_id=req.moodle_user_id,
        ),
    )
    return TokenResponse(access_token=create_access_token(user), user=user)


# ---------------------------------------------------------------- Seed


# Demo teacher → owned course mapping. Used by teacher-side endpoints to
# scope dashboard / summaries / analytics to one course per professor.
TEACHER_COURSE_MAP: dict[str, str] = {
    "teacher":         "ds101",   # 陳教授
    "teacher_huang":   "mk201",   # 黃教授
    "teacher_lin":     "chm301",  # 林教授
    "teacher_wang":    "eng201",  # 王教授
    "teacher_li":      "ipr101",  # 李教授
}


def seed_demo_users() -> dict[str, str]:
    """Create demo users matching demo_data.py student IDs (1001-1005). Idempotent."""
    if not demo_enabled():
        return {}
    init_db()
    demo = [
        ("teacher",        "teacher123", "陳教授", "teacher", None),
        ("teacher_huang",  "huang123",   "黃教授", "teacher", None),
        ("teacher_lin",    "lin123",     "林教授", "teacher", None),
        ("teacher_wang",   "wang123",    "王教授", "teacher", None),
        ("teacher_li",     "li123",      "李教授", "teacher", None),
        ("admin",          "admin123",   "系統管理員", "admin", None),
        ("student1001",    "student123", "A 陳同學", "student", 1001),
        ("student1002",    "student123", "B 林同學", "student", 1002),
        ("student1003",    "student123", "C 王同學", "student", 1003),
        ("student1004",    "student123", "D 李同學", "student", 1004),
        ("student1005",    "student123", "E 張同學", "student", 1005),
    ]
    created: dict[str, str] = {}
    for username, password, name, role, moodle_id in demo:
        if get_user_by_username(username):
            created[username] = "exists"
            continue
        try:
            create_user(
                RegisterRequest(
                    username=username,
                    password=password,
                    display_name=name,
                    role=role,  # type: ignore[arg-type]
                    moodle_user_id=moodle_id,
                )
            )
            created[username] = "created"
        except HTTPException as e:
            created[username] = f"error: {e.detail}"
    return created

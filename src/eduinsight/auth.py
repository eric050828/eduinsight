"""Authentication module for EduInsight (Version A — standalone JWT).

Provides:
- SQLite-backed user table (users.db separate from memory.db)
- /auth/register, /auth/login, /auth/me endpoints
- Bearer token middleware via FastAPI dependency

Lite-Mem (memory_db_path) is NOT touched — this module owns its own DB.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .config import settings

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
    password: str = Field(min_length=4, max_length=128)


class RegisterRequest(LoginRequest):
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
        yield conn
    finally:
        conn.close()


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
                created_at      REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS ix_users_moodle ON users(moodle_user_id);
            """
        )
        conn.commit()


# ---------------------------------------------------------------- Hashing


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- Tokens


def create_access_token(user: AuthUser) -> str:
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "moodle_user_id": user.moodle_user_id,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.now(UTC),
        "iss": "eduinsight",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="eduinsight")
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e


# ---------------------------------------------------------------- DB ops


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_user(req: RegisterRequest) -> AuthUser:
    if get_user_by_username(req.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")

    moodle_id = req.moodle_user_id
    # Auto-generate moodle_user_id for students if not provided (so chat/analytics keys exist)
    if moodle_id is None and req.role == "student":
        with _db() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(moodle_user_id), 1000) AS m FROM users WHERE role='student'"
            ).fetchone()
            moodle_id = int(row["m"]) + 1

    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, "
            "moodle_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                req.username,
                hash_password(req.password),
                req.display_name,
                req.role,
                moodle_id,
                datetime.now(UTC).timestamp(),
            ),
        )
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


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    if req.role == "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin must be created via seed script")
    user = create_user(req)
    return TokenResponse(access_token=create_access_token(user), user=user)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    row = get_user_by_username(req.username)
    if row is None or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    user = _row_to_user(row)
    return TokenResponse(access_token=create_access_token(user), user=user)


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

    In production, this should be locked behind a shared secret or disabled.
    Used by Playwright tests and local development to bypass the Moodle round-trip.
    """
    username = f"lti_{req.moodle_user_id}"
    existing = get_user_by_username(username)
    if existing:
        user = _row_to_user(existing)
    else:
        import secrets

        user = create_user(
            RegisterRequest(
                username=username,
                password=secrets.token_hex(16),
                display_name=req.display_name or username,
                role=req.role,
                moodle_user_id=req.moodle_user_id,
            )
        )
    return TokenResponse(access_token=create_access_token(user), user=user)


# ---------------------------------------------------------------- Seed


def seed_demo_users() -> dict[str, str]:
    """Create demo users matching demo_data.py student IDs (1001-1005). Idempotent."""
    init_db()
    demo = [
        ("teacher", "teacher123", "陳老師", "teacher", None),
        ("student1001", "student123", "A 陳同學", "student", 1001),
        ("student1002", "student123", "B 林同學", "student", 1002),
        ("student1003", "student123", "C 王同學", "student", 1003),
        ("student1004", "student123", "D 李同學", "student", 1004),
        ("student1005", "student123", "E 張同學", "student", 1005),
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

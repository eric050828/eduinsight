"""Audited user and persisted course catalog management."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from . import auth, courses
from .auth import AuthUser, require_role
from .platform_admin import record_audit

router = APIRouter(prefix="/admin", tags=["admin-management"])


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_null_and_blank(self):
        for key in self.model_fields_set:
            value = getattr(self, key)
            if value is None and key not in {"teacher_username", "moodle_user_id"}:
                raise ValueError(f"{key} cannot be null")
            if key in {"name", "display_name", "username", "teacher_username"}:
                if isinstance(value, str) and not value.strip():
                    raise ValueError(f"{key} cannot be blank")
        return self


class UserCreate(Mutation):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128, repr=False)
    display_name: str = Field(min_length=1, max_length=64)
    role: Literal["teacher", "student"] = "student"
    moodle_user_id: int | None = Field(default=None, ge=1)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value: str) -> str:
        if value is None:
            raise ValueError("Password cannot be null")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class UserPatch(Mutation):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: Literal["teacher", "student"] | None = None
    active: StrictBool | None = None


class PasswordReset(Mutation):
    password: str | None = Field(default=None, min_length=4, max_length=128, repr=False)
    _password_bytes = field_validator("password")(UserCreate.password_bytes.__func__)


class CourseCreate(Mutation):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=200)
    teacher_username: str | None = Field(default=None, min_length=2, max_length=64)


class CoursePatch(Mutation):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    teacher_username: str | None = Field(default=None, min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=20000)
    archived: StrictBool | None = None


def _existing_user(user_id: int) -> dict:
    row = auth.get_user_by_id(user_id)
    if row is None:
        raise HTTPException(404, "User not found")
    return row


@router.get("/users")
def list_users(
    role: auth.Role | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: AuthUser = Depends(require_role("admin")),
) -> dict:
    return auth.list_managed_users(role, q, limit, offset)


@router.post("/users", status_code=201)
def create_user(req: UserCreate, user: AuthUser = Depends(require_role("admin"))) -> dict:
    try:
        created = auth.create_user(auth.RegisterRequest(**req.model_dump()))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Username already exists") from exc
    record_audit(user.username, "user.created", str(created.id))
    return auth.public_user(_existing_user(created.id))


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    req: UserPatch,
    user: AuthUser = Depends(require_role("admin")),
) -> dict:
    _existing_user(user_id)
    changes = req.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "At least one field is required")
    if user_id == user.id and (changes.get("active") is False or "role" in changes):
        raise HTTPException(403, "Cannot disable or demote yourself")
    result = auth.update_managed_user(user_id, changes)
    if "role" in changes or changes.get("active") is False:
        auth.bump_token_version(user_id)
    record_audit(user.username, "user.updated", str(user_id))
    return result


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    req: PasswordReset = PasswordReset(),
    user: AuthUser = Depends(require_role("admin")),
) -> dict:
    _existing_user(user_id)
    password = req.password or secrets.token_urlsafe(18)
    auth.reset_user_password(user_id, password)
    auth.bump_token_version(user_id)
    record_audit(user.username, "user.password_reset", str(user_id))
    # Generated credentials are disclosed only in this response, never stored in plaintext.
    return (
        {"user_id": user_id, "password": password}
        if req.password is None
        else {
            "user_id": user_id,
            "reset": True,
        }
    )


def _validate_teacher(username: str | None) -> None:
    if username is None:
        return
    row = auth.get_user_by_username(username)
    if row is None or row["role"] != "teacher" or not row.get("active", 1):
        raise HTTPException(422, "Teacher must be an active teacher account")


@router.post("/courses", status_code=201)
def create_course(
    req: CourseCreate,
    user: AuthUser = Depends(require_role("admin")),
) -> courses.CourseInfo:
    _validate_teacher(req.teacher_username)
    try:
        with courses._catalog_db() as conn:
            conn.execute(
                "INSERT INTO course_catalog (id, name, teacher_username) VALUES (?, ?, ?)",
                (req.id, req.name, req.teacher_username),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Course already exists") from exc
    record_audit(user.username, "course.created", req.id)
    return courses._course_info(req.id)


@router.patch("/courses/{course_id}")
def patch_course(
    course_id: str,
    req: CoursePatch,
    user: AuthUser = Depends(require_role("teacher", "admin")),
) -> courses.CourseInfo:
    courses._check_course_access(user, course_id)
    changes = req.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "At least one field is required")
    if user.role == "teacher" and set(changes) != {"description"}:
        raise HTTPException(403, "Teachers may only edit their course description")
    if "teacher_username" in changes:
        _validate_teacher(changes["teacher_username"])
    with courses._catalog_db() as conn:
        conn.execute(
            "UPDATE course_catalog SET "
            + ", ".join(f"{key} = ?" for key in changes)
            + " WHERE id = ?",
            [*changes.values(), course_id],
        )
    record_audit(user.username, "course.updated", course_id)
    return courses._course_info(course_id)


def seed_demo_admin_data() -> dict:
    """Idempotent lazy catalog/settings setup, after auth/session initialization."""
    from .preferences import seed_defaults

    catalog = courses.catalog_entries()
    seed_defaults()
    return {"catalog_courses": len(catalog)}

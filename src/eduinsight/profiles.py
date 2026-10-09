"""Private profile overrides; the users table remains unchanged."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from . import auth
from .auth import AuthUser, Role, get_current_user

router = APIRouter(prefix="/profile", tags=["profiles"])
_http_url = TypeAdapter(HttpUrl)
SocialKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]
SocialURL = Annotated[str, StringConstraints(max_length=2048)]


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    location: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=2000)
    social_links: dict[SocialKey, SocialURL] | None = Field(default=None, max_length=20)
    avatar_url: str | None = Field(default=None, max_length=2048)

    @field_validator("display_name", "social_links", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar(cls, value):
        if value is not None:
            _http_url.validate_python(value)
        return value

    @field_validator("social_links")
    @classmethod
    def validate_social_links(cls, value):
        if value is not None:
            for url in value.values():
                _http_url.validate_python(url)
        return value


class Profile(BaseModel):
    id: int
    username: str
    role: Role
    joined_at: float
    display_name: str
    email: str | None = None
    location: str | None = None
    bio: str | None = None
    social_links: dict[str, str] = Field(default_factory=dict)
    avatar_url: str | None = None


@contextmanager
def _db():
    with auth._db() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS profiles ("
            "user_id INTEGER PRIMARY KEY REFERENCES users(id), "
            "display_name TEXT, email TEXT, location TEXT, bio TEXT, "
            "social_links TEXT NOT NULL DEFAULT '{}', avatar_url TEXT)"
        )
        conn.commit()
        yield conn


def init_db() -> None:
    """Initialize this module's table; routes also initialize it lazily."""
    with _db():
        pass


def _get_profile(conn, user_id: int) -> Profile:
    user = conn.execute(
        "SELECT id, username, role, created_at, display_name FROM users WHERE id = ?", (user_id,),
    ).fetchone()
    if user is None:
        raise HTTPException(401, "User not found")
    row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    fields = dict(row) if row is not None else {}
    return Profile(
        id=user["id"], username=user["username"], role=user["role"], joined_at=user["created_at"],
        display_name=fields.get("display_name") or user["display_name"],
        email=fields.get("email"), location=fields.get("location"), bio=fields.get("bio"),
        social_links=json.loads(fields.get("social_links", "{}")),
        avatar_url=fields.get("avatar_url"),
    )


@router.get("/me", response_model=Profile)
async def get_profile(user: AuthUser = Depends(get_current_user)) -> Profile:
    with _db() as conn:
        return _get_profile(conn, user.id)


@router.patch("/me", response_model=Profile)
async def patch_profile(
    patch: ProfilePatch, user: AuthUser = Depends(get_current_user),
) -> Profile:
    changes = patch.model_dump(exclude_unset=True)
    with _db() as conn:
        if changes:
            conn.execute(
                "INSERT INTO profiles (user_id) VALUES (?) ON CONFLICT DO NOTHING", (user.id,),
            )
            if "social_links" in changes:
                changes["social_links"] = json.dumps(changes["social_links"])
            # Keys come exclusively from the validated, extra-forbidden model.
            assignments = ", ".join(f"{field} = ?" for field in changes)
            conn.execute(
                f"UPDATE profiles SET {assignments} WHERE user_id = ?",
                (*changes.values(), user.id),
            )
            conn.commit()
        return _get_profile(conn, user.id)

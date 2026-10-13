"""Private JSON preferences and safe public platform settings."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from . import auth
from .auth import AuthUser, get_current_user, require_role
from .db import schema_once
from .platform_admin import record_audit

router = APIRouter(tags=["preferences"])

DEFAULT_SETTINGS = {
    "site_name": "EduInsight",
    "allow_self_register": True,
    "maintenance_banner": "",
}
PUBLIC_KEYS = ("site_name", "maintenance_banner")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["light", "dark", "system"] = "system"
    language: Literal["zh-TW", "en"] = "zh-TW"
    dashboard_layout: list[Annotated[str, Field(min_length=1)]] = Field(
        default_factory=list,
        max_length=30,
    )
    notifications: dict[str, StrictBool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def size_limit(self):
        if (
            len(json.dumps(self.model_dump(exclude_unset=True), ensure_ascii=False).encode("utf-8"))
            > 16 * 1024
        ):
            raise ValueError("Preferences must be at most 16 KB")
        return self


class PlatformSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_name: str | None = Field(default=None, min_length=1, max_length=200)
    allow_self_register: StrictBool | None = None
    maintenance_banner: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def non_null(self):
        for key in self.model_fields_set:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if self.site_name is not None and not self.site_name.strip():
            raise ValueError("site_name cannot be blank")
        return self


@contextmanager
def _db():
    with auth._db() as conn:
        with schema_once(conn, "preferences") as initialize:
            if initialize:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                        preferences TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS platform_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                """)
                for key, value in DEFAULT_SETTINGS.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO platform_settings (key, value) VALUES (?, ?)",
                        (key, json.dumps(value, ensure_ascii=False)),
                    )
                conn.commit()
        yield conn
        conn.commit()


def seed_defaults() -> None:
    with _db():
        pass


def _settings() -> dict:
    with _db() as conn:
        return {
            row["key"]: json.loads(row["value"])
            for row in conn.execute(
                "SELECT key, value FROM platform_settings",
            )
            if row["key"] in DEFAULT_SETTINGS
        }


@router.get("/me/preferences")
def get_preferences(user: AuthUser = Depends(get_current_user)) -> dict:
    with _db() as conn:
        row = conn.execute(
            "SELECT preferences FROM user_preferences WHERE user_id = ?", (user.id,)
        ).fetchone()
    return json.loads(row[0]) if row else {}


@router.put("/me/preferences")
def put_preferences(req: Preferences, user: AuthUser = Depends(get_current_user)) -> dict:
    value = req.model_dump(exclude_unset=True)
    with _db() as conn:
        conn.execute(
            "INSERT INTO user_preferences (user_id, preferences) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET preferences = excluded.preferences",
            (user.id, json.dumps(value, ensure_ascii=False)),
        )
    record_audit(user.username, "preferences.updated", str(user.id))
    return value


@router.get("/admin/settings")
def get_settings(user: AuthUser = Depends(require_role("admin"))) -> dict:
    return _settings()


@router.put("/admin/settings")
def put_settings(req: PlatformSettings, user: AuthUser = Depends(require_role("admin"))) -> dict:
    changes = req.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "At least one setting is required")
    with _db() as conn:
        for key, value in changes.items():
            conn.execute(
                "UPDATE platform_settings SET value = ? WHERE key = ?",
                (json.dumps(value, ensure_ascii=False), key),
            )
    record_audit(user.username, "settings.updated", "platform-settings")
    return _settings()


@router.get("/public/settings")
def public_settings() -> dict:
    values = _settings()
    return {key: values[key] for key in PUBLIC_KEYS}

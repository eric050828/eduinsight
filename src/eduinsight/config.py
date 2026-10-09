"""Application configuration via environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """EduInsight configuration.

    All values can be set via environment variables (case-insensitive)
    or a .env file in the project root.
    """

    # Moodle connection
    moodle_url: str = "https://moodle.ntust.edu.tw"
    moodle_token: str = ""

    # LLM (auto-detected from env: GEMINI_API_KEY / OPENAI_API_KEY / GROQ_API_KEY)
    llm_model: str = ""  # Override model name, empty = auto-detect

    # Lite-Mem storage
    memory_db_path: str = "eduinsight.db"
    memory_top_k: int = 8
    memory_embedder: str = "auto"  # "auto", "stub", "gemini", or "" to disable

    # Server
    env: Literal["development", "production"] = "development"
    demo_mode: bool | None = None  # None derives from env; production always disables demos
    enable_lti_bridge: bool = False
    login_throttle_enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    # CORS — comma-separated origins, e.g. "http://localhost:3000,https://edu-insight-two.vercel.app"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Auth mode: "jwt" (standalone Version A) | "lti" (Moodle Version B) | "both"
    auth_mode: str = "both"

    # JWT secret (Version A only). Generate via: openssl rand -hex 32
    jwt_secret: str = "dev-only-secret-change-me-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Internal user database for standalone mode (separate from memory_db)
    auth_db_path: str = "eduinsight_auth.db"

    # Frontend URL — used by LTI launch to redirect users into the Next.js app
    frontend_url: str = "http://localhost:3000"

    model_config = {"env_prefix": "EDUINSIGHT_", "env_file": ".env"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def production_settings(self) -> Settings:
        validate_production_settings(self)
        return self


def validate_production_settings(config: Settings | None = None) -> None:
    """Fail before startup/DB writes when production signing credentials are unsafe."""
    config = config if config is not None else settings
    if config.env != "production":
        return
    secret = config.jwt_secret.strip()
    placeholders = ("dev-only-secret", "change-me", "change_me", "changeme", "replace-with",
                    "replace_with", "replace-me", "replace_me", "placeholder",
                    "your-secret", "your_secret", "your_jwt_secret", "your-jwt-secret")
    if len(secret) < 32 or any(value in secret.lower() for value in placeholders):
        raise ValueError(
            "Production requires a random EDUINSIGHT_JWT_SECRET of at least 32 characters"
        )


def demo_enabled() -> bool:
    """Demo features are limited to development, with an optional explicit override."""
    return settings.env == "development" and settings.demo_mode is not False


settings = Settings()

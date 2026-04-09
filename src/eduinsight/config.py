"""Application configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """EduInsight configuration.

    All values can be set via environment variables (case-insensitive)
    or a .env file in the project root.
    """

    # Moodle connection
    moodle_url: str = "https://moodle.ntust.edu.tw"
    moodle_token: str = ""

    # Lite-Mem storage
    memory_db_path: str = "eduinsight.db"
    memory_top_k: int = 8

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = {"env_prefix": "EDUINSIGHT_", "env_file": ".env"}


settings = Settings()

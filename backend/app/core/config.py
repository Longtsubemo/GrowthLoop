"""Application settings loaded from environment variables.

Values are read from the process environment and, if present, a ``.env``
file in the working directory or the repository root (so a single root
``.env`` works when the server is started from ``backend/``). See
``.env.example`` at the repository root for the available variables.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """GrowthLoop backend configuration."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "GrowthLoop"
    debug: bool = True
    # Defaults match the local docker-compose PostgreSQL service.
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/growthloop"
    )
    # Comma-separated CORS origins allowed to call the API from a browser
    # (the React dev server runs on its own origin). The defaults match
    # `npm run dev`; the Playwright suite overrides this via the env var.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()

"""Application settings.

Reads configuration from environment variables (and an optional ``.env`` file)
so the Backend_API can associate requests with the logged-in user via a signed
session secret, and reach the relational store and geospatial index.

Requirement 1.4: the session secret configured here is used to sign the
HTTP-only session cookie that binds every user-context request to a user id.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for the backend service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # PostgreSQL (async SQLAlchemy + asyncpg).
    db_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/amazon_edge_return",
        alias="DB_URL",
        description="Async SQLAlchemy database URL for the relational store.",
    )

    # Redis geospatial demand index.
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
        description="Redis connection URL for the geospatial demand index.",
    )

    # Secret used to sign HTTP-only session cookies (Requirement 1.4).
    session_secret: str = Field(
        default="change-me-to-a-long-random-secret",
        alias="SESSION_SECRET",
        description="Secret used to sign session cookies.",
    )

    # CORS origins for the Next.js dev client.
    cors_origins: str = Field(
        default="http://localhost:3000",
        alias="CORS_ORIGINS",
        description="Comma-separated list of allowed CORS origins.",
    )

    # Expiry sweep scheduler (Requirements 3.4, 3.5, 9.4). The sweep is the
    # background task that transitions unmatched, window-expired SCANNING
    # returns to EXPIRED and auto-routes them. It is opt-in so tests and tooling
    # don't spin up a background loop; the sub-second cadence satisfies the
    # "within 1 second of detection" bound (Requirement 3.4).
    expiry_sweep_enabled: bool = Field(
        default=False,
        alias="EXPIRY_SWEEP_ENABLED",
        description="Start the background expiry sweep on app startup.",
    )
    expiry_sweep_interval_seconds: float = Field(
        default=0.5,
        alias="EXPIRY_SWEEP_INTERVAL_SECONDS",
        description="Cadence of the background expiry sweep, in seconds.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse the comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the environment is read once."""
    return Settings()

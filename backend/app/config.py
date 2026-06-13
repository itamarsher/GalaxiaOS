"""Application settings, loaded from the environment (prefix ``ABOS_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ABOS_", env_file=".env", extra="ignore")

    # Infra
    database_url: str = "postgresql+asyncpg://abos:abos@localhost:5432/abos"
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Envelope encryption: 32-byte master key, base64url-encoded.
    master_key: str = ""

    # Runtime safety caps (circuit breakers)
    max_task_depth: int = 4
    max_tasks_per_run: int = 200
    max_tasks_per_agent_window: int = 30
    max_loop_signature_repeats: int = 3
    max_steps_per_task: int = 12

    # Model defaults per role tier (overridable per-agent via Agent.model_pref)
    model_cheap: str = Field(default="claude-haiku-4-5")
    model_planner: str = Field(default="claude-sonnet-4-6")
    model_strategic: str = Field(default="claude-opus-4-8")

    # Budget OS / Copilot
    runway_alert_days: float = 14.0  # raise a decision request below this runway
    roi_pause_floor: float = 0.05  # reputation.roi below this is "low ROI"
    digest_hour_utc: int = 13  # daily digest cron hour
    runway_recompute_minute: int = 0  # hourly runway recompute


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

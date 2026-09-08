from __future__ import annotations

import os
from dataclasses import dataclass


def _boolean(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_host: str = os.getenv("DATABASE_HOST", "127.0.0.1")
    database_port: int = int(os.getenv("DATABASE_PORT", "5432"))
    database_name: str = os.getenv("DATABASE_NAME", "siligent_scheduler")
    database_user: str = os.getenv("DATABASE_USER", "siligent_scheduler")
    database_password: str = os.getenv("DATABASE_PASSWORD", "")
    practice_name: str = os.getenv("PRACTICE_NAME", "Siligent Dental")
    practice_timezone: str = os.getenv("PRACTICE_TIMEZONE", "America/New_York")
    scheduling_horizon_days: int = int(os.getenv("SCHEDULING_HORIZON_DAYS", "365"))
    bootstrap_admin_username: str = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    session_hours: int = int(os.getenv("SESSION_HOURS", "8"))
    cookie_secure: bool = _boolean("COOKIE_SECURE", True)
    local_model_enabled: bool = _boolean("LOCAL_MODEL_ENABLED", False)
    local_model_url: str = os.getenv(
        "LOCAL_MODEL_URL", "http://host.docker.internal:11434/api/generate"
    )
    local_model_id: str = os.getenv("LOCAL_MODEL_ID", "qwen3.5:4b")
    calibration_min_samples: int = int(os.getenv("CALIBRATION_MIN_SAMPLES", "20"))
    migration_dir: str = os.getenv("MIGRATION_DIR", "/app/database/migrations")


settings = Settings()

"""Application settings for GhostBusters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str = os.getenv("SERVICE_NAME", "ghostbusters")
    static_dir: Path = Path(os.getenv("STATIC_DIR", "static"))
    database_url: str | None = os.getenv("DATABASE_URL")
    redis_url: str | None = os.getenv("REDIS_URL")
    auto_create_schema: bool = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() in {"1", "true", "yes"}
    conftest_enabled: bool = os.getenv("CONFTEST_ENABLED", "true").lower() in {"1", "true", "yes"}
    conftest_executable: str = os.getenv("CONFTEST_EXECUTABLE", "conftest")
    conftest_policy_dir: Path = Path(os.getenv("CONFTEST_POLICY_DIR", "policies"))
    conftest_timeout_seconds: float = float(os.getenv("CONFTEST_TIMEOUT_SECONDS", "5"))
    minimum_policy_confidence: float = float(os.getenv("MINIMUM_POLICY_CONFIDENCE", "0.70"))
    external_retry_enabled: bool = os.getenv("EXTERNAL_RETRY_ENABLED", "true").lower() in {"1", "true", "yes"}
    external_retry_max_attempts: int = int(os.getenv("EXTERNAL_RETRY_MAX_ATTEMPTS", "3"))
    external_retry_initial_delay_seconds: float = float(os.getenv("EXTERNAL_RETRY_INITIAL_DELAY_SECONDS", "0.25"))
    external_retry_multiplier: float = float(os.getenv("EXTERNAL_RETRY_MULTIPLIER", "2"))
    external_retry_max_delay_seconds: float = float(os.getenv("EXTERNAL_RETRY_MAX_DELAY_SECONDS", "2"))
    external_retry_jitter_seconds: float = float(os.getenv("EXTERNAL_RETRY_JITTER_SECONDS", "0.10"))
    external_call_timeout_seconds: float = float(os.getenv("EXTERNAL_CALL_TIMEOUT_SECONDS", "5"))


settings = Settings()


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
    ai_enabled: bool = os.getenv("AI_ENABLED", "false").lower() in {"1", "true", "yes"}
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    gemini_fallback_model: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    gemini_api_version: str = os.getenv("GEMINI_API_VERSION", "v1")
    gemini_timeout_seconds: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "10"))
    gemini_max_planning_steps: int = int(os.getenv("GEMINI_MAX_PLANNING_STEPS", "6"))
    gemini_temperature: float = float(os.getenv("GEMINI_TEMPERATURE", "0.1"))
    ai_deterministic_fallback_enabled: bool = os.getenv(
        "AI_DETERMINISTIC_FALLBACK_ENABLED", "true"
    ).lower() in {"1", "true", "yes"}
    cloud_hunt_candidate_threshold: float = float(os.getenv("CLOUD_HUNT_CANDIDATE_THRESHOLD", "0.45"))
    cloud_hunt_high_confidence_threshold: float = float(os.getenv("CLOUD_HUNT_HIGH_CONFIDENCE_THRESHOLD", "0.75"))
    cloud_hunt_resource_age_days: int = int(os.getenv("CLOUD_HUNT_RESOURCE_AGE_DAYS", "60"))
    cloud_hunt_activity_lookback_days: int = int(os.getenv("CLOUD_HUNT_ACTIVITY_LOOKBACK_DAYS", "30"))
    cloud_hunt_utilization_lookback_days: int = int(os.getenv("CLOUD_HUNT_UTILIZATION_LOOKBACK_DAYS", "14"))
    cloud_hunt_low_cpu_threshold: float = float(os.getenv("CLOUD_HUNT_LOW_CPU_THRESHOLD", "10"))
    cloud_hunt_enabled: bool = os.getenv("CLOUD_HUNT_ENABLED", "true").lower() in {"1", "true", "yes"}


settings = Settings()


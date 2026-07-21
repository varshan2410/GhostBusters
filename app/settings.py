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


settings = Settings()


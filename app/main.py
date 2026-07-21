"""FastAPI application entrypoint for GhostBusters."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.models import HealthResponse
from app.settings import settings


app = FastAPI(title="GhostBusters", version="0.1.0")
static_path = Path(__file__).resolve().parent.parent / settings.static_dir


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)


@app.get("/")
def home() -> FileResponse:
    index_path = static_path / "index.html"
    return FileResponse(index_path)

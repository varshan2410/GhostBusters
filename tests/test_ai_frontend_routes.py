from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_frontend_exposes_actual_planning_mode_and_ai_boundary_copy() -> None:
    root = client.get("/").text
    script = client.get("/static/app.js").text
    assert "Planning:" in root
    assert "Gemini proposed investigation steps" in script
    assert "Mock Gemini proposed" in script
    assert "Gemini was unavailable or disabled" in script
    assert "Every proposed action is validated by deterministic safety rules" in script
    assert "[object Object]" not in root + script

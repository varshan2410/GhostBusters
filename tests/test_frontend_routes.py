from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_serves_agent_console() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "GhostBusters" in response.text
    assert "Simple View" in response.text
    assert "Technical Audit" in response.text
    assert 'id="simple-view"' in response.text
    assert 'id="technical-view" hidden' in response.text
    assert "/static/app.js?v=judge-v2" in response.text
    assert "/static/styles.css?v=judge-v2" in response.text


def test_root_explains_objective_and_entry_modes_accurately() -> None:
    response = client.get("/")

    assert "Investigation objective" in response.text
    assert "explicit FinOps and safety rules" in response.text
    assert "Demo mode uses prepared Terraform pull-request fixtures" in response.text
    assert "GitHub pull-request webhook" in response.text
    assert "pull request is opened or updated" in response.text
    assert "High-level goal" not in response.text
    assert "chatbot" not in response.text.lower()


def test_css_asset_served() -> None:
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--bg" in response.text
    assert ".stage-list" in response.text
    assert "max-width: 1500px" not in response.text


def test_javascript_asset_served() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "fetch" in response.text
    assert "stageDefinitions" in response.text
    assert "safeObject" in response.text
    assert "ensureCompatibleDom" in response.text
    assert "[object Object]" not in response.text

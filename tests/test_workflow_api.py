from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from core.webhook_dedup import NoopWebhookDeduplicator


client = TestClient(app)


def setup_function() -> None:
    # API unit tests must not depend on a live Redis service.
    main_module.webhook_deduplicator = NoopWebhookDeduplicator()
    client.post("/api/reset")


def test_workflow_api_start_get_approve_and_reset() -> None:
    response = client.post("/api/runs", json={"goal": "reduce cost", "scenario_name": "safe"})
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "pending_human_review"

    fetched = client.get(f"/api/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == run["id"]

    approved = client.post(
        f"/api/runs/{run['id']}/review",
        json={"action": "approve", "reviewer": "varsha", "comment": "approved"},
    )
    assert approved.status_code == 201
    assert approved.json()["status"] == "pr_created"
    assert approved.json()["mock_pr"]["monthly_savings"] == 70

    reset = client.post("/api/reset")
    assert reset.status_code == 200
    assert client.get("/api/runs").json() == []


def test_workflow_api_invalid_states_and_missing_resources() -> None:
    blocked = client.post("/api/runs", json={"goal": "check", "scenario_name": "destructive"}).json()
    approval = client.post(
        f"/api/runs/{blocked['id']}/review",
        json={"action": "approve", "reviewer": "varsha"},
    )
    assert approval.status_code == 409

    missing = client.post("/api/runs", json={"goal": "x", "scenario_name": "nope"})
    assert missing.status_code == 404


def test_workflow_api_request_context_modify_reject_and_webhook() -> None:
    evidence_needed = client.post(
        "/api/runs",
        json={"goal": "need evidence", "scenario_name": "missing_evidence"},
    ).json()
    requested = client.post(
        f"/api/runs/{evidence_needed['id']}/review",
        json={"action": "request_evidence", "reviewer": "r", "requested_sources": ["pricing"]},
    )
    assert requested.status_code == 200
    assert requested.json()["decision_record"]["tool_executions"][-1]["tool_name"] == "pricing"

    context = client.post(
        f"/api/runs/{evidence_needed['id']}/review",
        json={"action": "add_context", "reviewer": "r", "human_context": "manual note"},
    )
    assert context.status_code == 200
    assert any(item["source"] == "human_review" for item in context.json()["decision_record"]["evidence"])

    safe = client.post("/api/runs", json={"goal": "reduce", "scenario_name": "safe"}).json()
    modified = client.post(
        f"/api/runs/{safe['id']}/review",
        json={"action": "modify", "reviewer": "r", "modified_action": "schedule"},
    )
    assert modified.status_code == 200
    assert modified.json()["decision_record"]["preferred_action"] == "schedule"

    rejected = client.post(
        f"/api/runs/{modified.json()['id']}/review",
        json={"action": "reject", "reviewer": "r", "comment": "not now"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    webhook = client.post(
        "/webhooks/github",
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "delivery-1"},
        json={"action": "opened", "goal": "webhook goal", "scenario_name": "safe"},
    )
    duplicate = client.post(
        "/webhooks/github",
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "delivery-1"},
        json={"action": "opened", "goal": "webhook goal", "scenario_name": "safe"},
    )
    assert webhook.status_code == 201
    assert duplicate.status_code == 200
    assert webhook.json()["run"]["id"] == duplicate.json()["run"]["id"]


def test_workflow_api_webhook_unsupported_and_missing_delivery() -> None:
    unsupported_event = client.post(
        "/webhooks/github",
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "delivery-2"},
        json={},
    )
    assert unsupported_event.json()["status"] == "ignored"

    unsupported_action = client.post(
        "/webhooks/github",
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "delivery-3"},
        json={"action": "closed"},
    )
    assert unsupported_action.json()["status"] == "ignored"

    missing_delivery = client.post(
        "/webhooks/github",
        headers={"X-GitHub-Event": "pull_request"},
        json={"action": "opened"},
    )
    assert missing_delivery.status_code == 422


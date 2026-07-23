from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import app.main as main_module
from app.models import StartRunRequest
from app.settings import Settings
from core.webhook_dedup import NoopWebhookDeduplicator


class FakeGitHub:
    def get_pull_request(self, owner, repo, number):
        return {"number": number, "html_url": "https://github.test/demo/infra/pull/42", "title": "Resize staging", "user": {"login": "dev"}, "head": {"ref": "resize", "sha": "head-sha"}, "base": {"ref": "main", "sha": "base-sha"}}
    def list_pull_request_files(self, owner, repo, number):
        return [{"filename": "infra/main.tf", "status": "modified", "patch": '-  instance_type = "m5.large"\n+  instance_type = "m5.xlarge"'}, {"filename": "README.md", "status": "modified"}]
    def get_file_content(self, owner, repo, path, ref):
        return {"content": 'resource "aws_instance" "app" {\n  instance_type = "m5.xlarge"\n}\n', "sha": "file-sha"}


def signed_request(client: TestClient, payload: dict, secret: str, delivery: str = "delivery-real"):
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhooks/github", content=body, headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": delivery, "X-Hub-Signature-256": signature})


def test_valid_signature_allowlist_and_duplicate(monkeypatch) -> None:
    secret = "unit-test-webhook-secret"
    config = Settings(github_integration_enabled=True, github_webhook_secret=secret, github_allowed_repositories=("demo/infra",))
    monkeypatch.setattr(main_module, "settings", config)
    monkeypatch.setattr(main_module.workflow_service, "github_client", FakeGitHub())
    monkeypatch.setattr(main_module, "webhook_deduplicator", NoopWebhookDeduplicator())
    client = TestClient(main_module.app)
    client.post("/api/reset")
    payload = {"action": "opened", "number": 42, "repository": {"full_name": "demo/infra"}, "pull_request": {"number": 42}}
    first = signed_request(client, payload, secret)
    duplicate = signed_request(client, payload, secret)
    assert first.status_code == 201
    run = first.json()["run"]
    assert run["source_type"] == "terraform_pr"
    assert run["github_source"]["repository"] == "demo/infra"
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["run"]["id"] == run["id"]

    matching_reviews = [
        review for review in client.get("/api/reviews").json()
        if review["id"] == run["id"]
    ]
    assert len(matching_reviews) == 1
    review = matching_reviews[0]
    assert review["source_type"] == "terraform_pr"
    assert review["source_reference"] == "https://github.test/demo/infra/pull/42"
    assert review["repository"] == "demo/infra"
    assert review["pull_request_number"] == 42
    assert review["head_branch"] == "resize"
    assert review["base_branch"] == "main"
    assert review["commit_sha"] == "head-sha"
    assert review["terraform_address"] == "aws_instance.app"
    assert review["candidate"]["address"] == "aws_instance.app"


def test_invalid_missing_signature_and_disallowed_repository(monkeypatch) -> None:
    secret = "unit-test-webhook-secret"
    config = Settings(github_integration_enabled=True, github_webhook_secret=secret, github_allowed_repositories=("demo/infra",))
    monkeypatch.setattr(main_module, "settings", config)
    monkeypatch.setattr(main_module.workflow_service, "github_client", FakeGitHub())
    client = TestClient(main_module.app)
    payload = {"action": "opened", "number": 42, "repository": {"full_name": "other/repo"}, "pull_request": {"number": 42}}
    assert client.post("/webhooks/github", json=payload, headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "x"}).status_code == 401
    assert signed_request(client, payload, secret, "y").status_code == 403


def test_repository_webhook_cannot_fall_back_to_manual_demo(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", Settings(github_integration_enabled=False))
    client = TestClient(main_module.app)
    payload = {
        "action": "reopened",
        "number": 42,
        "repository": {"full_name": "demo/infra"},
        "pull_request": {"number": 42},
    }
    response = client.post(
        "/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "disabled-real-delivery",
        },
    )
    assert response.status_code == 503
    assert main_module.workflow_service.find_run_by_idempotency("disabled-real-delivery") is None


def test_authenticated_redelivery_repairs_legacy_review_in_place(monkeypatch) -> None:
    class CachedLegacyDelivery:
        def __init__(self) -> None:
            self.run_id = None

        def get_run_id(self, delivery_id):
            return self.run_id

        def remember(self, delivery_id, run_id):
            self.run_id = run_id
            return True

    secret = "unit-test-webhook-secret"
    config = Settings(
        github_integration_enabled=True,
        github_webhook_secret=secret,
        github_allowed_repositories=("demo/infra",),
    )
    monkeypatch.setattr(main_module, "settings", config)
    monkeypatch.setattr(main_module.workflow_service, "github_client", FakeGitHub())
    cached_delivery = CachedLegacyDelivery()
    monkeypatch.setattr(main_module, "webhook_deduplicator", cached_delivery)
    client = TestClient(main_module.app)
    client.post("/api/reset")
    legacy, _ = main_module.workflow_service.start_run(
        StartRunRequest(
            goal="Analyze a Terraform pull request for safe FinOps remediation.",
            scenario_name="safe",
            idempotency_key="legacy-webhook-delivery",
        )
    )
    cached_delivery.remember("legacy-webhook-delivery", legacy.id)
    payload = {
        "action": "reopened",
        "number": 42,
        "repository": {"full_name": "demo/infra"},
        "pull_request": {"number": 42},
    }
    response = signed_request(
        client, payload, secret, delivery="legacy-webhook-delivery"
    )
    assert response.status_code == 200
    repaired = response.json()["run"]
    assert repaired["id"] == str(legacy.id)
    assert repaired["source_type"] == "terraform_pr"
    assert repaired["github_source"]["repository"] == "demo/infra"
    assert len(main_module.workflow_service.list_runs()) == 1

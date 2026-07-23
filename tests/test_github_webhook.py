from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import app.main as main_module
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
    assert first.json()["run"]["github_source"]["repository"] == "demo/infra"
    assert duplicate.json()["status"] == "duplicate"


def test_invalid_missing_signature_and_disallowed_repository(monkeypatch) -> None:
    secret = "unit-test-webhook-secret"
    config = Settings(github_integration_enabled=True, github_webhook_secret=secret, github_allowed_repositories=("demo/infra",))
    monkeypatch.setattr(main_module, "settings", config)
    monkeypatch.setattr(main_module.workflow_service, "github_client", FakeGitHub())
    client = TestClient(main_module.app)
    payload = {"action": "opened", "number": 42, "repository": {"full_name": "other/repo"}, "pull_request": {"number": 42}}
    assert client.post("/webhooks/github", json=payload, headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "x"}).status_code == 401
    assert signed_request(client, payload, secret, "y").status_code == 403

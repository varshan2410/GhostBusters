from __future__ import annotations

import base64

import httpx
import pytest

from integrations.github_client import GitHubAPIError, GitHubClient


def client_for(handler) -> GitHubClient:
    return GitHubClient("secret-token", client=httpx.Client(base_url="https://api.github.test", transport=httpx.MockTransport(handler)))


def test_reads_pr_files_and_content_without_exposing_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-token"
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[{"filename": "main.tf"}])
        if "/contents/" in request.url.path:
            return httpx.Response(200, json={"content": base64.b64encode(b"resource {}\n").decode(), "sha": "file-sha"})
        return httpx.Response(200, json={"number": 42})
    client = client_for(handler)
    assert client.get_pull_request("demo", "infra", 42)["number"] == 42
    assert client.list_pull_request_files("demo", "infra", 42)[0]["filename"] == "main.tf"
    assert client.get_file_content("demo", "infra", "main.tf", "head")["content"] == "resource {}\n"


def test_api_errors_and_timeouts_are_sanitized() -> None:
    failing = client_for(lambda request: httpx.Response(403, json={"message": "token secret-token rejected"}))
    with pytest.raises(GitHubAPIError) as exc:
        failing.get_pull_request("demo", "infra", 42)
    assert "secret-token" not in str(exc.value)
    assert exc.value.category == "authentication"

    def timeout(request):
        raise httpx.ReadTimeout("secret-token", request=request)
    with pytest.raises(GitHubAPIError, match="timed out"):
        client_for(timeout).get_pull_request("demo", "infra", 42)

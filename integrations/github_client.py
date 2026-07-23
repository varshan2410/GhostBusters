"""Minimal GitHub REST client with sanitized failures and write-once operations."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx


class GitHubAPIError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com", timeout_seconds: float = 10, client: httpx.Client | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        self._client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)
        self._client.headers.update(headers)

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None, retry_read: bool = False) -> Any:
        attempts = 2 if retry_read else 1
        for attempt in range(attempts):
            try:
                response = self._client.request(method, path, json=json)
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    continue
                raise GitHubAPIError("timeout", "GitHub request timed out.") from exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if retry_read and status >= 500 and attempt + 1 < attempts:
                    continue
                category = "authentication" if status in {401, 403} else "not_found" if status == 404 else "api_error"
                raise GitHubAPIError(category, f"GitHub request failed safely with HTTP {status}.") from exc
            except httpx.HTTPError as exc:
                raise GitHubAPIError("connection", "GitHub could not be reached safely.") from exc
        raise GitHubAPIError("api_error", "GitHub request failed safely.")

    @staticmethod
    def _repo(owner: str, repo: str) -> str:
        return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._request("GET", f"{self._repo(owner, repo)}/pulls/{number}", retry_read=True)

    def list_pull_request_files(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"{self._repo(owner, repo)}/pulls/{number}/files?per_page=100", retry_read=True)

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> dict[str, Any]:
        payload = self._request("GET", f"{self._repo(owner, repo)}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}", retry_read=True)
        content = base64.b64decode(payload.get("content", "")).decode("utf-8")
        return {"content": content, "sha": payload.get("sha"), "path": payload.get("path", path)}

    def get_branch(self, owner: str, repo: str, branch: str) -> dict[str, Any]:
        return self._request("GET", f"{self._repo(owner, repo)}/branches/{quote(branch, safe='')}", retry_read=True)

    def create_branch(self, owner: str, repo: str, new_branch: str, source_sha: str) -> dict[str, Any]:
        return self._request("POST", f"{self._repo(owner, repo)}/git/refs", json={"ref": f"refs/heads/{new_branch}", "sha": source_sha})

    def update_or_create_file(self, owner: str, repo: str, branch: str, path: str, content: str, message: str, existing_sha: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch}
        if existing_sha:
            payload["sha"] = existing_sha
        return self._request("PUT", f"{self._repo(owner, repo)}/contents/{quote(path, safe='/')}", json=payload)

    def create_pull_request(self, owner: str, repo: str, title: str, body: str, head: str, base: str) -> dict[str, Any]:
        return self._request("POST", f"{self._repo(owner, repo)}/pulls", json={"title": title, "body": body, "head": head, "base": base})

    def list_open_pull_requests(self, owner: str, repo: str, head: str) -> list[dict[str, Any]]:
        return self._request("GET", f"{self._repo(owner, repo)}/pulls?state=open&head={quote(head, safe=':')}", retry_read=True)

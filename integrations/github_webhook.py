"""GitHub webhook validation helpers."""

from __future__ import annotations

import hashlib
import hmac


class GitHubWebhookError(Exception):
    pass


def verify_signature(body: bytes, signature: str | None, secret: str | None) -> bool:
    if not signature or not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def repository_allowed(repository: str, allowed_repositories: tuple[str, ...]) -> bool:
    normalized = repository.strip().lower()
    return bool(normalized and normalized in allowed_repositories)

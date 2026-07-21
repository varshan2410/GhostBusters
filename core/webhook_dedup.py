"""Redis-backed GitHub webhook delivery deduplication."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError


class WebhookDeduplicator(Protocol):
    def get_run_id(self, delivery_id: str) -> UUID | None: ...
    def remember(self, delivery_id: str, run_id: UUID) -> None: ...


class NoopWebhookDeduplicator:
    def get_run_id(self, delivery_id: str) -> UUID | None:
        return None

    def remember(self, delivery_id: str, run_id: UUID) -> None:
        return None


class RedisWebhookDeduplicator:
    def __init__(self, redis_url: str, ttl_seconds: int = 86400) -> None:
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def get_run_id(self, delivery_id: str) -> UUID | None:
        try:
            value = self.client.get(self._key(delivery_id))
            return UUID(value) if value else None
        except (RedisError, ValueError):
            return None

    def remember(self, delivery_id: str, run_id: UUID) -> None:
        try:
            self.client.set(self._key(delivery_id), str(run_id), ex=self.ttl_seconds)
        except RedisError:
            # PostgreSQL's unique idempotency key remains the durable fallback.
            return None

    @staticmethod
    def _key(delivery_id: str) -> str:
        return f"ghostbusters:webhook:{delivery_id}"

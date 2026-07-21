"""Redis-backed GitHub webhook delivery deduplication."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from app.settings import settings
from core.retry import RetryConfig, RetryExecutor


class WebhookDeduplicator(Protocol):
    def get_run_id(self, delivery_id: str) -> UUID | None: ...
    def remember(self, delivery_id: str, run_id: UUID) -> None: ...


class NoopWebhookDeduplicator:
    def get_run_id(self, delivery_id: str) -> UUID | None:
        return None

    def remember(self, delivery_id: str, run_id: UUID) -> None:
        return None


class RedisWebhookDeduplicator:
    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86400,
        retry_executor: RetryExecutor | None = None,
    ) -> None:
        self.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=settings.external_call_timeout_seconds,
            socket_connect_timeout=settings.external_call_timeout_seconds,
        )
        self.ttl_seconds = ttl_seconds
        self.retry_executor = retry_executor or RetryExecutor(
            RetryConfig.from_settings(),
            retryable_exceptions=(RedisConnectionError, RedisTimeoutError),
        )

    def get_run_id(self, delivery_id: str) -> UUID | None:
        execution = self._executor().execute(
            "redis_webhook_lookup",
            lambda: self.client.get(self._key(delivery_id)),
            idempotent=True,
        )
        if not execution.result.success:
            return None
        try:
            value = execution.value
            return UUID(value) if value else None
        except (RedisError, ValueError):
            return None

    def remember(self, delivery_id: str, run_id: UUID) -> None:
        self._executor().execute(
            "redis_webhook_store",
            lambda: self.client.set(
                self._key(delivery_id), str(run_id), ex=self.ttl_seconds
            ),
            idempotent=True,
        )
        # PostgreSQL's unique idempotency key remains the durable fallback.
        return None

    def _executor(self) -> RetryExecutor:
        # getattr preserves compatibility with lightweight test doubles built via __new__.
        return getattr(
            self,
            "retry_executor",
            RetryExecutor(
                RetryConfig.from_settings(),
                retryable_exceptions=(RedisConnectionError, RedisTimeoutError),
            ),
        )

    @staticmethod
    def _key(delivery_id: str) -> str:
        return f"ghostbusters:webhook:{delivery_id}"

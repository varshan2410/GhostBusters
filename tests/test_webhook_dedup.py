from __future__ import annotations

from uuid import uuid4

from redis.exceptions import RedisError
from redis.exceptions import ConnectionError as RedisConnectionError

from core.retry import RetryConfig, RetryExecutor
from core.webhook_dedup import NoopWebhookDeduplicator, RedisWebhookDeduplicator


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.expiries[key] = ex


class FailingRedis:
    def get(self, key: str) -> str | None:
        raise RedisError("unavailable")

    def set(self, key: str, value: str, ex: int) -> None:
        raise RedisError("unavailable")


def deduplicator_with(client: object) -> RedisWebhookDeduplicator:
    deduplicator = RedisWebhookDeduplicator.__new__(RedisWebhookDeduplicator)
    deduplicator.client = client  # type: ignore[assignment]
    deduplicator.ttl_seconds = 60
    return deduplicator


def test_redis_deduplicator_remembers_delivery_with_ttl() -> None:
    client = FakeRedis()
    deduplicator = deduplicator_with(client)
    run_id = uuid4()

    assert deduplicator.get_run_id("delivery-1") is None
    deduplicator.remember("delivery-1", run_id)

    assert deduplicator.get_run_id("delivery-1") == run_id
    assert client.expiries["ghostbusters:webhook:delivery-1"] == 60


def test_redis_failure_falls_back_without_breaking_webhook() -> None:
    deduplicator = deduplicator_with(FailingRedis())

    assert deduplicator.get_run_id("delivery-2") is None
    deduplicator.remember("delivery-2", uuid4())


def test_noop_deduplicator_is_safe_without_redis_configuration() -> None:
    deduplicator = NoopWebhookDeduplicator()

    assert deduplicator.get_run_id("delivery-3") is None
    deduplicator.remember("delivery-3", uuid4())


def test_redis_temporary_failure_is_retried_without_real_sleep() -> None:
    class FlakyRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def get(self, key: str) -> str | None:
            self.calls += 1
            if self.calls == 1:
                raise RedisConnectionError("temporary")
            return super().get(key)

    client = FlakyRedis()
    run_id = uuid4()
    client.values["ghostbusters:webhook:delivery-4"] = str(run_id)
    deduplicator = deduplicator_with(client)
    deduplicator.retry_executor = RetryExecutor(
        RetryConfig(
            max_attempts=2,
            initial_delay_seconds=0,
            max_delay_seconds=0,
            jitter_seconds=0,
        ),
        sleep=lambda delay: None,
        retryable_exceptions=(RedisConnectionError,),
    )

    assert deduplicator.get_run_id("delivery-4") == run_id
    assert client.calls == 2

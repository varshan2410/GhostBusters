from __future__ import annotations

from uuid import uuid4

from redis.exceptions import RedisError

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

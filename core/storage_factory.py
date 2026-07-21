"""Build storage adapters from environment-backed application settings."""

from app.settings import settings
from core.postgres_run_store import PostgresRunStore
from core.run_store import InMemoryRunStore, RunStore
from core.webhook_dedup import NoopWebhookDeduplicator, RedisWebhookDeduplicator, WebhookDeduplicator


def build_run_store() -> RunStore:
    if settings.database_url:
        return PostgresRunStore(settings.database_url, ensure_schema=settings.auto_create_schema)
    return InMemoryRunStore()


def build_webhook_deduplicator() -> WebhookDeduplicator:
    if settings.redis_url:
        return RedisWebhookDeduplicator(settings.redis_url)
    return NoopWebhookDeduplicator()

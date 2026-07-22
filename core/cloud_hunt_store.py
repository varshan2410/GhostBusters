"""Small PostgreSQL persistence boundary for Cloud Hunt records."""

from __future__ import annotations

import json
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from app.models import CloudHuntRun, ReviewCase


class CloudHuntPersistence(Protocol):
    def save_hunt(self, hunt: CloudHuntRun) -> None: ...
    def save_case(self, case: ReviewCase) -> None: ...
    def list_hunts(self) -> list[CloudHuntRun]: ...
    def list_cases(self) -> list[ReviewCase]: ...
    def clear(self) -> None: ...


class PostgresCloudHuntPersistence:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.ensure_schema()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS cloud_hunts (id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL);
                CREATE TABLE IF NOT EXISTS cloud_review_cases (id UUID PRIMARY KEY, updated_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL);
                CREATE INDEX IF NOT EXISTS cloud_review_cases_status_idx ON cloud_review_cases ((payload->>'status'));
            """)

    def save_hunt(self, hunt: CloudHuntRun) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO cloud_hunts (id, created_at, payload) VALUES (%s, %s, %s::jsonb) ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload", (hunt.id, hunt.started_at, json.dumps(hunt.model_dump(mode="json"))))

    def save_case(self, case: ReviewCase) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO cloud_review_cases (id, updated_at, payload) VALUES (%s, %s, %s::jsonb) ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at, payload = EXCLUDED.payload", (case.id, case.updated_at, json.dumps(case.model_dump(mode="json"))))

    def list_hunts(self) -> list[CloudHuntRun]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM cloud_hunts ORDER BY created_at").fetchall()
        return [CloudHuntRun.model_validate(row["payload"]) for row in rows]

    def list_cases(self) -> list[ReviewCase]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM cloud_review_cases ORDER BY updated_at").fetchall()
        return [ReviewCase.model_validate(row["payload"]) for row in rows]

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("TRUNCATE cloud_review_cases, cloud_hunts")

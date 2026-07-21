"""PostgreSQL-backed workflow storage with normalized reporting tables."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.rows import dict_row

from app.models import WorkflowRun
from core.run_store import DuplicateIdempotencyKeyError, RunNotFoundError, RunUpdater


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


class PostgresRunStore:
    """Persists each run atomically and projects nested records into tables."""

    def __init__(self, database_url: str, ensure_schema: bool = True) -> None:
        self.database_url = database_url
        if ensure_schema:
            self.ensure_schema()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    def create(self, run: WorkflowRun) -> WorkflowRun:
        try:
            with self._connect() as connection:
                self._write_run(connection, run, insert=True)
                self._replace_children(connection, run)
        except errors.UniqueViolation as exc:
            raise DuplicateIdempotencyKeyError(
                f"Duplicate idempotency key: {run.idempotency_key}"
            ) from exc
        return run.model_copy(deep=True)

    def get(self, run_id: UUID) -> WorkflowRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM workflow_runs WHERE id = %s", (run_id,)
            ).fetchone()
        if row is None:
            raise RunNotFoundError(f"Unknown run: {run_id}")
        return WorkflowRun.model_validate(row["payload"])

    def list(self) -> list[WorkflowRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM workflow_runs ORDER BY created_at"
            ).fetchall()
        return [WorkflowRun.model_validate(row["payload"]) for row in rows]

    def update(self, run_id: UUID, updater: RunUpdater) -> WorkflowRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, version FROM workflow_runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if row is None:
                raise RunNotFoundError(f"Unknown run: {run_id}")
            current = WorkflowRun.model_validate(row["payload"])
            replacement = updater(current.model_copy(deep=True)) if callable(updater) else updater
            replacement.version = int(row["version"]) + 1
            self._write_run(connection, replacement, insert=False)
            self._replace_children(connection, replacement)
        return replacement.model_copy(deep=True)

    def find_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM workflow_runs WHERE idempotency_key = %s", (key,)
            ).fetchone()
        return WorkflowRun.model_validate(row["payload"]) if row else None

    def delete_all(self) -> None:
        with self._connect() as connection:
            connection.execute("TRUNCATE workflow_runs CASCADE")

    def _write_run(self, connection: psycopg.Connection, run: WorkflowRun, insert: bool) -> None:
        payload = json.dumps(run.model_dump(mode="json"))
        if insert:
            connection.execute(
                """
                INSERT INTO workflow_runs
                    (id, goal, scenario_name, status, created_at, updated_at,
                     version, idempotency_key, error, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run.id, run.goal, run.scenario_name, run.status, run.created_at,
                 run.updated_at, run.version, run.idempotency_key, run.error, payload),
            )
            return
        connection.execute(
            """
            UPDATE workflow_runs
               SET status = %s, updated_at = %s, version = %s, error = %s,
                   payload = %s::jsonb
             WHERE id = %s
            """,
            (run.status, run.updated_at, run.version, run.error, payload, run.id),
        )

    def _replace_children(self, connection: psycopg.Connection, run: WorkflowRun) -> None:
        for table in ("evidence_records", "approvals", "audit_log"):
            connection.execute(f"DELETE FROM {table} WHERE run_id = %s", (run.id,))

        if run.decision_record:
            for item in run.decision_record.evidence:
                connection.execute(
                    """
                    INSERT INTO evidence_records
                        (run_id, resource_id, source, tool_name, claim, freshness_status,
                         reliability, collected_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (run.id, item.resource_id, item.source, item.tool_name, item.claim,
                     item.freshness_status, item.reliability, item.collected_at,
                     json.dumps(item.model_dump(mode="json"))),
                )
        for approval in run.human_reviews:
            connection.execute(
                """
                INSERT INTO approvals (run_id, reviewer, action, comment, created_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run.id, approval.reviewer, approval.action, approval.comment,
                 approval.created_at, json.dumps(approval.model_dump(mode="json"))),
            )
        for event in run.audit_events:
            connection.execute(
                """
                INSERT INTO audit_log
                    (run_id, sequence_number, timestamp, event_type, actor, summary, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run.id, event.sequence_number, event.timestamp, event.event_type,
                 event.actor, event.summary, json.dumps(event.details)),
            )

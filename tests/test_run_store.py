from __future__ import annotations

from uuid import uuid4

import pytest

from app.models import RunStatus, WorkflowRun
from core.run_store import DuplicateIdempotencyKeyError, InMemoryRunStore, RunNotFoundError
from integrations.base import utc_now


def make_run(key: str | None = None) -> WorkflowRun:
    now = utc_now()
    return WorkflowRun(
        id=uuid4(),
        goal="goal",
        scenario_name="safe",
        status=RunStatus.created,
        created_at=now,
        updated_at=now,
        idempotency_key=key,
    )


def test_unknown_run_raises_not_found() -> None:
    store = InMemoryRunStore()
    with pytest.raises(RunNotFoundError):
        store.get(uuid4())


def test_version_increments_on_update() -> None:
    store = InMemoryRunStore()
    run = store.create(make_run())

    updated = store.update(run.id, lambda current: current.model_copy(update={"status": RunStatus.keep}))

    assert updated.version == run.version + 1
    assert updated.status == RunStatus.keep


def test_list_returns_copies_and_reset_clears_runs() -> None:
    store = InMemoryRunStore()
    run = store.create(make_run())
    listed = store.list()
    listed[0].status = RunStatus.failed_safely

    assert store.get(run.id).status == RunStatus.created
    store.delete_all()
    assert store.list() == []


def test_duplicate_idempotency_key_is_prevented() -> None:
    store = InMemoryRunStore()
    store.create(make_run("same"))

    with pytest.raises(DuplicateIdempotencyKeyError):
        store.create(make_run("same"))


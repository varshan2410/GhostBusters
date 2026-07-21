"""Thread-safe in-memory workflow run store."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Protocol
from uuid import UUID

from app.models import WorkflowRun


class RunStoreError(Exception):
    """Base run store error."""


class RunNotFoundError(RunStoreError):
    """Raised when a run id is unknown."""


class DuplicateIdempotencyKeyError(RunStoreError):
    """Raised when an idempotency key already exists."""


RunUpdater = Callable[[WorkflowRun], WorkflowRun] | WorkflowRun


class RunStore(Protocol):
    """Storage boundary used by the workflow service."""

    def create(self, run: WorkflowRun) -> WorkflowRun: ...
    def get(self, run_id: UUID) -> WorkflowRun: ...
    def list(self) -> list[WorkflowRun]: ...
    def update(self, run_id: UUID, updater: RunUpdater) -> WorkflowRun: ...
    def find_by_idempotency_key(self, key: str) -> WorkflowRun | None: ...
    def delete_all(self) -> None: ...


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[UUID, WorkflowRun] = {}
        self._lock = RLock()

    def create(self, run: WorkflowRun) -> WorkflowRun:
        with self._lock:
            if run.idempotency_key and self._find_by_key_unlocked(run.idempotency_key) is not None:
                raise DuplicateIdempotencyKeyError(f"Duplicate idempotency key: {run.idempotency_key}")
            self._runs[run.id] = run.model_copy(deep=True)
            return self._runs[run.id].model_copy(deep=True)

    def get(self, run_id: UUID) -> WorkflowRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFoundError(f"Unknown run: {run_id}")
            return run.model_copy(deep=True)

    def list(self) -> list[WorkflowRun]:
        with self._lock:
            return [run.model_copy(deep=True) for run in self._runs.values()]

    def update(
        self,
        run_id: UUID,
        updater: RunUpdater,
    ) -> WorkflowRun:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                raise RunNotFoundError(f"Unknown run: {run_id}")
            replacement = updater(current.model_copy(deep=True)) if callable(updater) else updater
            replacement.version = current.version + 1
            self._runs[run_id] = replacement.model_copy(deep=True)
            return self._runs[run_id].model_copy(deep=True)

    def find_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        with self._lock:
            run = self._find_by_key_unlocked(key)
            return run.model_copy(deep=True) if run is not None else None

    def delete_all(self) -> None:
        with self._lock:
            self._runs.clear()

    def _find_by_key_unlocked(self, key: str) -> WorkflowRun | None:
        return next((run for run in self._runs.values() if run.idempotency_key == key), None)

"""Audit event helpers for workflow runs."""

from __future__ import annotations

from typing import Any

from app.models import AuditEvent, WorkflowRun
from integrations.base import utc_now


def append_audit_event(
    run: WorkflowRun,
    *,
    event_type: str,
    actor: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> WorkflowRun:
    next_sequence = len(run.audit_events) + 1
    run.audit_events.append(
        AuditEvent(
            sequence_number=next_sequence,
            timestamp=utc_now(),
            event_type=event_type,
            actor=actor,  # type: ignore[arg-type]
            summary=summary,
            details=details or {},
        )
    )
    run.updated_at = utc_now()
    return run


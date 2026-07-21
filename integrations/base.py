"""Shared interfaces and helpers for mock evidence tools."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange


@runtime_checkable
class EvidenceTool(Protocol):
    name: str

    def collect(
        self,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
    ) -> list[EvidenceItem]:
        """Collect evidence for one resource."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_evidence_item(
    *,
    source: str,
    tool_name: str,
    claim: str,
    value: Any,
    resource_id: str,
    freshness_status: str,
    reliability: float,
    metadata: dict[str, Any] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        source=source,
        tool_name=tool_name,
        claim=claim,
        value=value,
        resource_id=resource_id,
        collected_at=utc_now(),
        freshness_status=freshness_status,  # type: ignore[arg-type]
        reliability=reliability,
        metadata=metadata or {},
    )


def unavailable_item(
    *,
    source: str,
    tool_name: str,
    resource_id: str,
    claim: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> EvidenceItem:
    details = dict(metadata or {})
    details["reason"] = reason
    return build_evidence_item(
        source=source,
        tool_name=tool_name,
        claim=claim,
        value=None,
        resource_id=resource_id,
        freshness_status="unavailable",
        reliability=0.0,
        metadata=details,
    )


def as_list(values: Iterable[str] | None) -> list[str]:
    return list(values or [])


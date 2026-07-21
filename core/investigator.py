"""Execute planner-selected evidence tools."""

from __future__ import annotations

from integrations.base import unavailable_item, utc_now
from integrations.registry import ToolRegistry
from app.models import (
    EvidenceItem,
    ExternalCallEvent,
    InvestigationPlan,
    MissingEvidenceRecord,
    ScenarioDefinition,
    TerraformResourceChange,
    ToolExecutionRecord,
)
from core.retry import (
    InvalidEvidenceResponseError,
    InvalidExternalConfigurationError,
    RetryExecutor,
    default_retry_executor,
)


CRITICAL_SOURCES = {"pricing", "utilization", "dependencies"}


def collect_evidence(
    plan: InvestigationPlan,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
    retry_executor: RetryExecutor | None = None,
) -> tuple[list[EvidenceItem], list[ToolExecutionRecord], list[MissingEvidenceRecord]]:
    executor = retry_executor or default_retry_executor
    evidence: list[EvidenceItem] = []
    records: list[ToolExecutionRecord] = []
    missing: list[MissingEvidenceRecord] = []

    for tool_name in plan.selected_tools:
        tool = tool_registry.get(tool_name)
        reason = next(
            (note for note in plan.planning_notes if note.startswith(f"Selected {tool_name}:")),
            "Selected by investigation plan.",
        )
        started_at = utc_now()

        def operation() -> list[EvidenceItem]:
            if tool is None:
                raise InvalidExternalConfigurationError()
            items = tool.collect(scenario, resource)
            if not isinstance(items, list) or not all(isinstance(item, EvidenceItem) for item in items):
                raise InvalidEvidenceResponseError()
            return items

        execution = executor.execute(tool_name, operation, idempotent=True)
        if execution.result.success:
            items = execution.value or []
            evidence.extend(items)
            records.append(
                ToolExecutionRecord(
                    tool_name=tool_name,
                    selected_because=reason,
                    status="completed",
                    started_at=started_at,
                    completed_at=utc_now(),
                    input_summary=f"{resource.address} ({resource.resource_type})",
                    output_summary=f"{len(items)} evidence item(s)",
                    external_call=execution.result,
                )
            )
        else:
            failure = execution.result
            evidence.append(
                unavailable_item(
                    source=tool_name,
                    tool_name=tool_name,
                    resource_id=resource.address,
                    claim=f"{tool_name} evidence unavailable",
                    reason=failure.safe_message,
                    metadata={
                        "failure_category": failure.failure_category,
                        "attempts": failure.attempts,
                        "retryable": failure.retryable,
                        "retry_exhausted": failure.retry_exhausted,
                        "final_failure_type": failure.final_failure_type,
                    },
                )
            )
            records.append(
                ToolExecutionRecord(
                    tool_name=tool_name,
                    selected_because=reason,
                    status="failed",
                    started_at=started_at,
                    completed_at=utc_now(),
                    input_summary=f"{resource.address} ({resource.resource_type})",
                    error=failure.safe_message,
                    external_call=failure,
                )
            )

    for item in evidence:
        if item.freshness_status == "unavailable":
            missing.append(
                MissingEvidenceRecord(
                    source=item.source,
                    claim_needed=item.claim,
                    critical=item.source in CRITICAL_SOURCES,
                    impact="Critical evidence is unavailable." if item.source in CRITICAL_SOURCES else "Context is incomplete.",
                )
            )

    _record_alternative_evidence(evidence, records)
    return evidence, records, missing


def _record_alternative_evidence(
    evidence: list[EvidenceItem],
    records: list[ToolExecutionRecord],
) -> None:
    jira_unavailable = any(
        item.source == "jira" and item.freshness_status == "unavailable" for item in evidence
    )
    git_available = any(
        item.source == "git_activity" and item.freshness_status != "unavailable" for item in evidence
    )
    if not jira_unavailable or not git_available:
        return
    git_record = next(
        (record for record in records if record.tool_name == "git_activity"), None
    )
    if git_record is None or git_record.external_call is None:
        return
    git_record.external_call.events.append(
        ExternalCallEvent(
            event_type="alternative_evidence_selected",
            attempt=git_record.external_call.attempts,
            maximum_attempts=git_record.external_call.attempts,
            elapsed_ms=git_record.external_call.elapsed_ms,
            details={"alternative_for": "jira", "selected_source": "git_activity"},
        )
    )


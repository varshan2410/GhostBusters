"""Execute planner-selected evidence tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
QuestionSummarizer = Callable[[list[EvidenceItem]], "QuestionResolution"]


@dataclass(frozen=True, slots=True)
class QuestionResolution:
    summary: str | None
    missing_fields: tuple[str, ...] = ()


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

    _update_question_resolutions(plan, evidence)
    _record_alternative_evidence(evidence, records)
    return evidence, records, missing


def _update_question_resolutions(
    plan: InvestigationPlan,
    evidence: list[EvidenceItem],
) -> None:
    evidence_by_source: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        evidence_by_source.setdefault(item.source, []).append(item)

    for question in plan.questions:
        if question.status == "skipped":
            continue
        if question.required_evidence_sources and all(
            source in plan.skipped_tools for source in question.required_evidence_sources
        ):
            question.status = "skipped"
            question.resolution_summary = "Planner skipped the required evidence sources for this question."
            continue

        available_items: list[EvidenceItem] = []
        failed_sources: list[str] = []
        incomplete_sources: list[str] = []
        missing_sources: list[str] = []

        for source in question.required_evidence_sources:
            source_items = evidence_by_source.get(source, [])
            if not source_items:
                missing_sources.append(source)
                continue
            usable_items = [item for item in source_items if item.freshness_status != "unavailable"]
            if usable_items:
                available_items.extend(usable_items)
            elif all(item.freshness_status == "unavailable" for item in source_items):
                failed_sources.append(source)
            else:
                incomplete_sources.append(source)

        if not question.required_evidence_sources:
            if question.status == "unresolved" and question.resolution_summary is None:
                question.resolution_summary = "No evidence sources were required for this question."
            continue

        if not available_items:
            if len(failed_sources) == len(question.required_evidence_sources):
                question.status = "failed"
                question.resolution_summary = (
                    "All required evidence sources failed or were unavailable: "
                    f"{', '.join(sorted(failed_sources))}."
                )
            else:
                question.status = "unresolved"
                question.resolution_summary = _missing_summary(
                    failed_sources=failed_sources,
                    incomplete_sources=incomplete_sources,
                    missing_sources=missing_sources,
                )
            continue

        resolution = _summarize_question(question.id, available_items)
        unresolved_sources = sorted(set(failed_sources + incomplete_sources + missing_sources))
        if resolution.summary is not None and not unresolved_sources and not resolution.missing_fields:
            question.status = "resolved"
            question.resolution_summary = resolution.summary
            continue

        question.status = "unresolved"
        if resolution.summary is not None:
            missing_field_text = (
                f" Missing fields: {', '.join(resolution.missing_fields)}."
                if resolution.missing_fields
                else ""
            )
            question.resolution_summary = (
                f"{resolution.summary}{missing_field_text} Still missing: {', '.join(unresolved_sources)}."
                if unresolved_sources
                else f"{resolution.summary}{missing_field_text}"
            )
        else:
            missing_summary = _missing_summary(
                failed_sources=failed_sources,
                incomplete_sources=incomplete_sources,
                missing_sources=missing_sources,
            )
            if resolution.missing_fields:
                question.resolution_summary = (
                    f"{missing_summary} Missing fields: {', '.join(resolution.missing_fields)}."
                )
            else:
                question.resolution_summary = missing_summary


def _missing_summary(
    *,
    failed_sources: list[str],
    incomplete_sources: list[str],
    missing_sources: list[str],
) -> str:
    parts: list[str] = []
    if failed_sources:
        parts.append(f"failed sources: {', '.join(sorted(failed_sources))}")
    if incomplete_sources:
        parts.append(f"incomplete sources: {', '.join(sorted(incomplete_sources))}")
    if missing_sources:
        parts.append(f"missing sources: {', '.join(sorted(missing_sources))}")
    if not parts:
        return "Evidence was collected but did not fully resolve the question."
    return "Evidence remains insufficient: " + "; ".join(parts) + "."


def _summarize_question(question_id: str, evidence: list[EvidenceItem]) -> QuestionResolution:
    summarizers: dict[str, QuestionSummarizer] = {
        "cost_impact": _summarize_cost_impact,
        "utilization": _summarize_utilization,
        "project_context": _summarize_project_context,
        "git_activity": _summarize_git_activity,
        "dependencies": _summarize_dependencies,
    }
    summarizer = summarizers.get(question_id)
    if summarizer is None:
        return QuestionResolution(summary=None)
    return summarizer(evidence)


def _primary_value(evidence: list[EvidenceItem], source: str) -> dict[str, Any] | None:
    item = next(
        (
            candidate for candidate in evidence
            if candidate.source == source
            and candidate.freshness_status != "unavailable"
            and isinstance(candidate.value, dict)
        ),
        None,
    )
    return item.value if item is not None else None


def _missing_fields(value: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in fields if value.get(field) is None)


def _summarize_cost_impact(evidence: list[EvidenceItem]) -> QuestionResolution:
    value = _primary_value(evidence, "pricing")
    if value is None:
        return QuestionResolution(summary=None)
    missing_fields = _missing_fields(value, ("current_monthly_cost", "proposed_monthly_cost"))
    current = value.get("current_monthly_cost")
    proposed = value.get("proposed_monthly_cost")
    currency = value.get("currency", "USD")
    if missing_fields:
        return QuestionResolution(summary=None, missing_fields=missing_fields)
    savings = current - proposed
    return QuestionResolution(
        summary=(
            f"Current monthly cost is {currency} {current}, proposed monthly cost is "
            f"{currency} {proposed}, and estimated monthly savings are {currency} {savings}."
        )
    )


def _summarize_utilization(evidence: list[EvidenceItem]) -> QuestionResolution:
    value = _primary_value(evidence, "utilization")
    if value is None:
        return QuestionResolution(summary=None)
    missing_fields = _missing_fields(value, ("average_cpu_pct", "peak_cpu_pct"))
    average_cpu = value.get("average_cpu_pct")
    peak_cpu = value.get("peak_cpu_pct")
    if missing_fields:
        return QuestionResolution(summary=None, missing_fields=missing_fields)
    headroom_exists = peak_cpu < 70
    return QuestionResolution(
        summary=(
            f"Average CPU is {average_cpu}%, peak CPU is {peak_cpu}%, and rightsizing "
            f"headroom {'exists' if headroom_exists else 'does not exist'}."
        )
    )


def _summarize_project_context(evidence: list[EvidenceItem]) -> QuestionResolution:
    value = _primary_value(evidence, "jira")
    if value is None:
        return QuestionResolution(summary=None)
    missing_fields = _missing_fields(value, ("issue_key", "status"))
    issue_key = value.get("issue_key")
    status = value.get("status")
    if missing_fields or not issue_key:
        return QuestionResolution(summary=None, missing_fields=missing_fields or ("issue_key",))
    return QuestionResolution(summary=f"Jira issue {issue_key} is currently {status}.")


def _summarize_git_activity(evidence: list[EvidenceItem]) -> QuestionResolution:
    value = _primary_value(evidence, "git_activity")
    if value is None:
        return QuestionResolution(summary=None)
    missing_fields = _missing_fields(value, ("recent_commit_count", "days_since_last_commit"))
    recent_commit_count = value.get("recent_commit_count")
    days_since_last_commit = value.get("days_since_last_commit")
    if missing_fields:
        return QuestionResolution(summary=None, missing_fields=missing_fields)
    return QuestionResolution(
        summary=(
            f"Recent commit count is {recent_commit_count}, and the last commit was "
            f"{days_since_last_commit} day(s) ago."
        )
    )


def _summarize_dependencies(evidence: list[EvidenceItem]) -> QuestionResolution:
    value = _primary_value(evidence, "dependencies")
    if value is None:
        return QuestionResolution(summary=None)
    missing_fields = _missing_fields(
        value,
        ("active_downstream_dependencies", "blocking_services", "has_active_dependencies"),
    )
    active = value.get("active_downstream_dependencies")
    blocking = value.get("blocking_services")
    has_active = value.get("has_active_dependencies")
    if missing_fields or not isinstance(active, list) or not isinstance(blocking, list):
        return QuestionResolution(summary=None, missing_fields=missing_fields)
    if has_active:
        return QuestionResolution(
            summary=(
                f"Active downstream dependencies exist: {', '.join(active) or 'none listed'}; "
                f"blocking services: {', '.join(blocking) or 'none'}."
            )
        )
    return QuestionResolution(summary="No active downstream dependencies were found.")


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


"""Execute planner-selected evidence tools."""

from __future__ import annotations

from integrations.base import unavailable_item, utc_now
from integrations.registry import ToolRegistry
from app.models import (
    EvidenceItem,
    InvestigationPlan,
    MissingEvidenceRecord,
    ScenarioDefinition,
    TerraformResourceChange,
    ToolExecutionRecord,
)


CRITICAL_SOURCES = {"pricing", "utilization", "dependencies"}


def collect_evidence(
    plan: InvestigationPlan,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
) -> tuple[list[EvidenceItem], list[ToolExecutionRecord], list[MissingEvidenceRecord]]:
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
        if tool is None:
            records.append(
                ToolExecutionRecord(
                    tool_name=tool_name,
                    selected_because=reason,
                    status="failed",
                    started_at=started_at,
                    completed_at=utc_now(),
                    input_summary=resource.address,
                    error=f"Tool {tool_name} is not registered.",
                )
            )
            evidence.append(
                unavailable_item(
                    source=tool_name,
                    tool_name=tool_name,
                    resource_id=resource.address,
                    claim=f"{tool_name} evidence unavailable",
                    reason="tool not registered",
                )
            )
            continue

        try:
            items = tool.collect(scenario, resource)
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
                )
            )
        except Exception as exc:  # pragma: no cover - explicitly tested with a local failing tool
            evidence.append(
                unavailable_item(
                    source=tool_name,
                    tool_name=tool_name,
                    resource_id=resource.address,
                    claim=f"{tool_name} evidence unavailable",
                    reason=str(exc),
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
                    error=str(exc),
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

    return evidence, records, missing


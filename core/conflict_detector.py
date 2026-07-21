"""Detect deterministic conflicts in collected evidence."""

from __future__ import annotations

from app.models import ConflictRecord, EvidenceItem
from core.evidence_utils import active_dependencies, item_by_source, jira_status, recent_git_activity, utilization_values, value_for


def detect_conflicts(evidence: list[EvidenceItem]) -> list[ConflictRecord]:
    conflicts: list[ConflictRecord] = []
    status = jira_status(evidence)
    avg_cpu, peak_cpu = utilization_values(evidence)

    if status == "completed" and recent_git_activity(evidence):
        conflicts.append(
            ConflictRecord(
                claim="Jira completed but Git activity is recent",
                sources=["jira", "git_activity"],
                values=[value_for(evidence, "jira"), value_for(evidence, "git_activity")],
                severity="high",
                explanation="Completed Jira work conflicts with recent code activity.",
            )
        )

    if status == "inactive" and peak_cpu is not None and peak_cpu >= 75:
        conflicts.append(
            ConflictRecord(
                claim="Jira inactive but utilization is high",
                sources=["jira", "utilization"],
                values=[value_for(evidence, "jira"), value_for(evidence, "utilization")],
                severity="high",
                explanation="Inactive project status conflicts with high observed usage.",
            )
        )

    if avg_cpu is not None and peak_cpu is not None and avg_cpu <= 30 and peak_cpu >= 75:
        conflicts.append(
            ConflictRecord(
                claim="Low average CPU but high peak CPU",
                sources=["utilization"],
                values=[value_for(evidence, "utilization")],
                severity="medium",
                explanation="Average utilization looks low, but peak demand may not have enough headroom.",
            )
        )

    dependency_item = item_by_source(evidence, "dependencies")
    if dependency_item is not None and active_dependencies(evidence):
        conflicts.append(
            ConflictRecord(
                claim="Active dependency risk",
                sources=["dependencies"],
                values=[dependency_item.value],
                severity="high",
                explanation="Dependency evidence shows active downstream consumers.",
            )
        )

    utilization_item = item_by_source(evidence, "utilization")
    if utilization_item is not None and utilization_item.freshness_status == "stale":
        conflicts.append(
            ConflictRecord(
                claim="Stale utilization data used for current recommendation",
                sources=["utilization"],
                values=[utilization_item.value],
                severity="medium",
                explanation="Utilization evidence is stale and should not drive an automated recommendation.",
            )
        )

    return conflicts


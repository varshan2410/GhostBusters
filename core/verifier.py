"""Verifier checks that challenge the preferred action."""

from __future__ import annotations

from app.models import Alternative, ConflictRecord, EvidenceItem, TerraformResourceChange, VerifierFinding
from core.evidence_utils import active_dependencies, item_by_source, monthly_savings, pricing_values, utilization_values


RELIABILITY_THRESHOLD = 0.75
SAVINGS_THRESHOLD = 20.0


def run_verifier(
    resource: TerraformResourceChange,
    evidence: list[EvidenceItem],
    conflicts: list[ConflictRecord],
    preferred: Alternative,
) -> list[VerifierFinding]:
    findings: list[VerifierFinding] = []
    preferred_remediation = preferred.action in {"downsize", "schedule"}
    avg_cpu, peak_cpu = utilization_values(evidence)
    current_cost, proposed_cost = pricing_values(evidence)
    savings = monthly_savings(evidence)
    utilization_item = item_by_source(evidence, "utilization")
    jira_item = item_by_source(evidence, "jira")

    def add(check: str, status: str, severity: str, explanation: str, sources: list[str] | None = None) -> None:
        findings.append(
            VerifierFinding(
                check_name=check,
                status=status,  # type: ignore[arg-type]
                severity=severity,  # type: ignore[arg-type]
                explanation=explanation,
                evidence_sources=sources or [],
            )
        )

    add(
        "production_environment",
        "failed" if preferred_remediation and (resource.environment or "").lower() == "production" else "passed",
        "critical" if preferred_remediation and (resource.environment or "").lower() == "production" else "info",
        "Production resources cannot be automatically remediated." if (resource.environment or "").lower() == "production" else "Resource is non-production.",
        ["terraform"],
    )
    add(
        "terraform_delete_or_replacement",
        "failed" if preferred_remediation and resource.destructive else "passed",
        "critical" if preferred_remediation and resource.destructive else "info",
        "Terraform action contains delete." if resource.destructive else "Terraform action is not destructive.",
        ["terraform"],
    )
    add(
        "active_dependencies",
        "failed" if preferred_remediation and active_dependencies(evidence) else "passed",
        "critical" if preferred_remediation and active_dependencies(evidence) else "info",
        "Active downstream dependencies exist." if active_dependencies(evidence) else "No active dependencies were reported.",
        ["dependencies"],
    )
    add(
        "peak_utilization_headroom",
        "failed" if preferred.action == "downsize" and (peak_cpu is None or peak_cpu >= 70) else "passed",
        "critical" if preferred.action == "downsize" and (peak_cpu is None or peak_cpu >= 70) else "info",
        "Peak utilization lacks safe headroom." if peak_cpu is None or peak_cpu >= 70 else "Peak utilization has safe headroom.",
        ["utilization"],
    )
    add(
        "missing_utilization",
        "failed" if preferred.action == "downsize" and utilization_item is None else "passed",
        "critical" if preferred.action == "downsize" and utilization_item is None else "info",
        "Utilization evidence is missing." if utilization_item is None else "Utilization evidence is present.",
        ["utilization"],
    )
    add(
        "stale_utilization",
        "failed" if preferred.action == "downsize" and utilization_item is not None and utilization_item.freshness_status == "stale" else "passed",
        "high" if preferred.action == "downsize" and utilization_item is not None and utilization_item.freshness_status == "stale" else "info",
        "Utilization evidence is stale." if utilization_item is not None and utilization_item.freshness_status == "stale" else "Utilization evidence is not stale.",
        ["utilization"],
    )
    add(
        "missing_ownership_or_project_context",
        "warning" if jira_item is None else "passed",
        "medium" if jira_item is None else "info",
        "Project context is missing." if jira_item is None else "Project context evidence is present.",
        ["jira"],
    )
    git_conflict = any(conflict.claim == "Jira completed but Git activity is recent" for conflict in conflicts)
    add(
        "jira_git_conflict",
        "failed" if preferred_remediation and git_conflict else "passed",
        "critical" if preferred_remediation and git_conflict else "info",
        "Jira and Git activity conflict." if git_conflict else "No Jira/Git conflict detected.",
        ["jira", "git_activity"],
    )
    add(
        "minimum_monthly_savings",
        "failed" if preferred.action == "downsize" and savings < SAVINGS_THRESHOLD else "passed",
        "high" if preferred.action == "downsize" and savings < SAVINGS_THRESHOLD else "info",
        f"Monthly savings {savings:.2f} are below threshold." if savings < SAVINGS_THRESHOLD else "Monthly savings meet threshold.",
        ["pricing"],
    )
    add(
        "positive_savings",
        "failed" if preferred.action == "downsize" and (current_cost is None or proposed_cost is None or savings <= 0) else "passed",
        "critical" if preferred.action == "downsize" and (current_cost is None or proposed_cost is None or savings <= 0) else "info",
        "Savings are zero, negative, or unavailable." if savings <= 0 else "Savings are positive.",
        ["pricing"],
    )
    add(
        "proposed_instance_type_present",
        "failed" if preferred.action == "downsize" and not resource.proposed_instance_type else "passed",
        "critical" if preferred.action == "downsize" and not resource.proposed_instance_type else "info",
        "Proposed instance type is missing." if not resource.proposed_instance_type else "Proposed instance type is present.",
        ["terraform"],
    )
    low_reliability = [item.source for item in evidence if item.freshness_status != "unavailable" and item.reliability < RELIABILITY_THRESHOLD]
    add(
        "evidence_reliability_threshold",
        "failed" if preferred_remediation and low_reliability else "passed",
        "high" if preferred_remediation and low_reliability else "info",
        f"Evidence reliability below threshold for {', '.join(low_reliability)}." if low_reliability else "Evidence reliability meets threshold.",
        low_reliability,
    )

    return findings


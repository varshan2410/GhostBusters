"""Deterministic hard safety policies."""

from __future__ import annotations

from app.models import (
    Alternative,
    ConflictRecord,
    EvidenceItem,
    MissingEvidenceRecord,
    PolicyResult,
    TerraformResourceChange,
    VerifierFinding,
)
from core.evidence_utils import active_dependencies, monthly_savings, utilization_values


def evaluate_policy(
    resource: TerraformResourceChange,
    evidence: list[EvidenceItem],
    missing_evidence: list[MissingEvidenceRecord],
    preferred: Alternative,
    verifier_findings: list[VerifierFinding] | None = None,
    conflicts: list[ConflictRecord] | None = None,
) -> PolicyResult:
    evaluated_rules = [
        "terraform_delete_blocks_remediation",
        "replacement_containing_delete_blocks_remediation",
        "production_blocks_automated_remediation",
        "active_dependency_prevents_remediation",
        "missing_critical_utilization_prevents_downsizing",
        "high_peak_utilization_prevents_downsizing",
        "positive_savings_required_for_downsizing",
        "human_approval_required_for_remediation",
    ]
    blocking: list[str] = []
    warnings: list[str] = []
    remediation = preferred.action in {"downsize", "schedule"}
    hard_block_action = preferred.action == "blocked"
    context_action = preferred.action == "request_evidence"
    abstain_action = preferred.action == "abstain"

    if hard_block_action and resource.destructive:
        blocking.append("Terraform delete or replacement containing delete blocks remediation.")
    if hard_block_action and (resource.environment or "").lower() == "production":
        blocking.append("Production resource blocks automated remediation.")
    if remediation and resource.destructive:
        blocking.append("Terraform delete or replacement containing delete blocks remediation.")
    if remediation and (resource.environment or "").lower() == "production":
        blocking.append("Production resource blocks automated remediation.")
    if (remediation or abstain_action) and active_dependencies(evidence):
        blocking.append("Active dependency prevents remediation.")

    if preferred.action == "downsize":
        avg_cpu, peak_cpu = utilization_values(evidence)
        if any(item.source == "utilization" and item.critical for item in missing_evidence) or avg_cpu is None or peak_cpu is None:
            blocking.append("Missing critical utilization evidence prevents downsizing.")
        if peak_cpu is not None and peak_cpu >= 70:
            blocking.append("High peak utilization prevents downsizing.")
        if monthly_savings(evidence) <= 0:
            blocking.append("Negative or zero savings prevents downsizing.")

    if verifier_findings:
        if any(item.status == "failed" and item.severity == "critical" for item in verifier_findings):
            blocking.append("Critical verifier failure prevents approval eligibility.")

    if remediation:
        warnings.append("Human approval is mandatory before any remediation action.")

    context_reasons: list[str] = []
    if context_action:
        context_reasons.extend(
            f"Critical missing evidence from {item.source}: {item.claim_needed}"
            for item in missing_evidence
            if item.critical
        )
        context_reasons.extend(
            f"Unresolved {item.severity} conflict: {item.claim}"
            for item in conflicts or []
            if item.severity == "high"
        )
        if not context_reasons:
            context_reasons.append("Additional human context was requested before making a recommendation.")

    if blocking:
        return PolicyResult(
            allowed=False,
            status="blocked",
            blocking_reasons=sorted(set(blocking)),
            warnings=warnings,
            evaluated_rules=evaluated_rules,
            requires_human_approval=False,
        )

    if context_reasons:
        return PolicyResult(
            allowed=False,
            status="needs_human_context",
            blocking_reasons=sorted(set(context_reasons)),
            warnings=warnings,
            evaluated_rules=evaluated_rules,
            requires_human_approval=False,
        )

    return PolicyResult(
        allowed=True,
        status="passed",
        blocking_reasons=[],
        warnings=warnings,
        evaluated_rules=evaluated_rules,
        requires_human_approval=remediation,
    )

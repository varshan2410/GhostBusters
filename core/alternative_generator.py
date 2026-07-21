"""Generate deterministic remediation alternatives."""

from __future__ import annotations

from app.models import Alternative, ConflictRecord, EvidenceItem, MissingEvidenceRecord, TerraformResourceChange
from core.evidence_utils import active_dependencies, item_by_source, jira_status, monthly_savings, pricing_values, recent_git_activity, source_unavailable, utilization_values


LOW_AVG_CPU_THRESHOLD = 30.0
SAFE_PEAK_CPU_THRESHOLD = 70.0


def _score(base: float, rejection_count: int) -> float:
    return max(0.0, min(1.0, base - 0.15 * rejection_count))


def generate_alternatives(
    resource: TerraformResourceChange,
    evidence: list[EvidenceItem],
    missing_evidence: list[MissingEvidenceRecord],
    conflicts: list[ConflictRecord],
) -> list[Alternative]:
    alternatives: list[Alternative] = []
    savings = monthly_savings(evidence)
    _, proposed_cost = pricing_values(evidence)
    avg_cpu, peak_cpu = utilization_values(evidence)
    deps_active = active_dependencies(evidence)
    production = (resource.environment or "").lower() == "production"
    hard_blocked = resource.destructive or production
    high_conflict = any(conflict.severity == "high" for conflict in conflicts)
    critical_missing = any(item.critical for item in missing_evidence)
    utilization_item = item_by_source(evidence, "utilization")
    pricing_available = not source_unavailable(evidence, "pricing")
    utilization_fresh = utilization_item is not None and utilization_item.freshness_status == "fresh"

    alternatives.append(
        Alternative(
            action="keep",
            description="Keep the Terraform change unchanged for now.",
            proposed_instance_type=resource.current_instance_type,
            estimated_monthly_cost=None,
            supporting_evidence=["terraform"],
            risks=["Cost opportunity may remain unrealized."],
            assumptions=["No automated remediation is safer than an unsupported change."],
            eligible=True,
            score=0.35,
        )
    )

    if hard_blocked:
        alternatives.append(
            Alternative(
                action="blocked",
                description="Hard safety policy blocks automated remediation for this resource.",
                proposed_instance_type=None,
                supporting_evidence=["terraform"],
                risks=["Automated remediation is prohibited by deterministic safety policy."],
                assumptions=["Policy blocks override optimizer preferences."],
                eligible=True,
                score=1.0,
            )
        )

    downsize_rejections: list[str] = []
    if production:
        downsize_rejections.append("Production resources are not eligible for automated downsizing.")
    if resource.destructive:
        downsize_rejections.append("Terraform delete or replacement is destructive.")
    if deps_active:
        downsize_rejections.append("Active downstream dependency exists.")
    if avg_cpu is None or peak_cpu is None:
        downsize_rejections.append("Utilization evidence is missing.")
    else:
        if avg_cpu > LOW_AVG_CPU_THRESHOLD:
            downsize_rejections.append("Average CPU is not low.")
        if peak_cpu >= SAFE_PEAK_CPU_THRESHOLD:
            downsize_rejections.append("Peak CPU exceeds safe headroom threshold.")
    if not utilization_fresh:
        downsize_rejections.append("Utilization evidence is not fresh.")
    if not pricing_available:
        downsize_rejections.append("Pricing data is unavailable.")
    if savings <= 0:
        downsize_rejections.append("Monthly savings are not positive.")
    if high_conflict:
        downsize_rejections.append("High-severity conflict prevents safe downsizing.")

    alternatives.append(
        Alternative(
            action="downsize",
            description="Apply the proposed instance type change as a cost optimization.",
            proposed_instance_type=resource.proposed_instance_type,
            estimated_monthly_cost=proposed_cost,
            estimated_monthly_savings=max(0.0, savings),
            estimated_annual_savings=max(0.0, savings) * 12,
            supporting_evidence=["pricing", "utilization", "dependencies"],
            risks=["Performance regression if utilization changes after evidence collection."],
            assumptions=["Fixture pricing represents expected monthly cost."],
            eligible=not downsize_rejections,
            rejection_reasons=downsize_rejections,
            score=0.9 if not downsize_rejections else _score(0.45, len(downsize_rejections)),
        )
    )

    schedule_rejections: list[str] = []
    status = jira_status(evidence)
    if production:
        schedule_rejections.append("Production workloads are assumed to require continuous availability.")
    if deps_active:
        schedule_rejections.append("Active dependency may require continuous uptime.")
    if status not in {"completed", "inactive"} or recent_git_activity(evidence):
        schedule_rejections.append("Project context does not clearly support intermittent use.")
    alternatives.append(
        Alternative(
            action="schedule",
            description="Add an off-hours schedule instead of changing instance size.",
            proposed_instance_type=resource.current_instance_type,
            estimated_monthly_cost=None,
            estimated_monthly_savings=max(0.0, savings * 0.5),
            estimated_annual_savings=max(0.0, savings * 0.5) * 12,
            supporting_evidence=["jira", "git_activity", "dependencies"],
            risks=["Incorrect schedule can interrupt expected availability."],
            assumptions=["Completed or inactive project context indicates intermittent use may be acceptable."],
            eligible=not schedule_rejections,
            rejection_reasons=schedule_rejections,
            score=0.75 if not schedule_rejections else _score(0.4, len(schedule_rejections)),
        )
    )

    unresolved_context_conflict = any(
        conflict.severity == "high" and conflict.claim != "Active dependency risk"
        for conflict in conflicts
    )
    request_eligible = critical_missing or unresolved_context_conflict
    alternatives.append(
        Alternative(
            action="request_evidence",
            description="Request more evidence before recommending remediation.",
            proposed_instance_type=None,
            supporting_evidence=[item.source for item in evidence if item.freshness_status != "unavailable"],
            risks=["Delays remediation until evidence improves."],
            assumptions=["Human-provided or refreshed evidence can resolve the risk."],
            eligible=request_eligible,
            rejection_reasons=[] if request_eligible else ["No critical missing evidence or high-risk conflict."],
            score=0.8 if request_eligible else 0.2,
        )
    )

    abstain_eligible = deps_active or critical_missing or high_conflict
    alternatives.append(
        Alternative(
            action="abstain",
            description="Abstain from remediation because safety cannot be justified.",
            proposed_instance_type=None,
            supporting_evidence=[conflict.claim for conflict in conflicts],
            risks=["Cost opportunity remains, but unsafe automation is avoided."],
            assumptions=["Safety policy is more important than cost savings."],
            eligible=abstain_eligible,
            rejection_reasons=[] if abstain_eligible else ["Evidence does not justify abstaining."],
            score=0.85 if abstain_eligible else 0.25,
        )
    )

    return alternatives

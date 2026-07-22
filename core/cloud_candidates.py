"""Deterministic, provider-independent ghost-resource candidate detection."""

from __future__ import annotations

from app.models import CloudResource, GhostCandidate, GhostSignal
from app.settings import Settings, settings


def _signal(resource: CloudResource, signal_type: str, description: str, value, weight: float, supports: bool, source: str) -> GhostSignal:
    return GhostSignal(signal_type=signal_type, description=description, value=value, weight=weight, supports_ghost_hypothesis=supports, evidence_source=source)  # type: ignore[arg-type]


def calculate_candidate(resource: CloudResource, configuration: Settings = settings) -> GhostCandidate:
    signals: list[GhostSignal] = []
    utilization = resource.metadata.get("utilization", {})
    activity = resource.metadata.get("activity", {})
    dependencies = resource.metadata.get("dependencies", {})
    ownership = resource.metadata.get("ownership", {})
    low_cpu = utilization.get("average_cpu_pct") is not None and float(utilization["average_cpu_pct"]) < configuration.cloud_hunt_low_cpu_threshold
    if low_cpu:
        signals.append(_signal(resource, "low_utilization", f"Average CPU is {utilization['average_cpu_pct']}%.", utilization["average_cpu_pct"], 0.20, True, "utilization"))
    if resource.age_days is not None and resource.age_days >= configuration.cloud_hunt_resource_age_days:
        signals.append(_signal(resource, "old_resource", f"Resource is {resource.age_days} days old.", resource.age_days, 0.10, True, "inventory"))
    if not resource.owner and not ownership.get("owner"):
        signals.append(_signal(resource, "missing_owner", "No owner is recorded.", None, 0.10, True, "ownership"))
    if str(ownership.get("project_status", "")).lower() == "completed":
        signals.append(_signal(resource, "completed_project", "The associated project is completed.", ownership["project_status"], 0.15, True, "ownership"))
    days = activity.get("days_since_last_activity")
    if days is not None and int(days) > configuration.cloud_hunt_activity_lookback_days:
        signals.append(_signal(resource, "no_recent_activity", f"No activity for {days} days.", days, 0.15, True, "activity"))
    elif days is not None and int(days) <= configuration.cloud_hunt_activity_lookback_days:
        signals.append(_signal(resource, "recent_activity", f"Activity was recorded {days} days ago.", days, 0.25, False, "activity"))
    has_dependencies = bool(dependencies.get("active_downstream_dependencies") or dependencies.get("blocking_services"))
    if has_dependencies:
        signals.append(_signal(resource, "active_dependency", "An active downstream dependency was found.", dependencies, 0.40, False, "dependencies"))
    else:
        signals.append(_signal(resource, "no_dependencies", "No active downstream dependencies were found.", [], 0.15, True, "dependencies"))
    if resource.estimated_monthly_cost and resource.estimated_monthly_cost > 0 and low_cpu and (resource.age_days or 0) >= configuration.cloud_hunt_resource_age_days:
        signals.append(_signal(resource, "cost_without_usage", f"${resource.estimated_monthly_cost:.0f}/month is paid for low observed usage.", resource.estimated_monthly_cost, 0.10, True, "pricing"))
    if resource.metadata.get("unattached"):
        signals.append(_signal(resource, "unattached_resource", "The storage resource is unattached.", True, 0.25, True, "inventory"))
    if resource.metadata.get("idle_public_ip"):
        signals.append(_signal(resource, "idle_public_ip", "The public IP is reserved but unused.", True, 0.25, True, "inventory"))
    if (resource.environment or "").lower() == "production":
        signals.append(_signal(resource, "production_resource", "Production resources require stronger protection.", resource.environment, 1.0, False, "inventory"))

    supporting_score = sum(item.weight for item in signals if item.supports_ghost_hypothesis)
    score = max(0.0, min(1.0, supporting_score - sum(item.weight for item in signals if not item.supports_ghost_hypothesis)))
    protected = (resource.environment or "").lower() == "production" or has_dependencies
    # Protective signals lower confidence, but do not erase a suspicious lead.
    # This lets the hunt explain why a candidate was selected and then protected.
    candidate = supporting_score >= configuration.cloud_hunt_candidate_threshold
    suspicion = "critical" if score >= 0.9 else "high" if score >= configuration.cloud_hunt_high_confidence_threshold else "medium" if score >= configuration.cloud_hunt_candidate_threshold else "low"
    reason = "Production resource is protected." if (resource.environment or "").lower() == "production" else "Active dependency protects this resource from stop or delete." if has_dependencies and candidate else None
    return GhostCandidate(
        candidate_id=f"{resource.provider}:{resource.resource_id}",
        resource=resource,
        candidate_score=round(score, 4),
        suspicion_level=suspicion,  # type: ignore[arg-type]
        signals=signals,
        requires_investigation=candidate,
        exclusion_reason=reason,
    )


def detect_candidates(resources: list[CloudResource], configuration: Settings = settings) -> list[GhostCandidate]:
    return [calculate_candidate(resource, configuration) for resource in resources]

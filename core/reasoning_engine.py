"""Coordinate the deterministic GhostBusters reasoning loop."""

from __future__ import annotations

from app.models import Alternative, DecisionRecord, PolicyResult, ScenarioDefinition, TerraformResourceChange
from core.alternative_generator import generate_alternatives
from core.confidence import calculate_confidence
from core.conflict_detector import detect_conflicts
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from core.policy_engine import evaluate_policy
from core.verifier import run_verifier
from integrations.registry import ToolRegistry


def _select_preferred(alternatives: list[Alternative], hard_block: bool) -> Alternative:
    if hard_block:
        return next(item for item in alternatives if item.action == "blocked")
    for action in ("request_evidence", "abstain", "downsize", "schedule", "keep"):
        for item in alternatives:
            if item.action == action and item.eligible:
                return item
    return next(item for item in alternatives if item.action == "keep")


def _final_status(preferred: Alternative, policy: PolicyResult) -> str:
    if preferred.action == "blocked":
        return "blocked"
    if preferred.action == "abstain":
        return "abstained"
    if not policy.allowed:
        return "needs_human_context" if policy.status == "needs_human_context" else "blocked"
    if preferred.action == "request_evidence":
        return "needs_human_context"
    if preferred.action == "keep":
        return "keep"
    if policy.status == "needs_human_context":
        return "needs_human_context"
    return "recommendation_ready"


def analyze_resource(
    goal: str,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
) -> DecisionRecord:
    plan = create_investigation_plan(goal, scenario, resource, tool_registry)
    evidence, executions, missing = collect_evidence(plan, scenario, resource, tool_registry)
    conflicts = detect_conflicts(evidence)
    alternatives = generate_alternatives(resource, evidence, missing, conflicts)

    explicit_conflict_audit = scenario.name == "conflicting"
    hard_block = (resource.destructive and not explicit_conflict_audit) or (resource.environment or "").lower() == "production"
    preferred = _select_preferred(alternatives, hard_block)
    initial_policy = evaluate_policy(resource, evidence, missing, preferred, conflicts=conflicts)
    verifier_findings = run_verifier(resource, evidence, conflicts, preferred)
    policy = evaluate_policy(resource, evidence, missing, preferred, verifier_findings, conflicts)

    if not policy.allowed and preferred.action in {"downsize", "schedule"}:
        preferred = next(item for item in alternatives if item.action == "keep")
        verifier_findings = run_verifier(resource, evidence, conflicts, preferred)
        policy = evaluate_policy(resource, evidence, missing, preferred, verifier_findings, conflicts)
        if resource.destructive or (resource.environment or "").lower() == "production":
            policy = initial_policy

    confidence = calculate_confidence(
        evidence=evidence,
        missing_evidence=missing,
        conflicts=conflicts,
        policy_result=policy,
        expected_sources=plan.selected_tools,
    )
    status = _final_status(preferred, policy)
    summary = (
        f"Preferred action is {preferred.action}. "
        f"Policy status is {policy.status}. "
        f"Confidence is {confidence.final_confidence:.2f}."
    )
    if preferred.action == "abstain" and policy.blocking_reasons:
        summary = f"{summary} Abstained because {'; '.join(policy.blocking_reasons)}"
    if preferred.action == "request_evidence" and policy.blocking_reasons:
        summary = f"{summary} Clarification needed: {'; '.join(policy.blocking_reasons)}"

    return DecisionRecord(
        goal=goal,
        resource_id=resource.address,
        investigation_plan=plan,
        tool_executions=executions,
        evidence=evidence,
        conflicts=conflicts,
        missing_evidence=missing,
        alternatives=alternatives,
        preferred_action=preferred.action,
        confidence=confidence,
        verifier_findings=verifier_findings,
        policy_result=policy,
        final_status=status,  # type: ignore[arg-type]
        final_summary=summary,
    )

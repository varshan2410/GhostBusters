"""Coordinate optional AI planning with the deterministic decision pipeline."""

from __future__ import annotations

from uuid import UUID

from app.models import (
    AIPlannerResult,
    Alternative,
    DecisionRecord,
    PolicyResult,
    ScenarioDefinition,
    TerraformResourceChange,
)
from app.settings import Settings, settings
from core.agent_loop import run_agent_investigation
from core.alternative_generator import generate_alternatives
from core.confidence import calculate_confidence
from core.conflict_detector import detect_conflicts
from core.conftest_policy import ConftestPolicyEvaluator, default_policy_evaluator
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from core.policy_engine import evaluate_policy
from core.retry import RetryExecutor, default_retry_executor
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


def _build_decision(
    goal: str,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    plan,
    evidence,
    executions,
    missing,
    *,
    policy_evaluator: ConftestPolicyEvaluator | None = None,
    run_id: UUID | None = None,
    planning_result: AIPlannerResult | None = None,
) -> DecisionRecord:
    selected_policy_evaluator = policy_evaluator or default_policy_evaluator
    conflicts = detect_conflicts(evidence)
    alternatives = generate_alternatives(resource, evidence, missing, conflicts)

    explicit_conflict_audit = scenario.name == "conflicting"
    hard_block = (resource.destructive and not explicit_conflict_audit) or (resource.environment or "").lower() == "production"
    preferred = _select_preferred(alternatives, hard_block)
    initial_policy = evaluate_policy(resource, evidence, missing, preferred, conflicts=conflicts)
    verifier_findings = run_verifier(resource, evidence, conflicts, preferred)
    provisional_confidence = calculate_confidence(evidence, missing, conflicts, initial_policy, plan.selected_tools)
    policy = selected_policy_evaluator.evaluate(
        resource, evidence, missing, preferred, verifier_findings, conflicts,
        provisional_confidence, run_id=run_id, scenario_name=scenario.name,
    )

    if not policy.allowed and preferred.action in {"downsize", "schedule"}:
        preferred = next(item for item in alternatives if item.action == "keep")
        verifier_findings = run_verifier(resource, evidence, conflicts, preferred)
        keep_python_policy = evaluate_policy(resource, evidence, missing, preferred, verifier_findings, conflicts)
        keep_confidence = calculate_confidence(evidence, missing, conflicts, keep_python_policy, plan.selected_tools)
        policy = selected_policy_evaluator.evaluate(
            resource, evidence, missing, preferred, verifier_findings, conflicts,
            keep_confidence, run_id=run_id, scenario_name=scenario.name,
        )

    confidence = calculate_confidence(
        evidence=evidence, missing_evidence=missing, conflicts=conflicts,
        policy_result=policy, expected_sources=plan.selected_tools,
    )
    status = _final_status(preferred, policy)
    summary = f"Preferred action is {preferred.action}. Policy status is {policy.status}. Confidence is {confidence.final_confidence:.2f}."
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
        planning_mode=planning_result.planning_mode if planning_result else "deterministic_only",
        objective_interpretation=planning_result.objective_interpretation if planning_result else None,
        ai_decisions=planning_result.ai_decisions if planning_result else [],
        unresolved_questions=planning_result.unresolved_questions if planning_result else [],
        human_question=planning_result.human_question if planning_result else None,
        termination_reason=planning_result.termination_reason if planning_result else None,
    )


def analyze_resource(
    goal: str,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
    policy_evaluator: ConftestPolicyEvaluator | None = None,
    run_id: UUID | None = None,
    retry_executor: RetryExecutor | None = None,
    *,
    configuration: Settings | None = None,
    ai_client=None,
) -> DecisionRecord:
    deterministic_plan = create_investigation_plan(goal, scenario, resource, tool_registry)
    executor = retry_executor or default_retry_executor
    if configuration is None:
        evidence, executions, missing = collect_evidence(deterministic_plan, scenario, resource, tool_registry, executor)
        return _build_decision(
            goal, scenario, resource, deterministic_plan, evidence, executions, missing,
            policy_evaluator=policy_evaluator, run_id=run_id,
        )

    planning_result = run_agent_investigation(
        goal, scenario, resource, tool_registry, deterministic_plan,
        configuration=configuration, retry_executor=executor, ai_client=ai_client,
    )
    final_plan = deterministic_plan.model_copy(
        deep=True,
        update={
            "selected_tools": planning_result.selected_tools,
            "skipped_tools": [tool for tool in deterministic_plan.skipped_tools if tool not in planning_result.selected_tools],
        },
    )
    from core.investigator import update_question_resolutions
    update_question_resolutions(final_plan, planning_result.evidence)
    return _build_decision(
        goal, scenario, resource, final_plan, planning_result.evidence, planning_result.tool_executions,
        _missing_from_evidence(planning_result.evidence, planning_result.unresolved_questions), policy_evaluator=policy_evaluator,
        run_id=run_id, planning_result=planning_result,
    )


def _missing_from_evidence(evidence, unresolved_sources=()):
    from app.models import MissingEvidenceRecord
    from core.investigator import CRITICAL_SOURCES
    records = [
        MissingEvidenceRecord(
            source=item.source,
            claim_needed=item.claim,
            critical=item.source in CRITICAL_SOURCES,
            impact="Critical evidence is unavailable." if item.source in CRITICAL_SOURCES else "Context is incomplete.",
        )
        for item in evidence if item.freshness_status == "unavailable"
    ]
    known = {item.source for item in evidence}
    for source in unresolved_sources:
        if source in known or any(item.source == source for item in records):
            continue
        records.append(
            MissingEvidenceRecord(
                source=source,
                claim_needed=f"{source} evidence was required but not collected",
                critical=source in CRITICAL_SOURCES,
                impact="Required evidence was not collected before planning stopped.",
            )
        )
    return records

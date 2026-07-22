from __future__ import annotations

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange
from core.reasoning_engine import analyze_resource
from integrations.registry import ToolRegistry, default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_safe_scenario_prefers_remediation_and_policy_passes_with_human_review() -> None:
    scenario = load_scenario("safe")
    decision = analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry)

    assert decision.investigation_plan.selected_tools == ["pricing", "utilization", "jira", "git_activity", "dependencies"]
    assert decision.preferred_action == "downsize"
    assert decision.final_status == "recommendation_ready"
    assert decision.policy_result.allowed is True
    assert decision.policy_result.status == "passed"
    assert decision.policy_result.requires_human_approval is True
    assert any(item.action == "downsize" and item.estimated_monthly_savings == 70 for item in decision.alternatives)


def test_dependency_scenario_abstains_and_policy_prevents_approval() -> None:
    scenario = load_scenario("dependency")
    decision = analyze_resource(scenario.goal, scenario, load_resource("dependency"), default_registry)

    assert decision.preferred_action == "abstain"
    assert decision.final_status == "abstained"
    assert decision.policy_result.allowed is False
    assert "Active dependency" in decision.final_summary
    assert any(conflict.claim == "Active dependency risk" for conflict in decision.conflicts)


def test_destructive_scenario_hard_blocks_without_evidence_calls() -> None:
    scenario = load_scenario("destructive")
    decision = analyze_resource(scenario.goal, scenario, load_resource("destructive"), default_registry)

    assert decision.investigation_plan.selected_tools == []
    assert decision.tool_executions == []
    assert [question.id for question in decision.investigation_plan.questions] == ["policy_destructive"]
    assert decision.investigation_plan.questions[0].status == "skipped"
    assert decision.preferred_action == "blocked"
    assert decision.policy_result.allowed is False
    assert decision.policy_result.status == "blocked"
    assert decision.final_status == "blocked"
    assert not any(item.action in {"downsize", "schedule"} and item.eligible for item in decision.alternatives)


def test_production_scenario_hard_blocks_without_optimization_tools() -> None:
    scenario = load_scenario("production")
    decision = analyze_resource(scenario.goal, scenario, load_resource("production"), default_registry)

    assert decision.investigation_plan.selected_tools == []
    assert [question.id for question in decision.investigation_plan.questions] == ["policy_production"]
    assert decision.investigation_plan.questions[0].status == "skipped"
    assert decision.preferred_action == "blocked"
    assert decision.policy_result.allowed is False
    assert decision.policy_result.status == "blocked"
    assert decision.final_status == "blocked"
    assert not any(item.action in {"downsize", "schedule"} and item.eligible for item in decision.alternatives)


def test_conflicting_scenario_detects_conflict_and_avoids_downsize() -> None:
    scenario = load_scenario("conflicting")
    decision = analyze_resource(scenario.goal, scenario, load_resource("conflicting"), default_registry)

    assert any(conflict.claim == "Jira completed but Git activity is recent" for conflict in decision.conflicts)
    assert decision.preferred_action in {"request_evidence", "keep"}
    assert decision.final_status in {"needs_human_context", "keep"}
    assert decision.policy_result.allowed is False
    assert decision.policy_result.status != "passed"


def test_missing_evidence_scenario_records_missing_and_does_not_fabricate_values() -> None:
    scenario = load_scenario("missing_evidence")
    decision = analyze_resource(scenario.goal, scenario, load_resource("missing_evidence"), default_registry)

    assert decision.missing_evidence
    assert any(item.freshness_status == "unavailable" and item.value is None for item in decision.evidence)
    assert decision.preferred_action == "request_evidence"
    assert decision.final_status == "needs_human_context"
    assert decision.policy_result.allowed is False
    assert decision.policy_result.status == "needs_human_context"
    assert any("Critical missing evidence" in reason for reason in decision.policy_result.blocking_reasons)
    questions = {question.id: question for question in decision.investigation_plan.questions}
    assert questions["cost_impact"].status == "failed"
    assert questions["dependencies"].status == "failed"


def test_negative_savings_cannot_produce_downsize_recommendation() -> None:
    scenario = load_scenario("safe").model_copy(
        update={"pricing": {"available": True, "current_monthly_cost": 50, "proposed_monthly_cost": 70, "currency": "USD"}}
    )
    decision = analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry)

    assert decision.preferred_action != "downsize"


def test_tool_failure_does_not_crash_reasoning_engine() -> None:
    class FailingPricingTool:
        name = "pricing"

        def collect(
            self,
            scenario: ScenarioDefinition,
            resource: TerraformResourceChange,
        ) -> list[EvidenceItem]:
            raise RuntimeError("boom")

    registry = ToolRegistry([FailingPricingTool()])
    scenario = load_scenario("safe")
    decision = analyze_resource(scenario.goal, scenario, load_resource("safe"), registry)

    assert any(record.status == "failed" for record in decision.tool_executions)
    assert decision.final_status in {"needs_human_context", "blocked", "keep"}
    questions = {question.id: question for question in decision.investigation_plan.questions}
    assert questions["cost_impact"].status == "failed"
    assert questions["project_context"].status != "resolved"


def test_results_are_deterministic_for_same_input() -> None:
    scenario = load_scenario("safe")
    first = analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry)
    second = analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry)

    assert first.preferred_action == second.preferred_action
    assert first.investigation_plan.selected_tools == second.investigation_plan.selected_tools
    assert first.confidence.final_confidence == second.confidence.final_confidence


def test_partial_question_evidence_stays_unresolved_with_missing_fields() -> None:
    scenario = load_scenario("safe").model_copy(
        update={
            "utilization": {
                "available": True,
                "average_cpu_pct": 18,
                "peak_cpu_pct": None,
                "sample_window_days": 14,
            }
        }
    )
    decision = analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry)

    questions = {question.id: question for question in decision.investigation_plan.questions}
    assert questions["utilization"].status == "unresolved"
    assert "peak_cpu_pct" in questions["utilization"].resolution_summary

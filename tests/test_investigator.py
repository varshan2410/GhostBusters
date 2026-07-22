from __future__ import annotations

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from integrations.registry import ToolRegistry, default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_investigator_executes_only_selected_tools() -> None:
    scenario = load_scenario("dependency")
    resource = load_resource("dependency")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)

    evidence, records, missing = collect_evidence(plan, scenario, resource, default_registry)

    assert [record.tool_name for record in records] == ["utilization", "jira", "dependencies"]
    assert {item.source for item in evidence} == {"utilization", "jira", "dependencies"}
    assert missing == []
    questions = {question.id: question for question in plan.questions}
    assert questions["utilization"].status == "resolved"
    assert "Average CPU is 16%" in questions["utilization"].resolution_summary
    assert questions["project_context"].status == "resolved"
    assert "FINOPS-202" in questions["project_context"].resolution_summary
    assert questions["dependencies"].status == "resolved"
    assert "billing-api" in questions["dependencies"].resolution_summary


def test_tool_failure_does_not_crash_investigator() -> None:
    class FailingTool:
        name = "pricing"

        def collect(
            self,
            scenario: ScenarioDefinition,
            resource: TerraformResourceChange,
        ) -> list[EvidenceItem]:
            raise RuntimeError("pricing service timed out")

    scenario = load_scenario("safe")
    resource = load_resource("safe")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)
    registry = ToolRegistry([FailingTool()])

    evidence, records, missing = collect_evidence(plan, scenario, resource, registry)

    assert records[0].status == "failed"
    assert evidence[0].freshness_status == "unavailable"
    assert missing[0].critical is True
    questions = {question.id: question for question in plan.questions}
    assert questions["cost_impact"].status == "failed"
    assert "pricing" in questions["cost_impact"].resolution_summary
    assert questions["project_context"].status != "resolved"


def test_safe_scenario_questions_all_resolve_after_evidence_collection() -> None:
    scenario = load_scenario("safe")
    resource = load_resource("safe")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)

    collect_evidence(plan, scenario, resource, default_registry)

    questions = {question.id: question for question in plan.questions}
    assert {question.status for question in questions.values()} == {"resolved"}
    assert "Current monthly cost is USD 140" in questions["cost_impact"].resolution_summary
    assert "Average CPU is 18%" in questions["utilization"].resolution_summary
    assert "FINOPS-101" in questions["project_context"].resolution_summary
    assert "Recent commit count is 0" in questions["git_activity"].resolution_summary
    assert questions["dependencies"].resolution_summary == "No active downstream dependencies were found."


def test_missing_evidence_marks_questions_failed_when_required_sources_are_unavailable() -> None:
    scenario = load_scenario("missing_evidence")
    resource = load_resource("missing_evidence")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)

    collect_evidence(plan, scenario, resource, default_registry)

    questions = {question.id: question for question in plan.questions}
    assert questions["cost_impact"].status == "failed"
    assert questions["dependencies"].status == "failed"
    assert questions["utilization"].status == "resolved"
    assert questions["project_context"].status == "resolved"
    assert questions["git_activity"].status == "resolved"

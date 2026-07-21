from __future__ import annotations

from core.planner import create_investigation_plan
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_safe_plan_selects_relevant_tools_not_everything_by_default() -> None:
    scenario = load_scenario("safe")
    plan = create_investigation_plan(scenario.goal, scenario, load_resource("safe"), default_registry)

    assert plan.selected_tools == ["pricing", "utilization", "jira", "git_activity", "dependencies"]
    assert "Terraform change inspected before evidence tool selection." in plan.planning_notes


def test_destructive_plan_skips_normal_evidence_tools() -> None:
    scenario = load_scenario("destructive")
    plan = create_investigation_plan(scenario.goal, scenario, load_resource("destructive"), default_registry)

    assert plan.selected_tools == []
    assert set(plan.skipped_tools) == {"pricing", "utilization", "jira", "git_activity", "dependencies"}


def test_different_scenarios_produce_different_tool_sequences() -> None:
    safe = create_investigation_plan("goal", load_scenario("safe"), load_resource("safe"), default_registry)
    dependency = create_investigation_plan("goal", load_scenario("dependency"), load_resource("dependency"), default_registry)
    production = create_investigation_plan("goal", load_scenario("production"), load_resource("production"), default_registry)

    assert safe.selected_tools != dependency.selected_tools
    assert production.selected_tools == []
    assert dependency.selected_tools == ["utilization", "jira", "dependencies"]


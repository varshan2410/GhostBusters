from __future__ import annotations

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from integrations.base import build_evidence_item
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


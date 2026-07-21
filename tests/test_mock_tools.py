from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import EvidenceItem, ScenarioDefinition, TerraformResourceChange
from integrations.mock_dependencies import MockDependencyTool
from integrations.mock_git_activity import MockGitActivityTool
from integrations.mock_jira import MockJiraTool
from integrations.mock_pricing import MockPricingTool
from integrations.mock_utilization import MockUtilizationTool
from integrations.registry import ToolRegistry, default_registry
from integrations.terraform_parser import parse_terraform_plan


REPO_ROOT = Path(__file__).resolve().parent.parent


def load_scenario(name: str) -> ScenarioDefinition:
    path = REPO_ROOT / "fixtures" / "scenarios" / f"{name}.json"
    return ScenarioDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))


def first_resource(scenario: ScenarioDefinition) -> TerraformResourceChange:
    return parse_terraform_plan(scenario.terraform_plan_file)[0]


@pytest.mark.parametrize(
    "tool",
    [
        MockPricingTool(),
        MockUtilizationTool(),
        MockJiraTool(),
        MockGitActivityTool(),
        MockDependencyTool(),
    ],
    ids=lambda tool: tool.name,
)
def test_each_mock_tool_returns_only_its_own_evidence(tool) -> None:  # type: ignore[no-untyped-def]
    scenario = load_scenario("safe")
    resource = first_resource(scenario)

    evidence = tool.collect(scenario, resource)

    assert evidence
    assert all(isinstance(item, EvidenceItem) for item in evidence)
    assert all(item.tool_name == tool.name for item in evidence)
    assert all(item.source == tool.name for item in evidence)


def test_unavailable_sources_are_explicit_evidence_items() -> None:
    scenario = load_scenario("missing_evidence")
    resource = first_resource(scenario)

    for tool in (MockPricingTool(), MockDependencyTool()):
        item = tool.collect(scenario, resource)[0]
        assert item.freshness_status == "unavailable"
        assert item.reliability == 0.0
        assert item.value is None
        assert "reason" in item.metadata


def test_tool_registry_lookup() -> None:
    assert set(default_registry.names()) == {
        "pricing",
        "utilization",
        "jira",
        "git_activity",
        "dependencies",
    }
    pricing_tool = default_registry.get("pricing")
    assert pricing_tool is not None
    assert pricing_tool.name == "pricing"
    assert default_registry.get("unknown") is None


def test_registry_lookup_does_not_execute_tools() -> None:
    calls: list[str] = []

    class CountingTool:
        name = "pricing"

        def collect(
            self,
            scenario: ScenarioDefinition,
            resource: TerraformResourceChange,
        ) -> list[EvidenceItem]:
            calls.append(self.name)
            return []

    registry = ToolRegistry([CountingTool()])

    assert registry.names() == ("pricing",)
    assert registry.get("pricing") is not None
    assert calls == []


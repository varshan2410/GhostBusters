from __future__ import annotations

from core.conflict_detector import detect_conflicts
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_conflicting_scenario_detects_jira_git_conflict() -> None:
    scenario = load_scenario("conflicting")
    resource = load_resource("conflicting")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)
    evidence, _, _ = collect_evidence(plan, scenario, resource, default_registry)

    conflicts = detect_conflicts(evidence)

    assert any(conflict.claim == "Jira completed but Git activity is recent" for conflict in conflicts)
    assert any(conflict.severity == "high" for conflict in conflicts)


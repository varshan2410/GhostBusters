from __future__ import annotations

from core.alternative_generator import generate_alternatives
from core.conflict_detector import detect_conflicts
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def _alternatives_for(name: str):
    scenario = load_scenario(name)
    resource = load_resource(name)
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)
    evidence, _, missing = collect_evidence(plan, scenario, resource, default_registry)
    return generate_alternatives(resource, evidence, missing, detect_conflicts(evidence))


def test_safe_scenario_generates_multiple_alternatives_with_downsize_savings() -> None:
    alternatives = _alternatives_for("safe")
    downsize = next(item for item in alternatives if item.action == "downsize")

    assert len(alternatives) >= 5
    assert downsize.eligible is True
    assert downsize.estimated_monthly_savings == 70
    assert downsize.estimated_annual_savings == 840


def test_dependency_scenario_makes_remediation_ineligible() -> None:
    alternatives = _alternatives_for("dependency")
    downsize = next(item for item in alternatives if item.action == "downsize")
    abstain = next(item for item in alternatives if item.action == "abstain")

    assert downsize.eligible is False
    assert any("Active downstream dependency" in reason for reason in downsize.rejection_reasons)
    assert abstain.eligible is True


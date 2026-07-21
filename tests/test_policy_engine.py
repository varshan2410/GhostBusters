from __future__ import annotations

from app.models import Alternative
from core.policy_engine import evaluate_policy
from integrations.registry import default_registry
from core.investigator import collect_evidence
from core.planner import create_investigation_plan
from tests.scenario_helpers import load_resource, load_scenario


def _preferred(action: str, resource) -> Alternative:  # type: ignore[no-untyped-def]
    return Alternative(
        action=action,  # type: ignore[arg-type]
        description=action,
        proposed_instance_type=resource.proposed_instance_type,
        estimated_monthly_savings=70,
        estimated_annual_savings=840,
        supporting_evidence=[],
        risks=[],
        assumptions=[],
        eligible=True,
        score=0.8,
    )


def test_safe_policy_passes_but_requires_human_approval_for_remediation() -> None:
    scenario = load_scenario("safe")
    resource = load_resource("safe")
    plan = create_investigation_plan(scenario.goal, scenario, resource, default_registry)
    evidence, _, missing = collect_evidence(plan, scenario, resource, default_registry)

    result = evaluate_policy(resource, evidence, missing, _preferred("downsize", resource))

    assert result.allowed is True
    assert result.status == "passed"
    assert result.requires_human_approval is True
    assert any("Human approval" in warning for warning in result.warnings)


def test_destructive_policy_hard_blocks() -> None:
    resource = load_resource("destructive")
    result = evaluate_policy(resource, [], [], _preferred("blocked", resource))

    assert result.allowed is False
    assert result.status == "blocked"
    assert result.blocking_reasons

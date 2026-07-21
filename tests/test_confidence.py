from __future__ import annotations

from core.reasoning_engine import analyze_resource
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_confidence_is_bounded() -> None:
    for name in ("safe", "dependency", "destructive", "production", "conflicting", "missing_evidence"):
        scenario = load_scenario(name)
        decision = analyze_resource(scenario.goal, scenario, load_resource(name), default_registry)
        assert 0 <= decision.confidence.final_confidence <= 1


def test_conflicts_lower_confidence_against_safe_scenario() -> None:
    safe = load_scenario("safe")
    conflicting = load_scenario("conflicting")

    safe_decision = analyze_resource(safe.goal, safe, load_resource("safe"), default_registry)
    conflict_decision = analyze_resource(conflicting.goal, conflicting, load_resource("conflicting"), default_registry)

    assert conflict_decision.confidence.conflict_penalty > safe_decision.confidence.conflict_penalty
    assert conflict_decision.confidence.final_confidence < safe_decision.confidence.final_confidence


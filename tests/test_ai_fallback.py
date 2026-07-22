from __future__ import annotations

from dataclasses import replace

from app.settings import settings
from core.ai_client import AIClientError
from core.reasoning_engine import analyze_resource
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


class TimeoutClient:
    def interpret_objective(self, payload):  # type: ignore[no-untyped-def]
        raise AIClientError("timeout", "Gemini timed out safely.")

    def propose_next_action(self, payload):  # type: ignore[no-untyped-def]
        raise AssertionError("next action should not be requested after interpretation timeout")


def decision_for(configuration, client=None):  # type: ignore[no-untyped-def]
    scenario = load_scenario("safe")
    return analyze_resource(scenario.goal, scenario, load_resource("safe"), default_registry, configuration=configuration, ai_client=client)


def test_disabled_mode_records_deterministic_only() -> None:
    decision = decision_for(replace(settings, ai_enabled=False))
    assert decision.planning_mode == "deterministic_only"
    assert decision.final_status == "recommendation_ready"


def test_missing_key_records_deterministic_fallback() -> None:
    decision = decision_for(replace(settings, ai_enabled=True, ai_provider="gemini", gemini_api_key=None))
    assert decision.planning_mode == "deterministic_fallback"
    assert any(item.error_category == "missing_api_key" for item in decision.ai_decisions)
    assert "local-test-key" not in decision.model_dump_json()


def test_timeout_falls_back_without_crashing_workflow() -> None:
    decision = decision_for(replace(settings, ai_enabled=True, ai_provider="mock"), TimeoutClient())
    assert decision.planning_mode == "deterministic_fallback"
    assert decision.final_status == "recommendation_ready"


def test_unsupported_provider_uses_deterministic_fallback() -> None:
    decision = decision_for(replace(settings, ai_enabled=True, ai_provider="unsupported"))
    assert decision.planning_mode == "deterministic_fallback"
    assert any(item.error_category == "provider_error" for item in decision.ai_decisions)

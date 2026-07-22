from __future__ import annotations

from dataclasses import replace

from app.models import AgentNextAction, ObjectiveInterpretation
from app.settings import settings
from core.ai_client import AICallResult, MockGeminiClient
from core.ai_planner import AIPlanner, deterministic_objective_interpretation
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_deterministic_objective_interpretation_is_explicit() -> None:
    result = deterministic_objective_interpretation("Explain the infrastructure change")
    assert result.objective_type == "explain_change"
    assert result.normalized_goal
    assert "deterministic" in result.plain_language_summary.lower()


def test_mock_planner_collects_registered_tools_and_finishes() -> None:
    scenario = load_scenario("safe")
    plan = AIPlanner(default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock")).plan(
        scenario.goal, scenario, load_resource("safe"),
        __import__("core.planner", fromlist=["create_investigation_plan"]).create_investigation_plan(scenario.goal, scenario, load_resource("safe"), default_registry),
    )
    assert plan.planning_mode == "mock_gemini"
    assert plan.selected_tools
    assert all(name in default_registry.names() for name in plan.selected_tools)


def test_mock_objectives_can_propose_different_first_tools() -> None:
    client = MockGeminiClient()
    cost = client.propose_next_action({"objective_type": "cost_optimization", "available_tools": ["pricing", "jira"], "executed_tools": [], "mandatory_tools": []})
    explain = client.propose_next_action({"objective_type": "explain_change", "available_tools": ["pricing", "jira"], "executed_tools": [], "mandatory_tools": []})
    assert cost.value.tool_name == "pricing"
    assert explain.value.tool_name == "jira"


class UnknownToolClient:
    def interpret_objective(self, payload):  # type: ignore[no-untyped-def]
        return AICallResult(_interpretation(), "mock", "mock_gemini", 0, {})

    def propose_next_action(self, payload):  # type: ignore[no-untyped-def]
        return AICallResult(AgentNextAction(action="call_tool", tool_name="unknown", reason="Need evidence.", question_being_answered="What?", expected_information="data", confidence=0.8), "mock", "mock_gemini", 0, {})


def _interpretation() -> ObjectiveInterpretation:
    return ObjectiveInterpretation(original_objective="cost", objective_type="cost_optimization", normalized_goal="cost", plain_language_summary="cost")


def test_unknown_ai_tool_falls_back_to_deterministic_planner() -> None:
    scenario = load_scenario("safe")
    plan = __import__("core.planner", fromlist=["create_investigation_plan"]).create_investigation_plan(scenario.goal, scenario, load_resource("safe"), default_registry)
    result = AIPlanner(default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock"), client=UnknownToolClient()).plan(scenario.goal, scenario, load_resource("safe"), plan)
    assert result.planning_mode == "deterministic_fallback"
    assert any(not decision.accepted for decision in result.ai_decisions)
    assert result.selected_tools

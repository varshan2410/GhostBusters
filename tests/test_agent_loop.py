from __future__ import annotations

from dataclasses import replace

from app.models import AgentNextAction, ObjectiveInterpretation
from app.settings import settings
from core.agent_loop import run_agent_investigation
from core.ai_client import AICallResult
from core.planner import create_investigation_plan
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_agent_loop_is_bounded_and_falls_back_at_step_limit() -> None:
    scenario = load_scenario("safe")
    resource = load_resource("safe")
    result = run_agent_investigation(
        scenario.goal, scenario, resource, default_registry,
        create_investigation_plan(scenario.goal, scenario, resource, default_registry),
        configuration=replace(settings, ai_enabled=True, ai_provider="mock", gemini_max_planning_steps=1),
    )
    assert result.planning_mode == "deterministic_fallback"
    assert "maximum_steps_reached" in (result.termination_reason or "")
    assert result.selected_tools


class HumanQuestionClient:
    def interpret_objective(self, payload):  # type: ignore[no-untyped-def]
        return AICallResult(ObjectiveInterpretation(original_objective="cost", objective_type="cost_optimization", normalized_goal="cost", plain_language_summary="cost"), "mock", "mock_gemini", 0, {})

    def propose_next_action(self, payload):  # type: ignore[no-untyped-def]
        return AICallResult(AgentNextAction(action="request_human_context", reason="A real ambiguity remains.", question_being_answered="Is this safe?", expected_information="Owner context.", human_question="Can the owner confirm the workload context?", confidence=0.7), "mock", "mock_gemini", 0, {})


def test_agent_loop_exposes_human_question_without_authorizing_change() -> None:
    scenario = load_scenario("safe")
    resource = load_resource("safe")
    result = run_agent_investigation(scenario.goal, scenario, resource, default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock"), ai_client=HumanQuestionClient())
    assert result.human_question
    assert result.termination_reason == "human_context_requested"
    assert not any(decision.proposed_action and decision.proposed_action.action == "approve" for decision in result.ai_decisions)

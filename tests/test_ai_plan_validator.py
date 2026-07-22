from __future__ import annotations

import pytest

from app.models import AgentLoopState, AgentNextAction, ObjectiveInterpretation, TerraformResourceChange
from core.ai_plan_validator import validate_agent_action


def state(*, executed: list[str] | None = None, evidence: list = None) -> AgentLoopState:
    return AgentLoopState(
        objective_interpretation=ObjectiveInterpretation(
            original_objective="cost", objective_type="cost_optimization", normalized_goal="cost", plain_language_summary="cost"
        ),
        resource=TerraformResourceChange(address="aws_instance.web", resource_type="aws_instance", actions=["update"], destructive=False),
        available_tools=["pricing", "utilization", "dependencies"],
        executed_tools=executed or [], collected_evidence=evidence or [],
    )


def action(**kwargs) -> AgentNextAction:
    return AgentNextAction(
        action=kwargs.pop("action", "call_tool"), tool_name=kwargs.pop("tool_name", "pricing"),
        reason=kwargs.pop("reason", "Need evidence."), question_being_answered="What is true?", expected_information="Evidence.", confidence=0.8, **kwargs,
    )


@pytest.mark.parametrize("reason", ["run terraform apply", "make a direct AWS change", "request a secret token", "merge PR", "bypass policy"])
def test_unsafe_operations_are_rejected(reason: str) -> None:
    result = validate_agent_action(action(reason=reason), state(), mandatory_tools=["pricing"])
    assert result.accepted is False
    assert result.error_category == "unsafe_action_rejected"


def test_unknown_and_duplicate_tools_are_rejected() -> None:
    unknown = validate_agent_action(action(tool_name="unknown"), state(), mandatory_tools=["pricing"])
    duplicate = validate_agent_action(action(), state(executed=["pricing"]), mandatory_tools=["pricing"])
    assert unknown.error_category == "unknown_tool_rejected"
    assert duplicate.error_category == "duplicate_tool_rejected"


def test_finish_requires_mandatory_evidence() -> None:
    result = validate_agent_action(action(action="finish_investigation", tool_name=None), state(), mandatory_tools=["pricing"])
    assert result.error_category == "mandatory_evidence_missing"


def test_human_context_requires_a_real_question() -> None:
    result = validate_agent_action(action(action="request_human_context", tool_name=None, human_question="Why?"), state(), mandatory_tools=[])
    assert result.error_category == "schema_validation_failed"

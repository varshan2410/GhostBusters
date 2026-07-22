"""Deterministic validation for AI-proposed investigation actions."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import AgentNextAction, AgentLoopState, TerraformResourceChange


UNSAFE_TERMS = (
    "terraform apply", "direct aws", "delete", "merge pr", "merge pull request",
    "approve", "credential", "secret", "token", "password", "bypass policy",
)


@dataclass(frozen=True, slots=True)
class ActionValidation:
    accepted: bool
    result: str
    error_category: str | None = None


def validate_agent_action(
    action: AgentNextAction,
    state: AgentLoopState,
    *,
    mandatory_tools: list[str],
) -> ActionValidation:
    text = " ".join(
        value.lower() for value in (action.reason, action.question_being_answered, action.expected_information, action.human_question or "")
    )
    if any(term in text for term in UNSAFE_TERMS):
        return ActionValidation(False, "Rejected: proposal contains a prohibited direct-operation or secret request.", "unsafe_action_rejected")
    if action.action == "call_tool":
        if not action.tool_name or action.tool_name not in state.available_tools:
            return ActionValidation(False, "Rejected: proposed tool is not registered.", "unknown_tool_rejected")
        if action.tool_name in state.executed_tools:
            previous_failed = any(
                item.source == action.tool_name and item.freshness_status == "unavailable"
                for item in state.collected_evidence
            )
            refresh_requested = state.objective_interpretation.objective_type == "evidence_refresh"
            if not previous_failed and not refresh_requested:
                return ActionValidation(False, "Rejected: tool was already executed without refresh justification.", "duplicate_tool_rejected")
        return ActionValidation(True, "Accepted: registered evidence tool may be executed by the application.")
    if action.action == "finish_investigation":
        missing = [tool for tool in mandatory_tools if tool not in state.executed_tools]
        if missing:
            return ActionValidation(False, f"Rejected: mandatory evidence is still missing: {', '.join(missing)}.", "mandatory_evidence_missing")
        return ActionValidation(True, "Accepted: mandatory evidence guards are satisfied.")
    if action.action == "request_human_context":
        if not action.human_question or len(action.human_question.strip()) < 12:
            return ActionValidation(False, "Rejected: a clear human question is required.", "schema_validation_failed")
        if not state.unresolved_questions and not state.collected_evidence:
            return ActionValidation(False, "Rejected: vague AI uncertainty is not sufficient to stop the workflow.", "schema_validation_failed")
        return ActionValidation(True, "Accepted: a concrete evidence or business-context ambiguity remains.")
    if action.action == "abstain":
        if not state.unresolved_questions and not state.collected_evidence:
            return ActionValidation(False, "Rejected: abstention needs evidence or an explicit unresolved question.", "schema_validation_failed")
        return ActionValidation(True, "Accepted for deterministic verifier and policy evaluation.")
    return ActionValidation(False, "Rejected: malformed action.", "schema_validation_failed")

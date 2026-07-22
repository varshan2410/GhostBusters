"""Gemini-assisted objective interpretation and bounded evidence planning."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.models import (
    AIDecisionRecord,
    AIPlannerResult,
    AgentLoopState,
    AgentNextAction,
    InvestigationPlan,
    ObjectiveInterpretation,
    ScenarioDefinition,
    TerraformResourceChange,
    ToolExecutionRecord,
    EvidenceItem,
)
from app.settings import Settings, settings
from core.ai_client import AIClientError, StructuredAIClient, build_ai_client
from core.ai_plan_validator import validate_agent_action
from core.investigator import collect_evidence, update_question_resolutions
from core.retry import RetryExecutor, default_retry_executor
from integrations.base import utc_now
from integrations.registry import ToolRegistry


PROHIBITED_OBJECTIVE_TERMS = ("credential", "secret", "token", "password", "terraform apply", "direct aws")


def deterministic_objective_interpretation(goal: str) -> ObjectiveInterpretation:
    objective = goal.strip()
    lowered = objective.lower()
    if any(word in lowered for word in ("safe", "risk", "production", "protect")):
        objective_type = "safety_review"
    elif any(word in lowered for word in ("refresh", "current", "recent")):
        objective_type = "evidence_refresh"
    elif any(word in lowered for word in ("explain", "understand")):
        objective_type = "explain_change"
    elif any(word in lowered for word in ("cost", "save", "right", "spend")):
        objective_type = "cost_optimization"
    else:
        objective_type = "unsupported"
    return ObjectiveInterpretation(
        original_objective=objective,
        objective_type=objective_type,
        normalized_goal=objective or "Review this infrastructure change safely.",
        constraints=["No direct infrastructure mutation", "Human approval is required for remediation"],
        assumptions=["Terraform parsing and safety checks remain deterministic"],
        ambiguities=[] if objective else ["The objective was empty."],
        plain_language_summary="The objective is recorded as business context for deterministic FinOps and safety rules.",
    )


def _sanitized_resource(resource: TerraformResourceChange) -> dict[str, Any]:
    return {
        "address": resource.address,
        "resource_type": resource.resource_type,
        "actions": resource.actions,
        "environment": resource.environment,
        "current_instance_type": resource.current_instance_type,
        "proposed_instance_type": resource.proposed_instance_type,
        "destructive": resource.destructive,
    }


def _sanitized_evidence(evidence: list[EvidenceItem]) -> list[dict[str, Any]]:
    return [
        {
            "source": item.source,
            "claim": item.claim,
            "value": item.value,
            "freshness_status": item.freshness_status,
        }
        for item in evidence
    ]


class AIPlanner:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        retry_executor: RetryExecutor | None = None,
        configuration: Settings = settings,
        client: StructuredAIClient | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.retry_executor = retry_executor or default_retry_executor
        self.configuration = configuration
        self.client = client if client is not None else build_ai_client(configuration)

    def plan(
        self,
        goal: str,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
        deterministic_plan: InvestigationPlan,
    ) -> AIPlannerResult:
        objective = deterministic_objective_interpretation(goal)
        hard_block_reason = self._hard_block_reason(resource)
        if hard_block_reason:
            return self._deterministic_result(
                objective, scenario, resource, deterministic_plan,
                mode="deterministic_only", reason=hard_block_reason, category="hard_policy_precheck",
            )
        if not self.configuration.ai_enabled:
            return self._deterministic_result(
                objective, scenario, resource, deterministic_plan,
                mode="deterministic_only", reason="AI is disabled by configuration.", category="ai_disabled",
            )
        if self.client is None:
            return self._deterministic_result(
                objective, scenario, resource, deterministic_plan,
                mode="deterministic_fallback", reason="The configured AI provider is unsupported.", category="provider_error",
            )

        decisions: list[AIDecisionRecord] = []
        try:
            interpretation_call = self.client.interpret_objective({
                "objective": goal,
                "resource": _sanitized_resource(resource),
                "allowed_objective_types": ["cost_optimization", "safety_review", "evidence_refresh", "explain_change", "unsupported"],
                "deterministic_constraints": ["No direct mutation", "No credentials", "Human approval remains mandatory"],
            })
            interpretation = interpretation_call.value
            if not isinstance(interpretation, ObjectiveInterpretation):
                raise AIClientError("schema_validation_failed", "Objective interpretation schema was invalid.")
            self._validate_interpretation(interpretation)
            mode = interpretation_call.planning_mode
            decisions.append(self._decision(
                len(decisions) + 1, interpretation_call, "interpret_goal", "Objective and sanitized Terraform summary.", None,
                True, "Accepted: objective interpretation passed deterministic schema and safety checks.",
            ))
        except AIClientError as exc:
            return self._deterministic_result(
                objective, scenario, resource, deterministic_plan,
                mode="deterministic_fallback", reason=exc.safe_message, category=exc.category,
                decisions=decisions,
            )
        except Exception:
            return self._deterministic_result(
                objective, scenario, resource, deterministic_plan,
                mode="deterministic_fallback", reason="The objective interpretation was malformed.", category="schema_validation_failed",
                decisions=decisions,
            )

        state = AgentLoopState(
            objective_interpretation=interpretation,
            resource=resource,
            available_tools=list(self.tool_registry.names()),
            maximum_steps=max(1, self.configuration.gemini_max_planning_steps),
            planning_mode=mode,
        )
        all_executions: list[ToolExecutionRecord] = []
        all_evidence: list[EvidenceItem] = []
        mandatory = list(dict.fromkeys(deterministic_plan.selected_tools))
        for step in range(state.maximum_steps):
            state.current_step = step + 1
            state.executed_tools = [record.tool_name for record in all_executions]
            state.collected_evidence = all_evidence
            state.unresolved_questions = [tool for tool in mandatory if tool not in state.executed_tools]
            if scenario.name == "conflicting" and "business_context" not in state.unresolved_questions:
                state.unresolved_questions.append("business_context")
            payload = {
                "objective": interpretation.normalized_goal,
                "objective_type": interpretation.objective_type,
                "resource": _sanitized_resource(resource),
                "available_tools": [name for name in state.available_tools if name not in state.executed_tools],
                "tool_descriptions": {
                    "pricing": "Authoritative current and proposed monthly cost estimate.",
                    "utilization": "Average and peak CPU utilization over a sample window.",
                    "jira": "Project issue key and delivery status.",
                    "git_activity": "Recent commit count and days since last commit.",
                    "dependencies": "Active downstream services and blocking dependencies.",
                },
                "executed_tools": state.executed_tools,
                "evidence": _sanitized_evidence(all_evidence),
                "unresolved_questions": state.unresolved_questions,
                "mandatory_tools": mandatory,
                "deterministic_constraints": ["No direct mutation", "No secrets", "Mandatory evidence cannot be skipped"],
                "scenario_name": scenario.name,
                "conflicts": ["prepared conflict scenario"] if scenario.name == "conflicting" else [],
            }
            try:
                call = self.client.propose_next_action(payload)
                action = call.value
                if not isinstance(action, AgentNextAction):
                    raise AIClientError("schema_validation_failed", "Next-action schema was invalid.")
            except AIClientError as exc:
                return self._deterministic_result(
                    objective=interpretation, scenario=scenario, resource=resource, deterministic_plan=deterministic_plan,
                    mode="deterministic_fallback", reason=exc.safe_message, category=exc.category,
                    decisions=decisions, prior_evidence=all_evidence, prior_executions=all_executions,
                )
            validation = validate_agent_action(action, state, mandatory_tools=mandatory)
            purpose = "choose_next_tool" if action.action == "call_tool" else "decide_next_step"
            if all_evidence and action.action != "call_tool":
                purpose = "interpret_evidence"
            decisions.append(self._decision(
                len(decisions) + 1, call, purpose, f"Step {step + 1}: summarized evidence and unresolved requirements.", action,
                validation.accepted, validation.result,
                error_category=validation.error_category,
            ))
            if not validation.accepted:
                return self._deterministic_result(
                    objective=interpretation, scenario=scenario, resource=resource, deterministic_plan=deterministic_plan,
                    mode="deterministic_fallback", reason=validation.result, category=validation.error_category or "schema_validation_failed",
                    decisions=decisions, prior_evidence=all_evidence, prior_executions=all_executions,
                )
            if action.action == "call_tool":
                one_tool_plan = deterministic_plan.model_copy(deep=True, update={"selected_tools": [action.tool_name]})
                evidence, executions, _ = collect_evidence(one_tool_plan, scenario, resource, self.tool_registry, self.retry_executor)
                all_evidence.extend(evidence)
                all_executions.extend(executions)
                continue
            if action.action == "request_human_context":
                return self._result(
                    mode, interpretation, all_executions, all_evidence, decisions,
                    [tool for tool in mandatory if tool not in {record.tool_name for record in all_executions}],
                    action.human_question, "human_context_requested",
                )
            if action.action == "abstain":
                return self._result(mode, interpretation, all_executions, all_evidence, decisions, state.unresolved_questions, None, "ai_abstain_proposal")
            return self._result(mode, interpretation, all_executions, all_evidence, decisions, state.unresolved_questions, None, "ai_finished_evidence")

        return self._deterministic_result(
            objective=interpretation, scenario=scenario, resource=resource, deterministic_plan=deterministic_plan,
            mode="deterministic_fallback", reason="Gemini planning step limit was reached.", category="maximum_steps_reached",
            decisions=decisions, prior_evidence=all_evidence, prior_executions=all_executions,
        )

    def _deterministic_result(
        self,
        objective: ObjectiveInterpretation,
        scenario: ScenarioDefinition,
        resource: TerraformResourceChange,
        deterministic_plan: InvestigationPlan,
        *,
        mode: str,
        reason: str,
        category: str,
        decisions: list[AIDecisionRecord] | None = None,
        prior_evidence: list[EvidenceItem] | None = None,
        prior_executions: list[ToolExecutionRecord] | None = None,
    ) -> AIPlannerResult:
        prior_evidence = list(prior_evidence or [])
        prior_executions = list(prior_executions or [])
        executed = {record.tool_name for record in prior_executions}
        remaining_plan = deterministic_plan.model_copy(
            deep=True,
            update={"selected_tools": [tool for tool in deterministic_plan.selected_tools if tool not in executed]},
        )
        evidence, executions, _ = collect_evidence(remaining_plan, scenario, resource, self.tool_registry, self.retry_executor)
        combined_evidence = prior_evidence + evidence
        combined_executions = prior_executions + executions
        final_plan = deterministic_plan.model_copy(deep=True, update={"selected_tools": [record.tool_name for record in combined_executions]})
        update_question_resolutions(final_plan, combined_evidence)
        ai_decisions = list(decisions or [])
        ai_decisions.append(AIDecisionRecord(
            sequence_number=len(ai_decisions) + 1,
            model="deterministic-planner",
            planning_mode=mode,
            purpose="decide_next_step",
            input_summary="Sanitized AI planning failure or disabled configuration.",
            proposed_action=None,
            accepted=True,
            validation_result="Deterministic planner executed safely.",
            fallback_used=mode != "deterministic_only",
            fallback_reason=reason,
            latency_ms=0,
            created_at=utc_now(),
            usage_metadata={},
            error_category=category,
            error=None,
        ))
        return self._result(
            mode, objective, combined_executions, combined_evidence, ai_decisions,
            [question.id for question in final_plan.questions if question.status not in {"resolved", "skipped"}],
            None, f"{mode}:{category}",
        )

    @staticmethod
    def _hard_block_reason(resource: TerraformResourceChange) -> str | None:
        if resource.destructive or (resource.environment or "").lower() == "production":
            return "Gemini planning skipped by deterministic destructive or production precheck."
        return None

    @staticmethod
    def _validate_interpretation(interpretation: ObjectiveInterpretation) -> None:
        if not interpretation.normalized_goal.strip():
            raise AIClientError("schema_validation_failed", "Objective normalization was empty.")
        text = " ".join(interpretation.constraints + interpretation.assumptions + interpretation.ambiguities).lower()
        if any(term in text for term in PROHIBITED_OBJECTIVE_TERMS):
            raise AIClientError("unsafe_action_rejected", "Objective interpretation requested prohibited sensitive operations.")

    @staticmethod
    def _decision(
        sequence: int,
        call: Any,
        purpose: str,
        input_summary: str,
        action: AgentNextAction | None,
        accepted: bool,
        validation_result: str,
        *,
        error_category: str | None = None,
    ) -> AIDecisionRecord:
        return AIDecisionRecord(
            sequence_number=sequence,
            model=call.model,
            planning_mode=call.planning_mode,
            purpose=purpose,
            input_summary=input_summary,
            proposed_action=action,
            accepted=accepted,
            validation_result=validation_result,
            fallback_used=False,
            latency_ms=call.latency_ms,
            created_at=utc_now(),
            usage_metadata=call.usage_metadata,
            error_category=error_category,
        )

    @staticmethod
    def _result(
        mode: str,
        objective: ObjectiveInterpretation,
        executions: list[ToolExecutionRecord],
        evidence: list[EvidenceItem],
        decisions: list[AIDecisionRecord],
        unresolved: list[str],
        human_question: str | None,
        termination_reason: str,
    ) -> AIPlannerResult:
        return AIPlannerResult(
            planning_mode=mode, objective_interpretation=objective,
            selected_tools=[record.tool_name for record in executions],
            tool_executions=executions, evidence=evidence, ai_decisions=decisions,
            unresolved_questions=unresolved, human_question=human_question,
            termination_reason=termination_reason,
        )

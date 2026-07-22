"""Public high-level entry point for optional AI-assisted investigation planning."""

from __future__ import annotations

from app.models import AIPlannerResult, InvestigationPlan, ScenarioDefinition, TerraformResourceChange
from app.settings import Settings, settings
from core.ai_client import StructuredAIClient
from core.ai_planner import AIPlanner
from core.planner import create_investigation_plan
from core.retry import RetryExecutor
from integrations.registry import ToolRegistry


def run_agent_investigation(
    goal: str,
    scenario: ScenarioDefinition,
    resource: TerraformResourceChange,
    tool_registry: ToolRegistry,
    deterministic_plan: InvestigationPlan | None = None,
    *,
    configuration: Settings = settings,
    retry_executor: RetryExecutor | None = None,
    ai_client: StructuredAIClient | None = None,
) -> AIPlannerResult:
    """Return validated AI proposals/evidence while leaving decision authority deterministic."""
    plan = deterministic_plan or create_investigation_plan(goal, scenario, resource, tool_registry)
    return AIPlanner(
        tool_registry=tool_registry,
        retry_executor=retry_executor,
        configuration=configuration,
        client=ai_client,
    ).plan(goal, scenario, resource, plan)

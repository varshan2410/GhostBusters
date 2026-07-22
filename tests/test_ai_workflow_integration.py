from __future__ import annotations

from dataclasses import replace

from app.models import RunStatus
from app.settings import settings
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowService
from integrations.registry import default_registry


def test_mock_ai_workflow_records_mode_and_transparent_audit() -> None:
    service = WorkflowService(InMemoryRunStore(), default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock"))
    run, _ = service.start_run_request("safe")
    assert run.decision_record is not None
    assert run.decision_record.planning_mode == "mock_gemini"
    event_types = {event.event_type for event in run.audit_events}
    assert "ai_planning_started" in event_types
    assert "ai_goal_interpreted" in event_types
    assert "ai_action_validated" in event_types
    assert "ai_tool_selected" in event_types
    assert "ai_planning_completed" in event_types
    assert run.status == RunStatus.pending_human_review


def test_hard_blocked_resources_skip_ai_planning() -> None:
    service = WorkflowService(InMemoryRunStore(), default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock"))
    destructive, _ = service.start_run_request("destructive")
    production, _ = service.start_run_request("production")
    for run in (destructive, production):
        assert run.decision_record is not None
        assert run.decision_record.planning_mode == "deterministic_only"
        assert run.decision_record.tool_executions == []
        assert run.status == RunStatus.blocked
        assert any(event.event_type == "deterministic_planner_fallback" for event in run.audit_events)


def test_dependency_safety_remains_deterministic_after_mock_planning() -> None:
    service = WorkflowService(InMemoryRunStore(), default_registry, configuration=replace(settings, ai_enabled=True, ai_provider="mock"))
    run, _ = service.start_run_request("dependency")
    assert run.decision_record is not None
    assert run.decision_record.final_status == "abstained"
    assert run.decision_record.policy_result.allowed is False

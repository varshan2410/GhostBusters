from __future__ import annotations

import pytest

from app.models import HumanReviewRequest
from core.human_review import HumanReviewError, ensure_can_approve, ensure_can_modify
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowService


def test_safe_run_can_be_approved_after_human_review() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")

    decision = ensure_can_approve(run)

    assert decision.preferred_action == "downsize"


def test_blocked_run_cannot_be_approved() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("destructive")

    with pytest.raises(HumanReviewError):
        ensure_can_approve(run)


def test_invalid_modify_is_rejected_before_state_change() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")

    with pytest.raises(HumanReviewError):
        ensure_can_modify(
            run,
            HumanReviewRequest(
                action="modify",
                reviewer="reviewer",
                modified_action="blocked",
            ),
        )


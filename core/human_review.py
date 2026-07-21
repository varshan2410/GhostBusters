"""Human-in-the-loop validation helpers."""

from __future__ import annotations

from app.models import DecisionRecord, HumanReviewRequest, RunStatus, WorkflowRun


class HumanReviewError(Exception):
    """Raised for invalid human review transitions."""


def ensure_can_approve(run: WorkflowRun) -> DecisionRecord:
    decision = run.decision_record
    if run.status != RunStatus.pending_human_review or decision is None:
        raise HumanReviewError("Only runs pending human review can be approved.")
    if run.mock_pr is not None or run.status == RunStatus.pr_created:
        raise HumanReviewError("This run already has a simulated PR.")
    if not decision.policy_result.allowed:
        raise HumanReviewError("Policy does not allow approval.")
    if not decision.policy_result.requires_human_approval:
        raise HumanReviewError("This run does not require human approval.")
    if decision.preferred_action not in {"downsize", "schedule"}:
        raise HumanReviewError("Only downsize or schedule recommendations can be approved.")
    if any(item.status == "failed" and item.severity == "critical" for item in decision.verifier_findings):
        raise HumanReviewError("Critical verifier failure prevents approval.")
    return decision


def ensure_can_reject(run: WorkflowRun) -> None:
    if run.status not in {RunStatus.pending_human_review, RunStatus.needs_more_evidence}:
        raise HumanReviewError("Only pending or evidence-needed runs can be rejected.")


def ensure_can_request_evidence(run: WorkflowRun) -> DecisionRecord:
    if run.status not in {
        RunStatus.pending_human_review,
        RunStatus.needs_more_evidence,
        RunStatus.abstained,
    }:
        raise HumanReviewError("Evidence can only be requested for pending, evidence-needed, or abstained runs.")
    if run.decision_record is None:
        raise HumanReviewError("Run has no decision record.")
    return run.decision_record


def ensure_can_add_context(run: WorkflowRun, request: HumanReviewRequest) -> DecisionRecord:
    if not request.human_context:
        raise HumanReviewError("Human context is required.")
    if run.status in {RunStatus.pr_created, RunStatus.rejected}:
        raise HumanReviewError("Human context cannot be added in this state.")
    if run.decision_record is None:
        raise HumanReviewError("Run has no decision record.")
    return run.decision_record


def ensure_can_modify(run: WorkflowRun, request: HumanReviewRequest) -> DecisionRecord:
    if run.status not in {RunStatus.pending_human_review, RunStatus.needs_more_evidence}:
        raise HumanReviewError("Only pending or evidence-needed runs can be modified.")
    if request.modified_action is None:
        raise HumanReviewError("modified_action is required.")
    if request.modified_action in {"blocked"}:
        raise HumanReviewError("Cannot modify to a blocked action.")
    if run.decision_record is None:
        raise HumanReviewError("Run has no decision record.")
    return run.decision_record

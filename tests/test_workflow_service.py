from __future__ import annotations

from app.models import EvidenceItem, HumanReviewRequest, RunStatus, ScenarioDefinition, TerraformResourceChange, VerifierFinding
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowConflictError, WorkflowService
from integrations.registry import ToolRegistry, default_registry


def test_start_run_status_matrix_and_idempotency() -> None:
    service = WorkflowService(InMemoryRunStore())
    expected = {
        "safe": RunStatus.pending_human_review,
        "dependency": RunStatus.abstained,
        "destructive": RunStatus.blocked,
        "production": RunStatus.blocked,
        "conflicting": RunStatus.needs_more_evidence,
        "missing_evidence": RunStatus.needs_more_evidence,
    }

    for scenario, status in expected.items():
        run, created = service.start_run_request(scenario)
        assert created is True
        assert run.status == status

    first, created = service.start_run_request("safe", "same")
    second, duplicate_created = service.start_run_request("safe", "same")
    assert created is True
    assert duplicate_created is True
    assert first.id != second.id


def test_duplicate_idempotency_key_returns_same_run() -> None:
    from app.models import StartRunRequest

    service = WorkflowService(InMemoryRunStore())
    first, created = service.start_run(StartRunRequest(goal="goal", scenario_name="safe", idempotency_key="abc"))
    second, duplicate_created = service.start_run(StartRunRequest(goal="goal", scenario_name="safe", idempotency_key="abc"))

    assert created is True
    assert duplicate_created is False
    assert first.id == second.id


def test_safe_approval_creates_exactly_one_pr_and_duplicate_does_not_create_second() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")
    request = HumanReviewRequest(action="approve", reviewer="varsha", comment="approved")

    approved, created = service.review_run(run.id, request)
    duplicate, duplicate_created = service.review_run(run.id, request)

    assert created is True
    assert approved.status == RunStatus.pr_created
    assert approved.mock_pr is not None
    assert approved.mock_pr.monthly_savings == 70
    assert duplicate_created is False
    assert duplicate.mock_pr is not None
    assert duplicate.mock_pr.pr_number == approved.mock_pr.pr_number


def test_safe_downsize_pr_is_consistent_with_fixture_and_selected_alternative() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")
    decision = run.decision_record
    assert decision is not None
    downsize = next(item for item in decision.alternatives if item.action == "downsize")
    keep = next(item for item in decision.alternatives if item.action == "keep")

    assert decision.preferred_action == "downsize"
    assert keep.proposed_instance_type == "m5.xlarge"
    assert downsize.proposed_instance_type == "m5.large"
    assert downsize.proposed_instance_type != keep.proposed_instance_type
    assert downsize.estimated_monthly_savings == 70
    assert downsize.estimated_annual_savings == 840

    approved, _ = service.review_run(
        run.id,
        HumanReviewRequest(action="approve", reviewer="varsha", comment="consistent patch"),
    )
    assert approved.mock_pr is not None
    assert approved.mock_pr.chosen_action == "downsize"
    assert approved.mock_pr.current_instance_type == "m5.xlarge"
    assert approved.mock_pr.proposed_instance_type == "m5.large"
    assert '- instance_type = "m5.xlarge"' in approved.mock_pr.terraform_patch_preview
    assert '+ instance_type = "m5.large"' in approved.mock_pr.terraform_patch_preview
    assert '- instance_type = "m5.large"' not in approved.mock_pr.terraform_patch_preview
    assert '+ instance_type = "m5.xlarge"' not in approved.mock_pr.terraform_patch_preview
    assert approved.mock_pr.monthly_savings == 70
    assert approved.mock_pr.annual_savings == 840


def test_unsafe_runs_cannot_be_approved() -> None:
    service = WorkflowService(InMemoryRunStore())
    for scenario in ("destructive", "dependency", "missing_evidence"):
        run, _ = service.start_run_request(scenario)
        try:
            service.review_run(run.id, HumanReviewRequest(action="approve", reviewer="reviewer"))
        except WorkflowConflictError:
            pass
        else:  # pragma: no cover - clearer failure message
            raise AssertionError(f"{scenario} approval unexpectedly succeeded")


def test_reject_pending_and_needs_more_evidence_runs() -> None:
    service = WorkflowService(InMemoryRunStore())
    pending, _ = service.start_run_request("safe")
    evidence_needed, _ = service.start_run_request("missing_evidence")

    rejected_pending, _ = service.review_run(pending.id, HumanReviewRequest(action="reject", reviewer="r", comment="no"))
    rejected_evidence, _ = service.review_run(evidence_needed.id, HumanReviewRequest(action="reject", reviewer="r", comment="not enough"))

    assert rejected_pending.status == RunStatus.rejected
    assert rejected_pending.mock_pr is None
    assert rejected_evidence.status == RunStatus.rejected
    try:
        service.review_run(rejected_pending.id, HumanReviewRequest(action="approve", reviewer="r"))
    except WorkflowConflictError:
        pass
    else:
        raise AssertionError("Rejected run approval unexpectedly succeeded")


def test_request_evidence_reruns_only_requested_tool_and_records_audit() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")
    original_count = len(run.decision_record.tool_executions)  # type: ignore[union-attr]

    updated, _ = service.review_run(
        run.id,
        HumanReviewRequest(action="request_evidence", reviewer="r", requested_sources=["jira"]),
    )

    executions = updated.decision_record.tool_executions  # type: ignore[union-attr]
    assert len(executions) == original_count + 1
    assert executions[-1].tool_name == "jira"
    assert any(event.event_type == "workflow_resumed" for event in updated.audit_events)
    assert any(event.event_type == "additional_evidence_requested" for event in updated.audit_events)


def test_unknown_requested_evidence_source_is_rejected() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")

    try:
        service.review_run(
            run.id,
            HumanReviewRequest(action="request_evidence", reviewer="r", requested_sources=["unknown"]),
        )
    except WorkflowConflictError as exc:
        assert "Unknown evidence source" in str(exc)
    else:
        raise AssertionError("Unknown evidence source unexpectedly succeeded")


def test_tool_failure_is_handled_safely_during_request_evidence() -> None:
    class FailingPricing:
        name = "pricing"

        def collect(
            self,
            scenario: ScenarioDefinition,
            resource: TerraformResourceChange,
        ) -> list[EvidenceItem]:
            raise RuntimeError("pricing timeout")

    service = WorkflowService(InMemoryRunStore(), ToolRegistry([FailingPricing()]))
    run, _ = service.start_run_request("safe")
    updated, _ = service.review_run(
        run.id,
        HumanReviewRequest(action="request_evidence", reviewer="r", requested_sources=["pricing"]),
    )

    assert any(record.status == "failed" for record in updated.decision_record.tool_executions)  # type: ignore[union-attr]
    assert updated.status in {RunStatus.needs_more_evidence, RunStatus.keep, RunStatus.failed_safely}


def test_add_context_becomes_evidence_and_hard_block_remains_blocked() -> None:
    service = WorkflowService(InMemoryRunStore())
    safe, _ = service.start_run_request("safe")
    updated, _ = service.review_run(
        safe.id,
        HumanReviewRequest(
            action="add_context",
            reviewer="r",
            human_context="Required for a customer demo next week.",
        ),
    )
    assert any(item.source == "human_review" for item in updated.decision_record.evidence)  # type: ignore[union-attr]
    assert any(event.event_type == "human_context_added" for event in updated.audit_events)

    blocked, _ = service.start_run_request("production")
    still_blocked, _ = service.review_run(
        blocked.id,
        HumanReviewRequest(action="add_context", reviewer="r", human_context="Please approve."),
    )
    assert still_blocked.status == RunStatus.blocked


def test_modify_eligible_action_requires_later_approval_and_then_pr() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")

    modified, _ = service.review_run(
        run.id,
        HumanReviewRequest(action="modify", reviewer="r", modified_action="schedule"),
    )
    assert modified.status == RunStatus.pending_human_review
    assert modified.mock_pr is None
    assert modified.decision_record.preferred_action == "schedule"  # type: ignore[union-attr]

    approved, created = service.review_run(
        modified.id,
        HumanReviewRequest(action="approve", reviewer="r", comment="schedule instead"),
    )
    assert created is True
    assert approved.mock_pr is not None
    assert approved.mock_pr.chosen_action == "schedule"


def test_ineligible_modify_and_critical_verifier_failure_are_rejected() -> None:
    service = WorkflowService(InMemoryRunStore())
    run, _ = service.start_run_request("safe")
    try:
        service.review_run(run.id, HumanReviewRequest(action="modify", reviewer="r", modified_action="request_evidence"))
    except WorkflowConflictError:
        pass
    else:
        raise AssertionError("Ineligible modify unexpectedly succeeded")

    def add_critical(current):
        assert current.decision_record is not None
        current.decision_record.verifier_findings.append(
            VerifierFinding(
                check_name="critical",
                status="failed",
                severity="critical",
                explanation="forced",
                evidence_sources=[],
            )
        )
        return current

    broken = service.store.update(run.id, add_critical)
    try:
        service.review_run(broken.id, HumanReviewRequest(action="approve", reviewer="r"))
    except WorkflowConflictError:
        pass
    else:
        raise AssertionError("Critical verifier failure approval unexpectedly succeeded")

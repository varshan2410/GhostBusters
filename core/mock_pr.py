"""Deterministic simulated pull request generation."""

from __future__ import annotations

import re

from app.models import Alternative, DecisionRecord, HumanReviewRecord, MockPullRequest, TerraformResourceChange
from core.evidence_utils import monthly_savings
from integrations.base import utc_now


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _selected_alternative(decision: DecisionRecord) -> Alternative:
    return next(item for item in decision.alternatives if item.action == decision.preferred_action)


def create_mock_pull_request(
    *,
    pr_number: int,
    goal: str,
    decision: DecisionRecord,
    resource: TerraformResourceChange,
    approval: HumanReviewRecord,
) -> MockPullRequest:
    alternative = _selected_alternative(decision)
    action = decision.preferred_action
    branch = f"ghostbusters/{_slug(action)}-{_slug(resource.address)}"
    title = f"GhostBusters: {action} {resource.address}"
    monthly = alternative.estimated_monthly_savings or monthly_savings(decision.evidence)
    annual = alternative.estimated_annual_savings or monthly * 12
    before = resource.current_instance_type or "unknown"
    after = alternative.proposed_instance_type or resource.proposed_instance_type or before
    patch = f'- instance_type = "{before}"\n+ instance_type = "{after}"'
    evidence_summary = [
        f"{item.source}: {item.claim}" for item in decision.evidence if item.freshness_status != "unavailable"
    ]
    policy_summary = f"{decision.policy_result.status}: {'; '.join(decision.policy_result.warnings or decision.policy_result.blocking_reasons or ['passed'])}"
    verifier_summary = "; ".join(
        f"{item.check_name}={item.status}" for item in decision.verifier_findings[:6]
    )
    approval_summary = f"Approved by {approval.reviewer}: {approval.comment or 'no comment'}"
    body = (
        f"Goal: {goal}\n\n"
        f"Chosen remediation: {action}\n\n"
        f"Instance type change: {before} -> {after}\n\n"
        f"Monthly savings: ${monthly:.2f}\n"
        f"Annual savings: ${annual:.2f}\n"
        f"Confidence: {decision.confidence.final_confidence:.2f}\n\n"
        f"Evidence summary:\n- " + "\n- ".join(evidence_summary or ["No evidence collected"]) + "\n\n"
        f"Verifier summary: {verifier_summary}\n\n"
        f"Policy summary: {policy_summary}\n\n"
        f"Human approval: {approval_summary}\n\n"
        "Note: this is a simulated PR. No GitHub API call was made."
    )
    return MockPullRequest(
        pr_number=pr_number,
        repository="ghostbusters/demo",
        branch=branch,
        base_branch="main",
        title=title,
        body=body,
        created_at=utc_now(),
        status="open",
        resource_id=resource.address,
        chosen_action=action,
        current_instance_type=resource.current_instance_type,
        proposed_instance_type=after,
        terraform_patch_preview=patch,
        monthly_savings=monthly,
        annual_savings=annual,
        confidence=decision.confidence.final_confidence,
        policy_summary=policy_summary,
        evidence_summary=evidence_summary,
        human_approval_summary=approval_summary,
    )

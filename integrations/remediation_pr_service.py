"""Guarded creation of real GitHub remediation pull requests."""

from __future__ import annotations

import re
from uuid import UUID

from app.models import HumanReviewRecord, RealPullRequest, WorkflowRun
from app.settings import Settings, settings
from core.evidence_utils import active_dependencies
from integrations.base import utc_now
from integrations.github_client import GitHubAPIError, GitHubClient


class RemediationValidationError(Exception):
    pass


class RemediationPRService:
    def __init__(self, client: GitHubClient, configuration: Settings = settings) -> None:
        self.client = client
        self.configuration = configuration

    def create(self, run: WorkflowRun, approval: HumanReviewRecord) -> RealPullRequest:
        source, decision = run.github_source, run.decision_record
        if source is None or decision is None or not source.resource_changes:
            raise RemediationValidationError("GitHub source metadata is incomplete.")
        change = next((item for item in source.resource_changes if item.address == decision.resource_id), source.resource_changes[0])
        if change.destructive or change.replacement:
            raise RemediationValidationError("Destructive remediation is blocked.")
        if (source.environment or "").lower() == "production":
            raise RemediationValidationError("Production remediation is blocked.")
        if active_dependencies(decision.evidence):
            raise RemediationValidationError("Active dependencies block remediation.")
        if any(item.critical for item in decision.missing_evidence):
            raise RemediationValidationError("Critical evidence is missing.")
        if change.source_file not in source.terraform_files:
            raise RemediationValidationError("Target file was not part of the analysed Terraform pull request.")
        attribute = next((item for item in ("instance_type", "machine_type", "size") if item in change.changed_attributes), None)
        if attribute is None:
            raise RemediationValidationError("Only simple size-attribute remediation is supported.")
        expected = (change.after or {}).get(attribute)
        alternative = next((item for item in decision.alternatives if item.action == decision.preferred_action), None)
        replacement = alternative.proposed_instance_type if alternative else None
        if not expected or not replacement or expected == replacement:
            raise RemediationValidationError("A safe old and new size value could not be validated.")
        owner, repo = source.repository.split("/", 1)
        current = self.client.get_file_content(owner, repo, change.source_file, source.head_sha)
        pattern = re.compile(rf'({re.escape(attribute)}\s*=\s*"){re.escape(str(expected))}("\s*)')
        updated, count = pattern.subn(rf'\g<1>{replacement}\g<2>', current["content"])
        if count != 1:
            raise RemediationValidationError("Expected old value was not found exactly once; source may be stale.")
        key = f"{source.repository}:{source.pull_request_number}:{change.address}:{decision.preferred_action}:v{run.version}"
        slug = re.sub(r"[^a-z0-9-]+", "-", change.resource_name.lower()).strip("-")
        branch = f"{self.configuration.github_remediation_branch_prefix}/pr-{source.pull_request_number}-{slug}"
        existing = self.client.list_open_pull_requests(owner, repo, f"{owner}:{branch}")
        if existing:
            item = existing[0]
            return RealPullRequest(repository=source.repository, number=int(item["number"]), url=item["html_url"], branch=branch, base_branch=source.base_branch, title=item.get("title", "GhostBusters remediation"), created_at=utc_now(), idempotency_key=key, reused=True)
        try:
            self.client.get_branch(owner, repo, branch)
        except GitHubAPIError as exc:
            if exc.category != "not_found":
                raise
            self.client.create_branch(owner, repo, branch, source.head_sha)
        self.client.update_or_create_file(owner, repo, branch, change.source_file, updated, f"GhostBusters: {decision.preferred_action} {change.address}", current.get("sha"))
        monthly = alternative.estimated_monthly_savings if alternative else 0
        title = f"GhostBusters: Right-size {change.resource_name}"
        body = (
            f"GhostBusters identified a potential cost optimization.\n\nOriginal PR: #{source.pull_request_number}\n"
            f"Resource: {change.address}\nRecommendation: Change {expected} to {replacement}\n\n"
            "AI-generated explanation:\n" + (decision.objective_interpretation.plain_language_summary if decision.objective_interpretation else "Deterministic planning was used.") + "\n\n"
            "Deterministic evidence:\n- " + "\n- ".join(item.claim for item in decision.evidence) + "\n\n"
            f"Policy result: {decision.policy_result.status}\nHuman approval: {approval.reviewer}\n\n"
            f"Estimated savings: ${monthly:.0f}/month, ${monthly * 12:.0f}/year\n\n"
            "Safety: This PR does not apply infrastructure changes automatically."
        )
        created = self.client.create_pull_request(owner, repo, title, body, branch, source.base_branch)
        return RealPullRequest(repository=source.repository, number=int(created["number"]), url=created["html_url"], branch=branch, base_branch=source.base_branch, title=title, created_at=utc_now(), idempotency_key=key)

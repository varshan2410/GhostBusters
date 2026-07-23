"""Cloud Hunt orchestration and fixture-backed review cases."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models import (
    AuditEvent, CloudHuntRequest, CloudHuntRun, CloudHuntSummary, GhostCandidate,
    MockPullRequest, ReviewCase, ReviewCaseActionRequest,
)
from app.settings import Settings, settings
from core.cloud_candidates import detect_candidates
from core.workflow_service import WorkflowService
from integrations.base import utc_now
from integrations.cloud_registry import CloudProviderRegistry, default_cloud_registry
from core.cloud_hunt_store import CloudHuntPersistence, PostgresCloudHuntPersistence


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CloudHuntNotFoundError(Exception):
    pass


class CloudHuntConflictError(Exception):
    pass


class CloudHuntService:
    def __init__(self, registry: CloudProviderRegistry | None = None, configuration: Settings = settings, workflow_service: WorkflowService | None = None, persistence: CloudHuntPersistence | None = None) -> None:
        self.registry = registry or default_cloud_registry
        self.configuration = configuration
        self.workflow_service = workflow_service
        self.persistence = persistence or (PostgresCloudHuntPersistence(configuration.database_url) if configuration.database_url else None)
        self._hunts: dict[UUID, CloudHuntRun] = {}
        self._cases: dict[UUID, ReviewCase] = {}
        self._waivers: dict[str, datetime] = {}
        if self.persistence is not None:
            self._hunts = {item.id: item for item in self.persistence.list_hunts()}
            self._cases = {item.id: item for item in self.persistence.list_cases()}
            self._waivers = {item.resource_id: item.waiver_expiry for item in self._cases.values() if item.status == "waived" and item.waiver_expiry}

    def providers(self) -> list[dict[str, object]]:
        return [
            {"provider": name, "display_name": self.registry.get(name).display_name, "fixture_backed": True}
            for name in self.registry.names()
            if self.registry.get(name) is not None
        ]

    def fixtures(self, scope: str = "multi_cloud") -> list:
        return self.registry.list_resources(scope)

    def start_hunt(self, request: CloudHuntRequest) -> CloudHuntRun:
        if not self.configuration.cloud_hunt_enabled:
            raise CloudHuntConflictError("Cloud Hunt Mode is disabled by CLOUD_HUNT_ENABLED.")
        started = _now()
        hunt = CloudHuntRun(
            id=uuid4(), trigger_source=request.trigger_source, provider_scope=request.provider_scope,
            inventory_source=request.inventory_source, goal=request.goal, started_at=started,
            status="scanning", planning_mode="deterministic_only",
        )
        self._audit(hunt, "cloud_hunt_started", "Cloud Hunt started from controlled inventory fixtures.", {"provider_scope": request.provider_scope})
        resources = self.registry.list_resources(request.provider_scope)
        hunt.resources_scanned = len(resources)
        for resource in resources:
            self._audit(hunt, "provider_inventory_requested", f"Requested {resource.provider} inventory.", {"provider": resource.provider})
            self._audit(hunt, "resource_normalized", f"Normalized {resource.resource_name}.", {"provider": resource.provider, "resource_id": resource.resource_id})
        candidates = detect_candidates(resources, self.configuration)
        active_candidates: list[GhostCandidate] = []
        for candidate in candidates:
            self._audit(hunt, "candidate_signals_calculated", f"Calculated deterministic score {candidate.candidate_score:.2f}.", {"provider": candidate.resource.provider, "resource_id": candidate.resource.resource_id, "score": candidate.candidate_score})
            if not candidate.requires_investigation:
                self._audit(hunt, "candidate_skipped", f"Skipped healthy resource {candidate.resource.resource_name}.", {"resource_id": candidate.resource.resource_id})
                continue
            expiry = self._waivers.get(candidate.resource.resource_id)
            if expiry and expiry > _now():
                candidate.exclusion_reason = f"Active waiver until {expiry.date().isoformat()}."
                self._audit(hunt, "candidate_skipped", f"Skipped waived resource {candidate.resource.resource_name}.", {"resource_id": candidate.resource.resource_id, "waiver_expiry": expiry.isoformat()})
                continue
            active_candidates.append(candidate)
            self._audit(hunt, "candidate_selected", f"Selected {candidate.resource.resource_name} for investigation.", {"resource_id": candidate.resource.resource_id})
            adapter = self.registry.get(candidate.resource.provider)
            if adapter is not None:
                # These are read-only adapter calls; their normalized outputs feed the case explanation.
                for method_name in ("get_cost_evidence", "get_utilization_evidence", "get_dependency_evidence", "get_activity_evidence", "get_ownership_evidence"):
                    getattr(adapter, method_name)(candidate.resource.resource_id)
                    self._audit(hunt, "provider_adapter_called", f"Collected {method_name.removeprefix('get_').removesuffix('_evidence')} evidence.", {"provider": candidate.resource.provider, "resource_id": candidate.resource.resource_id, "method": method_name})
            case = self._create_case(hunt, candidate)
            self._cases[case.id] = case
            hunt.investigations_created += 1
            self._audit(hunt, "investigation_created", f"Created human review case for {candidate.resource.resource_name}.", {"review_id": str(case.id)})
        hunt.candidates = active_candidates
        hunt.candidates_found = len(active_candidates)
        hunt.protected_resources = sum(1 for item in active_candidates if self._is_protected(item))
        hunt.summary = self._summary(resources, active_candidates)
        hunt.completed_at = _now()
        hunt.status = "completed"
        self._audit(hunt, "cloud_hunt_completed", "Cloud Hunt completed; no provider mutation was performed.", {"candidates": hunt.candidates_found})
        self._hunts[hunt.id] = hunt.model_copy(deep=True)
        if self.persistence is not None:
            self.persistence.save_hunt(hunt)
            for case in self._cases.values():
                if case.source_reference == str(hunt.id):
                    self.persistence.save_case(case)
        return hunt.model_copy(deep=True)

    def list_hunts(self) -> list[CloudHuntRun]:
        return [item.model_copy(deep=True) for item in self._hunts.values()]

    def get_hunt(self, hunt_id: UUID) -> CloudHuntRun:
        if hunt_id not in self._hunts:
            raise CloudHuntNotFoundError(str(hunt_id))
        return self._hunts[hunt_id].model_copy(deep=True)

    def list_cases(self) -> list[ReviewCase]:
        cases = [item.model_copy(deep=True) for item in self._cases.values()]
        if self.workflow_service is not None:
            for run in self.workflow_service.list_runs():
                if run.decision_record is None:
                    continue
                github_source = run.github_source
                terraform_change = None
                if github_source is not None:
                    terraform_change = next(
                        (
                            change
                            for change in github_source.resource_changes
                            if change.address == run.decision_record.resource_id
                        ),
                        github_source.resource_changes[0] if github_source.resource_changes else None,
                    )
                cases.append(ReviewCase(
                    id=run.id, source_type=run.source_type,
                    source_reference=github_source.pull_request_url if github_source else str(run.id),
                    repository=github_source.repository if github_source else None,
                    pull_request_number=github_source.pull_request_number if github_source else None,
                    head_branch=github_source.head_branch if github_source else None,
                    base_branch=github_source.base_branch if github_source else None,
                    commit_sha=github_source.head_sha if github_source else None,
                    provider=github_source.provider if github_source and github_source.provider in {"aws", "azure", "gcp"} else None,
                    resource_id=run.decision_record.resource_id, resource_name=run.decision_record.resource_id,
                    recommendation=run.decision_record.preferred_action,
                    recommendation_reason=run.decision_record.final_summary,
                    confidence=run.decision_record.confidence.final_confidence,
                    risk_level="high" if run.status in {"blocked", "needs_more_evidence"} else "medium",
                    estimated_monthly_savings=next((a.estimated_monthly_savings for a in run.decision_record.alternatives if a.action == run.decision_record.preferred_action), 0),
                    estimated_annual_savings=next((a.estimated_annual_savings for a in run.decision_record.alternatives if a.action == run.decision_record.preferred_action), 0),
                    policy_status=run.decision_record.policy_result.status,
                    required_reviewer_role="platform_engineer", human_decision=run.human_reviews[-1].action if run.human_reviews else None,
                    final_outcome=run.status.value, created_at=run.created_at, updated_at=run.updated_at,
                    status="pr_created" if run.mock_pr or run.real_pr else "pending",
                    candidate=terraform_change,
                    terraform_address=terraform_change.address if terraform_change else None,
                    simulated_pr=run.mock_pr,
                ))
        return cases

    def get_case(self, case_id: UUID) -> ReviewCase:
        if case_id in self._cases:
            return self._cases[case_id].model_copy(deep=True)
        for case in self.list_cases():
            if case.id == case_id:
                return case
        raise CloudHuntNotFoundError(str(case_id))

    def act_on_case(self, case_id: UUID, request: ReviewCaseActionRequest) -> ReviewCase:
        case = self._cases.get(case_id)
        if case is None:
            raise CloudHuntNotFoundError(str(case_id))
        if case.status in {"rejected", "waived", "pr_created"}:
            raise CloudHuntConflictError(f"Review case is already {case.status}.")
        if request.action == "approve":
            if self._is_protected(case.candidate):
                raise CloudHuntConflictError("Protected resources require context and cannot be automatically remediated.")
            case.simulated_pr = self._simulated_pr(case, request.reviewer)
            case.status, case.final_outcome, case.human_decision = "pr_created", "simulated_pr_created", "approve"
        elif request.action == "reject":
            case.status, case.final_outcome, case.human_decision = "rejected", request.comment or "rejected", "reject"
        elif request.action == "waive":
            if request.waiver is None:
                raise CloudHuntConflictError("waiver details are required.")
            self._waivers[case.resource_id] = request.waiver.expiry_date
            case.waiver_expiry = request.waiver.expiry_date
            case.status, case.final_outcome, case.human_decision = "waived", request.waiver.reason, "waive"
            self._case_audit(case, "waiver_created", f"Waiver created by {request.reviewer}.", {"owner": request.waiver.owner, "expiry": request.waiver.expiry_date.isoformat()})
        elif request.action == "request_evidence":
            case.status, case.final_outcome, case.human_decision = "needs_more_evidence", request.comment or "Additional evidence requested", "request_evidence"
        elif request.action == "add_context":
            case.status, case.final_outcome, case.human_decision = "pending", request.human_context or request.comment or "Context added", "add_context"
        elif request.action == "modify":
            if not request.modified_action:
                raise CloudHuntConflictError("modified_action is required.")
            case.recommendation = request.modified_action
            case.status, case.final_outcome, case.human_decision = "pending", "recommendation_modified", "modify"
        case.updated_at = _now()
        self._case_audit(case, "human_decision_recorded", f"{request.action} recorded by {request.reviewer}.", {"comment": request.comment})
        self._cases[case.id] = case.model_copy(deep=True)
        if self.persistence is not None:
            self.persistence.save_case(case)
        return case.model_copy(deep=True)

    def reset(self) -> None:
        self._hunts.clear()
        self._cases.clear()
        self._waivers.clear()
        if self.persistence is not None:
            self.persistence.clear()

    def _create_case(self, hunt: CloudHuntRun, candidate: GhostCandidate) -> ReviewCase:
        resource = candidate.resource
        protected = self._is_protected(candidate)
        recent = any(signal.signal_type == "recent_activity" for signal in candidate.signals)
        unmanaged = not resource.infrastructure_as_code_managed or not resource.terraform_address
        if (resource.environment or "").lower() == "production":
            recommendation = "request_owner_confirmation"
        elif protected:
            recommendation = "keep"
        elif unmanaged and resource.normalized_resource_type == "public_ip":
            recommendation = "release_unused_ip"
        elif unmanaged:
            recommendation = "request_owner_confirmation"
        else:
            recommendation = "stop_for_observation"
        if recent:
            recommendation = "request_owner_confirmation"
        savings = resource.estimated_monthly_cost or 0.0
        return ReviewCase(
            id=uuid4(), source_type="cloud_hunt", source_reference=str(hunt.id), provider=resource.provider,
            resource_id=resource.resource_id, resource_name=resource.resource_name, recommendation=recommendation,
            recommendation_reason=" ".join(signal.description for signal in candidate.signals if signal.supports_ghost_hypothesis) or "Multiple inventory signals require review.",
            confidence=candidate.candidate_score, risk_level="high" if protected or (resource.environment or "").lower() == "production" else "medium",
            estimated_monthly_savings=0.0 if recommendation in {"keep", "request_owner_confirmation"} else savings,
            estimated_annual_savings=0.0 if recommendation in {"keep", "request_owner_confirmation"} else savings * 12,
            policy_status="needs_human_context" if protected or recent else "passed",
            required_reviewer_role="cloud_owner" if protected or (resource.environment or "").lower() == "production" else "application_owner" if not resource.owner else "finops_reviewer",
            created_at=_now(), updated_at=_now(), candidate=candidate, terraform_address=resource.terraform_address,
            status="needs_more_evidence" if recent else "pending",
        )

    def _simulated_pr(self, case: ReviewCase, reviewer: str) -> MockPullRequest:
        resource = case.candidate.resource if isinstance(case.candidate, GhostCandidate) else None
        managed = bool(resource and resource.infrastructure_as_code_managed and resource.terraform_address)
        patch = "Resource is not currently managed by Terraform. Proposal: import into Terraform or create a Jira remediation task." if not managed else f"# Simulated Cloud Hunt proposal\n# {case.recommendation} {resource.terraform_address}\n# No provider mutation was performed."
        return MockPullRequest(
            pr_number=1000 + len(self._cases), repository="ghostbusters/demo", branch=f"ghostbusters/cloud-hunt-{case.resource_id}", base_branch="main",
            title=f"GhostBusters Cloud Hunt: {case.recommendation} {case.resource_name}", body=case.recommendation_reason,
            created_at=_now(), status="open", resource_id=case.resource_id, chosen_action=case.recommendation,
            current_instance_type=None, proposed_instance_type=None, terraform_patch_preview=patch,
            monthly_savings=case.estimated_monthly_savings, annual_savings=case.estimated_annual_savings,
            confidence=case.confidence, policy_summary=case.policy_status,
            evidence_summary=[
                signal.description
                for signal in (case.candidate.signals if isinstance(case.candidate, GhostCandidate) else [])
            ],
            human_approval_summary=f"Approved by {reviewer}: simulated only.",
        )

    @staticmethod
    def _is_protected(candidate: GhostCandidate | object | None) -> bool:
        if not isinstance(candidate, GhostCandidate):
            return False
        return any(signal.signal_type in {"active_dependency", "production_resource", "recent_activity"} for signal in candidate.signals)

    def _summary(self, resources: list, candidates: list[GhostCandidate]) -> CloudHuntSummary:
        provider_breakdown: dict[str, dict[str, int | float]] = {}
        for resource in resources:
            item = provider_breakdown.setdefault(resource.provider, {"scanned": 0, "candidates": 0, "protected": 0, "monthly_waste": 0.0})
            item["scanned"] = int(item["scanned"]) + 1
        for candidate in candidates:
            item = provider_breakdown[candidate.resource.provider]
            item["candidates"] = int(item["candidates"]) + 1
            if CloudHuntService._is_protected(candidate):
                item["protected"] = int(item["protected"]) + 1
            item["monthly_waste"] = float(item["monthly_waste"]) + (candidate.resource.estimated_monthly_cost or 0.0)
        protected = sum(1 for candidate in candidates if CloudHuntService._is_protected(candidate))
        context = sum(1 for candidate in candidates if any(s.signal_type == "recent_activity" for s in candidate.signals))
        monthly = sum(candidate.resource.estimated_monthly_cost or 0.0 for candidate in candidates if not CloudHuntService._is_protected(candidate))
        return CloudHuntSummary(
            total_resources=len(resources), healthy_resources=len(resources) - len(candidates), candidates=len(candidates),
            high_confidence_candidates=sum(1 for candidate in candidates if candidate.candidate_score >= self.configuration.cloud_hunt_high_confidence_threshold),
            protected_candidates=protected, needs_human_context=context, estimated_monthly_waste=monthly,
            estimated_annual_waste=monthly * 12, provider_breakdown=provider_breakdown,
        )

    @staticmethod
    def _audit(hunt: CloudHuntRun, event_type: str, summary: str, details: dict) -> None:
        hunt.audit_events.append(AuditEvent(
            sequence_number=len(hunt.audit_events) + 1, timestamp=_now(), event_type=event_type,
            actor="agent", summary=summary, details=details,
        ))

    @staticmethod
    def _case_audit(case: ReviewCase, event_type: str, summary: str, details: dict) -> None:
        next_sequence = len(case.audit_events) + 1
        case.audit_events.append(AuditEvent(sequence_number=next_sequence, timestamp=_now(), event_type=event_type, actor="human", summary=summary, details=details))


cloud_hunt_service = CloudHuntService()

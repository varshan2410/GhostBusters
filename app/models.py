"""Shared application and evidence models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


FreshnessStatus = Literal["fresh", "stale", "unavailable", "unknown"]
ToolExecutionStatus = Literal["pending", "running", "completed", "failed", "skipped"]
ExternalCallEventType = Literal[
    "external_call_started",
    "external_call_succeeded",
    "external_call_retry_scheduled",
    "external_call_failed",
    "external_call_exhausted",
    "alternative_evidence_selected",
]
QuestionStatus = Literal["unresolved", "resolved", "failed", "skipped"]
ConflictSeverity = Literal["low", "medium", "high"]
AlternativeAction = Literal["keep", "downsize", "schedule", "request_evidence", "abstain", "blocked"]
VerifierStatus = Literal["passed", "warning", "failed"]
VerifierSeverity = Literal["info", "low", "medium", "high", "critical"]
PolicyStatus = Literal["passed", "blocked", "needs_human_context"]
PolicyEngine = Literal["python", "conftest", "python_fallback"]
FinalStatus = Literal["recommendation_ready", "blocked", "abstained", "needs_human_context", "keep"]
HumanReviewAction = Literal["approve", "reject", "request_evidence", "modify", "add_context"]
CloudProvider = Literal["aws", "azure", "gcp"]
CloudProviderScope = Literal["aws", "azure", "gcp", "multi_cloud"]
CloudHuntTrigger = Literal["manual_cloud_hunt", "scheduled_cloud_hunt"]
CloudHuntStatus = Literal["created", "scanning", "completed", "failed"]
NormalizedResourceType = Literal[
    "virtual_machine", "database", "storage_volume", "load_balancer", "public_ip", "other"
]
SuspicionLevel = Literal["low", "medium", "high", "critical"]
GhostSignalType = Literal[
    "low_utilization", "old_resource", "missing_owner", "completed_project",
    "no_recent_activity", "no_dependencies", "unattached_resource", "idle_public_ip",
    "cost_without_usage", "recent_activity", "active_dependency", "production_resource",
]
ReviewCaseSource = Literal["terraform_pr", "cloud_hunt", "manual_demo"]
ReviewCaseStatus = Literal["pending", "approved", "rejected", "needs_more_evidence", "waived", "pr_created"]
RequiredReviewerRole = Literal[
    "application_owner", "finops_reviewer", "platform_engineer", "cloud_owner", "administrator"
]
ObjectiveType = Literal[
    "cost_optimization", "safety_review", "evidence_refresh", "explain_change", "unsupported"
]
AgentAction = Literal["call_tool", "request_human_context", "finish_investigation", "abstain"]
AIPlanningMode = Literal[
    "gemini_primary",
    "gemini_fallback_model",
    "deterministic_fallback",
    "deterministic_only",
    "mock_gemini",
]
AIDecisionPurpose = Literal[
    "interpret_goal", "choose_next_tool", "interpret_evidence", "decide_next_step"
]


class RunStatus(StrEnum):
    created = "created"
    planning = "planning"
    investigating = "investigating"
    verifying = "verifying"
    blocked = "blocked"
    abstained = "abstained"
    keep = "keep"
    pending_human_review = "pending_human_review"
    needs_more_evidence = "needs_more_evidence"
    approved = "approved"
    rejected = "rejected"
    pr_created = "pr_created"
    failed_safely = "failed_safely"


class AppModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(AppModel):
    status: str
    service: str


class TerraformResourceChange(AppModel):
    address: str
    resource_type: str
    actions: list[str]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    environment: str | None = None
    current_instance_type: str | None = None
    proposed_instance_type: str | None = None
    destructive: bool
    tags: dict[str, Any] | None = None


class ObjectiveInterpretation(AppModel):
    original_objective: str
    objective_type: ObjectiveType
    normalized_goal: str
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    plain_language_summary: str


class AgentNextAction(AppModel):
    action: AgentAction
    tool_name: str | None = None
    reason: str
    question_being_answered: str
    expected_information: str
    human_question: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class AIDecisionRecord(AppModel):
    sequence_number: int
    model: str
    planning_mode: AIPlanningMode
    purpose: AIDecisionPurpose
    input_summary: str
    proposed_action: AgentNextAction | None = None
    accepted: bool
    validation_result: str
    fallback_used: bool = False
    fallback_reason: str | None = None
    latency_ms: int | None = None
    created_at: datetime
    usage_metadata: dict[str, Any] = Field(default_factory=dict)
    error_category: str | None = None
    error: str | None = None


class EvidenceItem(AppModel):
    source: str
    tool_name: str
    claim: str
    value: Any
    resource_id: str
    collected_at: datetime
    freshness_status: FreshnessStatus
    reliability: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalCallEvent(AppModel):
    event_type: ExternalCallEventType
    attempt: int
    maximum_attempts: int
    failure_category: str | None = None
    retryable: bool | None = None
    retry_delay_seconds: float | None = None
    elapsed_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class ExternalCallExecutionResult(AppModel):
    tool_name: str
    success: bool
    attempts: int
    retry_exhausted: bool
    failure_category: str | None = None
    retryable: bool | None = None
    final_failure_type: str | None = None
    elapsed_ms: int = 0
    safe_message: str
    events: list[ExternalCallEvent] = Field(default_factory=list)


class ToolExecutionRecord(AppModel):
    tool_name: str
    selected_because: str
    status: ToolExecutionStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    external_call: ExternalCallExecutionResult | None = None


class AgentLoopState(AppModel):
    objective_interpretation: ObjectiveInterpretation
    resource: TerraformResourceChange
    available_tools: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    collected_evidence: list[EvidenceItem] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    ai_decisions: list[AIDecisionRecord] = Field(default_factory=list)
    current_step: int = 0
    maximum_steps: int = 6
    termination_reason: str | None = None
    human_context_required: bool = False
    planning_mode: AIPlanningMode = "deterministic_only"


class ResourceEvidence(AppModel):
    resource_id: str
    environment: str | None = None
    current_instance_type: str | None = None
    proposed_instance_type: str | None = None
    terraform_actions: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    conflicting_claims: list[str] = Field(default_factory=list)


class ScenarioDefinition(AppModel):
    name: str
    description: str
    goal: str
    terraform_plan_file: str
    pricing: dict[str, Any]
    utilization: dict[str, Any]
    jira: dict[str, Any]
    git_activity: dict[str, Any]
    dependencies: dict[str, Any]
    expected_behavior: dict[str, Any]


class InvestigationQuestion(AppModel):
    id: str
    question: str
    required_evidence_sources: list[str] = Field(default_factory=list)
    status: QuestionStatus = "unresolved"
    resolution_summary: str | None = None


class InvestigationPlan(AppModel):
    goal: str
    resource_id: str
    questions: list[InvestigationQuestion] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    skipped_tools: list[str] = Field(default_factory=list)
    planning_notes: list[str] = Field(default_factory=list)


class AIPlannerResult(AppModel):
    planning_mode: AIPlanningMode
    objective_interpretation: ObjectiveInterpretation
    selected_tools: list[str] = Field(default_factory=list)
    tool_executions: list[ToolExecutionRecord] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    ai_decisions: list[AIDecisionRecord] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    human_question: str | None = None
    termination_reason: str


class ConflictRecord(AppModel):
    claim: str
    sources: list[str]
    values: list[Any]
    severity: ConflictSeverity
    explanation: str


class MissingEvidenceRecord(AppModel):
    source: str
    claim_needed: str
    critical: bool
    impact: str


class Alternative(AppModel):
    action: AlternativeAction
    description: str
    proposed_instance_type: str | None = None
    estimated_monthly_cost: float | None = None
    estimated_monthly_savings: float = 0.0
    estimated_annual_savings: float = 0.0
    supporting_evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)


class ConfidenceBreakdown(AppModel):
    evidence_completeness: float = Field(ge=0.0, le=1.0)
    evidence_reliability: float = Field(ge=0.0, le=1.0)
    evidence_freshness: float = Field(ge=0.0, le=1.0)
    conflict_penalty: float = Field(ge=0.0, le=1.0)
    policy_certainty: float = Field(ge=0.0, le=1.0)
    final_confidence: float = Field(ge=0.0, le=1.0)
    explanation: list[str] = Field(default_factory=list)


class VerifierFinding(AppModel):
    check_name: str
    status: VerifierStatus
    severity: VerifierSeverity
    explanation: str
    evidence_sources: list[str] = Field(default_factory=list)


class PolicyViolation(AppModel):
    code: str
    message: str
    severity: VerifierSeverity = "critical"


class PolicyResult(AppModel):
    allowed: bool
    status: PolicyStatus
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_rules: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    engine: PolicyEngine = "python"
    policy_version: str = "1.0"
    violations: list[PolicyViolation] = Field(default_factory=list)
    fallback_reason: str | None = None


class DecisionRecord(AppModel):
    goal: str
    resource_id: str
    investigation_plan: InvestigationPlan
    tool_executions: list[ToolExecutionRecord] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    missing_evidence: list[MissingEvidenceRecord] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    preferred_action: str
    confidence: ConfidenceBreakdown
    verifier_findings: list[VerifierFinding] = Field(default_factory=list)
    policy_result: PolicyResult
    final_status: FinalStatus
    final_summary: str
    planning_mode: AIPlanningMode = "deterministic_only"
    objective_interpretation: ObjectiveInterpretation | None = None
    ai_decisions: list[AIDecisionRecord] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    human_question: str | None = None
    termination_reason: str | None = None


class StartRunRequest(AppModel):
    goal: str
    scenario_name: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    human_context: str | None = None
    idempotency_key: str | None = None


class HumanReviewRequest(AppModel):
    action: HumanReviewAction
    reviewer: str
    comment: str | None = None
    requested_sources: list[str] = Field(default_factory=list)
    modified_action: AlternativeAction | None = None
    human_context: str | None = None


class HumanReviewRecord(AppModel):
    reviewer: str
    action: HumanReviewAction
    comment: str | None = None
    requested_sources: list[str] = Field(default_factory=list)
    modified_action: AlternativeAction | None = None
    human_context: str | None = None
    created_at: datetime


class AuditEvent(AppModel):
    sequence_number: int
    timestamp: datetime
    event_type: str
    actor: Literal["agent", "human", "policy", "system", "tool"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class MockPullRequest(AppModel):
    pr_number: int
    repository: str
    branch: str
    base_branch: str
    title: str
    body: str
    created_at: datetime
    status: str
    resource_id: str
    chosen_action: str
    current_instance_type: str | None = None
    proposed_instance_type: str | None = None
    terraform_patch_preview: str
    monthly_savings: float
    annual_savings: float
    confidence: float
    policy_summary: str
    evidence_summary: list[str] = Field(default_factory=list)
    human_approval_summary: str


class WorkflowRun(AppModel):
    id: UUID
    goal: str
    scenario_name: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    decision_record: DecisionRecord | None = None
    human_reviews: list[HumanReviewRecord] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    mock_pr: MockPullRequest | None = None
    version: int = 1
    idempotency_key: str | None = None
    error: str | None = None


class CloudResource(AppModel):
    provider: CloudProvider
    account_or_subscription_id: str
    region_or_location: str
    resource_id: str
    resource_name: str
    provider_resource_type: str
    normalized_resource_type: NormalizedResourceType
    status: str
    environment: str | None = None
    owner: str | None = None
    project: str | None = None
    created_at: datetime | None = None
    age_days: int | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    infrastructure_as_code_managed: bool | None = None
    terraform_address: str | None = None
    estimated_monthly_cost: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GhostSignal(AppModel):
    signal_type: GhostSignalType
    description: str
    value: Any
    weight: float
    supports_ghost_hypothesis: bool
    evidence_source: str


class GhostCandidate(AppModel):
    candidate_id: str
    resource: CloudResource
    candidate_score: float = Field(ge=0.0, le=1.0)
    suspicion_level: SuspicionLevel
    signals: list[GhostSignal] = Field(default_factory=list)
    requires_investigation: bool
    exclusion_reason: str | None = None


class CloudHuntSummary(AppModel):
    total_resources: int = 0
    healthy_resources: int = 0
    candidates: int = 0
    high_confidence_candidates: int = 0
    protected_candidates: int = 0
    needs_human_context: int = 0
    estimated_monthly_waste: float = 0.0
    estimated_annual_waste: float = 0.0
    provider_breakdown: dict[str, dict[str, int | float]] = Field(default_factory=dict)


class CloudHuntRun(AppModel):
    id: UUID
    trigger_source: CloudHuntTrigger
    provider_scope: CloudProviderScope
    inventory_source: str = "fixtures"
    goal: str
    started_at: datetime
    completed_at: datetime | None = None
    status: CloudHuntStatus
    resources_scanned: int = 0
    candidates_found: int = 0
    investigations_created: int = 0
    protected_resources: int = 0
    errors: list[str] = Field(default_factory=list)
    planning_mode: AIPlanningMode = "deterministic_only"
    audit_events: list[AuditEvent] = Field(default_factory=list)
    summary: CloudHuntSummary = Field(default_factory=CloudHuntSummary)
    candidates: list[GhostCandidate] = Field(default_factory=list)


class ReviewCase(AppModel):
    id: UUID
    source_type: ReviewCaseSource
    source_reference: str
    provider: CloudProvider | None = None
    resource_id: str
    resource_name: str
    recommendation: str
    recommendation_reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: str
    estimated_monthly_savings: float = 0.0
    estimated_annual_savings: float = 0.0
    policy_status: str
    required_reviewer_role: RequiredReviewerRole
    human_decision: str | None = None
    final_outcome: str | None = None
    created_at: datetime
    updated_at: datetime
    waiver_expiry: datetime | None = None
    status: ReviewCaseStatus = "pending"
    candidate: GhostCandidate | None = None
    terraform_address: str | None = None
    simulated_pr: MockPullRequest | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)


class CloudHuntRequest(AppModel):
    provider_scope: CloudProviderScope = "multi_cloud"
    inventory_source: str = "fixtures"
    goal: str = "Find forgotten cloud resources without disrupting active workloads"
    trigger_source: CloudHuntTrigger = "manual_cloud_hunt"


class WaiverRequest(AppModel):
    reason: str
    expiry_date: datetime
    owner: str
    review_date: datetime | None = None


class ReviewCaseActionRequest(AppModel):
    action: Literal["approve", "reject", "request_evidence", "add_context", "modify", "waive"]
    reviewer: str = "demo-reviewer"
    comment: str | None = None
    requested_sources: list[str] = Field(default_factory=list)
    modified_action: str | None = None
    human_context: str | None = None
    waiver: WaiverRequest | None = None

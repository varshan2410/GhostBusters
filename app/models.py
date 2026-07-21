"""Shared application and evidence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FreshnessStatus = Literal["fresh", "stale", "unavailable", "unknown"]
ToolExecutionStatus = Literal["pending", "running", "completed", "failed", "skipped"]
QuestionStatus = Literal["unresolved", "resolved", "failed", "skipped"]
ConflictSeverity = Literal["low", "medium", "high"]
AlternativeAction = Literal["keep", "downsize", "schedule", "request_evidence", "abstain", "blocked"]
VerifierStatus = Literal["passed", "warning", "failed"]
VerifierSeverity = Literal["info", "low", "medium", "high", "critical"]
PolicyStatus = Literal["passed", "blocked", "needs_human_context"]
FinalStatus = Literal["recommendation_ready", "blocked", "abstained", "needs_human_context", "keep"]


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


class ToolExecutionRecord(AppModel):
    tool_name: str
    selected_because: str
    status: ToolExecutionStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None


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


class PolicyResult(AppModel):
    allowed: bool
    status: PolicyStatus
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_rules: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False


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

"""Shared application and evidence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FreshnessStatus = Literal["fresh", "stale", "unavailable", "unknown"]
ToolExecutionStatus = Literal["pending", "running", "completed", "failed", "skipped"]


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


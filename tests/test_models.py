from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    EvidenceItem,
    ResourceEvidence,
    ScenarioDefinition,
    TerraformResourceChange,
    ToolExecutionRecord,
)


def test_core_models_validate_typed_payloads() -> None:
    collected_at = datetime.now(timezone.utc)
    resource = TerraformResourceChange(
        address="aws_instance.app",
        resource_type="aws_instance",
        actions=["update"],
        before={"instance_type": "t3.large"},
        after={"instance_type": "m5.xlarge"},
        environment="staging",
        current_instance_type="t3.large",
        proposed_instance_type="m5.xlarge",
        destructive=False,
        tags={"Environment": "staging"},
    )
    evidence = EvidenceItem(
        source="pricing",
        tool_name="pricing",
        claim="Estimated monthly cost",
        value={"current": 140, "proposed": 70},
        resource_id=resource.address,
        collected_at=collected_at,
        freshness_status="fresh",
        reliability=0.95,
        metadata={"scenario": "safe"},
    )
    record = ToolExecutionRecord(
        tool_name="pricing",
        selected_because="EC2 instance type changed",
        status="completed",
        started_at=collected_at,
        completed_at=collected_at,
        input_summary="one EC2 resource",
        output_summary="pricing evidence collected",
    )
    resource_evidence = ResourceEvidence(
        resource_id=resource.address,
        environment=resource.environment,
        current_instance_type=resource.current_instance_type,
        proposed_instance_type=resource.proposed_instance_type,
        terraform_actions=resource.actions,
        evidence_items=[evidence],
    )
    scenario = ScenarioDefinition(
        name="safe",
        description="Safe staging fixture",
        goal="Reduce staging compute spend",
        terraform_plan_file="fixtures/terraform/safe_plan.json",
        pricing={"available": True},
        utilization={"available": True},
        jira={"available": True},
        git_activity={"available": True},
        dependencies={"available": True},
        expected_behavior={"decision": "safe to review"},
    )

    assert resource.destructive is False
    assert evidence.reliability == 0.95
    assert record.status == "completed"
    assert resource_evidence.evidence_items == [evidence]
    assert scenario.name == "safe"


def test_evidence_reliability_is_bounded() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            source="pricing",
            tool_name="pricing",
            claim="Invalid reliability",
            value=None,
            resource_id="aws_instance.app",
            collected_at=datetime.now(timezone.utc),
            freshness_status="fresh",
            reliability=1.1,
            metadata={},
        )


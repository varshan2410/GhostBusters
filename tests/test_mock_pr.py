from __future__ import annotations

from app.models import HumanReviewRecord
from core.mock_pr import create_mock_pull_request
from core.reasoning_engine import analyze_resource
from integrations.base import utc_now
from integrations.registry import default_registry
from tests.scenario_helpers import load_resource, load_scenario


def test_mock_pr_includes_savings_and_patch_preview() -> None:
    scenario = load_scenario("safe")
    resource = load_resource("safe")
    decision = analyze_resource(scenario.goal, scenario, resource, default_registry)
    approval = HumanReviewRecord(
        reviewer="varsha",
        action="approve",
        comment="approved",
        created_at=utc_now(),
    )

    pr = create_mock_pull_request(
        pr_number=101,
        goal=scenario.goal,
        decision=decision,
        resource=resource,
        approval=approval,
    )

    assert pr.monthly_savings == 70
    assert pr.annual_savings == 840
    assert pr.current_instance_type == "m5.xlarge"
    assert pr.proposed_instance_type == "m5.large"
    assert '- instance_type = "m5.xlarge"' in pr.terraform_patch_preview
    assert '+ instance_type = "m5.large"' in pr.terraform_patch_preview
    assert pr.current_instance_type != pr.proposed_instance_type
    assert "m5.xlarge" in pr.body
    assert "m5.large" in pr.body
    assert "simulated PR" in pr.body

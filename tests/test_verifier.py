from __future__ import annotations

from app.models import Alternative
from core.policy_engine import evaluate_policy
from core.verifier import run_verifier
from integrations.base import build_evidence_item
from tests.scenario_helpers import load_resource


def test_verifier_critical_failure_overrides_optimizer_preference() -> None:
    resource = load_resource("safe")
    preferred = Alternative(
        action="downsize",
        description="Unsafe downsize",
        proposed_instance_type=resource.proposed_instance_type,
        estimated_monthly_savings=70,
        estimated_annual_savings=840,
        supporting_evidence=[],
        risks=[],
        assumptions=[],
        eligible=True,
        score=0.9,
    )
    evidence = [
        build_evidence_item(
            source="pricing",
            tool_name="pricing",
            claim="cost",
            value={"current_monthly_cost": 140, "proposed_monthly_cost": 70},
            resource_id=resource.address,
            freshness_status="fresh",
            reliability=0.95,
        ),
        build_evidence_item(
            source="utilization",
            tool_name="utilization",
            claim="util",
            value={"average_cpu_pct": 20, "peak_cpu_pct": 95},
            resource_id=resource.address,
            freshness_status="fresh",
            reliability=0.95,
        ),
    ]

    findings = run_verifier(resource, evidence, [], preferred)
    policy = evaluate_policy(resource, evidence, [], preferred, findings)

    assert any(item.check_name == "peak_utilization_headroom" and item.status == "failed" for item in findings)
    assert policy.allowed is False


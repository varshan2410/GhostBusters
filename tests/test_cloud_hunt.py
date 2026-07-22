from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import CloudHuntRequest, CloudResource, ReviewCaseActionRequest, WaiverRequest
from core.cloud_candidates import calculate_candidate
from core.cloud_hunt_service import CloudHuntService
from integrations.cloud_registry import build_fixture_cloud_registry


def test_each_provider_fixture_inventory_loads_and_normalizes() -> None:
    registry = build_fixture_cloud_registry()
    assert len(registry.list_resources("aws")) == 4
    assert len(registry.list_resources("azure")) == 3
    assert len(registry.list_resources("gcp")) == 3
    assert len(registry.list_resources("multi_cloud")) == 10
    resource = registry.get("aws").get_resource_details("i-forgotten-test")  # type: ignore[union-attr]
    assert resource is not None
    assert resource.normalized_resource_type == "virtual_machine"


def test_low_cpu_alone_is_not_a_candidate() -> None:
    resource = CloudResource(
        provider="aws", account_or_subscription_id="a", region_or_location="r", resource_id="i", resource_name="i",
        provider_resource_type="ec2", normalized_resource_type="virtual_machine", status="running",
        age_days=2, owner="team", estimated_monthly_cost=10, metadata={"utilization": {"average_cpu_pct": 2}, "dependencies": {"active_downstream_dependencies": ["service"]}},
    )
    candidate = calculate_candidate(resource)
    assert candidate.candidate_score < 0.45
    assert candidate.requires_investigation is False


def test_multiple_signals_create_candidate_and_dependency_protects() -> None:
    registry = build_fixture_cloud_registry()
    forgotten = registry.get("aws").get_resource_details("i-forgotten-test")  # type: ignore[union-attr]
    staging = registry.get("aws").get_resource_details("i-staging-api")  # type: ignore[union-attr]
    assert forgotten is not None and staging is not None
    assert calculate_candidate(forgotten).candidate_score >= 0.75
    protected = calculate_candidate(staging)
    assert protected.requires_investigation is True
    assert any(signal.signal_type == "active_dependency" for signal in protected.signals)


def test_recent_activity_reduces_confidence_and_production_is_protected() -> None:
    registry = build_fixture_cloud_registry()
    idle = registry.get("gcp").get_resource_details("gce-idle-test")  # type: ignore[union-attr]
    production = registry.get("aws").get_resource_details("i-healthy-prod")  # type: ignore[union-attr]
    assert idle is not None and production is not None
    candidate = calculate_candidate(idle)
    assert any(signal.signal_type == "recent_activity" for signal in candidate.signals)
    assert candidate.candidate_score < 0.45
    assert any(signal.signal_type == "production_resource" for signal in calculate_candidate(production).signals)


def test_hunt_summary_cases_and_approval_are_fixture_only() -> None:
    service = CloudHuntService()
    hunt = service.start_hunt(CloudHuntRequest())
    assert hunt.resources_scanned == 10
    assert hunt.candidates_found >= 4
    cases = service.list_cases()
    assert cases
    strong = next(case for case in cases if case.resource_id == "i-forgotten-test")
    approved = service.act_on_case(strong.id, ReviewCaseActionRequest(action="approve", reviewer="judge"))
    assert approved.status == "pr_created"
    assert approved.simulated_pr is not None
    assert "No provider mutation" in approved.simulated_pr.terraform_patch_preview or "Simulated" in approved.simulated_pr.terraform_patch_preview


def test_dependency_protection_and_waiver_suppress_future_hunts() -> None:
    service = CloudHuntService()
    first = service.start_hunt(CloudHuntRequest())
    protected = next(case for case in service.list_cases() if case.resource_id == "i-staging-api")
    try:
        service.act_on_case(protected.id, ReviewCaseActionRequest(action="approve", reviewer="judge"))
    except Exception as exc:
        assert "Protected" in str(exc)
    else:
        raise AssertionError("Dependency-protected resource was approved")
    strong = next(case for case in service.list_cases() if case.resource_id == "i-forgotten-test")
    service.act_on_case(strong.id, ReviewCaseActionRequest(
        action="waive", reviewer="owner", waiver=WaiverRequest(
            reason="Customer migration", owner="owner", expiry_date=datetime.now(timezone.utc) + timedelta(days=7)
        )
    ))
    second = service.start_hunt(CloudHuntRequest())
    assert all(candidate.resource.resource_id != "i-forgotten-test" for candidate in second.candidates)


def test_api_cloud_hunt_and_review_queue() -> None:
    client = TestClient(app)
    client.post("/api/reset")
    assert len(client.get("/api/cloud/providers").json()) == 3
    response = client.post("/api/cloud/hunts", json={"provider_scope": "multi_cloud"})
    assert response.status_code == 200
    hunt = response.json()
    assert hunt["summary"]["total_resources"] == 10
    queue = client.get("/api/reviews")
    assert queue.status_code == 200
    assert any(item["source_type"] == "cloud_hunt" for item in queue.json())

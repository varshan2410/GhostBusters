from __future__ import annotations

from app.models import (
    GitHubTerraformChange,
    GitHubTerraformResourceChange,
    HumanReviewRequest,
    StartRunRequest,
)
from app.settings import Settings
from core.cloud_hunt_service import CloudHuntService
from core.run_store import InMemoryRunStore
from core.workflow_service import WorkflowService
from integrations.github_client import GitHubAPIError


def source(destructive: bool = False, environment: str | None = "staging") -> GitHubTerraformChange:
    return GitHubTerraformChange(
        repository="demo/infra", pull_request_number=42, pull_request_url="https://github.test/demo/infra/pull/42",
        pull_request_title="Resize", author="dev", base_branch="main", base_sha="base", head_branch="resize", head_sha="head",
        changed_files=["infra/main.tf"], terraform_files=["infra/main.tf"], provider="aws", environment=environment,
        resource_changes=[GitHubTerraformResourceChange(address="aws_instance.app", provider="aws", resource_type="aws_instance", resource_name="app", actions=["delete"] if destructive else ["update"], before={"instance_type": "m5.large"}, after={"instance_type": "m5.xlarge"}, changed_attributes=["instance_type"], destructive=destructive, source_file="infra/main.tf")],
    )


def test_github_investigation_review_queue_and_simulated_fallback() -> None:
    service = WorkflowService(InMemoryRunStore(), configuration=Settings(ai_enabled=False, github_integration_enabled=False, github_create_real_pr=False))
    run, created = service.start_github_run(source(), "delivery-42")
    assert created is True
    assert run.status == "pending_human_review"
    assert run.source_type == "terraform_pr"
    cloud_hunt = CloudHuntService(workflow_service=service)
    review = next(case for case in cloud_hunt.list_cases() if case.id == run.id)
    assert review.source_type == "terraform_pr"
    assert review.source_reference.endswith("/pull/42")
    assert review.repository == "demo/infra"
    assert review.pull_request_number == 42
    assert review.head_branch == "resize"
    assert review.base_branch == "main"
    assert review.commit_sha == "head"
    assert review.terraform_address == "aws_instance.app"
    assert isinstance(review.candidate, GitHubTerraformResourceChange)
    approved, _ = service.review_run(run.id, HumanReviewRequest(action="approve", reviewer="judge"))
    assert approved.mock_pr is not None
    assert approved.real_pr is None
    approved_review = next(case for case in cloud_hunt.list_cases() if case.id == run.id)
    assert approved_review.simulated_pr is not None
    assert approved_review.simulated_pr.pr_number == approved.mock_pr.pr_number


def test_manual_demo_review_remains_manual_demo() -> None:
    service = WorkflowService(InMemoryRunStore(), configuration=Settings(ai_enabled=False))
    run, created = service.start_run(
        StartRunRequest(goal="Review the demo safely.", scenario_name="safe")
    )
    assert created is True
    review = next(case for case in CloudHuntService(workflow_service=service).list_cases() if case.id == run.id)
    assert run.source_type == "manual_demo"
    assert review.source_type == "manual_demo"
    assert review.source_reference == str(run.id)
    assert review.repository is None
    assert review.candidate is None
    assert review.terraform_address is None


def test_authenticated_redelivery_reclassifies_legacy_run_without_duplication() -> None:
    service = WorkflowService(InMemoryRunStore(), configuration=Settings(ai_enabled=False))
    legacy, created = service.start_run(
        StartRunRequest(
            goal="Analyze a Terraform pull request for safe FinOps remediation.",
            scenario_name="safe",
            idempotency_key="legacy-delivery-42",
        )
    )
    repaired, duplicate_created = service.start_github_run(
        source(), "legacy-delivery-42"
    )
    assert created is True
    assert duplicate_created is False
    assert repaired.id == legacy.id
    assert repaired.source_type == "terraform_pr"
    assert repaired.github_source is not None
    assert len(service.list_runs()) == 1
    review = CloudHuntService(workflow_service=service).get_case(repaired.id)
    assert review.source_type == "terraform_pr"
    assert review.terraform_address == "aws_instance.app"


def test_destructive_and_production_github_changes_are_blocked_before_normal_approval() -> None:
    service = WorkflowService(InMemoryRunStore(), configuration=Settings(ai_enabled=True, ai_provider="mock"))
    destructive, _ = service.start_github_run(source(destructive=True), "delete")
    production, _ = service.start_github_run(source(environment="production"), "prod")
    assert destructive.status == "blocked"
    assert production.status == "blocked"
    assert destructive.decision_record is not None
    assert destructive.decision_record.planning_mode == "deterministic_only"


def test_explicit_real_pr_mode_uses_guarded_github_writer() -> None:
    class GitHubWriter:
        def __init__(self) -> None:
            self.created = 0
        def get_file_content(self, owner, repo, path, ref):
            return {"content": 'resource "aws_instance" "app" {\n  instance_type = "m5.xlarge"\n}\n', "sha": "file-sha"}
        def list_open_pull_requests(self, owner, repo, head):
            return []
        def get_branch(self, owner, repo, branch):
            raise GitHubAPIError("not_found", "not found")
        def create_branch(self, owner, repo, branch, source_sha):
            return {}
        def update_or_create_file(self, owner, repo, branch, path, content, message, existing_sha):
            assert path == "infra/main.tf"
            return {}
        def create_pull_request(self, owner, repo, title, body, head, base):
            self.created += 1
            return {"number": 77, "html_url": "https://github.test/demo/infra/pull/77"}

    writer = GitHubWriter()
    config = Settings(ai_enabled=False, github_integration_enabled=True, github_create_real_pr=True, github_allowed_repositories=("demo/infra",))
    service = WorkflowService(InMemoryRunStore(), configuration=config, github_client=writer)  # type: ignore[arg-type]
    run, _ = service.start_github_run(source(), "delivery-real-write")
    approved, _ = service.review_run(run.id, HumanReviewRequest(action="approve", reviewer="judge"))
    assert approved.real_pr is not None
    assert approved.mock_pr is None
    assert writer.created == 1

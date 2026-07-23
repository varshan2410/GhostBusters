"""FastAPI application entrypoint for GhostBusters."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    CloudHuntRequest, HealthResponse, HumanReviewRequest, ReviewCaseActionRequest,
    ReviewCase, StartRunRequest, WorkflowRun,
)
from app.settings import settings
from core.run_store import RunNotFoundError
from core.storage_factory import build_webhook_deduplicator
from core.workflow_service import (
    ScenarioNotFoundError,
    WorkflowConflictError,
    list_scenarios,
    workflow_service,
)
from core.cloud_hunt_service import CloudHuntConflictError, CloudHuntNotFoundError, cloud_hunt_service
from integrations.github_client import GitHubAPIError
from integrations.github_webhook import repository_allowed, verify_signature
from integrations.terraform_runner import TerraformAnalysisError, parse_github_terraform_change, select_terraform_files


app = FastAPI(title="GhostBusters", version="0.1.0")
static_path = Path(__file__).resolve().parent.parent / settings.static_dir
webhook_deduplicator = build_webhook_deduplicator()
app.mount("/static", StaticFiles(directory=static_path), name="static")
cloud_hunt_service.workflow_service = workflow_service


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)


@app.get("/")
def home() -> FileResponse:
    index_path = static_path / "index.html"
    return FileResponse(index_path)


@app.get("/api/scenarios")
def api_scenarios() -> dict[str, list[str]]:
    return {"scenarios": list_scenarios()}


@app.post("/api/runs", response_model=WorkflowRun, status_code=201)
def create_run(request: StartRunRequest, response: Response) -> WorkflowRun:
    try:
        run, created = workflow_service.start_run(request)
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Run failed safely: {exc}") from exc
    if not created:
        response.status_code = 200
    return run


@app.get("/api/runs", response_model=list[WorkflowRun])
def list_runs() -> list[WorkflowRun]:
    return workflow_service.list_runs()


@app.get("/api/runs/{run_id}", response_model=WorkflowRun)
def get_run(run_id: UUID) -> WorkflowRun:
    try:
        return workflow_service.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/review", response_model=WorkflowRun)
def review_run(run_id: UUID, request: HumanReviewRequest, response: Response) -> WorkflowRun:
    try:
        run, maybe_pr_created = workflow_service.review_run(run_id, request)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if maybe_pr_created and (run.mock_pr is not None or run.real_pr is not None):
        response.status_code = 201
    return run


@app.post("/api/reset")
def reset_runs() -> dict[str, str]:
    result = workflow_service.reset()
    cloud_hunt_service.reset()
    return result


@app.get("/api/cloud/providers")
def cloud_providers() -> list[dict[str, object]]:
    return cloud_hunt_service.providers()


@app.get("/api/cloud/hunt/fixtures")
def cloud_hunt_fixtures(provider_scope: str = Query("multi_cloud")) -> list[object]:
    return cloud_hunt_service.fixtures(provider_scope)


@app.post("/api/cloud/hunts")
def start_cloud_hunt(request: CloudHuntRequest):
    try:
        return cloud_hunt_service.start_hunt(request)
    except CloudHuntConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/cloud/hunts")
def list_cloud_hunts():
    return cloud_hunt_service.list_hunts()


@app.get("/api/cloud/hunts/{hunt_id}")
def get_cloud_hunt(hunt_id: UUID):
    try:
        return cloud_hunt_service.get_hunt(hunt_id)
    except CloudHuntNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/reviews", response_model=list[ReviewCase])
def list_review_cases(
    source_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    required_role: str | None = None,
    risk: str | None = None,
) -> list[ReviewCase]:
    cases = cloud_hunt_service.list_cases()
    return [case for case in cases if
            (source_type is None or case.source_type == source_type) and
            (provider is None or case.provider == provider) and
            (status is None or case.status == status) and
            (required_role is None or case.required_reviewer_role == required_role) and
            (risk is None or case.risk_level == risk)]


@app.get("/api/reviews/{review_id}", response_model=ReviewCase)
def get_review_case(review_id: UUID) -> ReviewCase:
    try:
        return cloud_hunt_service.get_case(review_id)
    except CloudHuntNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/reviews/{review_id}/action", response_model=ReviewCase)
def act_on_review_case(review_id: UUID, request: ReviewCaseActionRequest) -> ReviewCase:
    try:
        return cloud_hunt_service.act_on_case(review_id, request)
    except CloudHuntNotFoundError:
        if request.action == "waive":
            raise HTTPException(status_code=404, detail="Cloud Hunt review case not found.")
        try:
            run_request = HumanReviewRequest(
                action=request.action, reviewer=request.reviewer, comment=request.comment,
                requested_sources=request.requested_sources, modified_action=request.modified_action, human_context=request.human_context,
            )
            workflow_service.review_run(review_id, run_request)
            return next(case for case in cloud_hunt_service.list_cases() if case.id == review_id)
        except (StopIteration, WorkflowConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CloudHuntConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    response: Response,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, object]:
    if not x_github_delivery:
        raise HTTPException(status_code=422, detail="X-GitHub-Delivery header is required.")
    raw_body = await request.body()
    if settings.github_integration_enabled and not verify_signature(raw_body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature.")
    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"Unsupported event: {x_github_event}"}
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Malformed webhook JSON.") from exc
    action = payload.get("action")
    if action not in {"opened", "reopened", "synchronize"}:
        return {"status": "ignored", "reason": f"Unsupported pull_request action: {action}"}
    repository_delivery = bool(payload.get("repository") or payload.get("pull_request"))
    cached_run_id = webhook_deduplicator.get_run_id(x_github_delivery)
    if cached_run_id is not None:
        try:
            cached_run = workflow_service.get_run(cached_run_id)
            cached_legacy_github_run = (
                settings.github_integration_enabled
                and repository_delivery
                and cached_run.source_type == "manual_demo"
                and cached_run.github_source is None
            )
            if not cached_legacy_github_run:
                return {"status": "duplicate", "run": cached_run}
        except RunNotFoundError:
            pass
    durable = workflow_service.find_run_by_idempotency(x_github_delivery)
    legacy_github_run = (
        durable is not None
        and settings.github_integration_enabled
        and durable.source_type == "manual_demo"
        and durable.github_source is None
        and repository_delivery
    )
    if durable is not None and not legacy_github_run:
        return {"status": "duplicate", "run": durable}
    if settings.github_integration_enabled:
        repository = str((payload.get("repository") or {}).get("full_name") or "")
        if not repository_allowed(repository, settings.github_allowed_repositories):
            raise HTTPException(status_code=403, detail="Repository is not allowed for GitHub integration.")
        client = workflow_service.github_client
        if client is None:
            raise HTTPException(status_code=503, detail="GitHub integration is enabled but credentials are unavailable.")
        try:
            number = int((payload.get("pull_request") or {}).get("number") or payload.get("number"))
            owner, repo = repository.split("/", 1)
            pr = client.get_pull_request(owner, repo, number)
            files = client.list_pull_request_files(owner, repo, number)
            selected, _ = select_terraform_files(files)
            head_sha = str((pr.get("head") or {}).get("sha") or "")
            fetched = {item["filename"]: client.get_file_content(owner, repo, item["filename"], head_sha)["content"] for item in selected}
            source = parse_github_terraform_change(repository, pr, files, fetched)
            run, created = workflow_service.start_github_run(source, x_github_delivery)
        except (GitHubAPIError, TerraformAnalysisError, ValueError, KeyError) as exc:
            detail = str(exc) if isinstance(exc, TerraformAnalysisError) else "GitHub integration failed safely."
            raise HTTPException(status_code=422, detail=detail) from exc
        webhook_deduplicator.remember(x_github_delivery, run.id)
        response.status_code = 201 if created else 200
        return {"status": "created" if created else "duplicate", "run": run}
    if repository_delivery:
        raise HTTPException(
            status_code=503,
            detail="GitHub integration is disabled. Enable it and restart the API before delivering repository webhooks.",
        )
    goal = payload.get("goal") or "Analyze Terraform pull request for safe FinOps remediation."
    scenario_name = payload.get("scenario_name") or "safe"
    try:
        run, created = workflow_service.start_run(
            StartRunRequest(
                goal=goal,
                scenario_name=scenario_name,
                idempotency_key=x_github_delivery,
            )
        )
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    webhook_deduplicator.remember(x_github_delivery, run.id)
    response.status_code = 201 if created else 200
    return {"status": "created" if created else "duplicate", "run": run}

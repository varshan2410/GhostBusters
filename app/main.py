"""FastAPI application entrypoint for GhostBusters."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.models import HealthResponse, HumanReviewRequest, StartRunRequest, WorkflowRun
from app.settings import settings
from core.run_store import RunNotFoundError
from core.storage_factory import build_webhook_deduplicator
from core.workflow_service import (
    ScenarioNotFoundError,
    WorkflowConflictError,
    list_scenarios,
    workflow_service,
)


app = FastAPI(title="GhostBusters", version="0.1.0")
static_path = Path(__file__).resolve().parent.parent / settings.static_dir
webhook_deduplicator = build_webhook_deduplicator()


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
    if maybe_pr_created and run.mock_pr is not None:
        response.status_code = 201
    return run


@app.post("/api/reset")
def reset_runs() -> dict[str, str]:
    return workflow_service.reset()


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    response: Response,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> dict[str, object]:
    if not x_github_delivery:
        raise HTTPException(status_code=422, detail="X-GitHub-Delivery header is required.")
    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"Unsupported event: {x_github_event}"}
    payload = await request.json()
    action = payload.get("action")
    if action not in {"opened", "reopened", "synchronize"}:
        return {"status": "ignored", "reason": f"Unsupported pull_request action: {action}"}
    cached_run_id = webhook_deduplicator.get_run_id(x_github_delivery)
    if cached_run_id is not None:
        try:
            return {"status": "duplicate", "run": workflow_service.get_run(cached_run_id)}
        except RunNotFoundError:
            pass
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

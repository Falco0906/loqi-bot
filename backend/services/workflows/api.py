"""HTTP adapters for legacy web-workflow runtime reads."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.identity import dependencies as identity_dependencies
from services.workspace import access as workspace_access
from services.workflows import service
from services.workflows.events import get_events, get_latest_sequence
from services.workflows.models import PlanningInput
from services.workflows.progress import calculate_progress
from services.workflows.runtime import get_active_runtimes, get_all_runtimes, get_history


router = APIRouter(tags=["Workflows"])


class ExecuteWorkflowRequest(BaseModel):
    plan_id: str
    goal: str
    reasoning: str = ""
    estimated_duration: str = ""
    risk_level: str = "low"
    requires_approval: bool = False
    steps: list[dict]


def _owned_runtime_or_404(workflow_id: str, request: Request | None, session_token: str = ""):
    """Preserve the legacy fail-closed workflow ownership response."""
    bearer_token = identity_dependencies.web_session_token(request) if request is not None else session_token
    runtime = service.owned_runtime(workflow_id, bearer_token)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return runtime


@router.post("/api/web/session/{session_token}/plan")
async def plan_workflow_endpoint(session_token: str, payload: PlanningInput, request: Request = None):
    """Plan against the authenticated caller's explicitly selected workspace."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, owner_id)
    return await service.plan_workspace_workflow(
        user_id=owner_id,
        workspace_id=selected_workspace.workspace_id,
        session_token=session_token,
        objective=payload.objective,
        current_page=payload.current_page,
    )


def _lifecycle_result(operation, workflow_id: str, session_token: str) -> dict:
    try:
        return operation(workflow_id, session_token)
    except service.WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workflow not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/web/session/{session_token}/workflows/execute")
async def execute_workflow_endpoint(
    session_token: str,
    payload: ExecuteWorkflowRequest,
    request: Request = None,
):
    """Start the existing synchronous legacy workflow runtime."""
    session_token = identity_dependencies.web_session_token(request)
    return service.start_workflow(
        session_token=session_token,
        plan_id=payload.plan_id,
        goal=payload.goal,
        reasoning=payload.reasoning,
        estimated_duration=payload.estimated_duration,
        risk_level=payload.risk_level,
        requires_approval=payload.requires_approval,
        steps=payload.steps,
    )


@router.post("/api/web/session/{session_token}/workflows/{workflow_id}/approve")
async def approve_workflow_step(session_token: str, workflow_id: str, request: Request = None):
    """Approve one owned workflow through its canonical lifecycle operation."""
    session_token = identity_dependencies.web_session_token(request)
    return _lifecycle_result(service.approve_workflow_for_session, workflow_id, session_token)


@router.post("/api/web/session/{session_token}/workflows/{workflow_id}/pause")
async def pause_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    """Pause one owned workflow through its canonical lifecycle operation."""
    session_token = identity_dependencies.web_session_token(request)
    return _lifecycle_result(service.pause_workflow_for_session, workflow_id, session_token)


@router.post("/api/web/session/{session_token}/workflows/{workflow_id}/resume")
async def resume_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    """Resume one owned workflow through its canonical lifecycle operation."""
    session_token = identity_dependencies.web_session_token(request)
    return _lifecycle_result(service.resume_workflow_for_session, workflow_id, session_token)


@router.post("/api/web/session/{session_token}/workflows/{workflow_id}/cancel")
async def cancel_workflow_endpoint(session_token: str, workflow_id: str, request: Request = None):
    """Cancel one owned workflow through its canonical lifecycle operation."""
    session_token = identity_dependencies.web_session_token(request)
    return _lifecycle_result(service.cancel_workflow_for_session, workflow_id, session_token)


@router.get("/api/web/session/{session_token}/workflows")
async def list_workflows(session_token: str, request: Request = None):
    """List runtime summaries scoped to the request's bearer session."""
    session_token = identity_dependencies.web_session_token(request)
    workflows = get_all_runtimes(session_token)
    return {
        "ok": True,
        "workflows": [workflow.summary() for workflow in workflows],
        "active": [calculate_progress(workflow) for workflow in get_active_runtimes(session_token)],
    }


@router.get("/api/web/session/{session_token}/workflows/history")
async def workflow_history(
    session_token: str,
    status: str | None = None,
    limit: int = 50,
    request: Request = None,
):
    """Return the legacy session-scoped runtime history envelope."""
    session_token = identity_dependencies.web_session_token(request)
    return {
        "ok": True,
        "history": get_history(session_token, status_filter=status, limit=limit),
    }


@router.get("/api/web/session/{session_token}/workflows/{workflow_id}")
async def get_workflow_status(session_token: str, workflow_id: str, request: Request = None):
    """Return status and progress only for the workflow's creating session."""
    runtime = _owned_runtime_or_404(workflow_id, request, session_token)
    return {
        "ok": True,
        "runtime": runtime.to_dict(),
        "progress": calculate_progress(runtime),
    }


@router.get("/api/web/session/{session_token}/workflows/{workflow_id}/events")
async def get_workflow_events_endpoint(session_token: str, workflow_id: str, request: Request = None):
    """Return the complete legacy workflow event list for its owner."""
    _owned_runtime_or_404(workflow_id, request, session_token)
    return {"ok": True, "events": get_events(workflow_id)}


@router.get("/api/web/session/{session_token}/workflows/{workflow_id}/events/stream")
async def workflow_events_after(
    session_token: str,
    workflow_id: str,
    after: int = 0,
    request: Request = None,
):
    """Return polling events after a sequence cursor; this is not an SSE stream."""
    _owned_runtime_or_404(workflow_id, request, session_token)
    return {
        "ok": True,
        "events": get_events(workflow_id, after_sequence=after),
        "latest_sequence": get_latest_sequence(workflow_id),
    }

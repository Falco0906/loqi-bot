from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.operations.diagnostics import (
    _get_version,
    get_build_metadata,
    get_repository_provider,
)

router = APIRouter(tags=["operations"])


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/ready")
async def ready():
    """Readiness is lifecycle-driven (PR10.6): ALIVE != READY.

    No external calls (no Supabase/Gmail/OpenAI probe) and no optional
    integration is required for readiness — the existing architecture
    intentionally supports degraded-mode operation.
    """
    from services.lifecycle import get_state
    state = get_state()
    if state == "ready":
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": state})


@router.get("/version")
async def version():
    build = get_build_metadata()
    return {
        "application": "Loqi",
        "version": _get_version(),
        "commit": build.get("commit", ""),
        "build_timestamp": build.get("build_timestamp", ""),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "repository_provider": get_repository_provider().value,
    }

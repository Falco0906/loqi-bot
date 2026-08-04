from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.operations.diagnostics import (
    _get_version,
    get_build_metadata,
    get_repository_provider,
    get_startup_time,
    validate_config,
)

router = APIRouter(tags=["operations"])


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/ready")
async def ready():
    failures: list[str] = []

    startup_time = get_startup_time()
    if startup_time is None:
        failures.append("application_startup_not_complete")

    config_errors = validate_config()
    if config_errors:
        failures.append(f"configuration_missing: {', '.join(e['variable'] for e in config_errors)}")

    from services.persistence.database import get_connection_manager
    cm = get_connection_manager()
    if cm is None:
        failures.append("database_connection_not_initialized")
    else:
        client = cm.get_client()
        if client is None:
            failures.append("database_client_unavailable")
        else:
            try:
                import asyncio
                # Probe a table that the launch migrations guarantee to exist,
                # not a throwaway _dummy table (which trips the PostgREST
                # schema cache on freshly migrated databases).
                result = await asyncio.to_thread(
                    lambda: client.table("workflow_sessions").select("id").limit(0).execute()
                )
            except Exception as e:
                failures.append(f"database_connection_failed: {e}")

    provider = get_repository_provider()
    if not provider:
        failures.append("repository_provider_not_initialized")

    if failures:
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "failures": failures},
        )

    return {"status": "ready"}


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

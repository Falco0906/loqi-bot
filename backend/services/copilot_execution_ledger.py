"""Durable idempotency, audit, and observability boundary for Copilot mutations.

This module deliberately owns *execution bookkeeping only*.  Domain services
remain the canonical owners of campaigns, leads, drafts, replies, and jobs.
The ledger lets a retried Copilot turn return its original authoritative tool
outcome without running the domain mutation a second time.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


logger = logging.getLogger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
_TERMINAL = frozenset({"completed", "accepted", "failed", "verification_failed", "declined", "cancelled"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Keep ledger values JSON serializable and bounded enough for auditing."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, list):
        return [_json_safe(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key)[:128]: _json_safe(item) for key, item in list(value.items())[:100]}
    return str(value)[:4000]


def operation_fingerprint(tool_name: str, decision: dict[str, Any]) -> str:
    """Fingerprint server-accepted, non-authority decision fields only.

    User/workspace identity is supplied separately by the authenticated route;
    model-provided identity fields are intentionally excluded.
    """
    allowed = {
        key: decision.get(key)
        for key in (
            "search_context", "lead_ids", "filters", "sort", "limit",
            "campaign_id", "draft_id", "draft_ids", "conversation_id",
            "campaign", "campaign_updates", "edit_request", "send_at",
            "reply_body", "page_context", "active_search",
        )
        if key in decision
    }
    payload = json.dumps(
        {"tool": tool_name, "inputs": _json_safe(allowed)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_request_key(request_id: str | None, *, conversation_key: str, tool_name: str, fingerprint: str) -> str:
    """Prefer a client turn id, but never use it as authority.

    Older clients do not supply a turn id. Their deterministic fallback is
    deliberately conservative: a network replay cannot repeat a mutation.
    Newer clients use a fresh id per submitted turn and may perform an
    intentional identical mutation in a later turn.
    """
    candidate = str(request_id or "").strip()
    if _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    legacy = f"{conversation_key}|{tool_name}|{fingerprint}"
    return "legacy-" + hashlib.sha256(legacy.encode("utf-8")).hexdigest()[:48]


class CopilotExecutionRepository:
    """Supabase repository for the durable Copilot execution/audit ledger."""

    table_name = "copilot_action_executions"

    def __init__(self, client_provider: Callable[[], Any] | None = None) -> None:
        self._client_provider = client_provider

    def _client(self):
        if self._client_provider is not None:
            return self._client_provider()
        from services.supabase import get_supabase_client
        return get_supabase_client()

    async def get(self, *, user_id: str, workspace_id: str, idempotency_key: str) -> dict[str, Any] | None:
        client = self._client()
        if client is None:
            raise RuntimeError("Copilot execution ledger persistence is unavailable")

        def _read():
            return (
                client.table(self.table_name).select("*")
                .eq("user_id", user_id).eq("workspace_id", workspace_id)
                .eq("idempotency_key", idempotency_key).limit(1).execute()
            )

        result = await asyncio.to_thread(_read)
        rows = getattr(result, "data", None) or []
        return dict(rows[0]) if rows and isinstance(rows[0], dict) else None

    async def claim(
        self, *, user_id: str, workspace_id: str, idempotency_key: str,
        fingerprint: str, tool_name: str,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim an execution through the table's unique key.

        A concurrent insert loses at the database boundary, then reads the
        winner's durable record. No in-process lock is relied upon.
        """
        existing = await self.get(
            user_id=user_id, workspace_id=workspace_id, idempotency_key=idempotency_key,
        )
        if existing:
            return existing, False
        client = self._client()
        if client is None:
            raise RuntimeError("Copilot execution ledger persistence is unavailable")
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "workspace_id": workspace_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
            "tool_name": tool_name,
            "status": "running",
            "result": {},
            "audit": {"events": [{"at": _now(), "event": "claimed"}]},
        }
        try:
            await asyncio.to_thread(lambda: client.table(self.table_name).insert(row).execute())
            return row, True
        except Exception:
            # A unique violation is the expected concurrent/retry path. Read
            # only within the exact authenticated tenant scope; otherwise the
            # persistence failure remains explicit and fails closed.
            existing = await self.get(
                user_id=user_id, workspace_id=workspace_id, idempotency_key=idempotency_key,
            )
            if existing:
                return existing, False
            raise

    async def finish(
        self, *, execution_id: str, user_id: str, workspace_id: str,
        status: str, result: dict[str, Any], error_code: str = "",
        audit_event: str,
    ) -> dict[str, Any]:
        client = self._client()
        if client is None:
            raise RuntimeError("Copilot execution ledger persistence is unavailable")
        patch = {
            "status": status,
            "result": _json_safe(result),
            "error_code": error_code or None,
            "completed_at": _now(),
            "updated_at": _now(),
            "audit": {"events": [
                {"at": _now(), "event": "claimed"},
                {"at": _now(), "event": audit_event, "status": status},
            ]},
        }
        # The id is generated locally but the user/workspace predicates make
        # the update tenant-scoped even if a stale/malformed id reaches here.
        response = await asyncio.to_thread(
            lambda: client.table(self.table_name).update(patch)
            .eq("id", execution_id).eq("user_id", user_id).eq("workspace_id", workspace_id)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            raise RuntimeError("Copilot execution record could not be finalized")
        return dict(rows[0])


class CopilotExecutionService:
    """Runs a single mutation once and records a truthful durable outcome."""

    def __init__(self, repository: CopilotExecutionRepository | None = None) -> None:
        self._repository = repository or CopilotExecutionRepository()

    async def _audit(
        self, *, event: str, execution_id: str, user_id: str,
        workspace_id: str, tool_name: str, status: str = "",
    ) -> None:
        """Mirror the durable ledger record into Loqi's canonical audit log.

        The execution row remains the recovery authority. An audit-log outage
        cannot make a completed domain mutation disappear or invite a retry.
        """
        try:
            from services.persistence.launch import AuditLogRepository
            await AuditLogRepository().record(
                workspace_id=workspace_id,
                user_id=user_id,
                action=f"copilot.{event}",
                entity_type="copilot_action_execution",
                entity_id=execution_id,
                request_id=execution_id,
                metadata={"tool": tool_name, "status": status},
                actor_type="user",
            )
        except Exception:
            logger.warning("copilot.execution.audit_log_failed event=%s execution=%s", event, execution_id, exc_info=True)

    async def execute(
        self, *, tool_name: str, user_id: str, workspace_id: str,
        request_id: str | None, conversation_key: str, decision: dict[str, Any],
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not user_id or not workspace_id:
            logger.warning("copilot.execution.rejected reason=missing_authenticated_scope tool=%s", tool_name)
            return {"ok": False, "status": "authorization_failed", "tool": tool_name,
                    "reason": "Copilot could not verify the active workspace for this change."}
        fingerprint = operation_fingerprint(tool_name, decision)
        key = safe_request_key(request_id, conversation_key=conversation_key, tool_name=tool_name, fingerprint=fingerprint)
        try:
            record, claimed = await self._repository.claim(
                user_id=user_id, workspace_id=workspace_id, idempotency_key=key,
                fingerprint=fingerprint, tool_name=tool_name,
            )
        except Exception:
            logger.exception("copilot.execution.ledger_unavailable tool=%s workspace=%s", tool_name, workspace_id)
            return {"ok": False, "status": "recovery_required", "tool": tool_name,
                    "reason": "Copilot could not safely record this change, so no action was taken."}

        if not claimed:
            if str(record.get("request_fingerprint") or "") != fingerprint or str(record.get("tool_name") or "") != tool_name:
                logger.warning("copilot.execution.idempotency_conflict tool=%s workspace=%s", tool_name, workspace_id)
                return {"ok": False, "status": "idempotency_conflict", "tool": tool_name,
                        "reason": "This request identifier is already associated with a different Copilot action."}
            status = str(record.get("status") or "")
            logger.info("copilot.execution.replayed tool=%s workspace=%s execution=%s status=%s", tool_name, workspace_id, record.get("id"), status)
            if status == "running":
                return {"ok": False, "status": "in_progress", "tool": tool_name,
                        "execution_id": record.get("id"),
                        "reason": "This change is already running. Copilot will use its recorded result when it completes."}
            result = record.get("result")
            if isinstance(result, dict):
                return {**result, "replayed": True, "execution_id": record.get("id")}
            return {"ok": False, "status": "recovery_required", "tool": tool_name,
                    "execution_id": record.get("id"),
                    "reason": "The prior change has a durable record but no recoverable result."}

        execution_id = str(record.get("id") or "")
        logger.info("copilot.execution.claimed tool=%s workspace=%s execution=%s", tool_name, workspace_id, execution_id)
        await self._audit(
            event="claimed", execution_id=execution_id, user_id=user_id,
            workspace_id=workspace_id, tool_name=tool_name, status="running",
        )
        try:
            logger.info("copilot.execution.tool_started tool=%s workspace=%s execution=%s", tool_name, workspace_id, execution_id)
            result = await operation()
        except Exception:
            logger.exception("copilot.execution.tool_exception tool=%s workspace=%s execution=%s", tool_name, workspace_id, execution_id)
            result = {"ok": False, "status": "failed", "tool": tool_name,
                      "reason": "Copilot could not complete the requested change."}

        if not isinstance(result, dict):
            result = {"ok": False, "status": "failed", "tool": tool_name,
                      "reason": "Copilot received an invalid result from the requested change."}
        result.setdefault("tool", tool_name)
        status = str(result.get("status") or ("completed" if result.get("ok") else "failed"))
        if status in {"failed", "verification_failed", "declined", "cancelled"}:
            # A terminal failure status is authoritative even if a legacy
            # adapter accidentally leaves an optimistic ``ok`` flag behind.
            result["ok"] = False
        if status not in _TERMINAL:
            # Accepted durable jobs are real outcomes; their linked job owns
            # follow-up/recovery. All other non-terminal responses remain
            # explicit rather than being presented as success.
            status = "accepted" if status in {"queued", "running", "accepted"} and result.get("operation") else "failed"
            result["status"] = status
            result["ok"] = status == "accepted"
        try:
            await self._repository.finish(
                execution_id=execution_id, user_id=user_id, workspace_id=workspace_id,
                status=status, result=result,
                error_code="" if result.get("ok") else status,
                audit_event="verified" if status == "completed" else status,
            )
        except Exception:
            # The domain operation may have happened. Do not claim success
            # without its recoverable ledger outcome; the next attempt must
            # inspect the running record instead of duplicate it.
            logger.exception("copilot.execution.finalize_failed tool=%s workspace=%s execution=%s", tool_name, workspace_id, execution_id)
            return {"ok": False, "status": "recovery_required", "tool": tool_name,
                    "execution_id": execution_id,
                    "reason": "The change may need recovery because Copilot could not record its final state."}

        logger.info("copilot.execution.finished tool=%s workspace=%s execution=%s status=%s verified=%s", tool_name, workspace_id, execution_id, status, status == "completed")
        await self._audit(
            event="finished", execution_id=execution_id, user_id=user_id,
            workspace_id=workspace_id, tool_name=tool_name, status=status,
        )
        return {**result, "execution_id": execution_id}

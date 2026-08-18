"""Shared abandoned-registration cleanup logic (SaaS lifecycle).

Single source of truth for the conservative abandoned-registration predicate
and cleanup used by:

1. the manual operator CLI (scripts/cleanup_abandoned_registration.py)
2. the automatic periodic cleanup (wired into the app lifespan)
3. lazy signup reclaim (AuthService.begin_registration)

SAFE-TO-CLEAN (all must hold, else REFUSE / SKIP and delete nothing for that
email):
- no email_identities row is linked to a user (user_id == "")
- no registration_sessions is COMPLETED
- no registration_session.user_id resolves to an existing identity_users row
- (automatic mode additionally requires every registration for the email to be
  EXPIRED — a non-expired registration means the flow may still be active)

Only these tables are ever deleted (in this order): registration_sessions,
verification_tokens, unlinked email_identities. identity_users, credentials,
sessions, refresh tokens, organizations, workspaces, connected/external
identities, and billing are NEVER selected.

PostgREST has no multi-statement transaction: cleanup is idempotent (deleting
an already-deleted row is a no-op) and each row is re-verified immediately
before deletion in apply mode, so concurrent/duplicate execution is harmless.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("loqi.identity.registration_cleanup")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

CLEAN_TABLES = ("registration_sessions", "verification_tokens", "email_identities")


def abandoned_cleanup_runtime_enabled() -> tuple[bool, str]:
    """Fail-closed runtime gate for AUTOMATIC abandoned-registration cleanup.

    Automatic cleanup (periodic job AND request-path lazy reclaim) may only
    run when BOTH:
    - the application is in an explicitly production environment
      (config_validation.is_production: ENVIRONMENT or APP_ENV == production)
    - AND ABANDONED_REGISTRATION_CLEANUP_ENABLED is explicitly set to a truthy
      value ("1"/"true"/"yes")

    Any other state (development, missing variable, unknown value) disables
    automatic cleanup. This is defense in depth: tests that set
    ENVIRONMENT=production while entering the lifespan, or that connect to a
    shared Supabase project through a local .env, can never trigger a
    destructive cleanup because the explicit enable flag is absent in tests.

    Returns (enabled, reason). The operator CLI is NOT gated by this — it is
    an explicit human action with its own dry-run/--apply contract.
    """
    from services.config_validation import is_production

    if not is_production():
        return False, "not an explicitly production environment"
    raw = os.getenv("ABANDONED_REGISTRATION_CLEANUP_ENABLED", "").strip().lower()
    if raw not in {"1", "true", "yes"}:
        return False, "ABANDONED_REGISTRATION_CLEANUP_ENABLED is not enabled"
    return True, "enabled"


def resolve_automatic_cleanup_client() -> Any:
    """Resolve the Supabase client for AUTOMATIC cleanup, or None.

    This is the ONLY way automatic call sites (the periodic loop and the
    request-path lazy reclaim) may obtain a client. It returns None unless the
    fail-closed runtime gate is satisfied, so automatic cleanup never
    implicitly resolves the shared ``get_supabase_client()``. Tests exercise
    the automatic path by injecting an explicit fake client into the execution
    functions; they can never reach a real external cleanup target through
    this accessor while the gate is not satisfied.
    """
    enabled, _reason = abandoned_cleanup_runtime_enabled()
    if not enabled:
        return None
    from services.supabase import get_supabase_client
    return get_supabase_client()


def normalize_email(email: str) -> str:
    """Mirror AuthService._normalize_email exactly (strip + lowercase)."""
    return (email or "").strip().lower()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at: str | None, now: str) -> bool:
    return bool(expires_at) and str(expires_at) < now


@dataclass
class AbandonedPlan:
    target_email: str = ""
    delete: dict[str, list[str]] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)
    orphan_identity_user_ids: list[str] = field(default_factory=list)
    refusal_reason: str = ""
    require_expired: bool = False

    def summarize(self) -> dict[str, Any]:
        return {
            "target_email": self.target_email,
            "found": self.found,
            "deletes_by_table": {t: len(v) for t, v in self.delete.items() if v},
            "total_rows": sum(len(v) for v in self.delete.values()),
            "orphan_identity_user_ids": self.orphan_identity_user_ids,
            "refusal_reason": self.refusal_reason,
            "require_expired": self.require_expired,
        }


def build_abandoned_plan(
    *,
    target_email: str,
    registration_sessions: list[dict[str, Any]],
    verification_tokens: list[dict[str, Any]],
    email_identities: list[dict[str, Any]],
    identity_users: list[dict[str, Any]],
    require_expired: bool = False,
    now: str | None = None,
) -> AbandonedPlan:
    """Pure plan-builder. Conservative: refuses on any sign of a canonical
    account; never selects identity_users/credentials/sessions/orgs/billing."""
    plan = AbandonedPlan(require_expired=require_expired)
    email = normalize_email(target_email)
    if not email:
        plan.refusal_reason = "target email is empty"
        return plan
    if not _EMAIL_RE.match(email):
        plan.refusal_reason = "target email is not a valid email"
        return plan
    plan.target_email = email
    now = now or _iso_now()

    identities = [ei for ei in email_identities if str(ei.get("email", "")).lower() == email]
    regs = [rs for rs in registration_sessions if str(rs.get("email", "")).lower() == email]
    tokens = [vt for vt in verification_tokens if str(vt.get("target", "")).lower() == email]

    plan.found = {
        "registration_sessions": len(regs),
        "verification_tokens": len(tokens),
        "email_identities": len(identities),
    }

    identity_ids = {str(u.get("id", "")) for u in identity_users}

    # HARD REFUSALS (a canonical account may exist).
    linked = [ei for ei in identities if str(ei.get("user_id", ""))]
    if linked:
        plan.refusal_reason = (
            "email identity is linked to a user; this looks like a completed account — refusing"
        )
        return plan
    for rs in regs:
        if str(rs.get("status", "")).lower() == "completed":
            plan.refusal_reason = "a completed registration exists for this email — refusing"
            return plan
        rs_user = str(rs.get("user_id", "") or "")
        if rs_user and rs_user in identity_ids:
            plan.refusal_reason = (
                "a registration references an existing canonical user — refusing"
            )
            return plan

    # Automatic mode: a non-expired registration means the flow may still be
    # active. Prefer leaving the email blocked over deleting mid-flow state.
    if require_expired:
        active = [rs for rs in regs if not _is_expired(rs.get("expires_at"), now)]
        if active:
            plan.refusal_reason = "active (non-expired) registration present — skipping"
            return plan

    # Orphan identity_user references from failed completions: report only.
    for rs in regs:
        rs_user = str(rs.get("user_id", "") or "")
        if rs_user and rs_user not in identity_ids and rs_user not in plan.orphan_identity_user_ids:
            plan.orphan_identity_user_ids.append(rs_user)

    # Only ever delete these three tables, and only rows proven to belong to
    # this abandoned registration.
    candidates = {
        "registration_sessions": [str(rs.get("id", "")) for rs in regs if rs.get("id")],
        "verification_tokens": [str(vt.get("id", "")) for vt in tokens if vt.get("id")],
        "email_identities": [str(ei.get("id", "")) for ei in identities if ei.get("id")],
    }
    for table, ids in candidates.items():
        if ids:
            plan.delete[table] = ids
    return plan


def apply_abandoned_plan(
    plan: AbandonedPlan,
    *,
    dry_run: bool = True,
    client: Any = None,
    identity_user_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply the plan. In dry-run returns the summary without writing.

    In apply mode, each row is re-verified against its current DB state
    immediately before deletion (idempotent; concurrent/duplicate runs are
    harmless; PostgREST non-transactionality is handled per-row best-effort).
    """
    summary = plan.summarize()
    if dry_run:
        return summary
    if plan.refusal_reason:
        return summary  # never mutate on refusal

    if client is None:
        from services.supabase import get_supabase_client
        client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    email = plan.target_email
    now = _iso_now()

    # Resolve identity_users ids once (needed to re-verify session user links).
    if identity_user_ids is None:
        try:
            ids = getattr(client.table("identity_users").select("id").execute(), "data", None) or []
            identity_user_ids = {str(r.get("id", "")) for r in ids}
        except Exception:
            identity_user_ids = set()

    failures: list[dict[str, Any]] = []
    applied = 0

    # Re-read each row and re-verify it still belongs to this abandoned
    # registration before deleting (race-safe compare-then-delete best effort).
    for rs_id in plan.delete.get("registration_sessions", []):
        try:
            row = _get_row(client, "registration_sessions", rs_id)
            if row is None:
                continue  # already removed — idempotent
            status = str(row.get("status", "")).lower()
            rs_user = str(row.get("user_id", "") or "")
            expired = _is_expired(row.get("expires_at"), now)
            if status == "completed" or (rs_user and rs_user in identity_user_ids):
                continue
            if plan.require_expired and not expired:
                continue
            client.table("registration_sessions").delete().eq("id", rs_id).execute()
            applied += 1
        except Exception as exc:  # noqa: BLE001
            failures.append({"table": "registration_sessions", "id": rs_id, "error": type(exc).__name__})

    for vt_id in plan.delete.get("verification_tokens", []):
        try:
            row = _get_row(client, "verification_tokens", vt_id)
            if row is None:
                continue
            if str(row.get("target", "")).lower() != email:
                continue
            client.table("verification_tokens").delete().eq("id", vt_id).execute()
            applied += 1
        except Exception as exc:  # noqa: BLE001
            failures.append({"table": "verification_tokens", "id": vt_id, "error": type(exc).__name__})

    for ei_id in plan.delete.get("email_identities", []):
        try:
            row = _get_row(client, "email_identities", ei_id)
            if row is None:
                continue
            if str(row.get("email", "")).lower() != email or str(row.get("user_id", "")):
                continue  # unlinked only
            client.table("email_identities").delete().eq("id", ei_id).execute()
            applied += 1
        except Exception as exc:  # noqa: BLE001
            failures.append({"table": "email_identities", "id": ei_id, "error": type(exc).__name__})

    summary["applied_updates"] = applied
    summary["failures"] = failures
    return summary


def _get_row(client: Any, table: str, row_id: str) -> dict[str, Any] | None:
    try:
        result = client.table(table).select("*").eq("id", row_id).limit(1).execute()
        data = getattr(result, "data", None) or []
        return data[0] if data else None
    except Exception:
        return None


def _load_snapshot(client: Any | None = None, email: str | None = None):
    if client is None:
        from services.supabase import get_supabase_client
        client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    def _rows(table, select="*", field=None):
        q = client.table(table).select(select)
        if field and email:
            q = q.eq(field, email)
        try:
            return getattr(q.execute(), "data", None) or []
        except Exception:
            return []

    if email:
        registration_sessions = _rows("registration_sessions", "id, email, status, user_id, expires_at", "email")
        verification_tokens = _rows("verification_tokens", "id, target, purpose, used_at", "target")
        email_identities = _rows("email_identities", "id, email, user_id, is_verified, is_primary", "email")
        # Load identity_users ids only when needed for the user-link check.
        identity_users = _rows("identity_users", "id") if any(
            str(rs.get("user_id", "")) for rs in registration_sessions
        ) else []
        return registration_sessions, verification_tokens, email_identities, identity_users
    registration_sessions = _rows("registration_sessions", "id, email, status, user_id, expires_at")
    verification_tokens = _rows("verification_tokens", "id, target, purpose, used_at")
    email_identities = _rows("email_identities", "id, email, user_id, is_verified, is_primary")
    identity_users = _rows("identity_users", "id")
    return registration_sessions, verification_tokens, email_identities, identity_users


def cleanup_abandoned_email(
    email: str,
    *,
    dry_run: bool = True,
    require_expired: bool = False,
    client: Any = None,
) -> tuple[AbandonedPlan, dict[str, Any]]:
    """Reclaim an email blocked by abandoned registration state.

    Used by lazy signup cleanup (require_expired=True) and by the operator CLI.
    Never touches a canonical account; ambiguous states are refused.
    """
    regs, tokens, identities, users = _load_snapshot(client=client, email=normalize_email(email))
    plan = build_abandoned_plan(
        target_email=email,
        registration_sessions=regs,
        verification_tokens=tokens,
        email_identities=identities,
        identity_users=users,
        require_expired=require_expired,
    )
    summary = apply_abandoned_plan(plan, dry_run=dry_run, client=client,
                                   identity_user_ids={str(u.get("id", "")) for u in users})
    return plan, summary


def run_abandoned_cleanup(
    *,
    dry_run: bool = True,
    client: Any = None,
) -> dict[str, Any]:
    """Scan all registrations and clean every SAFE-TO-CLEAN expired abandoned
    one. Returns counts; never logs emails/tokens. Idempotent + race-safe."""
    if client is None:
        from services.supabase import get_supabase_client
        client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    regs, tokens, identities, users = _load_snapshot(client=client)
    identity_ids = {str(u.get("id", "")) for u in users}

    # Group rows by normalized email.
    by_email: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rs in regs:
        by_email.setdefault(normalize_email(str(rs.get("email", ""))), {}).setdefault(
            "registration_sessions", []).append(rs)
    for vt in tokens:
        by_email.setdefault(normalize_email(str(vt.get("target", ""))), {}).setdefault(
            "verification_tokens", []).append(vt)
    for ei in identities:
        by_email.setdefault(normalize_email(str(ei.get("email", ""))), {}).setdefault(
            "email_identities", []).append(ei)

    scanned = 0
    cleaned_emails = 0
    skipped = 0
    cleaned_rows = 0
    failures = 0
    for email, rows in by_email.items():
        if not email:
            continue
        scanned += 1
        plan = build_abandoned_plan(
            target_email=email,
            registration_sessions=rows.get("registration_sessions", []),
            verification_tokens=rows.get("verification_tokens", []),
            email_identities=rows.get("email_identities", []),
            identity_users=users,
            require_expired=True,
        )
        if plan.refusal_reason:
            skipped += 1
            continue
        if not plan.delete:
            continue
        summary = apply_abandoned_plan(plan, dry_run=dry_run, client=client,
                                       identity_user_ids=identity_ids)
        cleaned_rows += summary.get("applied_updates", 0)
        failures += len(summary.get("failures", []))
        if not dry_run:
            cleaned_emails += 1
        else:
            cleaned_emails += 1  # dry-run counts candidate emails too

    return {
        "scanned": scanned,
        "cleaned_emails": cleaned_emails,
        "cleaned_rows": cleaned_rows,
        "skipped": skipped,
        "failures": failures,
        "dry_run": dry_run,
    }
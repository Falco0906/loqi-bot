"""Safe cleanup of ABANDONED / FAILED email signups (pre-account recovery).

Operator fallback for reclaiming emails blocked by abandoned registration
state. The conservative predicate and delete logic now live in the shared
module `services/identity/registration_cleanup.py` (single source of truth,
also used by the automatic periodic cleanup and lazy signup reclaim).

Manual mode does NOT require the registration to be expired (the operator is
explicitly targeting it); the automatic job requires expiry. It only ever
deletes: registration_sessions, verification_tokens, and UNLINKED
email_identities. It never deletes identity_users, credentials, sessions,
refresh tokens, organizations, workspaces, connected/external identities, or
billing.

Dry-run by default; only --apply mutates. Idempotent.

Usage:
    python3 backend/scripts/cleanup_abandoned_registration.py --email user@example.com
    python3 backend/scripts/cleanup_abandoned_registration.py --email user@example.com --apply
    python3 backend/scripts/cleanup_abandoned_registration.py --registration-session-id <id> [--apply]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

# Re-export the shared single-source-of-truth logic so existing importers and
# tests keep working unchanged.
from services.identity.registration_cleanup import (  # noqa: E402
    AbandonedPlan,
    apply_abandoned_plan,
    build_abandoned_plan,
    cleanup_abandoned_email,
    normalize_email,
)

__all__ = ["AbandonedPlan", "apply_abandoned_plan", "build_abandoned_plan", "normalize_email"]


def _load_snapshot():
    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    def _rows(table, select="*"):
        try:
            return getattr(client.table(table).select(select).execute(), "data", None) or []
        except Exception:
            return []

    return {
        "registration_sessions": _rows("registration_sessions", "id, email, status, user_id, expires_at"),
        "verification_tokens": _rows("verification_tokens", "id, target, purpose, used_at"),
        "email_identities": _rows("email_identities", "id, email, user_id, is_verified, is_primary"),
        "identity_users": _rows("identity_users", "id"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean up abandoned / failed email signups (pre-account recovery)",
    )
    parser.add_argument("--email", default="", help="target email (normalized exactly as signup)")
    parser.add_argument("--registration-session-id", dest="reg_id", default="",
                        help="optionally pin a specific registration session (must match --email)")
    parser.add_argument("--apply", action="store_true", help="perform deletion (default: dry-run)")
    args = parser.parse_args(argv)

    if not args.email and not args.reg_id:
        parser.error("an explicit --email or --registration-session-id target is required")

    print("=" * 70)
    print("SaaS test-account recovery — abandoned REGISTRATION cleanup")
    print("DRY RUN (no writes)" if not args.apply else "APPLY")
    print("WARNING: never deletes canonical accounts, credentials, sessions,")
    print("         orgs, workspaces, connected accounts, or billing data.")
    print("=" * 70)

    snapshot = _load_snapshot()

    resolved_email = normalize_email(args.email)
    if args.reg_id:
        session = next((rs for rs in snapshot["registration_sessions"] if str(rs.get("id", "")) == args.reg_id), None)
        if session is None:
            print(f"REFUSED: registration session not found: {args.reg_id}")
            return 2
        session_email = normalize_email(str(session.get("email", "")))
        if resolved_email and resolved_email != session_email:
            print("REFUSED: --email and --registration-session-id refer to different attempts")
            return 2
        resolved_email = session_email
        if not resolved_email:
            print("REFUSED: registration session has no email")
            return 2
        snapshot = dict(snapshot)
        snapshot["registration_sessions"] = [session]

    plan = build_abandoned_plan(target_email=resolved_email, **snapshot)

    if plan.refusal_reason:
        print(f"REFUSED: {plan.refusal_reason}")
        return 3

    summary = apply_abandoned_plan(plan, dry_run=not args.apply)

    print(f"Target email:    {summary.get('target_email')}")
    print(f"Found records:   {summary.get('found')}")
    for table, count in sorted(summary.get("deletes_by_table", {}).items()):
        print(f"  WOULD DELETE {table}: {count}")
    if summary.get("orphan_identity_user_ids"):
        print("  NOTE orphan identity_user ids (reported, NOT deleted):",
              ", ".join(i[:8] for i in summary["orphan_identity_user_ids"]))
    if "failures" in summary:
        print(f"APPLIED rows: {summary.get('applied_updates')}")
        for f in summary["failures"]:
            print(f"  FAILED {f['table']} {f['id']}: {f['error']}")
    if not summary["deletes_by_table"]:
        print("Nothing to clean for this email.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
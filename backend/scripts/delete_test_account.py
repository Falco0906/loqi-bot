"""Safe operator/development test-account removal (SaaS-1.7 recovery tool).

Removes a single, explicitly-targeted account (and every record it owns) that
became unusable during production testing — NOT a public "delete any account"
endpoint, and NOT a bulk operation.

Safety model:
- explicit target required: `--email <email>` or `--user-id <uuid>`
- dry-run by default; only `--apply` mutates anything
- resolves the canonical identity and prints counts/types before any write
- refuses ambiguous targets (one email mapping to multiple users)
- never deletes shared organizations/workspaces that contain other users
  (those are skipped and reported)
- never touches billing records (reported as skipped)
- revokes/deletes the target's sessions + refresh tokens, web-session
  bindings, OAuth state, connected/external identities, credentials, and
  identity rows
- ordered, idempotent, reports partial failures (PostgREST has no
  multi-statement transaction; cleanup is best-effort per table and is never
  claimed to be atomic)

Usage:
    python3 backend/scripts/delete_test_account.py --email user@example.com           # dry-run
    python3 backend/scripts/delete_test_account.py --email user@example.com --apply   # delete
    python3 backend/scripts/delete_test_account.py --user-id <uuid> --apply

Never print secrets, tokens, password hashes, or verification tokens.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

# Deletion order: children before parents; no FK constraints exist, so order is
# logical only. identity_users is removed last.
DELETE_ORDER = [
    "refresh_tokens",
    "sessions",
    "web_session_bindings",
    "oauth_sessions",
    "connected_accounts",
    "external_identities",
    "password_reset_requests",
    "verification_tokens",
    "password_credentials",
    "registration_sessions",
    "email_identities",
    "workspace_members",
    "discoveries",
    "workspaces",
    "memberships",
    "invitations",
    "jobs",
    "organizations",
    "identity_users",
]

SKIPPED_ON_APPLY = ("billing_customers", "billing_subscriptions",
                    "billing_checkout_sessions", "billing_invoices", "billing_events")


@dataclass
class CleanupPlan:
    target_user_id: str = ""
    target_email: str = ""
    delete: dict[str, list[str]] = field(default_factory=dict)
    skip: list[dict[str, Any]] = field(default_factory=list)

    def summarize(self) -> dict[str, Any]:
        return {
            "target_user_id": self.target_user_id,
            "target_email": self.target_email,
            "deletes_by_table": {t: len(v) for t, v in self.delete.items() if v},
            "total_rows": sum(len(v) for v in self.delete.values()),
            "skipped": self.skip,
        }


def _distinct(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return seen


def build_cleanup_plan(
    *,
    target_email: str = "",
    target_user_id: str = "",
    identity_users: list[dict[str, Any]],
    email_identities: list[dict[str, Any]],
    password_credentials: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    refresh_tokens: list[dict[str, Any]],
    registration_sessions: list[dict[str, Any]],
    verification_tokens: list[dict[str, Any]],
    password_reset_requests: list[dict[str, Any]],
    oauth_sessions: list[dict[str, Any]],
    web_session_bindings: list[dict[str, Any]],
    external_identities: list[dict[str, Any]],
    connected_accounts: list[dict[str, Any]],
    workspaces: list[dict[str, Any]],
    workspace_members: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    invitations: list[dict[str, Any]],
    organizations: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    discoveries: list[dict[str, Any]],
) -> CleanupPlan:
    """Build the deletion plan without mutating anything. Pure + testable."""
    plan = CleanupPlan()

    if not target_email and not target_user_id:
        raise ValueError("an explicit --email or --user-id target is required")

    # Resolve the canonical user id.
    if target_user_id:
        if not any(str(u.get("id", "")) == target_user_id for u in identity_users):
            raise ValueError(f"identity_users: user id not found: {target_user_id}")
        user_id = target_user_id
        plan.target_user_id = user_id
        plan.target_email = target_email
    else:
        email = (target_email or "").strip().lower()
        if not email:
            raise ValueError("an explicit --email or --user-id target is required")
        matched = [ei for ei in email_identities if str(ei.get("email", "")).lower() == email]
        if not matched:
            raise ValueError(f"no email identity found for the given email")
        user_ids = _distinct([str(ei.get("user_id", "")) for ei in matched])
        if len(user_ids) > 1:
            raise ValueError("ambiguous target: email maps to more than one user; use --user-id")
        if not user_ids:
            # Email identity exists but is unlinked (user_id == "") — it may be
            # from an abandoned verification; treat as a pending/orphan record.
            plan.target_email = email
            plan.target_user_id = ""
            _collect(plan, "email_identities", [str(ei.get("id", "")) for ei in matched])
            _collect(plan, "registration_sessions", [
                str(rs.get("id", "")) for rs in registration_sessions
                if str(rs.get("email", "")).lower() == email
            ])
            _collect(plan, "verification_tokens", [
                str(vt.get("id", "")) for vt in verification_tokens
                if str(vt.get("target", "")).lower() == email
            ])
            return plan
        user_id = user_ids[0]
        plan.target_user_id = user_id
        plan.target_email = email

    uid = plan.target_user_id

    # Identity / auth rows keyed directly by user id.
    _collect(plan, "email_identities", [
        str(ei.get("id", "")) for ei in email_identities
        if str(ei.get("user_id", "")) == uid
        or (plan.target_email and str(ei.get("email", "")).lower() == plan.target_email)
    ])
    _collect(plan, "password_credentials", [
        str(pc.get("id", "")) for pc in password_credentials if str(pc.get("user_id", "")) == uid
    ])
    _collect(plan, "sessions", [
        str(s.get("id", "")) for s in sessions if str(s.get("user_id", "")) == uid
    ])
    _collect(plan, "registration_sessions", [
        str(rs.get("id", "")) for rs in registration_sessions
        if str(rs.get("user_id", "")) == uid
        or (plan.target_email and str(rs.get("email", "")).lower() == plan.target_email)
    ])
    _collect(plan, "verification_tokens", [
        str(vt.get("id", "")) for vt in verification_tokens
        if plan.target_email and str(vt.get("target", "")).lower() == plan.target_email
    ])
    _collect(plan, "password_reset_requests", [
        str(pr.get("id", "")) for pr in password_reset_requests if str(pr.get("user_id", "")) == uid
    ])
    _collect(plan, "oauth_sessions", [
        str(os_.get("id", "")) for os_ in oauth_sessions if str(os_.get("user_id", "")) == uid
    ])
    _collect(plan, "web_session_bindings", [
        str(wb.get("id", "")) for wb in web_session_bindings
        if str(wb.get("canonical_user_id", "")) == uid
    ])
    _collect(plan, "external_identities", [
        str(ei.get("id", "")) for ei in external_identities if str(ei.get("user_id", "")) == uid
    ])
    _collect(plan, "connected_accounts", [
        str(ca.get("id", "")) for ca in connected_accounts if str(ca.get("user_id", "")) == uid
    ])
    _collect(plan, "jobs", [
        str(j.get("id", "")) for j in jobs if str(j.get("user_id", "")) == uid
    ])

    # Refresh tokens are keyed by session; resolve via the target's sessions.
    session_ids = set(
        str(s.get("id", "")) for s in sessions if str(s.get("user_id", "")) == uid
    )
    _collect(plan, "refresh_tokens", [
        str(rt.get("id", "")) for rt in refresh_tokens
        if str(rt.get("session_id", "")) in session_ids
    ])

    # Workspaces owned by the target: only delete if no OTHER members.
    owned_workspaces = [w for w in workspaces if str(w.get("owner_user_id", "")) == uid]
    _collect(plan, "workspace_members", [
        str(wm.get("id", "")) for wm in workspace_members if str(wm.get("user_id", "")) == uid
    ])
    for w in owned_workspaces:
        wid = str(w.get("id", ""))
        other_members = [
            wm for wm in workspace_members
            if str(wm.get("workspace_id", "")) == wid and str(wm.get("user_id", "")) != uid
        ]
        if other_members:
            plan.skip.append({"resource": "workspaces", "id": wid, "reason": "shared (other members)"})
            continue
        plan.delete.setdefault("workspaces", []).append(wid)
        _collect(plan, "discoveries", [
            str(d.get("id", "")) for d in discoveries if str(d.get("workspace_id", "")) == wid
        ])

    # Organizations owned by the target: delete only when sole member.
    owned_orgs = [o for o in organizations if str(o.get("created_by", "")) == uid]
    for o in owned_orgs:
        oid = str(o.get("id", ""))
        org_members = [m for m in memberships if str(m.get("organization_id", "")) == oid]
        other_users = _distinct([str(m.get("user_id", "")) for m in org_members if str(m.get("user_id", "")) != uid])
        if other_users:
            plan.skip.append({"resource": "organizations", "id": oid, "reason": "shared (other members)"})
            continue
        plan.delete.setdefault("organizations", []).append(oid)
        _collect(plan, "memberships", [str(m.get("id", "")) for m in org_members])
        _collect(plan, "invitations", [
            str(i.get("id", "")) for i in invitations if str(i.get("organization_id", "")) == oid
        ])
    # Non-owned memberships (target is a plain member of someone else's org):
    # delete only the membership row, never the org.
    _collect(plan, "memberships", [
        str(m.get("id", "")) for m in memberships
        if str(m.get("user_id", "")) == uid and str(m.get("organization_id", "")) not in plan.delete.get("organizations", [])
    ])

    # identity_users last.
    _collect(plan, "identity_users", [uid])

    # Billing is never deleted blindly — reported as skipped.
    plan.skip.append({"resource": "billing_*", "id": "*", "reason": "never deleted by this tool"})
    return plan


def _collect(plan: CleanupPlan, table: str, ids: list[str]) -> None:
    existing = plan.delete.setdefault(table, [])
    for i in ids:
        if i and i not in existing:
            existing.append(i)


def apply_cleanup_plan(plan: CleanupPlan, *, dry_run: bool = True) -> dict[str, Any]:
    """Execute the plan. In dry-run mode returns the summary without writing.

    In apply mode deletes table-by-table in DELETE_ORDER; each table is
    best-effort and failures are collected (never claimed to be atomic).
    """
    summary = plan.summarize()
    if dry_run:
        return summary
    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")
    failures: list[dict[str, Any]] = []
    applied = 0
    for table in DELETE_ORDER:
        ids = plan.delete.get(table, [])
        if not ids:
            continue
        for rid in ids:
            try:
                client.table(table).delete().eq("id", rid).execute()
                applied += 1
            except Exception as exc:  # noqa: BLE001
                failures.append({"table": table, "id": rid, "error": type(exc).__name__})
    summary["applied_updates"] = applied
    summary["failures"] = failures
    return summary


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
        "identity_users": _rows("identity_users", "id"),
        "email_identities": _rows("email_identities", "id, user_id, email"),
        "password_credentials": _rows("password_credentials", "id, user_id"),
        "sessions": _rows("sessions", "id, user_id"),
        "refresh_tokens": _rows("refresh_tokens", "id, session_id"),
        "registration_sessions": _rows("registration_sessions", "id, user_id, email"),
        "verification_tokens": _rows("verification_tokens", "id, target"),
        "password_reset_requests": _rows("password_reset_requests", "id, user_id"),
        "oauth_sessions": _rows("oauth_sessions", "id, user_id"),
        "web_session_bindings": _rows("web_session_bindings", "id, canonical_user_id"),
        "external_identities": _rows("external_identities", "id, user_id"),
        "connected_accounts": _rows("connected_accounts", "id, user_id"),
        "workspaces": _rows("workspaces", "id, owner_user_id"),
        "workspace_members": _rows("workspace_members", "id, workspace_id, user_id"),
        "memberships": _rows("memberships", "id, user_id, organization_id"),
        "invitations": _rows("invitations", "id, organization_id"),
        "organizations": _rows("organizations", "id, created_by"),
        "jobs": _rows("jobs", "id, user_id"),
        "discoveries": _rows("discoveries", "id, workspace_id"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete a single test account (safe cleanup tool)")
    parser.add_argument("--email", default="", help="target email (resolved to the canonical identity)")
    parser.add_argument("--user-id", dest="user_id", default="", help="target canonical user id")
    parser.add_argument("--apply", action="store_true", help="perform deletions (default: dry-run)")
    args = parser.parse_args(argv)

    if not args.email and not args.user_id:
        parser.error("an explicit --email or --user-id target is required")

    print("=" * 70)
    print("SaaS-1.7 test-account cleanup —", "DRY RUN (no writes)" if not args.apply else "APPLY")
    print("WARNING: this removes the targeted account and its owned records.")
    print("         It never deletes shared orgs/workspaces or billing data.")
    print("=" * 70)

    snapshot = _load_snapshot()
    try:
        plan = build_cleanup_plan(target_email=args.email, target_user_id=args.user_id, **snapshot)
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2

    summary = apply_cleanup_plan(plan, dry_run=not args.apply)

    print(f"Target user id:  {summary.get('target_user_id') or '(none — orphan/pending only)'}")
    print(f"Target email:    {summary.get('target_email') or '(not provided)'}")
    for table, count in sorted(summary.get("deletes_by_table", {}).items()):
        print(f"  WOULD DELETE {table}: {count}")
    for item in summary.get("skipped", []):
        print(f"  SKIP {item.get('resource')} {item.get('id')}: {item.get('reason')}")
    if "failures" in summary:
        print(f"APPLIED rows: {summary.get('applied_updates')}")
        for f in summary["failures"]:
            print(f"  FAILED {f['table']} {f['id']}: {f['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
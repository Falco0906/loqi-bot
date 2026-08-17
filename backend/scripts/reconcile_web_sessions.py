"""Legacy synthetic web-user → canonical identity reconciliation (SaaS-1.7).

Pre-SaaS web sessions created synthetic legacy ``users`` rows
(``telegram_id = 'web:<token>'``). Workspace / provider / connected-account
records may therefore be keyed by those synthetic ids rather than a canonical
``identity_users`` id.

SaaS-1.6 established a deterministic mapping: the web-session token
(``web:<token>``) is durably bound to a canonical user via
``web_session_bindings``. This script re-keys records from the synthetic id to
the canonical id using that mapping.

Rules (safety-first):
- only rows whose owner/user is a synthetic web user are considered;
- a synthetic user maps ONLY when exactly one binding exists for its token and
  the canonical user exists in identity_users;
- no binding, missing canonical user, or ambiguous mapping ⇒ recorded as
  orphaned/ambiguous, never guessed, never mutated;
- a target (canonical, provider/account/org) that already exists is skipped
  (no duplicate ownership);
- never deletes rows; idempotent (re-running finds nothing left to do);
- ``--dry-run`` (default) reports counts without writing.

Usage:
    python -m scripts.reconcile_web_sessions --dry-run
    python -m scripts.reconcile_web_sessions            # apply
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# Make `services` importable regardless of CWD (matches the convention in
# scripts/backfill_diagnose.py and scripts/mission_control_diag.py), so this
# script can be run reliably from the repository root:
#   python3 backend/scripts/reconcile_web_sessions.py
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv

# Load backend/.env when present so a repo-root run reaches Supabase without
# relying on ambient env (existing environment variables are never overridden).
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))


def _web_token(telegram_id: str) -> str:
    return telegram_id[4:] if telegram_id.startswith("web:") else ""


@dataclass
class ReconciliationPlan:
    mapped: list[dict[str, Any]] = field(default_factory=list)
    orphaned: list[dict[str, Any]] = field(default_factory=list)
    skipped_duplicates: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def summarize(self) -> dict[str, Any]:
        return {
            "mapped": len(self.mapped),
            "orphaned": len(self.orphaned),
            "skipped_duplicates": len(self.skipped_duplicates),
            "workspaces_to_rekey": self.counts.get("workspaces", 0),
            "connected_accounts_to_rekey": self.counts.get("connected_accounts", 0),
            "external_identities_to_rekey": self.counts.get("external_identities", 0),
        }


def build_reconciliation_plan(
    *,
    web_users: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    identity_user_ids: set[str],
    workspaces: list[dict[str, Any]],
    connected_accounts: list[dict[str, Any]],
    external_identities: list[dict[str, Any]],
) -> ReconciliationPlan:
    """Build the reconciliation plan without mutating anything.

    ``web_users``: [{id, telegram_id}] (legacy users with ``web:`` telegram_id)
    ``bindings``: [{session_key, canonical_user_id}] (web_session_bindings)
    ``identity_user_ids``: set of canonical identity_users ids
    ``workspaces``/``connected_accounts``/``external_identities``: rows with an
      ``owner_user_id``/``user_id`` field.
    """
    plan = ReconciliationPlan()
    binding_by_token: dict[str, str] = {}
    for b in bindings:
        token = b.get("session_key", "")
        canonical = b.get("canonical_user_id", "")
        if not token or not canonical:
            continue
        if token in binding_by_token and binding_by_token[token] != canonical:
            binding_by_token[token] = ""  # ambiguous binding
        else:
            binding_by_token[token] = canonical

    by_table = {
        "workspaces": ("owner_user_id", workspaces),
        "connected_accounts": ("user_id", connected_accounts),
        "external_identities": ("user_id", external_identities),
    }

    def _target_key(table: str, row: dict[str, Any]) -> tuple[str, ...]:
        # NOTE: connected_accounts has no organization_id column (migration
        # 005); its stable unique key is (provider, account_id).
        fields = {
            "workspaces": ("organization_id",),
            "connected_accounts": ("provider", "account_id"),
            "external_identities": ("provider", "provider_subject"),
        }[table]
        return tuple(sorted((row.get(k) or "") for k in fields))

    # Group existing rows by (table, target_key) so we can detect a row that
    # a canonical user ALREADY owns for the same key (duplicate protection).
    rows_by_key: dict[str, dict[tuple[str, ...], list[dict[str, Any]]]] = {}
    for table, (_field, rows) in by_table.items():
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(_target_key(table, row), []).append(row)
        rows_by_key[table] = grouped

    for user in web_users:
        token = _web_token(user.get("telegram_id", ""))
        if not token:
            continue
        synthetic_id = str(user.get("id", ""))
        canonical = binding_by_token.get(token, "")
        if not canonical:
            plan.orphaned.append({
                "synthetic_user_id": synthetic_id,
                "reason": "no_binding",
            })
            continue
        if canonical not in identity_user_ids:
            plan.orphaned.append({
                "synthetic_user_id": synthetic_id,
                "canonical_user_id": canonical,
                "reason": "missing_canonical_user",
            })
            continue

        entry: dict[str, Any] = {
            "synthetic_user_id": synthetic_id,
            "canonical_user_id": canonical,
            "workspaces": [],
            "connected_accounts": [],
            "external_identities": [],
        }
        for table, (field, rows) in by_table.items():
            for row in rows:
                if str(row.get(field, "")) != synthetic_id:
                    continue
                key = _target_key(table, row)
                siblings = rows_by_key[table].get(key, [])
                already_owned_by_canonical = any(
                    str(other.get(field, "")) == canonical and other.get("id") != row.get("id")
                    for other in siblings
                )
                if already_owned_by_canonical:
                    plan.skipped_duplicates.append({
                        "table": table,
                        "row_id": row.get("id"),
                        "synthetic_user_id": synthetic_id,
                        "canonical_user_id": canonical,
                    })
                    continue
                entry[table].append(row.get("id"))
        plan.mapped.append(entry)

    plan.counts = {
        "workspaces": sum(len(e["workspaces"]) for e in plan.mapped),
        "connected_accounts": sum(len(e["connected_accounts"]) for e in plan.mapped),
        "external_identities": sum(len(e["external_identities"]) for e in plan.mapped),
    }
    return plan


def apply_reconciliation_plan(plan: ReconciliationPlan, *, dry_run: bool = True) -> dict[str, Any]:
    """Re-key records in the plan. In dry-run mode returns counts without
    touching the database; otherwise performs bounded UPDATEs keyed by row id.

    Returns the summary dict (idempotent: re-running after an apply yields an
    empty plan for the re-keyed rows).
    """
    summary = plan.summarize()
    if dry_run:
        return summary
    from services.supabase import get_supabase_client

    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")
    field_by_table = {
        "workspaces": "owner_user_id",
        "connected_accounts": "user_id",
        "external_identities": "user_id",
    }
    updated = 0
    for entry in plan.mapped:
        canonical = entry["canonical_user_id"]
        for table, field in field_by_table.items():
            for row_id in entry[table]:
                client.table(table).update({field: canonical}).eq("id", row_id).execute()
                updated += 1
    summary["applied_updates"] = updated
    return summary


def _load_snapshot():
    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    def _rows(table, select="*"):
        return getattr(client.table(table).select(select).execute(), "data", None) or []

    web_users = []
    for u in _rows("users", "id, telegram_id"):
        if (u.get("telegram_id") or "").startswith("web:"):
            web_users.append(u)
    bindings = _rows("web_session_bindings", "session_key, canonical_user_id")
    identity_ids = {str(r.get("id", "")) for r in _rows("identity_users", "id")}
    workspaces = _rows("workspaces", "id, owner_user_id, organization_id")
    connected_accounts = _rows(
        "connected_accounts",
        "id, user_id, provider, account_id",
    )
    external_identities = _rows(
        "external_identities",
        "id, user_id, provider, provider_subject",
    )
    return web_users, bindings, identity_ids, workspaces, connected_accounts, external_identities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile legacy synthetic web users")
    parser.add_argument("--apply", action="store_true", help="perform updates (default: dry-run)")
    args = parser.parse_args(argv)

    snapshot = _load_snapshot()
    plan = build_reconciliation_plan(
        web_users=snapshot[0],
        bindings=snapshot[1],
        identity_user_ids=snapshot[2],
        workspaces=snapshot[3],
        connected_accounts=snapshot[4],
        external_identities=snapshot[5],
    )
    summary = apply_reconciliation_plan(plan, dry_run=not args.apply)

    print("SaaS-1.7 web-session reconciliation —", "DRY RUN" if not args.apply else "APPLIED")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    for orphan in plan.orphaned:
        print(f"  ORPHAN {orphan}")
    for skip in plan.skipped_duplicates:
        print(f"  SKIP duplicate {skip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
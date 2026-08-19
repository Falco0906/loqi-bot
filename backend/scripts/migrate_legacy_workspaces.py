#!/usr/bin/env python3
"""SaaS-2.8 — Production workspace & tenant migration operator CLI.

DRY-RUN FIRST. Default mode produces a complete READ-ONLY migration report and
never writes. Only ``--apply --confirm`` performs writes, and only after
re-reading durable state (a stale dry-run plan is never trusted).

Reports:
    LEGACY WORKSPACES  /  ORGANIZATIONS  /  MEMBERSHIPS  /  CHILD RESOURCES
    plus per-candidate plans.

Examples:
    python3 backend/scripts/migrate_legacy_workspaces.py                       # dry-run report
    python3 backend/scripts/migrate_legacy_workspaces.py --workspace-id <id>   # dry-run, one
    python3 backend/scripts/migrate_legacy_workspaces.py --apply --confirm     # apply all ready
    python3 backend/scripts/migrate_legacy_workspaces.py --user-id <id> --apply --confirm

Requires migrations 028 (workflow_session_id) + 030 (workspace_migrations) for
``--apply``. Dry-run is read-only and schema-safe. Never run automatically.
"""

from __future__ import annotations

import argparse
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from services.persistence.launch.legacy_workspace_migration import (  # noqa: E402
    apply_migration_plan,
    build_migration_plan,
    detect_legacy_workspaces,
)
from services.persistence.launch.workspace_reconciliation import (  # noqa: E402
    record_migration,
    reconcile_workspace,
    verify_migration,
)

__all__ = ["apply_migration_plan", "build_migration_plan", "detect_legacy_workspaces"]


def _print_report(report: dict) -> None:
    print("LEGACY WORKSPACES")
    print("-" * 18)
    print(f"  Total active workspaces: {report['total_active_workspaces']}")
    print(f"  Legacy: {report['legacy_workspaces']}")
    print(f"  Non-legacy: {report['non_legacy_workspaces']}")
    print(f"  Already migrated: {report['already_migrated_workspaces']}")
    print(f"  With organization_id: {report['workspaces_with_organization_id']}")
    print(f"  Without organization_id: {report['workspaces_without_organization_id']}")
    print(f"  Org missing: {report['workspaces_org_id_missing_organization']}")
    print(f"  Missing owner: {report['workspaces_missing_owner']}")
    print(f"  Owner user missing: {report['workspaces_owner_user_missing']}")
    print(f"  Owner no membership: {report['workspaces_owner_no_membership']}")
    print(f"  Owner 1 membership: {report['workspaces_owner_one_membership']}")
    print(f"  Owner multi membership: {report['workspaces_owner_multi_membership']}")
    print(f"  Org conflicts membership: {report['workspaces_org_id_conflicts_membership']}")
    print()
    print("RECONCILIATION")
    print("  READY:", report["ready"], "| BLOCKED:", report["blocked"],
          "| MANUAL_REVIEW:", report["manual_review"])
    if report.get("blocker_categories"):
        print("  Blocker categories:", report["blocker_categories"])
    print()
    print("ORGANIZATIONS")
    dups = report.get("duplicate_organizations") or []
    print("  Duplicate-candidate groups:", len(dups))
    for g in dups[:10]:
        print(f"    owner={g['owner_user_id']} orgs={[o['id'] for o in g['organizations']]}")
    print()
    print("MEMBERSHIPS")
    md = report.get("duplicate_memberships") or []
    print("  Duplicate user/org groups:", len(md))
    for g in md[:10]:
        print(f"    user={g['user_id']} org={g['organization_id']} ids={[m['id'] for m in g['memberships']]}")
    print()
    print("CHILD RESOURCES (per affected workspace)")
    affected = report.get("affected_workspaces") or {}
    for ws_id, info in list(affected.items())[:20]:
        print(f"  {ws_id} [{info['status']}] {info.get('reason','')}")
        counts = info.get("child_counts") or {}
        if counts:
            print("     " + ", ".join(f"{t}={c}" for t, c in counts.items() if c))


def _print_candidate(client, workspace_id: str) -> dict:
    rec = reconcile_workspace(client, workspace_id)
    print(f"  legacy workspace : {workspace_id}")
    print(f"  owner_user_id    : {rec.get('owner_user_id','')}")
    print(f"  proposed org     : {rec.get('organization_id','') or '(none)'}")
    print(f"  evidence         : {rec.get('evidence','') or rec.get('reason','')}")
    if rec.get("organization_candidates"):
        print(f"  candidates       : {[c['organization_id'] for c in rec['organization_candidates']]}")
    plan = build_migration_plan(client, workspace_id)
    print(f"  would-create id  : {plan.get('new_workspace_id') or '(none)'}")
    counts = plan.get("child_counts") or {}
    if counts:
        print("  child resources  : " + ", ".join(f"{t}={c}" for t, c in counts.items() if c))
    print(f"  status           : {rec['status'].upper()}")
    print()
    return rec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SaaS-2.8 production workspace & tenant migration (dry-run first)",
    )
    parser.add_argument("--workspace-id", dest="workspace_id", default="",
                        help="scope to this workspace id")
    parser.add_argument("--user-id", dest="user_id", default="",
                        help="scope to workspaces owned by this user")
    parser.add_argument("--organization-id", dest="organization_id", default="",
                        help="scope to workspaces in this organization")
    parser.add_argument("--limit", type=int, default=0,
                        help="process at most N workspaces (controlled batch)")
    parser.add_argument("--adoption-plan", action="store_true",
                        help="produce a read-only legacy organization adoption report (never writes)")
    parser.add_argument("--apply", action="store_true",
                        help="perform writes (requires --confirm)")
    parser.add_argument("--confirm", action="store_true",
                        help="explicit confirmation required with --apply")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("Loqi SaaS-2.8.1 — legacy organization adoption planning")
    if args.adoption_plan and args.apply:
        print("REFUSED: --adoption-plan is read-only and cannot combine with --apply.")
        return 2
    if args.apply and not args.confirm:
        print("REFUSED: --apply requires --confirm. No writes performed.")
        return 2
    print("ADOPTION PLAN (read-only)" if args.adoption_plan
          else ("APPLY MODE" if (args.apply and args.confirm) else "DRY RUN (no writes)"))
    print("=" * 72)

    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        print("FATAL: Supabase client unavailable")
        return 1

    if args.adoption_plan:
        from services.persistence.launch.workspace_reconciliation import build_adoption_report
        report = build_adoption_report(client)
        print("LEGACY ORGANIZATION ADOPTION — READ-ONLY REPORT")
        print("Legacy workspaces:", report["legacy_workspaces"])
        print("Classifications:", report["counts"])
        print()
        plans = report["plans"]
        for ws_id, plan in list(plans.items())[:20]:
            print(f"  {ws_id} -> {plan['classification']} "
                  f"proposed_org={plan['proposed_organization_id'] or '(none)'} "
                  f"action={plan['membership_action']} evidence={plan['organization_evidence'] or plan['blockers']}")
        if len(plans) > 20:
            print(f"  ... and {len(plans) - 20} more")
        print()
        print("Read-only — no production writes performed. Re-run with an explicit "
              "operator-approved adoption command to act.")
        return 0

    if args.workspace_id:
        targets = [{"workspace_id": args.workspace_id}]
    else:
        legacy = detect_legacy_workspaces(client)
        targets = [
            w for w in legacy
            if (not args.user_id or w["owner_user_id"] == args.user_id)
            and (not args.organization_id or w["organization_id"] == args.organization_id)
        ]
    if args.limit and len(targets) > args.limit:
        targets = targets[: args.limit]

    if not args.workspace_id:
        from services.persistence.launch.workspace_reconciliation import inspect_production
        _print_report(inspect_production(client))

    if not targets:
        print("No legacy workspaces matched.")
        return 0

    print(f"Legacy workspaces to process: {len(targets)}\n")
    ready = blocked = manual = migrated = 0
    for target in targets:
        rec = _print_candidate(client, target["workspace_id"])
        if rec.get("already_migrated"):
            continue
        if rec["status"] == "blocked":
            blocked += 1
            continue
        if rec["status"] == "manual_review":
            manual += 1
            continue
        ready += 1
        if args.apply and args.confirm:
            # Re-read durable state at apply time; never trust a stale plan.
            plan = build_migration_plan(client, target["workspace_id"])
            if not plan.get("ready"):
                print(f"  -> SKIPPED (state changed): {plan.get('blockers')}")
                continue
            result = apply_migration_plan(client, plan, dry_run=False)
            if result.get("applied"):
                try:
                    record_migration(
                        client,
                        legacy_workspace_id=target["workspace_id"],
                        new_workspace_id=result["new_workspace_id"],
                        workflow_session_id=result.get("workflow_session_id", ""),
                        organization_id=result.get("organization_id", ""),
                        owner_user_id=result.get("owner_user_id", ""),
                        status="applied",
                    )
                    verification = verify_migration(client, plan)
                except Exception as e:  # noqa: BLE001
                    verification = {"all_ok": False, "error": str(e)}
                migrated += 1
                print(f"  -> APPLIED: new workspace {result['new_workspace_id']}")
                print(f"     verification: {verification}")
            else:
                print(f"  -> NOT APPLIED: {result.get('reason')} {result.get('blockers', [])}")

    print("=" * 72)
    print(f"READY: {ready} | BLOCKED: {blocked} | MANUAL_REVIEW: {manual}")
    if args.apply and args.confirm:
        print(f"APPLIED: {migrated}")
    else:
        print("Dry-run only — re-run with --apply --confirm to migrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

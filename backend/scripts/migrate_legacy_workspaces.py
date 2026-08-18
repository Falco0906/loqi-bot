#!/usr/bin/env python3
"""SaaS-2.3 — Legacy workspace migration operator script.

Detects legacy workspaces (workspaces.id == workflow_sessions.id, channel=
'workspace') and, on explicit ``--apply``, mints a new canonical workspace id,
preserves owner/organization/metadata, records the workflow-session provenance,
remaps workspace-owned child resources, and soft-deletes the legacy workspace.

DRY-RUN BY DEFAULT. Only ``--apply`` performs writes. Never run automatically;
never touches production unless the operator explicitly selects a target and
passes ``--apply``.

Examples:
    python3 backend/scripts/migrate_legacy_workspaces.py                        # dry-run, all
    python3 backend/scripts/migrate_legacy_workspaces.py --workspace-id <id>    # dry-run, one
    python3 backend/scripts/migrate_legacy_workspaces.py --workspace-id <id> --apply

Requires migration 028 to have been applied (workflow_session_id column) for
``--apply``; dry-run is read-only and schema-safe.
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

__all__ = ["apply_migration_plan", "build_migration_plan", "detect_legacy_workspaces"]


def _print_plan(plan: dict) -> None:
    print(f"  legacy workspace : {plan.get('legacy_workspace_id')}")
    print(f"  new workspace id : {plan.get('new_workspace_id') or '(none)'}")
    print(f"  owner_user_id    : {plan.get('owner_user_id')}")
    print(f"  organization_id  : {plan.get('organization_id')}")
    print(f"  workflow_session : {plan.get('workflow_session_id')}")
    counts = plan.get("child_counts") or {}
    if counts:
        print("  child resources  : " + ", ".join(f"{t}={c}" for t, c in counts.items()))
    if plan.get("already_migrated"):
        print("  status           : ALREADY MIGRATED (no work)")
    elif plan.get("ready"):
        print("  status           : READY")
    else:
        print("  status           : BLOCKED")
        for b in plan.get("blockers", []):
            print(f"    - {b}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect and (on --apply) migrate legacy workspaces",
    )
    parser.add_argument("--workspace-id", dest="workspace_id", default="",
                        help="migrate only this legacy workspace id")
    parser.add_argument("--user-id", dest="user_id", default="",
                        help="migrate only workspaces owned by this user")
    parser.add_argument("--organization-id", dest="organization_id", default="",
                        help="migrate only workspaces in this organization")
    parser.add_argument("--apply", action="store_true",
                        help="perform the migration (default: dry-run, no writes)")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("Loqi SaaS-2.3 — legacy workspace migration")
    print("DRY RUN (no writes)" if not args.apply else "APPLY")
    print("WARNING: only run --apply after reviewing the dry-run plan.")
    print("=" * 72)

    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        print("FATAL: Supabase client unavailable (check SUPABASE_URL/SUPABASE_KEY)")
        return 1

    if args.workspace_id:
        targets = [{"workspace_id": args.workspace_id}]
    else:
        legacy = detect_legacy_workspaces(client)
        targets = [
            w for w in legacy
            if (not args.user_id or w["owner_user_id"] == args.user_id)
            and (not args.organization_id or w["organization_id"] == args.organization_id)
        ]

    if not targets:
        print("No legacy workspaces matched.")
        return 0

    print(f"Legacy workspaces to process: {len(targets)}\n")

    ready = 0
    blocked = 0
    migrated = 0
    blocker_categories: dict[str, int] = {}
    for target in targets:
        plan = build_migration_plan(client, target["workspace_id"])
        _print_plan(plan)
        print()
        if plan.get("already_migrated"):
            continue
        if not plan.get("ready"):
            blocked += 1
            for b in plan.get("blockers", []):
                key = b.split(":")[0]
                blocker_categories[key] = blocker_categories.get(key, 0) + 1
            continue
        ready += 1
        if args.apply:
            result = apply_migration_plan(client, plan, dry_run=False)
            if result.get("applied"):
                migrated += 1
                print(f"  -> APPLIED: new workspace {result.get('new_workspace_id')}")
            else:
                print(f"  -> NOT APPLIED: {result.get('reason')} {result.get('blockers', [])}")

    print("=" * 72)
    print(f"Ready: {ready} | Blocked: {blocked} | Already-migrated: "
          f"{len(targets) - ready - blocked}")
    if blocker_categories:
        print("Blocker categories:", blocker_categories)
    if args.apply:
        print(f"Applied: {migrated}")
    else:
        print("Dry-run only — re-run with --apply to migrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

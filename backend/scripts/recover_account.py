#!/usr/bin/env python3
"""Operator-only account recovery CLI.

Recovers a legacy completed account that is missing its durable organization +
owner membership (accounts completed before commit c6aa780, when identity
org/membership were in-memory and lost on restart/redeploy).

DRY-RUN BY DEFAULT. Only --apply performs writes.

Example:
    python3 backend/scripts/recover_account.py --email tofu9262@gmail.com
    python3 backend/scripts/recover_account.py --email tofu9262@gmail.com --user-id <id> --apply

Guarantees:
- creates exactly ONE organization + ONE owner (active) membership using the
  same durable repositories/schema as normal signup completion;
- refuses if the email identity is missing/unverified/unlinked, if the pinned
  user_id does not own the email identity, or if no password credential exists;
- refuses if an organization or membership already exists (idempotent);
- never creates/updates identity_users, never alters the password, never
  bypasses email verification, never touches billing, never deletes anything.
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

from services.identity.account_recovery import (  # noqa: E402
    apply_recovery_plan,
    build_recovery_plan,
)

__all__ = ["apply_recovery_plan", "build_recovery_plan"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision the missing durable organization + owner membership "
                    "for a legacy completed account",
    )
    parser.add_argument("--email", required=True, help="canonical email (as stored in email_identities)")
    parser.add_argument("--user-id", dest="user_id", default="",
                        help="optional pin; must own the email identity")
    parser.add_argument("--apply", action="store_true",
                        help="perform the write (default: dry-run, no writes)")
    args = parser.parse_args(argv)

    print("=" * 70)
    print("Loqi account recovery — durable org + owner membership provisioning")
    print("DRY RUN (no writes)" if not args.apply else "APPLY")
    print("WARNING: only ever missing durable org/membership rows; never touches")
    print("         identity_users, passwords, email verification, or billing.")
    print("=" * 70)

    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        print("FATAL: Supabase client unavailable (check SUPABASE_URL/SUPABASE_KEY)")
        return 1

    plan = build_recovery_plan(args.email, user_id=args.user_id, client=client)
    print("\nTarget:   ", plan.email)
    print("User id:  ", plan.user_id)
    print("Verified email identity:", plan.email_verified, "| linked:", plan.email_linked)
    print("Password credential:    ", plan.password_credential_exists)
    print("Existing memberships:   ", len(plan.existing_memberships))
    print("Existing organizations: ", len(plan.existing_organizations))
    print("Would create org:       ", repr(plan.org_name))
    print("Ready:                  ", plan.ready)
    for b in plan.blockers:
        print("  BLOCKER:", b)

    if not plan.ready:
        print("\nREFUSED — account is not recoverable by this tool (see blockers).")
        print("No writes performed.")
        return 2

    result = apply_recovery_plan(plan, dry_run=not args.apply)
    print("\nResult:", result)
    if result.get("applied"):
        print("Recovery applied. The account can now log in.")
    elif result.get("dry_run"):
        print("Dry-run complete. Re-run with --apply to perform the write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

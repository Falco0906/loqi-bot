"""SaaS-2.8 — Production workspace & tenant reconciliation.

Operator-only, dry-run-first tooling that produces a complete READ-ONLY
migration report and classifies each legacy workspace as
READY / BLOCKED / MANUAL_REVIEW.

Reconciliation never guesses organization ownership: a workspace is READY only
when exactly one organization can be deterministically proven as its owner
(via the owner's ACTIVE memberships or an existing valid organization_id).
Multiple plausible candidates -> MANUAL_REVIEW. None -> BLOCKED.

All inspection is read-only. Apply is handled by the operator CLI
(scripts/migrate_legacy_workspaces.py --apply --confirm); it is never run here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.supabase import get_supabase_client

from .legacy_workspace_migration import (
    CHILD_WORKSPACE_TABLES,
    _already_migrated,
    _count,
    _first,
    _select,
    detect_legacy_workspaces,
)

OPTIONAL_REFERENCE_TABLES: tuple[str, ...] = (
    "notifications",
    "audit_log",
    "usage_records",
    "subscriptions",
)


def active_memberships(client: Any, user_id: str) -> list[dict[str, Any]]:
    return _select(client, "memberships", where=[
        ("user_id", "eq", user_id),
        ("status", "eq", "active"),
    ])


def org_candidates(client: Any, owner_user_id: str) -> list[dict[str, Any]]:
    """Organizations the owner is an ACTIVE member of (deterministic candidates)."""
    org_ids = sorted({m.get("organization_id", "") for m in active_memberships(client, owner_user_id)
                      if m.get("organization_id")})
    orgs = []
    for oid in org_ids:
        org = _first(client, "organizations", where=[("id", "eq", oid)])
        if org is not None:
            orgs.append({"organization_id": oid, "name": org.get("name", "")})
    return orgs


def reconcile_workspace(client: Any, workspace_id: str) -> dict[str, Any]:
    """Classify one workspace for migration (READY/BLOCKED/MANUAL_REVIEW)."""
    ws = _first(client, "workspaces",
                where=[("id", "eq", workspace_id), ("deleted_at", "is", "null")])
    if ws is None:
        return {"workspace_id": workspace_id, "status": "blocked",
                "reason": "workspace not found or soft-deleted"}

    owner_user_id = ws.get("owner_user_id", "") or ""
    org_id = ws.get("organization_id", "") or ""

    if _already_migrated(client, workspace_id):
        return {"workspace_id": workspace_id, "status": "manual_review",
                "reason": "already migrated (provenance set)", "already_migrated": True}

    if not owner_user_id:
        return {"workspace_id": workspace_id, "status": "blocked",
                "reason": "owner_user_id is missing"}
    owner = _first(client, "identity_users", where=[("id", "eq", owner_user_id)])
    if owner is None:
        return {"workspace_id": workspace_id, "status": "blocked",
                "reason": "owner user does not exist"}

    memberships = active_memberships(client, owner_user_id)

    # Existing organization_id is the strongest evidence if it is valid.
    if org_id:
        org = _first(client, "organizations", where=[("id", "eq", org_id)])
        if org is None:
            return {"workspace_id": workspace_id, "status": "blocked",
                    "reason": "organization does not exist"}
        # Confirm the owner is an ACTIVE member of that org.
        if not any(m.get("organization_id") == org_id for m in memberships):
            return {"workspace_id": workspace_id, "status": "manual_review",
                    "reason": "workspace.organization_id conflicts with owner's active membership"}
        return {"workspace_id": workspace_id, "status": "ready",
                "organization_id": org_id, "owner_user_id": owner_user_id,
                "evidence": "workspace.organization_id matches owner's active membership"}

    # No organization_id: derive from the owner's ACTIVE memberships.
    if not memberships:
        return {"workspace_id": workspace_id, "status": "blocked",
                "reason": "owner has no active organization membership"}
    cands = org_candidates(client, owner_user_id)
    if len(cands) == 1:
        return {"workspace_id": workspace_id, "status": "ready",
                "organization_id": cands[0]["organization_id"],
                "owner_user_id": owner_user_id,
                "evidence": "owner has exactly one active organization membership"}
    if len(cands) > 1:
        return {"workspace_id": workspace_id, "status": "manual_review",
                "reason": "owner has multiple active organization memberships; ambiguous",
                "owner_user_id": owner_user_id,
                "organization_candidates": cands}
    return {"workspace_id": workspace_id, "status": "blocked",
            "reason": "owner's active memberships resolve to no organization"}


def child_counts_for(client: Any, workspace_id: str) -> dict[str, int]:
    return {t: _count(client, t, [("workspace_id", "eq", workspace_id)])
            for t in CHILD_WORKSPACE_TABLES}


def duplicate_memberships(client: Any) -> list[dict[str, Any]]:
    """Detect duplicate active memberships per (user, org)."""
    rows = _select(client, "memberships")
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for m in rows:
        by_key.setdefault((m.get("user_id", ""), m.get("organization_id", "")), []).append(m)
    return [
        {
            "user_id": k[0], "organization_id": k[1],
            "memberships": [{ "id": m.get("id"), "status": m.get("status"),
                              "role": m.get("role"), "created_at": m.get("created_at") } for m in v],
        }
        for k, v in by_key.items() if len(v) > 1
    ]


def duplicate_organizations(client: Any) -> list[dict[str, Any]]:
    """Report orgs sharing the same canonical owner (created_by) as duplicates."""
    rows = _select(client, "organizations", where=[("deleted_at", "is", "null")])
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for o in rows:
        by_owner.setdefault(o.get("created_by", "") or o.get("owner_id", ""), []).append(o)
    return [
        {"owner_user_id": k, "organizations": [{
            "id": o.get("id"), "name": o.get("name", ""), "slug": o.get("slug", ""),
            "created_at": o.get("created_at"),
        } for o in v]}
        for k, v in by_owner.items() if len(v) > 1
    ]


def inspect_production(client: Any = None) -> dict[str, Any]:
    """READ-ONLY: full migration report. Never writes."""
    client = client or get_supabase_client()
    workspaces = _select(client, "workspaces", where=[("deleted_at", "is", "null")])
    session_ids = {r["id"] for r in _select(client, "workflow_sessions",
                                            where=[("channel", "eq", "workspace")])}
    # Internally-consistent categories: every active workspace is exactly one of
    # legacy (id matches a channel='workspace' workflow session) or non-legacy.
    legacy_ids = {w["id"] for w in workspaces if w["id"] in session_ids}
    legacy_count = len(legacy_ids)
    non_legacy_count = len(workspaces) - legacy_count

    with_org = sum(1 for w in workspaces if (w.get("organization_id") or ""))
    without_org = len(workspaces) - with_org
    missing_org = sum(1 for w in workspaces
                      if (w.get("organization_id") or "") and
                      _first(client, "organizations",
                             where=[("id", "eq", w["organization_id"])]) is None)
    missing_owner = sum(1 for w in workspaces if not (w.get("owner_user_id") or ""))
    owner_missing_user = 0
    owner_no_membership = 0
    owner_one_membership = 0
    owner_multi_membership = 0
    org_conflicts = 0
    for w in workspaces:
        oid = w.get("owner_user_id", "")
        if not oid:
            continue
        if _first(client, "identity_users", where=[("id", "eq", oid)]) is None:
            owner_missing_user += 1
            continue
        mems = active_memberships(client, oid)
        if not mems:
            owner_no_membership += 1
        elif len(mems) == 1:
            owner_one_membership += 1
        else:
            owner_multi_membership += 1
        if (w.get("organization_id") or "") and not any(
            m.get("organization_id") == w["organization_id"] for m in mems
        ):
            org_conflicts += 1

    # Per-workspace reconciliation summary.
    ready = blocked = manual = 0
    blocker_categories: dict[str, int] = {}
    affected: dict[str, Any] = {}
    for ws in workspaces:
        if ws["id"] not in session_ids:
            continue
        rec = reconcile_workspace(client, ws["id"])
        if rec["status"] == "ready":
            ready += 1
        elif rec["status"] == "blocked":
            blocked += 1
            blocker_categories[rec.get("reason", "blocked")] = \
                blocker_categories.get(rec.get("reason", "blocked"), 0) + 1
        else:
            manual += 1
        affected[ws["id"]] = {"status": rec["status"],
                              "reason": rec.get("reason", ""),
                              "child_counts": child_counts_for(client, ws["id"])}

    return {
        "total_active_workspaces": len(workspaces),
        "legacy_workspaces": legacy_count,
        "already_migrated_workspaces": sum(
            1 for w in workspaces if (w.get("workflow_session_id") or "") and w["id"] != w["workflow_session_id"]
        ),
        "non_legacy_workspaces": non_legacy_count,
        "workspaces_with_organization_id": with_org,
        "workspaces_without_organization_id": without_org,
        "workspaces_org_id_missing_organization": missing_org,
        "workspaces_missing_owner": missing_owner,
        "workspaces_owner_user_missing": owner_missing_user,
        "workspaces_owner_no_membership": owner_no_membership,
        "workspaces_owner_one_membership": owner_one_membership,
        "workspaces_owner_multi_membership": owner_multi_membership,
        "workspaces_org_id_conflicts_membership": org_conflicts,
        "duplicate_organizations": duplicate_organizations(client),
        "duplicate_memberships": duplicate_memberships(client),
        "ready": ready,
        "blocked": blocked,
        "manual_review": manual,
        "blocker_categories": blocker_categories,
        "affected_workspaces": affected,
    }


# ─── Migration mapping (durable idempotency / rollback) ────────────────

def record_migration(client: Any, *, legacy_workspace_id: str, new_workspace_id: str,
                     workflow_session_id: str, organization_id: str, owner_user_id: str,
                     status: str = "applied", error: str = "") -> None:
    """Upsert a durable migration mapping record (idempotent by legacy id)."""
    existing = _first(client, "workspace_migrations",
                      where=[("legacy_workspace_id", "eq", legacy_workspace_id)])
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": existing.get("id") if existing else str(__import__("uuid").uuid4()),
        "legacy_workspace_id": legacy_workspace_id,
        "new_workspace_id": new_workspace_id,
        "workflow_session_id": workflow_session_id,
        "organization_id": organization_id,
        "owner_user_id": owner_user_id,
        "status": status,
        "error": error,
        "updated_at": now,
    }
    if existing:
        client.table("workspace_migrations").update(row).eq("id", row["id"]).execute()
    else:
        row["created_at"] = now
        client.table("workspace_migrations").insert(row).execute()


def find_migration(client: Any, legacy_workspace_id: str) -> dict[str, Any] | None:
    return _first(client, "workspace_migrations",
                  where=[("legacy_workspace_id", "eq", legacy_workspace_id)])


def verify_migration(client: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Post-migration verification for a migrated legacy workspace."""
    legacy_id = plan["legacy_workspace_id"]
    new_id = plan["new_workspace_id"]
    checks: dict[str, Any] = {}
    new_ws = _first(client, "workspaces", where=[("id", "eq", new_id)])
    checks["new_workspace_exists"] = new_ws is not None
    checks["owner_correct"] = bool(new_ws) and (new_ws.get("owner_user_id") == plan.get("owner_user_id"))
    checks["org_correct"] = bool(new_ws) and (new_ws.get("organization_id") == plan.get("organization_id"))
    checks["workflow_session_id_correct"] = bool(new_ws) and (new_ws.get("workflow_session_id") == legacy_id)
    legacy_ws = _first(client, "workspaces", where=[("id", "eq", legacy_id)])
    checks["legacy_soft_deleted"] = bool(legacy_ws) and (legacy_ws.get("deleted_at") is not None)
    checks["workflow_session_intact"] = _first(
        client, "workflow_sessions", where=[("id", "eq", legacy_id)]) is not None
    remaining = sum(_count(client, t, [("workspace_id", "eq", legacy_id)])
                    for t in CHILD_WORKSPACE_TABLES)
    checks["no_children_remain_under_legacy"] = remaining == 0
    checks["all_ok"] = all(checks.get(k) for k in (
        "new_workspace_exists", "owner_correct", "org_correct", "workflow_session_id_correct",
        "legacy_soft_deleted", "workflow_session_intact", "no_children_remain_under_legacy"))
    return checks


# ─── Organization adoption planning (SaaS-2.8.1, read-only) ─────────────

def _all_memberships(client: Any, user_id: str) -> list[dict[str, Any]]:
    return _select(client, "memberships", where=[("user_id", "eq", user_id)])


def _historical_org_ids(client: Any, user_id: str) -> set[str]:
    """Organization ids referenced by the user's registration sessions (durable)."""
    rows = _select(client, "registration_sessions")
    return {r.get("organization_id", "") for r in rows
            if r.get("organization_id") and (r.get("user_id") == user_id)}


def membership_action_for(proposed_org: str, memberships: list[dict[str, Any]]) -> str:
    """Determine the required membership transition for a proposed org."""
    for m in memberships:
        if m.get("organization_id") == proposed_org:
            status = (m.get("status") or "").lower()
            if status == "active":
                return "none"
            if status == "pending":
                return "activate"
            if status == "removed":
                return "reactivate"
            if status == "left":
                return "rejoin"
    return "create"


def adoption_plan_for_workspace(client: Any = None, workspace_id: str = "") -> dict[str, Any]:
    """Read-only deterministic adoption plan for one legacy workspace.

    Never writes. Returns a machine-readable plan with a classification:
      READY_FOR_ADOPTION / BLOCKED / MANUAL_REVIEW / NO_DETERMINISTIC_ORG
    plus a proposed organization, evidence and required membership action.
    """
    client = client or get_supabase_client()

    def _result(classification, *, proposed="", evidence="", action="none",
                memberships=None, blockers=None):
        return {
            "workspace_id": workspace_id,
            "classification": classification,
            "proposed_organization_id": proposed,
            "organization_evidence": evidence,
            "membership_action": action,
            "memberships": memberships or [],
            "blockers": blockers or [],
            "requires_manual_approval": classification != "READY_FOR_ADOPTION",
        }

    ws = _first(client, "workspaces",
                where=[("id", "eq", workspace_id), ("deleted_at", "is", "null")])
    if ws is None:
        return _result("BLOCKED", blockers=["workspace not found or soft-deleted"])
    if _already_migrated(client, workspace_id):
        return _result("BLOCKED", blockers=["already migrated"])

    owner = ws.get("owner_user_id", "") or ""
    org_id = ws.get("organization_id", "") or ""
    if not owner:
        return _result("BLOCKED", blockers=["owner_user_id is missing"])
    if _first(client, "identity_users", where=[("id", "eq", owner)]) is None:
        return _result("BLOCKED", blockers=["owner user does not exist"])

    memberships = _all_memberships(client, owner)
    active_memberships = [m for m in memberships if (m.get("status") or "").lower() == "active"]

    def _org_exists(oid: str) -> bool:
        return oid and _first(client, "organizations", where=[("id", "eq", oid)]) is not None

    # Rule A: valid workspace.organization_id + owner ACTIVE membership.
    if org_id and _org_exists(org_id):
        if any(m.get("organization_id") == org_id for m in active_memberships):
            return _result("READY_FOR_ADOPTION", proposed=org_id,
                           evidence="workspace.organization_id valid and owner has ACTIVE membership",
                           action="none", memberships=memberships)
        # Owner has a (non-active) membership in the workspace's org.
        if any(m.get("organization_id") == org_id for m in memberships):
            return _result("READY_FOR_ADOPTION", proposed=org_id,
                           evidence="workspace.organization_id valid; owner has a membership record",
                           action=membership_action_for(org_id, memberships),
                           memberships=memberships)
        return _result("MANUAL_REVIEW",
                       blockers=["workspace.organization_id valid but owner has no membership in it"],
                       memberships=memberships)

    # Dangling organization_id: prove the intended org from durable relationships.
    if org_id and not _org_exists(org_id):
        candidate_orgs = sorted({m.get("organization_id") for m in memberships
                                 if _org_exists(m.get("organization_id"))})
        if len(candidate_orgs) == 1:
            return _result("READY_FOR_ADOPTION", proposed=candidate_orgs[0],
                           evidence="dangling organization_id; owner's sole membership org",
                           action=membership_action_for(candidate_orgs[0], memberships),
                           memberships=memberships)
        if len(candidate_orgs) > 1:
            return _result("MANUAL_REVIEW",
                           blockers=["dangling organization_id; owner has multiple membership orgs"],
                           memberships=memberships)
        return _result("NO_DETERMINISTIC_ORG",
                       blockers=["dangling organization_id and no deterministic owner-org link"],
                       memberships=memberships)

    # No organization_id: derive from owner's ACTIVE memberships.
    active_orgs = sorted({m.get("organization_id") for m in active_memberships
                          if _org_exists(m.get("organization_id"))})
    if len(active_orgs) == 1:
        return _result("READY_FOR_ADOPTION", proposed=active_orgs[0],
                       evidence="owner has exactly one ACTIVE organization membership",
                       action="none", memberships=memberships)
    if len(active_orgs) > 1:
        return _result("MANUAL_REVIEW",
                       blockers=["owner has multiple ACTIVE organizations; ambiguous"],
                       memberships=memberships)

    # No ACTIVE membership: historical registration/session org link.
    historical = sorted({oid for oid in _historical_org_ids(client, owner) if _org_exists(oid)})
    if len(historical) == 1:
        return _result("READY_FOR_ADOPTION", proposed=historical[0],
                       evidence="deterministic historical registration org link",
                       action="create", memberships=memberships)
    if len(historical) > 1:
        return _result("MANUAL_REVIEW",
                       blockers=["multiple historical orgs; ambiguous"],
                       memberships=memberships)
    return _result("NO_DETERMINISTIC_ORG",
                   blockers=["no active membership and no deterministic organization evidence"],
                   memberships=memberships)


def build_adoption_report(client: Any = None) -> dict[str, Any]:
    """Read-only aggregate adoption report across ALL legacy workspaces."""
    client = client or get_supabase_client()
    workspaces = _select(client, "workspaces", where=[("deleted_at", "is", "null")])
    session_ids = {r["id"] for r in _select(client, "workflow_sessions",
                                            where=[("channel", "eq", "workspace")])}
    counts = {"READY_FOR_ADOPTION": 0, "BLOCKED": 0, "MANUAL_REVIEW": 0,
              "NO_DETERMINISTIC_ORG": 0}
    plans: dict[str, Any] = {}
    for w in workspaces:
        if w["id"] not in session_ids:
            continue
        plan = adoption_plan_for_workspace(client, w["id"])
        plans[w["id"]] = plan
        counts[plan["classification"]] = counts.get(plan["classification"], 0) + 1
    return {"legacy_workspaces": len(plans), "counts": counts, "plans": plans}

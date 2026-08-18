"""Safe operator-only account recovery: provision the durable organization +
owner membership that a legacy completed account is missing.

Background: before commit c6aa780, the identity organization/owner-membership
lived only in in-memory repositories, so an account completed under that build
has no durable `organizations` / `memberships` rows. login() then correctly
rejects it at the active-membership gate ("No active organization
membership"). This module rebuilds exactly the rows normal signup completion
would have written, using the same durable repositories and schema, without
touching the user, credentials, billing, or verification state.

Fail-closed design:
- dry-run by default; only an explicit --apply (operator CLI) mutates.
- refuses if the email identity is missing, unverified, or unlinked.
- refuses if the supplied user_id does not match the email identity's user_id.
- refuses if no password credential exists (never fabricates auth).
- refuses if an organization or owner membership already exists (idempotent;
  a pre-existing row means this is not a missing-data recovery).
- never inserts or updates identity_users.
- never touches password, billing, or verification tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.identity.services.organization_service import OrganizationService
from services.supabase import _run_blocking


@dataclass
class RecoveryPlan:
    email: str = ""
    user_id: str = ""
    display_name: str = ""
    email_identity_id: str = ""
    email_verified: bool = False
    email_linked: bool = False
    password_credential_exists: bool = False
    existing_memberships: list[dict[str, Any]] = field(default_factory=list)
    existing_organizations: list[dict[str, Any]] = field(default_factory=list)
    org_name: str = "My Organization"
    user_id_mismatch: bool = False

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def blockers(self) -> list[str]:
        reasons: list[str] = []
        if not self.email:
            reasons.append("target email is required")
        if self.user_id_mismatch:
            reasons.append("pinned user_id does not own the email identity")
        if not self.email_verified:
            reasons.append("email identity is missing or not verified")
        if not self.email_linked:
            reasons.append("email identity is not linked to a user_id")
        if not self.password_credential_exists:
            reasons.append("no password credential exists for the user")
        if self.existing_memberships:
            reasons.append(
                f"membership already exists ({len(self.existing_memberships)} row(s))"
            )
        if self.existing_organizations:
            reasons.append(
                f"organization already exists ({len(self.existing_organizations)} row(s))"
            )
        return reasons

    def summarize(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "user_id": self.user_id,
            "ready": self.ready,
            "blockers": self.blockers,
            "email_identity_id": self.email_identity_id,
            "email_verified": self.email_verified,
            "email_linked": self.email_linked,
            "password_credential_exists": self.password_credential_exists,
            "existing_memberships": self.existing_memberships,
            "existing_organizations": self.existing_organizations,
            "would_create_organization": self.org_name,
            "would_create_membership": {"role": "owner", "status": "active"},
        }


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _first(data: list[dict[str, Any]]) -> dict[str, Any] | None:
    return data[0] if data else None


def build_recovery_plan(
    email: str,
    user_id: str = "",
    client: Any = None,
) -> RecoveryPlan:
    """Read-only scan of durable identity state for a candidate account.

    Uses the supplied PostgREST-like client (FakeClient in tests, the real
    Supabase client in the operator CLI). Never writes.
    """
    from services.supabase import get_supabase_client

    client = client or get_supabase_client()
    if client is None:
        raise RuntimeError("Supabase client unavailable")

    plan = RecoveryPlan(email=normalize_email(email))

    ei = _first(getattr(
        client.table("email_identities").select("*").eq("email", plan.email).limit(1).execute(),
        "data", None,
    ) or [])
    if ei is None:
        return plan

    plan.email_identity_id = ei.get("id", "")
    plan.email_verified = bool(ei.get("is_verified"))
    plan.email_linked = bool(ei.get("user_id"))
    plan.user_id = ei.get("user_id", "")

    if user_id and user_id != plan.user_id:
        # The caller pinned a user_id that does not own this email identity.
        # Refuse loudly instead of recovering the wrong account.
        plan.user_id_mismatch = True
        return plan

    if not plan.email_linked:
        return plan

    pc = _first(getattr(
        client.table("password_credentials").select("id").eq("user_id", plan.user_id).limit(1).execute(),
        "data", None,
    ) or [])
    plan.password_credential_exists = pc is not None

    plan.existing_memberships = [
        {
            "organization_id": m.get("organization_id"),
            "role": m.get("role"),
            "status": m.get("status"),
        }
        for m in (
            getattr(client.table("memberships").select("*").eq("user_id", plan.user_id).execute(), "data", None)
            or []
        )
    ]
    plan.existing_organizations = [
        {
            "id": o.get("id"),
            "slug": o.get("slug"),
            "status": o.get("status"),
            "deleted_at": o.get("deleted_at"),
        }
        for o in (
            getattr(client.table("organizations").select("*").eq("created_by", plan.user_id).execute(), "data", None)
            or []
        )
    ]

    user = _first(getattr(
        client.table("identity_users").select("display_name").eq("id", plan.user_id).limit(1).execute(),
        "data", None,
    ) or [])
    if user and user.get("display_name"):
        plan.display_name = user.get("display_name", "")
        plan.org_name = f"{plan.display_name.strip()}'s Organization"

    return plan


def apply_recovery_plan(
    plan: RecoveryPlan,
    dry_run: bool = True,
    org_repo: Any = None,
    mem_repo: Any = None,
) -> dict[str, Any]:
    """Create exactly one organization + one owner membership (or report why not).

    Reuses the same durable repositories and OrganizationService.create_organization
    path as normal signup completion, so recovered rows are byte-identical in
    shape to a fresh completion. Idempotent: refuses when a membership or
    organization already exists. Never mutates identity_users.

    ``dry_run=True`` (default) performs no writes at all.
    """
    if not plan.ready:
        return {
            "applied": False,
            "dry_run": dry_run,
            "reason": "not ready",
            "blockers": plan.blockers,
        }
    if dry_run:
        return {
            "applied": False,
            "dry_run": True,
            "reason": "dry-run (no writes)",
            "blockers": [],
            "plan": plan.summarize(),
        }

    from services.persistence.repositories.identity_org_repositories import (
        SupabaseIdentityMembershipRepository,
        SupabaseIdentityOrganizationRepository,
    )

    org_repo = org_repo or SupabaseIdentityOrganizationRepository()
    mem_repo = mem_repo or SupabaseIdentityMembershipRepository()
    org_svc = OrganizationService(org_repo, mem_repo)

    org, membership, _event = _run_blocking(
        org_svc.create_organization(plan.org_name, plan.user_id)
    )
    return {
        "applied": True,
        "dry_run": False,
        "organization_id": org.id,
        "organization_name": org.name,
        "organization_slug": org.slug,
        "membership_id": membership.id,
        "membership_role": membership.role,
        "membership_status": membership.status.value,
        "user_id": plan.user_id,
    }

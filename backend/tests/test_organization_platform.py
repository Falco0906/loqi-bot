from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio

from services.organizations.api import register_deps as _register_org_deps, OrgDeps as _OrgDeps
from services.organizations.repositories import (
    InMemoryInvitationRepository as _InMemoryInvitationRepository,
    InMemoryMembershipRepository as _InMemoryMembershipRepository,
    InMemoryOrganizationRepository as _InMemoryOrganizationRepository,
)
from services.organizations.resolver import CurrentOrganizationResolver as _CurrentOrganizationResolver
from services.organizations.services import (
    InvitationService as _InvitationService,
    MembershipService as _MembershipService,
    OrganizationService as _OrganizationService,
)

from services.organizations.exceptions import (
    InvitationExpired,
    InvitationNotFound,
    LastOwnerCannotBeRemoved,
    LastOwnerCannotLeave,
    MembershipAlreadyExists,
    MembershipNotFound,
    OrganizationNameTaken,
    OrganizationNotFound,
    OrganizationSlugTaken,
)
from services.organizations.models import (
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationStatus,
)
from services.organizations.repositories import (
    InMemoryInvitationRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
)
from services.organizations.resolver import CurrentOrganizationResolver
from services.organizations.services import (
    InvitationService,
    MembershipService,
    OrganizationService,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def org_repo() -> InMemoryOrganizationRepository:
    return InMemoryOrganizationRepository()


@pytest.fixture
def membership_repo() -> InMemoryMembershipRepository:
    return InMemoryMembershipRepository()


@pytest.fixture
def invitation_repo() -> InMemoryInvitationRepository:
    return InMemoryInvitationRepository()


@pytest.fixture
def org_service(org_repo, membership_repo) -> OrganizationService:
    return OrganizationService(org_repo, membership_repo)


@pytest.fixture
def membership_service(org_repo, membership_repo) -> MembershipService:
    return MembershipService(membership_repo, org_repo)


@pytest.fixture
def invitation_service(invitation_repo, membership_repo, membership_service) -> InvitationService:
    return InvitationService(invitation_repo, membership_repo, membership_service)


@pytest.fixture
def resolver(org_repo, membership_repo) -> CurrentOrganizationResolver:
    return CurrentOrganizationResolver(org_repo, membership_repo)


# ─── OrganizationService Tests ──────────────────────────────────────


class TestOrganizationService:

    async def test_create_organization(self, org_service) -> None:
        org = await org_service.create_organization(
            name="Acme Corp",
            created_by="user-1",
            display_name="Acme Corporation",
            description="A test company",
        )
        assert org.name == "Acme Corp"
        assert org.display_name == "Acme Corporation"
        assert org.description == "A test company"
        assert org.created_by == "user-1"
        assert org.status == OrganizationStatus.ACTIVE
        assert not org.is_deleted
        assert org.slug is not None
        assert len(org_service.events) == 1
        assert org_service.events[0].event_type.value == "organization.created"

    async def test_create_organization_generates_slug(self, org_service) -> None:
        org = await org_service.create_organization(
            name="My New Org",
            created_by="user-1",
        )
        assert org.slug == "my-new-org"

    async def test_create_organization_with_custom_slug(self, org_service) -> None:
        org = await org_service.create_organization(
            name="My Org",
            created_by="user-1",
            slug="my-custom-org",
        )
        assert org.slug == "my-custom-org"

    async def test_create_organization_slug_taken(self, org_service) -> None:
        await org_service.create_organization(name="First", created_by="user-1", slug="same-slug")
        with pytest.raises(OrganizationSlugTaken):
            await org_service.create_organization(name="Second", created_by="user-2", slug="same-slug")

    async def test_create_organization_name_taken(self, org_service) -> None:
        await org_service.create_organization(name="Same Name", created_by="user-1")
        with pytest.raises(OrganizationNameTaken):
            await org_service.create_organization(name="Same Name", created_by="user-2")

    async def test_create_organization_adds_owner_membership(self, org_service, membership_repo) -> None:
        org = await org_service.create_organization(name="Owner Test", created_by="user-owner")
        membership = await membership_repo.find_by_user_and_org("user-owner", org.id)
        assert membership is not None
        assert membership.role == MembershipRole.OWNER
        assert membership.status == MembershipStatus.ACTIVE

    async def test_get_organization(self, org_service) -> None:
        org = await org_service.create_organization(name="Get Test", created_by="user-1")
        found = await org_service.get_organization(org.id)
        assert found.id == org.id
        assert found.name == "Get Test"

    async def test_get_organization_not_found(self, org_service) -> None:
        with pytest.raises(OrganizationNotFound):
            await org_service.get_organization("nonexistent")

    async def test_get_organization_deleted(self, org_service) -> None:
        org = await org_service.create_organization(name="Delete Me", created_by="user-1")
        await org_service.soft_delete_organization(org.id, "user-1")
        with pytest.raises(OrganizationNotFound):
            await org_service.get_organization(org.id)

    async def test_get_organization_by_slug(self, org_service) -> None:
        org = await org_service.create_organization(name="Slug Test", created_by="user-1")
        found = await org_service.get_organization_by_slug(org.slug)
        assert found.id == org.id

    async def test_update_organization(self, org_service) -> None:
        org = await org_service.create_organization(name="Old Name", created_by="user-1")
        updated = await org_service.update_organization(
            org.id, updated_by="user-1", name="New Name", description="Updated desc"
        )
        assert updated.name == "New Name"
        assert updated.description == "Updated desc"
        assert len(org_service.events) == 2
        assert org_service.events[1].event_type.value == "organization.updated"

    async def test_update_organization_slug_taken(self, org_service) -> None:
        await org_service.create_organization(name="First", created_by="user-1", slug="existing")
        org2 = await org_service.create_organization(name="Second", created_by="user-2", slug="second")
        with pytest.raises(OrganizationSlugTaken):
            await org_service.update_organization(org2.id, updated_by="user-2", slug="existing")

    async def test_soft_delete_organization(self, org_service) -> None:
        org = await org_service.create_organization(name="To Delete", created_by="user-1")
        await org_service.soft_delete_organization(org.id, "user-1")
        assert org.is_deleted
        assert len(org_service.events) == 2
        assert org_service.events[1].event_type.value == "organization.deleted"

    async def test_list_user_organizations(self, org_service) -> None:
        org1 = await org_service.create_organization(name="Org One", created_by="user-multi")
        org2 = await org_service.create_organization(name="Org Two", created_by="user-multi")
        orgs = await org_service.list_user_organizations("user-multi")
        assert len(orgs) == 2
        assert {o.id for o in orgs} == {org1.id, org2.id}

    async def test_list_user_organizations_excludes_deleted(self, org_service) -> None:
        org = await org_service.create_organization(name="To Hide", created_by="user-multi")
        await org_service.soft_delete_organization(org.id, "user-multi")
        orgs = await org_service.list_user_organizations("user-multi")
        assert len(orgs) == 0

    async def test_events_cleared(self, org_service) -> None:
        await org_service.create_organization(name="Events Test", created_by="user-1")
        assert len(org_service.events) == 1
        org_service.clear_events()
        assert len(org_service.events) == 0


# ─── MembershipService Tests ────────────────────────────────────────


class TestMembershipService:

    async def test_add_member(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Membership Test", created_by="user-owner")
        membership = await membership_service.add_member(org.id, "user-member")
        assert membership.user_id == "user-member"
        assert membership.role == MembershipRole.MEMBER
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.organization_id == org.id

    async def test_add_member_to_inactive_org(self, org_service, membership_service) -> None:
        from services.organizations.exceptions import OrganizationNotActive
        org = await org_service.create_organization(name="Inactive Org", created_by="user-1")
        org.status = OrganizationStatus.SUSPENDED
        await org_service._org_repo.save(org)
        with pytest.raises(OrganizationNotActive):
            await membership_service.add_member(org.id, "user-2")
        from services.organizations.exceptions import OrganizationNotActive
        with pytest.raises(OrganizationNotActive):
            await membership_service.add_member(org.id, "user-2")

    async def test_add_duplicate_member(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Duplicates", created_by="user-owner")
        await membership_service.add_member(org.id, "user-dupe")
        with pytest.raises(MembershipAlreadyExists):
            await membership_service.add_member(org.id, "user-dupe")

    async def test_add_member_reactivates_removed(self, org_service, membership_service, membership_repo) -> None:
        org = await org_service.create_organization(name="Rejoin", created_by="user-owner")
        await membership_service.add_member(org.id, "user-rejoin")
        membership = await membership_repo.find_by_user_and_org("user-rejoin", org.id)
        membership.mark_removed()
        await membership_repo.save(membership)
        new_membership = await membership_service.add_member(org.id, "user-rejoin")
        assert new_membership.is_active
        assert new_membership.status == MembershipStatus.ACTIVE

    async def test_remove_member(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Remove Member", created_by="user-owner")
        await membership_service.add_member(org.id, "user-to-remove")
        await membership_service.remove_member(org.id, "user-to-remove", "user-owner")
        membership = await membership_service._membership_repo.find_by_user_and_org("user-to-remove", org.id)
        assert membership.status == MembershipStatus.REMOVED

    async def test_remove_last_owner_fails(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Last Owner", created_by="user-owner")
        await membership_service.add_member(
            org.id, "user-admin", role=MembershipRole.ADMIN,
        )
        with pytest.raises(LastOwnerCannotBeRemoved):
            await membership_service.remove_member(org.id, "user-owner", "user-admin")

    async def test_non_member_cannot_remove_member(self, org_service, membership_service) -> None:
        from services.organizations.exceptions import InsufficientRole
        org = await org_service.create_organization(name="Intruder Org", created_by="user-owner")
        with pytest.raises(InsufficientRole):
            await membership_service.remove_member(org.id, "user-owner", "intruder")

    async def test_self_remove_fails(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Self Remove", created_by="user-owner")
        with pytest.raises(LastOwnerCannotLeave):
            await membership_service.remove_member(org.id, "user-owner", "user-owner")

    async def test_leave_organization(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Leave Org", created_by="user-owner")
        await membership_service.add_member(org.id, "user-leaver")
        await membership_service.leave_organization("user-leaver", org.id)
        membership = await membership_service._membership_repo.find_by_user_and_org("user-leaver", org.id)
        assert membership.status == MembershipStatus.LEFT

    async def test_owner_cannot_leave_as_last(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Last Owner Leave", created_by="user-owner")
        with pytest.raises(LastOwnerCannotLeave):
            await membership_service.leave_organization("user-owner", org.id)

    async def test_change_role(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Role Change", created_by="user-owner")
        await membership_service.add_member(org.id, "user-to-promote")
        membership = await membership_service.change_role(
            org.id, "user-to-promote", MembershipRole.ADMIN, "user-owner"
        )
        assert membership.role == MembershipRole.ADMIN

    async def test_transfer_ownership(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Transfer", created_by="user-owner")
        await membership_service.add_member(org.id, "user-new-owner")
        await membership_service.transfer_ownership(org.id, "user-owner", "user-new-owner")
        old_owner = await membership_service._membership_repo.find_by_user_and_org("user-owner", org.id)
        new_owner = await membership_service._membership_repo.find_by_user_and_org("user-new-owner", org.id)
        assert old_owner.role == MembershipRole.ADMIN
        assert new_owner.role == MembershipRole.OWNER

    async def test_get_memberships(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="List Members", created_by="user-owner")
        await membership_service.add_member(org.id, "user-a")
        await membership_service.add_member(org.id, "user-b")
        members = await membership_service.get_memberships(org.id)
        assert len(members) == 3  # owner + 2 members

    async def test_get_user_membership(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Get Member", created_by="user-owner")
        membership = await membership_service.get_user_membership("user-owner", org.id)
        assert membership.role == MembershipRole.OWNER

    async def test_get_user_membership_not_found(self, org_service, membership_service) -> None:
        org = await org_service.create_organization(name="Not Found", created_by="user-owner")
        with pytest.raises(MembershipNotFound):
            await membership_service.get_user_membership("nobody", org.id)


# ─── InvitationService Tests ────────────────────────────────────────


class TestInvitationService:

    async def test_invite(self, org_service, invitation_service) -> None:
        org = await org_service.create_organization(name="Invite Test", created_by="user-owner")
        invitation = await invitation_service.invite(org.id, "test@example.com", created_by="user-owner")
        assert invitation.email == "test@example.com"
        assert invitation.organization_id == org.id
        assert invitation.status == InvitationStatus.PENDING
        assert invitation.token is not None
        assert len(invitation.token) > 0

    async def test_accept_invitation(self, org_service, invitation_service) -> None:
        org = await org_service.create_organization(name="Accept Invite", created_by="user-owner")
        invitation = await invitation_service.invite(org.id, "newuser@example.com", created_by="user-owner")
        membership = await invitation_service.accept_invitation(invitation.token, "user-new")
        assert membership.organization_id == org.id
        assert membership.user_id == "user-new"
        assert membership.role == MembershipRole.MEMBER
        invitation = await invitation_service._invitation_repo.get(invitation.id)
        assert invitation.status == InvitationStatus.ACCEPTED

    async def test_accept_invitation_invalid_token(self, invitation_service) -> None:
        with pytest.raises(InvitationNotFound):
            await invitation_service.accept_invitation("bad-token", "user-1")

    async def test_accept_expired_invitation(self, org_service, invitation_service) -> None:
        from datetime import datetime, timezone, timedelta
        org = await org_service.create_organization(name="Expired Invite", created_by="user-owner")
        invitation = await invitation_service.invite(org.id, "late@example.com", created_by="user-owner")
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await invitation_service._invitation_repo.save(invitation)
        with pytest.raises(InvitationExpired):
            await invitation_service.accept_invitation(invitation.token, "user-late")

    async def test_revoke_invitation(self, org_service, invitation_service) -> None:
        org = await org_service.create_organization(name="Revoke Invite", created_by="user-owner")
        invitation = await invitation_service.invite(org.id, "revoked@example.com", created_by="user-owner")
        await invitation_service.revoke_invitation(invitation.id, "user-owner")
        invitation = await invitation_service._invitation_repo.get(invitation.id)
        assert invitation.status == InvitationStatus.REVOKED

    async def test_get_organization_invitations(self, org_service, invitation_service) -> None:
        org = await org_service.create_organization(name="List Invites", created_by="user-owner")
        await invitation_service.invite(org.id, "a@example.com", created_by="user-owner")
        await invitation_service.invite(org.id, "b@example.com", created_by="user-owner")
        invitations = await invitation_service.get_organization_invitations(org.id)
        assert len(invitations) == 2


# ─── CurrentOrganizationResolver Tests ──────────────────────────────


class TestCurrentOrganizationResolver:

    async def test_resolve_returns_first_membership(self, org_service, resolver) -> None:
        org = await org_service.create_organization(name="Resolver Test", created_by="user-1")
        resolved = await resolver.resolve("user-1")
        assert resolved == org.id

    async def test_resolve_returns_none_when_no_membership(self, resolver) -> None:
        resolved = await resolver.resolve("user-no-org")
        assert resolved is None

    async def test_require_raises_when_no_membership(self, resolver) -> None:
        with pytest.raises(MembershipNotFound):
            await resolver.require("user-no-org")

    async def test_get_role(self, org_service, resolver) -> None:
        org = await org_service.create_organization(name="Role Test", created_by="user-owner")
        role = await resolver.get_role("user-owner", org.id)
        assert role == MembershipRole.OWNER.value

    async def test_require_at_least_admin_owner(self, org_service, resolver) -> None:
        org = await org_service.create_organization(name="Admin Check", created_by="user-owner")
        await resolver.require_at_least_admin("user-owner", org.id)

    async def test_require_at_least_admin_member_fails(self, org_service, resolver) -> None:
        from services.organizations.services import MembershipService
        org = await org_service.create_organization(name="Fail Admin", created_by="user-owner")
        ms = MembershipService(resolver._membership_repo, resolver._org_repo)
        await ms.add_member(org.id, "user-member")
        with pytest.raises(PermissionError):
            await resolver.require_at_least_admin("user-member", org.id)

    async def test_require_owner(self, org_service, resolver) -> None:
        org = await org_service.create_organization(name="Owner Check", created_by="user-owner")
        await resolver.require_owner("user-owner", org.id)

    async def test_require_owner_admin_fails(self, org_service, resolver) -> None:
        from services.organizations.services import MembershipService
        org = await org_service.create_organization(name="Fail Owner", created_by="user-owner")
        ms = MembershipService(resolver._membership_repo, resolver._org_repo)
        await ms.add_member(org.id, "user-admin", role=MembershipRole.ADMIN)
        with pytest.raises(PermissionError):
            await resolver.require_owner("user-admin", org.id)

    async def test_resolve_org_id_with_explicit(self, resolver) -> None:
        result = await resolver.resolve_org_id("any-user", "explicit-org")
        assert result == "explicit-org"


# ─── API Integration Tests ──────────────────────────────────────────


@pytest.fixture(scope="module")
def org_api_client() -> TestClient:
    from main import app
    _org_repo = _InMemoryOrganizationRepository()
    _membership_repo = _InMemoryMembershipRepository()
    _invitation_repo = _InMemoryInvitationRepository()
    _org_svc = _OrganizationService(_org_repo, _membership_repo)
    _membership_svc = _MembershipService(_membership_repo, _org_repo)
    _invitation_svc = _InvitationService(_invitation_repo, _membership_repo, _membership_svc)
    _resolver = _CurrentOrganizationResolver(_org_repo, _membership_repo)
    _register_org_deps(_OrgDeps(
        org_service=_org_svc,
        membership_service=_membership_svc,
        invitation_service=_invitation_svc,
        resolver=_resolver,
    ))
    client = TestClient(app)
    return client


class TestOrganizationAPI:

    def _auth_headers(self, user_id: str = "api-user") -> dict[str, str]:
        return {"X-User-ID": user_id}

    def _override_auth(self, client, user_id: str = "api-user"):
        from services.organizations.api import _get_current_user
        async def override() -> str:
            return user_id
        client.app.dependency_overrides[_get_current_user] = override

    def _clear_overrides(self, client):
        client.app.dependency_overrides.clear()

    def _setup(self, client, user: str = "api-user"):
        self._override_auth(client, user)
        return self._auth_headers(user)

    def test_create_org_via_api(self, org_api_client):
        self._setup(org_api_client, "api-user")
        resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "API Test Org", "slug": "api-test"},
        )
        self._clear_overrides(org_api_client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "API Test Org"
        assert data["slug"] == "api-test"

    def test_create_org_unauthorized(self, org_api_client):
        self._clear_overrides(org_api_client)
        resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "No Auth"},
        )
        assert resp.status_code == 401

    def test_list_orgs(self, org_api_client):
        self._setup(org_api_client, "list-user")
        org_api_client.post(
            "/api/v1/organizations",
            json={"name": "List Org"},
        )
        resp = org_api_client.get("/api/v1/organizations")
        self._clear_overrides(org_api_client)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["organizations"]) >= 1

    def test_get_org(self, org_api_client):
        self._setup(org_api_client, "get-user")
        create_resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "Get Org Test"},
        )
        org_id = create_resp.json()["id"]
        resp = org_api_client.get(f"/api/v1/organizations/{org_id}")
        self._clear_overrides(org_api_client)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Org Test"

    def test_update_org(self, org_api_client):
        self._setup(org_api_client, "update-user")
        create_resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "Update Org"},
        )
        org_id = create_resp.json()["id"]
        resp = org_api_client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Updated Org"},
        )
        self._clear_overrides(org_api_client)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Org"

    def test_delete_org(self, org_api_client):
        self._setup(org_api_client, "delete-user")
        create_resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "Delete Org"},
        )
        org_id = create_resp.json()["id"]
        resp = org_api_client.delete(f"/api/v1/organizations/{org_id}")
        self._clear_overrides(org_api_client)
        assert resp.status_code == 204

    def test_invite_via_api(self, org_api_client):
        self._setup(org_api_client, "invite-owner")
        create_resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "Invite Org"},
        )
        org_id = create_resp.json()["id"]
        resp = org_api_client.post(
            f"/api/v1/organizations/{org_id}/invitations",
            json={"email": "test@example.com"},
        )
        self._clear_overrides(org_api_client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "test@example.com"

    def test_list_members(self, org_api_client):
        self._setup(org_api_client, "member-owner")
        create_resp = org_api_client.post(
            "/api/v1/organizations",
            json={"name": "Members Org"},
        )
        org_id = create_resp.json()["id"]
        resp = org_api_client.get(f"/api/v1/organizations/{org_id}/members")
        self._clear_overrides(org_api_client)
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 1
        assert members[0]["role"] == "owner"


# ─── Onboarding Integration Test ────────────────────────────────────


class TestOnboardingOrgIntegration:

    async def test_complete_workspace_integrates_with_org_service(
        self, org_service,
    ) -> None:
        from services.onboarding.models import LifecycleState, StepId, StepRecord
        from services.onboarding.repositories import (
            InMemoryLifecycleRepository,
            InMemoryOnboardingSessionRepository,
        )
        from services.onboarding.services import LifecycleService, OnboardingService as OS

        lifecycle_repo = InMemoryLifecycleRepository()
        session_repo = InMemoryOnboardingSessionRepository()
        lifecycle_svc = LifecycleService(lifecycle_repo)
        onboarding_svc = OS(lifecycle_svc, session_repo, org_service=org_service)

        lc = await lifecycle_svc.get_or_create("integ-user")
        lc.transition_to(LifecycleState.PROFILE_SETUP)
        await lifecycle_repo.save(lc)

        await onboarding_svc.complete_profile("integ-user", "Test User")

        session, events = await onboarding_svc.complete_workspace(
            "integ-user", "My Onboarded Org", slug="my-onboarded-org",
        )
        assert len(events) >= 1
        orgs = await org_service.list_user_organizations("integ-user")
        names = [o.name for o in orgs]
        assert "My Onboarded Org" in names
        found = await org_service.get_organization_by_slug("my-onboarded-org")
        assert found is not None
        assert found.created_by == "integ-user"

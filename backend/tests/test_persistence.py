"""Tests for M2.1 — Production Persistence Layer.

Supabase repositories are tested with a mock Supabase client.
When no Supabase credentials are available, the client returns None
and repositories fall back gracefully (no persistence, no crash).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.identity.models import (
    PasswordResetRequest,
    RefreshToken,
    Session,
    User,
    VerificationToken,
    VerificationTokenPurpose,
)
from services.billing.models import (
    BillingEvent,
    BillingInterval,
    CheckoutSession,
    CheckoutStatus,
    Customer,
    Invoice,
    InvoiceStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from services.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationSettings,
    OrganizationStatus,
)
from services.persistence import (
    RepositoryProvider,
    reset_connection_manager,
    reset_repository_provider,
    set_connection_manager,
    set_repository_provider,
)
from services.persistence.database import SupabaseConnectionManager
from services.persistence.repositories import (
    SupabaseBillingEventRepository,
    SupabaseCheckoutRepository,
    SupabaseCustomerRepository,
    SupabaseInvitationRepository,
    SupabaseInvoiceRepository,
    SupabaseMembershipRepository,
    SupabaseOrganizationRepository,
    SupabasePasswordResetRepository,
    SupabasePlanRepository,
    SupabaseRefreshTokenRepository,
    SupabaseSessionRepository,
    SupabaseSubscriptionRepository,
    SupabaseUserRepository,
    SupabaseVerificationTokenRepository,
)


# ─── Helpers ─────────────────────────────────────────────────────────────

def _mock_client():
    """Create a MagicMock that acts like a Supabase client."""
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.eq.return_value = client
    client.neq.return_value = client
    client.gt.return_value = client
    client.gte.return_value = client
    client.lt.return_value = client
    client.lte.return_value = client
    client.limit.return_value = client
    client.order.return_value = client
    client.is_.return_value = client
    client.in_.return_value = client
    client.execute.return_value = MagicMock(data=[])
    return client


def _row_result(data: list[dict]):
    return MagicMock(data=data)


def _make_future(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    reset_repository_provider()
    reset_connection_manager()
    set_repository_provider(RepositoryProvider.SUPABASE)


@pytest.fixture
def mock_cm():
    """Set up a connection manager with a mock client."""
    client = _mock_client()
    cm = SupabaseConnectionManager(url="http://test", key="test-key")
    cm._client = client
    set_connection_manager(cm)
    return cm, client


def _mock_data(*rows: dict) -> MagicMock:
    """Return a MagicMock whose execute() returns the given rows as data."""
    result = MagicMock()
    result.data = list(rows)
    execute_mock = MagicMock(return_value=result)
    return execute_mock


# ═══════════════════════════════════════════════════════════════════════════
# 1. SupabaseUserRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseUserRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseUserRepository()
        user = User(display_name="Alice", locale="en")

        # save — no existing
        client.execute.return_value = _row_result([])
        saved = await repo.save(user)
        assert saved.id == user.id

        # get
        client.execute.return_value = _row_result([{
            "id": user.id,
            "display_name": "Alice",
            "avatar_url": "",
            "locale": "en",
            "created_at": _make_future(),
            "updated_at": _make_future(),
            "deleted_at": None,
        }])
        fetched = await repo.get(user.id)
        assert fetched is not None
        assert fetched.id == user.id
        assert fetched.display_name == "Alice"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseUserRepository()
        client.execute.return_value = _row_result([])
        fetched = await repo.get("nonexistent")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseUserRepository()
        client.execute = _mock_data({"id": "u1"})
        deleted = await repo.delete("u1")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseUserRepository()
        client.execute = _mock_data()
        deleted = await repo.delete("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseUserRepository()
        user = User(display_name="Bob")
        saved = await repo.save(user)
        assert saved.id == user.id
        fetched = await repo.get(user.id)
        assert fetched is None
        deleted = await repo.delete(user.id)
        assert deleted is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. SupabaseSessionRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseSessionRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        session = Session(
            user_id="u1",
            organization_id="o1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        client.execute.return_value = _row_result([])
        saved = await repo.save(session)
        assert saved.id == session.id

        client.execute.return_value = _row_result([{
            "id": session.id,
            "user_id": "u1",
            "organization_id": "o1",
            "provider_type": "",
            "device_info": "",
            "ip_address": "",
            "user_agent": "",
            "last_activity_at": _make_future(),
            "expires_at": _make_future(),
            "revoked_at": None,
            "created_at": _make_future(),
        }])
        fetched = await repo.get(session.id)
        assert fetched is not None
        assert fetched.user_id == "u1"

    @pytest.mark.asyncio
    async def test_find_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        client.execute.return_value = _row_result([
            {"id": "s1", "user_id": "u1", "organization_id": "o1",
             "provider_type": "", "device_info": "", "ip_address": "",
             "user_agent": "", "last_activity_at": _make_future(),
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
            {"id": "s2", "user_id": "u1", "organization_id": "o1",
             "provider_type": "", "device_info": "", "ip_address": "",
             "user_agent": "", "last_activity_at": _make_future(),
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
        ])
        sessions = await repo.find_by_user_id("u1")
        assert len(sessions) == 2
        assert all(s.user_id == "u1" for s in sessions)

    @pytest.mark.asyncio
    async def test_find_active_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        client.execute.return_value = _row_result([
            {"id": "s1", "user_id": "u1", "organization_id": "o1",
             "provider_type": "", "device_info": "", "ip_address": "",
             "user_agent": "", "last_activity_at": _make_future(),
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
        ])
        sessions = await repo.find_active_by_user_id("u1")
        assert len(sessions) == 1
        assert sessions[0].is_active

    @pytest.mark.asyncio
    async def test_count_active_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        client.execute.return_value = _row_result([
            {"id": "s1", "user_id": "u1", "organization_id": "o1",
             "provider_type": "", "device_info": "", "ip_address": "",
             "user_agent": "", "last_activity_at": _make_future(),
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
        ])
        count = await repo.count_active_by_user_id("u1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_revoke_all_for_user(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        client.execute = _mock_data({"id": "s1"}, {"id": "s2"})
        count = await repo.revoke_all_for_user("u1")
        assert count == 2

    @pytest.mark.asyncio
    async def test_revoke_all_for_org(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSessionRepository()
        client.execute = _mock_data({"id": "s1"})
        count = await repo.revoke_all_for_org("o1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_no_client(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseSessionRepository()
        assert await repo.find_by_user_id("u1") == []
        assert await repo.find_active_by_user_id("u1") == []
        assert await repo.revoke_all_for_user("u1") == 0
        assert await repo.revoke_all_for_org("o1") == 0
        assert await repo.count_active_by_user_id("u1") == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. SupabaseRefreshTokenRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseRefreshTokenRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        rt = RefreshToken(
            session_id="s1",
            family="f1",
            token_hash="hash1",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(rt)
        assert saved.id == rt.id

        client.execute.return_value = _row_result([{
            "id": rt.id,
            "session_id": "s1",
            "token_hash": "hash1",
            "family": "f1",
            "sequence": 1,
            "expires_at": _make_future(),
            "revoked_at": None,
            "created_at": _make_future(),
        }])
        fetched = await repo.get(rt.id)
        assert fetched is not None
        assert fetched.session_id == "s1"

    @pytest.mark.asyncio
    async def test_find_active_by_session_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute.return_value = _row_result([{
            "id": "rt1", "session_id": "s1", "token_hash": "hash1",
            "family": "f1", "sequence": 1,
            "expires_at": _make_future(), "revoked_at": None,
            "created_at": _make_future(),
        }])
        found = await repo.find_active_by_session_id("s1")
        assert found is not None
        assert found.session_id == "s1"

    @pytest.mark.asyncio
    async def test_find_by_family(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute.return_value = _row_result([
            {"id": "rt1", "session_id": "s1", "token_hash": "h1",
             "family": "f1", "sequence": 1,
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
            {"id": "rt2", "session_id": "s2", "token_hash": "h2",
             "family": "f1", "sequence": 2,
             "expires_at": _make_future(), "revoked_at": None,
             "created_at": _make_future()},
        ])
        tokens = await repo.find_by_family("f1")
        assert len(tokens) == 2

    @pytest.mark.asyncio
    async def test_find_by_hash(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute.return_value = _row_result([{
            "id": "rt1", "session_id": "s1", "token_hash": "hash_abc",
            "family": "f1", "sequence": 1,
            "expires_at": _make_future(), "revoked_at": None,
            "created_at": _make_future(),
        }])
        found = await repo.find_by_hash("hash_abc")
        assert found is not None
        assert str(found.token_hash) == "hash_abc"

    @pytest.mark.asyncio
    async def test_revoke_all_for_session(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute = _mock_data({"id": "rt1"})
        count = await repo.revoke_all_for_session("s1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_revoke_all_for_user(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute = _mock_data({"id": "rt1"}, {"id": "rt2"})
        count = await repo.revoke_all_for_user("u1", ["s1", "s2"])
        assert count == 2

    @pytest.mark.asyncio
    async def test_revoke_all_for_user_empty(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        count = await repo.revoke_all_for_user("u1", [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_revoke_family(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseRefreshTokenRepository()
        client.execute = _mock_data({"id": "rt1"}, {"id": "rt2"})
        count = await repo.revoke_family("f1")
        assert count == 2


# ═══════════════════════════════════════════════════════════════════════════
# 4. SupabaseVerificationTokenRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseVerificationTokenRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseVerificationTokenRepository()
        vt = VerificationToken(
            purpose=VerificationTokenPurpose.VERIFY_EMAIL,
            target="alice@test.com",
            token_hash="vt_hash",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(vt)
        assert saved.id == vt.id

        client.execute.return_value = _row_result([{
            "id": vt.id,
            "purpose": "verify_email",
            "target": "alice@test.com",
            "token_hash": "vt_hash",
            "expires_at": _make_future(),
            "used_at": None,
            "created_at": _make_future(),
        }])
        fetched = await repo.get(vt.id)
        assert fetched is not None

    @pytest.mark.asyncio
    async def test_find_valid_by_target_and_purpose(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseVerificationTokenRepository()
        client.execute.return_value = _row_result([{
            "id": "vt1",
            "purpose": "verify_email",
            "target": "alice@test.com",
            "token_hash": "hash1",
            "expires_at": _make_future(),
            "used_at": None,
            "created_at": _make_future(),
        }])
        found = await repo.find_valid_by_target_and_purpose(
            "alice@test.com", "verify_email"
        )
        assert found is not None
        assert found.target == "alice@test.com"

    @pytest.mark.asyncio
    async def test_find_by_target(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseVerificationTokenRepository()
        client.execute.return_value = _row_result([
            {"id": "vt1", "purpose": "verify_email", "target": "a@b.com",
             "token_hash": "h1", "expires_at": _make_future(),
             "used_at": None, "created_at": _make_future()},
        ])
        tokens = await repo.find_by_target("a@b.com")
        assert len(tokens) == 1

    @pytest.mark.asyncio
    async def test_find_by_hash(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseVerificationTokenRepository()
        client.execute.return_value = _row_result([{
            "id": "vt1", "purpose": "verify_email", "target": "a@b.com",
            "token_hash": "hash_xyz", "expires_at": _make_future(),
            "used_at": None, "created_at": _make_future(),
        }])
        found = await repo.find_by_hash("hash_xyz")
        assert found is not None
        assert str(found.token_hash) == "hash_xyz"

    @pytest.mark.asyncio
    async def test_invalidate_all_for_target(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseVerificationTokenRepository()
        client.execute = _mock_data({"id": "vt1"})
        count = await repo.invalidate_all_for_target("a@b.com")
        assert count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. SupabasePasswordResetRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabasePasswordResetRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePasswordResetRepository()
        pr = PasswordResetRequest(
            user_id="u1",
            token_hash="pr_hash",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(pr)
        assert saved.id == pr.id

        client.execute.return_value = _row_result([{
            "id": pr.id,
            "user_id": "u1",
            "token_hash": "pr_hash",
            "expires_at": _make_future(),
            "used_at": None,
            "created_at": _make_future(),
        }])
        fetched = await repo.get(pr.id)
        assert fetched is not None

    @pytest.mark.asyncio
    async def test_find_valid_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePasswordResetRepository()
        client.execute.return_value = _row_result([{
            "id": "pr1", "user_id": "u1",
            "token_hash": "hash1",
            "expires_at": _make_future(), "used_at": None,
            "created_at": _make_future(),
        }])
        found = await repo.find_valid_by_user_id("u1")
        assert found is not None
        assert found.user_id == "u1"

    @pytest.mark.asyncio
    async def test_invalidate_all_for_user(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePasswordResetRepository()
        client.execute = _mock_data({"id": "pr1"})
        count = await repo.invalidate_all_for_user("u1")
        assert count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. SupabaseOrganizationRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseOrganizationRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        org = Organization(name="Test Org", slug="test-org", created_by="u1")

        client.execute.return_value = _row_result([])
        saved = await repo.save(org)
        assert saved.id == org.id

        client.execute.return_value = _row_result([{
            "id": org.id,
            "name": "Test Org",
            "slug": "test-org",
            "display_name": "",
            "description": "",
            "avatar_url": "",
            "created_by": "u1",
            "status": "active",
            "metadata": "{}",
            "settings": "{}",
            "created_at": _make_future(),
            "updated_at": _make_future(),
            "deleted_at": None,
        }])
        fetched = await repo.get(org.id)
        assert fetched is not None
        assert fetched.id == org.id
        assert fetched.name == "Test Org"
        assert fetched.slug == "test-org"
        assert fetched.status == OrganizationStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_save_with_settings(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        settings = OrganizationSettings(timezone="US/Eastern", locale="es")
        org = Organization(name="With Settings", slug="with-settings", created_by="u1", settings=settings)

        client.execute.return_value = _row_result([])
        saved = await repo.save(org)
        assert saved.id == org.id

        client.execute.return_value = _row_result([{
            "id": org.id,
            "name": "With Settings",
            "slug": "with-settings",
            "display_name": "",
            "description": "",
            "avatar_url": "",
            "created_by": "u1",
            "status": "active",
            "metadata": "{}",
            "settings": '{"timezone": "US/Eastern", "locale": "es", "branding": {}, "preferences": {}, "created_at": "' + _make_future() + '", "updated_at": "' + _make_future() + '"}',
            "created_at": _make_future(),
            "updated_at": _make_future(),
            "deleted_at": None,
        }])
        fetched = await repo.get(org.id)
        assert fetched is not None
        assert fetched.settings is not None
        assert fetched.settings.timezone == "US/Eastern"
        assert fetched.settings.locale == "es"

    @pytest.mark.asyncio
    async def test_find_by_slug(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        client.execute.return_value = _row_result([{
            "id": "o1", "name": "Test Org", "slug": "test-org",
            "display_name": "", "description": "", "avatar_url": "",
            "created_by": "u1", "status": "active",
            "metadata": "{}", "settings": "{}",
            "created_at": _make_future(), "updated_at": _make_future(),
            "deleted_at": None,
        }])
        found = await repo.find_by_slug("test-org")
        assert found is not None
        assert found.id == "o1"

    @pytest.mark.asyncio
    async def test_find_by_slug_nonexistent(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        client.execute.return_value = _row_result([])
        found = await repo.find_by_slug("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_by_name(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        client.execute.return_value = _row_result([{
            "id": "o1", "name": "Test Org", "slug": "test-org",
            "display_name": "", "description": "", "avatar_url": "",
            "created_by": "u1", "status": "active",
            "metadata": "{}", "settings": "{}",
            "created_at": _make_future(), "updated_at": _make_future(),
            "deleted_at": None,
        }])
        found = await repo.find_by_name("Test Org")
        assert found is not None
        assert found.id == "o1"

    @pytest.mark.asyncio
    async def test_find_owned_by(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseOrganizationRepository()
        client.execute.return_value = _row_result([
            {"id": "o1", "name": "Org 1", "slug": "org-1",
             "display_name": "", "description": "", "avatar_url": "",
             "created_by": "u1", "status": "active",
             "metadata": "{}", "settings": "{}",
             "created_at": _make_future(), "updated_at": _make_future(),
             "deleted_at": None},
            {"id": "o2", "name": "Org 2", "slug": "org-2",
             "display_name": "", "description": "", "avatar_url": "",
             "created_by": "u1", "status": "active",
             "metadata": "{}", "settings": "{}",
             "created_at": _make_future(), "updated_at": _make_future(),
             "deleted_at": None},
        ])
        orgs = await repo.find_owned_by("u1")
        assert len(orgs) == 2

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseOrganizationRepository()
        org = Organization(name="No DB", slug="no-db", created_by="u1")
        saved = await repo.save(org)
        assert saved.id == org.id
        fetched = await repo.get(org.id)
        assert fetched is None
        assert await repo.find_by_slug("no-db") is None
        assert await repo.find_by_name("No DB") is None
        assert await repo.find_owned_by("u1") == []


# ═══════════════════════════════════════════════════════════════════════════
# 7. SupabaseMembershipRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseMembershipRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        membership = Membership(
            organization_id="o1",
            user_id="u1",
            role=MembershipRole.ADMIN,
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(membership)
        assert saved.id == membership.id

        client.execute.return_value = _row_result([{
            "id": membership.id,
            "organization_id": "o1",
            "user_id": "u1",
            "role": "admin",
            "status": "active",
            "joined_at": _make_future(),
            "invited_by": "",
        }])
        fetched = await repo.get(membership.id)
        assert fetched is not None
        assert fetched.user_id == "u1"
        assert fetched.role == MembershipRole.ADMIN
        assert fetched.is_active

    @pytest.mark.asyncio
    async def test_find_by_user_and_org(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([{
            "id": "m1", "organization_id": "o1", "user_id": "u1",
            "role": "member", "status": "active",
            "joined_at": _make_future(), "invited_by": "",
        }])
        found = await repo.find_by_user_and_org("u1", "o1")
        assert found is not None
        assert found.id == "m1"

    @pytest.mark.asyncio
    async def test_find_by_user_and_org_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([])
        found = await repo.find_by_user_and_org("u1", "o1")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_by_org_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([
            {"id": "m1", "organization_id": "o1", "user_id": "u1",
             "role": "member", "status": "active",
             "joined_at": _make_future(), "invited_by": ""},
            {"id": "m2", "organization_id": "o1", "user_id": "u2",
             "role": "owner", "status": "active",
             "joined_at": _make_future(), "invited_by": ""},
        ])
        members = await repo.find_by_org_id("o1")
        assert len(members) == 2

    @pytest.mark.asyncio
    async def test_find_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([
            {"id": "m1", "organization_id": "o1", "user_id": "u1",
             "role": "member", "status": "active",
             "joined_at": _make_future(), "invited_by": ""},
        ])
        members = await repo.find_by_user_id("u1")
        assert len(members) == 1

    @pytest.mark.asyncio
    async def test_count_owners(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([
            {"id": "m1", "organization_id": "o1", "user_id": "u1",
             "role": "owner", "status": "active",
             "joined_at": _make_future(), "invited_by": ""},
        ])
        count = await repo.count_owners("o1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_count_owners_none(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([])
        count = await repo.count_owners("o1")
        assert count == 0

    @pytest.mark.asyncio
    async def test_find_active_by_user_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseMembershipRepository()
        client.execute.return_value = _row_result([
            {"id": "m1", "organization_id": "o1", "user_id": "u1",
             "role": "member", "status": "active",
             "joined_at": _make_future(), "invited_by": ""},
        ])
        active = await repo.find_active_by_user_id("u1")
        assert len(active) == 1
        assert active[0].is_active

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseMembershipRepository()
        membership = Membership(organization_id="o1", user_id="u1")
        saved = await repo.save(membership)
        assert saved.id == membership.id
        assert await repo.get(membership.id) is None
        assert await repo.find_by_user_and_org("u1", "o1") is None
        assert await repo.find_by_org_id("o1") == []
        assert await repo.find_by_user_id("u1") == []
        assert await repo.count_owners("o1") == 0
        assert await repo.find_active_by_user_id("u1") == []


# ═══════════════════════════════════════════════════════════════════════════
# 8. SupabaseInvitationRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseInvitationRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvitationRepository()
        invitation = Invitation(
            organization_id="o1",
            email="alice@test.com",
            role=MembershipRole.MEMBER,
            token="tok123",
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(invitation)
        assert saved.id == invitation.id

        client.execute.return_value = _row_result([{
            "id": invitation.id,
            "organization_id": "o1",
            "email": "alice@test.com",
            "role": "member",
            "token": "tok123",
            "expires_at": _make_future(),
            "status": "pending",
            "created_by": "",
            "accepted_at": None,
            "created_at": _make_future(),
        }])
        fetched = await repo.get(invitation.id)
        assert fetched is not None
        assert fetched.email == "alice@test.com"
        assert fetched.token == "tok123"
        assert fetched.status == InvitationStatus.PENDING

    @pytest.mark.asyncio
    async def test_find_by_org_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvitationRepository()
        client.execute.return_value = _row_result([
            {"id": "i1", "organization_id": "o1", "email": "a@b.com",
             "role": "member", "token": "t1",
             "expires_at": _make_future(), "status": "pending",
             "created_by": "", "accepted_at": None, "created_at": _make_future()},
            {"id": "i2", "organization_id": "o1", "email": "b@c.com",
             "role": "admin", "token": "t2",
             "expires_at": _make_future(), "status": "pending",
             "created_by": "", "accepted_at": None, "created_at": _make_future()},
        ])
        invitations = await repo.find_by_org_id("o1")
        assert len(invitations) == 2

    @pytest.mark.asyncio
    async def test_find_pending_by_email(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvitationRepository()
        client.execute.return_value = _row_result([
            {"id": "i1", "organization_id": "o1", "email": "a@b.com",
             "role": "member", "token": "t1",
             "expires_at": _make_future(), "status": "pending",
             "created_by": "", "accepted_at": None, "created_at": _make_future()},
        ])
        pending = await repo.find_pending_by_email("a@b.com")
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_find_by_token(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvitationRepository()
        client.execute.return_value = _row_result([{
            "id": "i1", "organization_id": "o1", "email": "a@b.com",
            "role": "member", "token": "unique-token",
            "expires_at": _make_future(), "status": "pending",
            "created_by": "", "accepted_at": None, "created_at": _make_future(),
        }])
        found = await repo.find_by_token("unique-token")
        assert found is not None
        assert found.token == "unique-token"

    @pytest.mark.asyncio
    async def test_find_by_token_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvitationRepository()
        client.execute.return_value = _row_result([])
        found = await repo.find_by_token("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseInvitationRepository()
        invitation = Invitation(organization_id="o1", email="a@b.com", token="t1")
        saved = await repo.save(invitation)
        assert saved.id == invitation.id
        assert await repo.get(invitation.id) is None
        assert await repo.find_by_org_id("o1") == []
        assert await repo.find_pending_by_email("a@b.com") == []
        assert await repo.find_by_token("t1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. SupabasePlanRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabasePlanRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePlanRepository()
        plan = Plan(code="pro_monthly", name="Professional", price=7900)

        client.execute.return_value = _row_result([])
        saved = await repo.save(plan)
        assert saved.id == plan.id

        client.execute.return_value = _row_result([{
            "id": plan.id,
            "code": "pro_monthly",
            "name": "Professional",
            "description": "",
            "billing_interval": "monthly",
            "currency": "usd",
            "price": 7900,
            "metadata": "{}",
            "created_at": _make_future(),
        }])
        fetched = await repo.get(plan.id)
        assert fetched is not None
        assert fetched.code == "pro_monthly"
        assert fetched.price == 7900

    @pytest.mark.asyncio
    async def test_find_by_code(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePlanRepository()
        client.execute.return_value = _row_result([{
            "id": "p1", "code": "starter_monthly", "name": "Starter",
            "description": "", "billing_interval": "monthly",
            "currency": "usd", "price": 2900, "metadata": "{}",
            "created_at": _make_future(),
        }])
        found = await repo.find_by_code("starter_monthly")
        assert found is not None
        assert found.code == "starter_monthly"

    @pytest.mark.asyncio
    async def test_find_by_code_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePlanRepository()
        client.execute.return_value = _row_result([])
        found = await repo.find_by_code("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_list_active(self, mock_cm):
        cm, client = mock_cm
        repo = SupabasePlanRepository()
        client.execute.return_value = _row_result([
            {"id": "p1", "code": "p1", "name": "Plan 1",
             "description": "", "billing_interval": "monthly",
             "currency": "usd", "price": 1000, "metadata": "{}",
             "created_at": _make_future()},
            {"id": "p2", "code": "p2", "name": "Plan 2",
             "description": "", "billing_interval": "yearly",
             "currency": "usd", "price": 10000, "metadata": "{}",
             "created_at": _make_future()},
        ])
        plans = await repo.list_active()
        assert len(plans) == 2

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabasePlanRepository()
        plan = Plan(code="test", name="Test", price=0)
        saved = await repo.save(plan)
        assert saved.id == plan.id
        assert await repo.get(plan.id) is None
        assert await repo.find_by_code("test") is None
        assert await repo.list_active() == []


# ═══════════════════════════════════════════════════════════════════════════
# 10. SupabaseCustomerRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseCustomerRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCustomerRepository()
        customer = Customer(
            organization_id="org1",
            provider="stripe",
            provider_customer_id="cus_abc123",
            email="org@test.com",
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(customer)
        assert saved.id == customer.id

        client.execute.return_value = _row_result([{
            "id": customer.id,
            "organization_id": "org1",
            "provider": "stripe",
            "provider_customer_id": "cus_abc123",
            "email": "org@test.com",
            "metadata": "{}",
            "created_at": _make_future(),
        }])
        fetched = await repo.get(customer.id)
        assert fetched is not None
        assert fetched.organization_id == "org1"
        assert fetched.provider_customer_id == "cus_abc123"

    @pytest.mark.asyncio
    async def test_find_by_organization_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCustomerRepository()
        client.execute.return_value = _row_result([{
            "id": "c1", "organization_id": "org1",
            "provider": "stripe", "provider_customer_id": "cus_1",
            "email": "org@test.com", "metadata": "{}",
            "created_at": _make_future(),
        }])
        found = await repo.find_by_organization_id("org1")
        assert found is not None
        assert found.id == "c1"

    @pytest.mark.asyncio
    async def test_find_by_provider_customer_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCustomerRepository()
        client.execute.return_value = _row_result([{
            "id": "c1", "organization_id": "org1",
            "provider": "stripe", "provider_customer_id": "cus_abc",
            "email": "org@test.com", "metadata": "{}",
            "created_at": _make_future(),
        }])
        found = await repo.find_by_provider_customer_id("cus_abc")
        assert found is not None
        assert found.provider_customer_id == "cus_abc"

    @pytest.mark.asyncio
    async def test_find_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCustomerRepository()
        client.execute.return_value = _row_result([])
        assert await repo.find_by_organization_id("nonexistent") is None
        assert await repo.find_by_provider_customer_id("nonexistent") is None

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseCustomerRepository()
        customer = Customer(organization_id="o1", provider_customer_id="c1")
        saved = await repo.save(customer)
        assert saved.id == customer.id
        assert await repo.get(customer.id) is None
        assert await repo.find_by_organization_id("o1") is None
        assert await repo.find_by_provider_customer_id("c1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 11. SupabaseSubscriptionRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseSubscriptionRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSubscriptionRepository()
        sub = Subscription(
            organization_id="org1",
            customer_id="c1",
            provider_subscription_id="sub_abc",
            status=SubscriptionStatus.ACTIVE,
            plan_id="p1",
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(sub)
        assert saved.id == sub.id

        client.execute.return_value = _row_result([{
            "id": sub.id,
            "organization_id": "org1",
            "customer_id": "c1",
            "provider_subscription_id": "sub_abc",
            "status": "active",
            "plan_id": "p1",
            "trial_ends_at": None,
            "current_period_start": _make_future(),
            "current_period_end": _make_future(60),
            "cancel_at_period_end": False,
            "canceled_at": None,
            "created_at": _make_future(),
            "updated_at": _make_future(),
        }])
        fetched = await repo.get(sub.id)
        assert fetched is not None
        assert fetched.organization_id == "org1"
        assert fetched.status == SubscriptionStatus.ACTIVE
        assert fetched.is_active

    @pytest.mark.asyncio
    async def test_find_by_organization_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSubscriptionRepository()
        client.execute.return_value = _row_result([
            {"id": "s1", "organization_id": "org1", "customer_id": "c1",
             "provider_subscription_id": "sub1", "status": "active",
             "plan_id": "p1", "trial_ends_at": None,
             "current_period_start": None, "current_period_end": None,
             "cancel_at_period_end": False, "canceled_at": None,
             "created_at": _make_future(), "updated_at": _make_future()},
        ])
        subs = await repo.find_by_organization_id("org1")
        assert len(subs) == 1

    @pytest.mark.asyncio
    async def test_find_active_by_organization_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSubscriptionRepository()
        client.execute.return_value = _row_result([{
            "id": "s1", "organization_id": "org1", "customer_id": "c1",
            "provider_subscription_id": "sub1", "status": "active",
            "plan_id": "p1", "trial_ends_at": None,
            "current_period_start": None, "current_period_end": None,
            "cancel_at_period_end": False, "canceled_at": None,
            "created_at": _make_future(), "updated_at": _make_future(),
        }])
        found = await repo.find_active_by_organization_id("org1")
        assert found is not None
        assert found.is_active

    @pytest.mark.asyncio
    async def test_find_active_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSubscriptionRepository()
        client.execute.return_value = _row_result([])
        found = await repo.find_active_by_organization_id("org1")
        assert found is None

    @pytest.mark.asyncio
    async def test_find_by_provider_subscription_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseSubscriptionRepository()
        client.execute.return_value = _row_result([{
            "id": "s1", "organization_id": "org1", "customer_id": "c1",
            "provider_subscription_id": "sub_prov", "status": "active",
            "plan_id": "p1", "trial_ends_at": None,
            "current_period_start": None, "current_period_end": None,
            "cancel_at_period_end": False, "canceled_at": None,
            "created_at": _make_future(), "updated_at": _make_future(),
        }])
        found = await repo.find_by_provider_subscription_id("sub_prov")
        assert found is not None
        assert found.provider_subscription_id == "sub_prov"

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseSubscriptionRepository()
        sub = Subscription(organization_id="o1", customer_id="c1")
        saved = await repo.save(sub)
        assert saved.id == sub.id
        assert await repo.get(sub.id) is None
        assert await repo.find_by_organization_id("o1") == []
        assert await repo.find_active_by_organization_id("o1") is None
        assert await repo.find_by_provider_subscription_id("s1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 12. SupabaseCheckoutRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseCheckoutRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCheckoutRepository()
        session = CheckoutSession(
            organization_id="org1",
            customer_id="c1",
            provider_checkout_id="cs_abc",
            plan_id="p1",
            url="https://checkout.stripe.com/test",
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(session)
        assert saved.id == session.id

        client.execute.return_value = _row_result([{
            "id": session.id,
            "organization_id": "org1",
            "customer_id": "c1",
            "provider_checkout_id": "cs_abc",
            "plan_id": "p1",
            "status": "open",
            "url": "https://checkout.stripe.com/test",
            "mode": "subscription",
            "success_url": "",
            "cancel_url": "",
            "trial_days": 0,
            "metadata": "{}",
            "created_at": _make_future(),
            "completed_at": None,
        }])
        fetched = await repo.get(session.id)
        assert fetched is not None
        assert fetched.provider_checkout_id == "cs_abc"
        assert fetched.status == CheckoutStatus.OPEN

    @pytest.mark.asyncio
    async def test_find_by_organization_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCheckoutRepository()
        client.execute.return_value = _row_result([
            {"id": "cs1", "organization_id": "org1", "customer_id": "c1",
             "provider_checkout_id": "cs1", "plan_id": "p1",
             "status": "open", "url": "", "mode": "subscription",
             "success_url": "", "cancel_url": "", "trial_days": 0,
             "metadata": "{}", "created_at": _make_future(), "completed_at": None},
        ])
        sessions = await repo.find_by_organization_id("org1")
        assert len(sessions) == 1

    @pytest.mark.asyncio
    async def test_find_by_provider_checkout_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseCheckoutRepository()
        client.execute.return_value = _row_result([{
            "id": "cs1", "organization_id": "org1", "customer_id": "c1",
            "provider_checkout_id": "cs_prov", "plan_id": "p1",
            "status": "open", "url": "", "mode": "subscription",
            "success_url": "", "cancel_url": "", "trial_days": 0,
            "metadata": "{}", "created_at": _make_future(), "completed_at": None,
        }])
        found = await repo.find_by_provider_checkout_id("cs_prov")
        assert found is not None
        assert found.provider_checkout_id == "cs_prov"

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseCheckoutRepository()
        session = CheckoutSession(organization_id="o1", customer_id="c1")
        saved = await repo.save(session)
        assert saved.id == session.id
        assert await repo.get(session.id) is None
        assert await repo.find_by_organization_id("o1") == []
        assert await repo.find_by_provider_checkout_id("cs1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 13. SupabaseInvoiceRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseInvoiceRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvoiceRepository()
        invoice = Invoice(
            organization_id="org1",
            customer_id="c1",
            subscription_id="s1",
            provider_invoice_id="in_abc",
            amount_due=2900,
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(invoice)
        assert saved.id == invoice.id

        client.execute.return_value = _row_result([{
            "id": invoice.id,
            "organization_id": "org1",
            "customer_id": "c1",
            "subscription_id": "s1",
            "provider_invoice_id": "in_abc",
            "status": "draft",
            "amount_due": 2900,
            "amount_paid": 0,
            "currency": "usd",
            "period_start": _make_future(),
            "period_end": _make_future(60),
            "paid_at": None,
            "hosted_url": "",
            "metadata": "{}",
            "created_at": _make_future(),
        }])
        fetched = await repo.get(invoice.id)
        assert fetched is not None
        assert fetched.amount_due == 2900
        assert fetched.status == InvoiceStatus.DRAFT

    @pytest.mark.asyncio
    async def test_find_by_organization_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvoiceRepository()
        client.execute.return_value = _row_result([
            {"id": "i1", "organization_id": "org1", "customer_id": "c1",
             "subscription_id": "s1", "provider_invoice_id": "inv1",
             "status": "paid", "amount_due": 1000, "amount_paid": 1000,
             "currency": "usd", "period_start": None, "period_end": None,
             "paid_at": _make_future(), "hosted_url": "",
             "metadata": "{}", "created_at": _make_future()},
        ])
        invoices = await repo.find_by_organization_id("org1")
        assert len(invoices) == 1
        assert invoices[0].is_paid

    @pytest.mark.asyncio
    async def test_find_by_provider_invoice_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseInvoiceRepository()
        client.execute.return_value = _row_result([{
            "id": "i1", "organization_id": "org1", "customer_id": "c1",
            "subscription_id": "s1", "provider_invoice_id": "inv_prov",
            "status": "draft", "amount_due": 0, "amount_paid": 0,
            "currency": "usd", "period_start": None, "period_end": None,
            "paid_at": None, "hosted_url": "",
            "metadata": "{}", "created_at": _make_future(),
        }])
        found = await repo.find_by_provider_invoice_id("inv_prov")
        assert found is not None
        assert found.provider_invoice_id == "inv_prov"

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseInvoiceRepository()
        invoice = Invoice(organization_id="o1", customer_id="c1", subscription_id="s1")
        saved = await repo.save(invoice)
        assert saved.id == invoice.id
        assert await repo.get(invoice.id) is None
        assert await repo.find_by_organization_id("o1") == []
        assert await repo.find_by_provider_invoice_id("inv1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 14. SupabaseBillingEventRepository
# ═══════════════════════════════════════════════════════════════════════════

class TestSupabaseBillingEventRepository:

    @pytest.mark.asyncio
    async def test_save_and_get(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseBillingEventRepository()
        event = BillingEvent(
            event_type="invoice.paid",
            provider_event_id="evt_abc",
            provider="stripe",
            organization_id="org1",
        )
        client.execute.return_value = _row_result([])
        saved = await repo.save(event)
        assert saved.id == event.id

        client.execute.return_value = _row_result([{
            "id": event.id,
            "event_type": "invoice.paid",
            "provider_event_id": "evt_abc",
            "provider": "stripe",
            "organization_id": "org1",
            "data": "{}",
            "idempotency_key": "",
            "processed": False,
            "created_at": _make_future(),
            "processed_at": None,
        }])
        fetched = await repo.get(event.id)
        assert fetched is not None
        assert fetched.event_type == "invoice.paid"
        assert fetched.processed is False

    @pytest.mark.asyncio
    async def test_find_by_provider_event_id(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseBillingEventRepository()
        client.execute.return_value = _row_result([{
            "id": "e1", "event_type": "checkout.session.completed",
            "provider_event_id": "evt_checkout", "provider": "stripe",
            "organization_id": "org1", "data": "{}",
            "idempotency_key": "", "processed": True,
            "created_at": _make_future(), "processed_at": _make_future(),
        }])
        found = await repo.find_by_provider_event_id("evt_checkout")
        assert found is not None
        assert found.processed is True

    @pytest.mark.asyncio
    async def test_find_by_idempotency_key(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseBillingEventRepository()
        client.execute.return_value = _row_result([{
            "id": "e1", "event_type": "checkout.session.completed",
            "provider_event_id": "evt_1", "provider": "stripe",
            "organization_id": "org1", "data": "{}",
            "idempotency_key": "idem_key_123", "processed": False,
            "created_at": _make_future(), "processed_at": None,
        }])
        found = await repo.find_by_idempotency_key("idem_key_123")
        assert found is not None
        assert found.idempotency_key == "idem_key_123"

    @pytest.mark.asyncio
    async def test_find_not_found(self, mock_cm):
        cm, client = mock_cm
        repo = SupabaseBillingEventRepository()
        client.execute.return_value = _row_result([])
        assert await repo.find_by_provider_event_id("nonexistent") is None
        assert await repo.find_by_idempotency_key("nonexistent") is None

    @pytest.mark.asyncio
    async def test_no_client_fallback(self):
        cm = SupabaseConnectionManager(url="", key="")
        set_connection_manager(cm)
        repo = SupabaseBillingEventRepository()
        event = BillingEvent(
            event_type="test", provider_event_id="evt1", provider="stripe",
        )
        saved = await repo.save(event)
        assert saved.id == event.id
        assert await repo.get(event.id) is None
        assert await repo.find_by_provider_event_id("evt1") is None
        assert await repo.find_by_idempotency_key("key1") is None


# ═══════════════════════════════════════════════════════════════════════════
# 15. Config switching
# ═══════════════════════════════════════════════════════════════════════════

class TestRepositoryConfig:

    def test_default_provider(self):
        reset_repository_provider()
        assert get_repository_provider() == RepositoryProvider.IN_MEMORY

    def test_set_and_reset(self):
        reset_repository_provider()
        set_repository_provider(RepositoryProvider.SUPABASE)
        assert get_repository_provider() == RepositoryProvider.SUPABASE
        reset_repository_provider()
        assert get_repository_provider() == RepositoryProvider.IN_MEMORY


from services.persistence.config import (
    get_repository_provider,
    set_repository_provider,
    reset_repository_provider,
)

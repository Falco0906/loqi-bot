"""Regression: Supabase `_deserialize` must convert str-based Enums to Enums.

The base repository deserializer previously returned raw strings for
str-Enums (e.g. RegistrationSessionStatus) because the plain-str branch
matched first. Callers that read `.value` (e.g.
`/api/v1/auth/signup/email/status`) then raised AttributeError → HTTP 500 in
production. This guards the ordering across every persistence model that
carries an enum.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.persistence.base_repository import _deserialize
from services.identity.models import (
    RegistrationSession,
    RegistrationSessionStatus,
    VerificationToken,
    VerificationTokenPurpose,
)
from services.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
)
from services.billing.models import Subscription, SubscriptionStatus

_NOW = datetime.now(timezone.utc).isoformat()


def _row(**kwargs):
    base = {
        "id": "00000000-0000-4000-8000-000000000000",
        "created_at": _NOW,
        "updated_at": _NOW,
        "expires_at": _NOW,
    }
    base.update(kwargs)
    return base


class TestStrEnumDeserialization:

    def test_registration_session_status_is_enum(self):
        rs = _deserialize(RegistrationSession, _row(status="pending"))
        assert isinstance(rs.status, RegistrationSessionStatus)
        assert rs.status == RegistrationSessionStatus.PENDING
        assert rs.status.value == "pending"

    def test_verification_token_purpose_is_enum(self):
        vt = _deserialize(VerificationToken, _row(
            purpose="verify_email", target="t", token_hash="h",
        ))
        assert isinstance(vt.purpose, VerificationTokenPurpose)
        assert vt.purpose == VerificationTokenPurpose.VERIFY_EMAIL

    def test_membership_role_and_status_are_enums(self):
        m = _deserialize(Membership, _row(
            organization_id="o", user_id="u", role="admin", status="active",
            joined_at=_NOW, invited_by="",
        ))
        assert isinstance(m.role, MembershipRole) and m.role == MembershipRole.ADMIN
        assert isinstance(m.status, MembershipStatus) and m.status == MembershipStatus.ACTIVE

    def test_invitation_status_is_enum(self):
        inv = _deserialize(Invitation, _row(
            organization_id="o", email="e@x.com", role="member",
            token="t", status="pending", created_by="",
        ))
        assert isinstance(inv.status, InvitationStatus) and inv.status == InvitationStatus.PENDING

    def test_subscription_status_is_enum(self):
        s = _deserialize(Subscription, _row(
            organization_id="o", customer_id="c", provider_subscription_id="p",
            status="active", plan_id="",
        ))
        assert isinstance(s.status, SubscriptionStatus) and s.status == SubscriptionStatus.ACTIVE

    def test_plain_str_fields_remain_str(self):
        rs = _deserialize(RegistrationSession, _row(status="pending"))
        assert isinstance(rs.email, str) or rs.email == ""
        assert isinstance(rs.id, str)
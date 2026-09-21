"""Owner-scoped provider resolution and test-recipient boundary tests."""
from __future__ import annotations

from services.communication import provider_registry as communication_registry
from services.outbound import outbound_registry
from services.outbound.outbound_models import DraftMessage, Recipient
from services.outbound.service import resolve_provider_for_draft


class _CommunicationProvider:
    def __init__(self, owner_id, email, connected=True):
        self._user_id = owner_id
        self._mailbox_email = email
        self._connected = connected


class _OutboundProvider:
    provider_type = "gmail"


def _register(provider_id, owner_id, email):
    communication_registry.register_instance(provider_id, _CommunicationProvider(owner_id, email))
    outbound_registry.register_instance(provider_id, _OutboundProvider())


def _draft(provider_id):
    return DraftMessage(
        id="draft-1", provider_id=provider_id, subject="Subject", body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="me@example.com", name="Me"),
    )


def setup_function():
    communication_registry._instances.clear()
    outbound_registry._instances.clear()


def teardown_function():
    communication_registry._instances.clear()
    outbound_registry._instances.clear()


def test_stored_provider_is_used_when_owned_and_connected():
    _register("provider-a", "owner-a", "a@example.com")
    draft = _draft("provider-a")

    assert resolve_provider_for_draft(draft, "owner-a") == "provider-a"


def test_stale_or_foreign_provider_resolves_to_owners_provider():
    _register("provider-b", "owner-b", "b@example.com")
    _register("provider-a", "owner-a", "a@example.com")
    draft = _draft("provider-b")

    assert resolve_provider_for_draft(draft, "owner-a") == "provider-a"
    assert draft.provider_id == "provider-a"


def test_no_owners_provider_fails_closed():
    _register("provider-b", "owner-b", "b@example.com")

    assert resolve_provider_for_draft(_draft("provider-b"), "owner-a") == ""

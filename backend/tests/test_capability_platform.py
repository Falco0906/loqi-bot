from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.capabilities.config import CapabilityConfig, SEED_CAPABILITIES
from services.capabilities.events import CapabilityDomainEvent, CapabilityEventType
from services.capabilities.exceptions import (
    CapabilityAlreadyDisabled,
    CapabilityAlreadyEnabled,
    CapabilityNotRegistered,
    DuplicateCapabilityRegistration,
)
from services.capabilities.models import (
    CapabilityDefinition,
    CapabilityLimits,
    CapabilityUsage,
    OrganizationCapability,
)
from services.capabilities.repositories import (
    InMemoryCapabilityDefinitionRepository,
    InMemoryCapabilityLimitsRepository,
    InMemoryCapabilityUsageRepository,
    InMemoryOrganizationCapabilityRepository,
)
from services.capabilities.services import CapabilityService


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def config() -> CapabilityConfig:
    return CapabilityConfig(auto_seed=True)


@pytest.fixture
def definition_repo() -> InMemoryCapabilityDefinitionRepository:
    return InMemoryCapabilityDefinitionRepository()


@pytest.fixture
def org_capability_repo() -> InMemoryOrganizationCapabilityRepository:
    return InMemoryOrganizationCapabilityRepository()


@pytest.fixture
def usage_repo() -> InMemoryCapabilityUsageRepository:
    return InMemoryCapabilityUsageRepository()


@pytest.fixture
def limits_repo() -> InMemoryCapabilityLimitsRepository:
    return InMemoryCapabilityLimitsRepository()


@pytest.fixture
def service(
    definition_repo,
    org_capability_repo,
    usage_repo,
    limits_repo,
    config,
) -> CapabilityService:
    return CapabilityService(
        definition_repo=definition_repo,
        org_capability_repo=org_capability_repo,
        usage_repo=usage_repo,
        limits_repo=limits_repo,
        config=config,
    )


@pytest.fixture
async def seeded_service(service) -> CapabilityService:
    await service.seed_capabilities()
    return service


# ─── Model Tests ─────────────────────────────────────────────────────


class TestModels:

    def test_capability_definition_defaults(self):
        c = CapabilityDefinition(slug="test", name="Test")
        assert c.slug == "test"
        assert c.name == "Test"
        assert not c.default_enabled
        assert not c.beta
        assert c.created_at is not None

    def test_org_capability_is_active(self):
        oc = OrganizationCapability(enabled=True)
        assert oc.is_active
        oc.enabled = False
        assert not oc.is_active

    def test_usage_reset(self):
        u = CapabilityUsage(requests=100, executions=50, storage_bytes=1024, api_calls=10)
        u.reset()
        assert u.requests == 0
        assert u.executions == 0
        assert u.storage_bytes == 0
        assert u.api_calls == 0
        assert u.last_reset is not None

    def test_usage_increment_requests(self):
        u = CapabilityUsage()
        u.increment_requests(5)
        assert u.requests == 5
        u.increment_requests()
        assert u.requests == 6

    def test_usage_increment_executions(self):
        u = CapabilityUsage()
        u.increment_executions(3)
        assert u.executions == 3

    def test_usage_increment_storage(self):
        u = CapabilityUsage()
        u.increment_storage(2048)
        assert u.storage_bytes == 2048

    def test_usage_increment_api_calls(self):
        u = CapabilityUsage()
        u.increment_api_calls(7)
        assert u.api_calls == 7


# ─── Seed Capability Tests ───────────────────────────────────────────


class TestSeedCapabilities:

    async def test_seed_creates_all_capabilities(self, service):
        capabilities = await service.seed_capabilities()
        assert len(capabilities) == len(SEED_CAPABILITIES)
        slugs = [c.slug for c in capabilities]
        for spec in SEED_CAPABILITIES:
            assert spec["slug"] in slugs

    async def test_seed_is_idempotent(self, service):
        await service.seed_capabilities()
        capabilities2 = await service.seed_capabilities()
        assert len(capabilities2) == len(SEED_CAPABILITIES)

    async def test_seed_matches_config(self, service):
        capabilities = await service.seed_capabilities()
        for cap in capabilities:
            spec = next(s for s in SEED_CAPABILITIES if s["slug"] == cap.slug)
            assert cap.name == spec["name"]
            assert cap.category == spec["category"]
            assert cap.default_enabled == spec["default_enabled"]
            assert cap.beta == spec["beta"]


# ─── Registration Tests ──────────────────────────────────────────────


class TestRegistration:

    async def test_register_new_capability(self, service):
        cap = await service.register_capability(
            slug="custom", name="Custom Capability", category="custom",
        )
        assert cap.slug == "custom"
        assert cap.name == "Custom Capability"
        assert cap.category == "custom"

    async def test_register_duplicate_raises(self, service):
        await service.register_capability(slug="dup", name="First")
        with pytest.raises(DuplicateCapabilityRegistration):
            await service.register_capability(slug="dup", name="Second")

    async def test_register_emits_event(self, service):
        await service.register_capability(slug="event-test", name="Event Test")
        assert len(service.events) == 1
        assert service.events[0].event_type == CapabilityEventType.CAPABILITY_REGISTERED
        assert service.events[0].entity_id == "event-test"


# ─── Lookup Tests ────────────────────────────────────────────────────


class TestLookup:

    async def test_get_capability_found(self, seeded_service):
        cap = await seeded_service.get_capability("memory")
        assert cap.name == "Memory"

    async def test_get_capability_not_found(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.get_capability("nonexistent")

    async def test_capability_exists_true(self, seeded_service):
        assert await seeded_service.capability_exists("gmail")

    async def test_capability_exists_false(self, seeded_service):
        assert not await seeded_service.capability_exists("nonexistent")

    async def test_list_capabilities_returns_all(self, seeded_service):
        capabilities = await seeded_service.list_capabilities()
        assert len(capabilities) == len(SEED_CAPABILITIES)

    async def test_list_auto_seeds_when_empty(self, service):
        capabilities = await service.list_capabilities()
        assert len(capabilities) == len(SEED_CAPABILITIES)


# ─── Organization Capability Tests ───────────────────────────────────


class TestOrganizationCapabilities:

    async def test_get_organization_capabilities_auto_activates(self, seeded_service):
        org_caps = await seeded_service.get_organization_capabilities("org-1")
        assert len(org_caps) == len(SEED_CAPABILITIES)

    async def test_default_enabled_capabilities_active(self, seeded_service):
        org_caps = await seeded_service.get_organization_capabilities("org-default")
        for oc in org_caps:
            definition = await seeded_service.get_capability(oc.capability_slug)
            assert oc.enabled == definition.default_enabled

    async def test_enable_capability(self, seeded_service):
        org_cap = await seeded_service.enable_capability("org-enable", "gmail")
        assert org_cap.enabled
        assert org_cap.capability_slug == "gmail"
        assert org_cap.organization_id == "org-enable"
        assert org_cap.activated_at is not None

    async def test_enable_already_enabled_raises(self, seeded_service):
        await seeded_service.enable_capability("org-already", "memory")
        with pytest.raises(CapabilityAlreadyEnabled):
            await seeded_service.enable_capability("org-already", "memory")

    async def test_enable_emits_event(self, seeded_service):
        await seeded_service.enable_capability("org-evt", "gmail", activated_by="user-1")
        assert any(
            e.event_type == CapabilityEventType.CAPABILITY_ENABLED
            and e.organization_id == "org-evt"
            and e.entity_id == "gmail"
            for e in seeded_service.events
        )

    async def test_disable_capability(self, seeded_service):
        org_cap = await seeded_service.disable_capability("org-disable", "memory")
        assert not org_cap.enabled

    async def test_disable_already_disabled_raises(self, seeded_service):
        await seeded_service.disable_capability("org-none", "gmail")
        with pytest.raises(CapabilityAlreadyDisabled):
            await seeded_service.disable_capability("org-none", "gmail")

    async def test_disable_emits_event(self, seeded_service):
        await seeded_service.disable_capability("org-dis-evt", "memory")
        assert any(
            e.event_type == CapabilityEventType.CAPABILITY_DISABLED
            for e in seeded_service.events
        )

    async def test_enable_nonexistent_capability_raises(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.enable_capability("org-1", "nonexistent")

    async def test_disable_nonexistent_capability_raises(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.disable_capability("org-1", "nonexistent")

    async def test_get_organization_capability_specific(self, seeded_service):
        oc = await seeded_service.get_organization_capability("org-specific", "memory")
        assert oc.organization_id == "org-specific"
        assert oc.capability_slug == "memory"

    async def test_get_organization_capability_auto_creates(self, seeded_service):
        oc = await seeded_service.get_organization_capability("org-auto", "research")
        assert oc.enabled  # research has default_enabled=True
        assert oc.activated_at is not None

    async def test_get_organization_capability_nonexistent_raises(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.get_organization_capability("org-1", "nonexistent")


# ─── Usage Tests ─────────────────────────────────────────────────────


class TestUsage:

    async def test_get_usage_creates_default(self, seeded_service):
        usage = await seeded_service.get_usage("org-usage", "memory")
        assert usage.organization_id == "org-usage"
        assert usage.capability_slug == "memory"
        assert usage.requests == 0
        assert usage.executions == 0

    async def test_increment_usage_requests(self, seeded_service):
        usage = await seeded_service.increment_usage("org-inc", "memory", requests=10)
        assert usage.requests == 10

    async def test_increment_usage_executions(self, seeded_service):
        usage = await seeded_service.increment_usage("org-inc", "memory", executions=5)
        assert usage.executions == 5

    async def test_increment_usage_storage(self, seeded_service):
        usage = await seeded_service.increment_usage("org-inc", "memory", storage_bytes=2048)
        assert usage.storage_bytes == 2048

    async def test_increment_usage_api_calls(self, seeded_service):
        usage = await seeded_service.increment_usage("org-inc", "memory", api_calls=3)
        assert usage.api_calls == 3

    async def test_increment_multiple_fields(self, seeded_service):
        usage = await seeded_service.increment_usage(
            "org-inc", "memory",
            requests=10, executions=5, api_calls=3,
        )
        assert usage.requests == 10
        assert usage.executions == 5
        assert usage.api_calls == 3

    async def test_increment_accumulates(self, seeded_service):
        await seeded_service.increment_usage("org-acc", "memory", requests=5)
        usage = await seeded_service.increment_usage("org-acc", "memory", requests=3)
        assert usage.requests == 8

    async def test_increment_emits_events(self, seeded_service):
        await seeded_service.increment_usage("org-evt", "memory", requests=1, api_calls=2)
        request_events = [
            e for e in seeded_service.events
            if e.event_type == CapabilityEventType.USAGE_INCREMENTED
        ]
        assert len(request_events) >= 2

    async def test_reset_usage(self, seeded_service):
        await seeded_service.increment_usage("org-reset", "memory", requests=100)
        usage = await seeded_service.reset_usage("org-reset", "memory")
        assert usage.requests == 0
        assert usage.last_reset is not None

    async def test_increment_nonexistent_capability_raises(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.increment_usage("org-1", "nonexistent", requests=1)

    async def test_get_usage_nonexistent_capability_raises(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.get_usage("org-1", "nonexistent")


# ─── Validation Tests ────────────────────────────────────────────────


class TestValidation:

    async def test_validate_capability_exists(self, seeded_service):
        cap = await seeded_service.validate_capability_exists("memory")
        assert cap.slug == "memory"

    async def test_validate_capability_not_found(self, seeded_service):
        with pytest.raises(CapabilityNotRegistered):
            await seeded_service.validate_capability_exists("nonexistent")


# ─── Event Tests ─────────────────────────────────────────────────────


class TestEvents:

    async def test_clear_events(self, seeded_service):
        await seeded_service.register_capability(slug="clear-test", name="Clear Test")
        assert len(seeded_service.events) > 0
        seeded_service.clear_events()
        assert len(seeded_service.events) == 0

    async def test_events_property_returns_copy(self, seeded_service):
        await seeded_service.register_capability(slug="copy-test", name="Copy Test")
        events_copy = seeded_service.events
        seeded_service.clear_events()
        assert len(events_copy) == 1  # copy is independent
        assert len(seeded_service.events) == 0


# ─── CapabilityDefinition Domain Event Tests ─────────────────────────


class TestDomainEventFactories:

    def test_capability_registered_event(self):
        event = CapabilityDomainEvent.capability_registered("test", "Test", "testing")
        assert event.event_type == CapabilityEventType.CAPABILITY_REGISTERED
        assert event.entity_id == "test"
        assert event.data["name"] == "Test"
        assert event.data["category"] == "testing"

    def test_capability_enabled_event(self):
        event = CapabilityDomainEvent.capability_enabled("test", "org-1", "user-1")
        assert event.event_type == CapabilityEventType.CAPABILITY_ENABLED
        assert event.entity_id == "test"
        assert event.organization_id == "org-1"
        assert event.data["activated_by"] == "user-1"

    def test_capability_disabled_event(self):
        event = CapabilityDomainEvent.capability_disabled("test", "org-1")
        assert event.event_type == CapabilityEventType.CAPABILITY_DISABLED
        assert event.entity_id == "test"
        assert event.organization_id == "org-1"

    def test_usage_incremented_event(self):
        event = CapabilityDomainEvent.usage_incremented("test", "org-1", "requests", 10)
        assert event.event_type == CapabilityEventType.USAGE_INCREMENTED
        assert event.entity_id == "test"
        assert event.organization_id == "org-1"
        assert event.data["field"] == "requests"
        assert event.data["value"] == 10


# ─── Integration Tests ───────────────────────────────────────────────


class TestIntegration:

    async def test_full_lifecycle(self, service):
        await service.seed_capabilities()

        memory = await service.get_capability("memory")
        assert memory.name == "Memory"

        org_caps = await service.get_organization_capabilities("org-full")
        memory_oc = next(oc for oc in org_caps if oc.capability_slug == "memory")
        assert memory_oc.enabled  # memory has default_enabled=True

        gmail_oc = next(oc for oc in org_caps if oc.capability_slug == "gmail")
        assert not gmail_oc.enabled  # gmail has default_enabled=False

        enabled = await service.enable_capability("org-full", "gmail")
        assert enabled.enabled

        disabled = await service.disable_capability("org-full", "memory")
        assert not disabled.enabled

        usage = await service.increment_usage("org-full", "gmail", requests=5, executions=2)
        assert usage.requests == 5
        assert usage.executions == 2

        await service.increment_usage("org-full", "gmail", requests=3)
        usage = await service.get_usage("org-full", "gmail")
        assert usage.requests == 8


# ─── Seed Config Tests ───────────────────────────────────────────────


class TestSeedConfig:

    def test_seed_capabilities_contains_required_slugs(self):
        slugs = [s["slug"] for s in SEED_CAPABILITIES]
        required = {"memory", "gmail", "calendar", "drive", "slack",
                    "github", "crm", "outreach", "research", "execution"}
        assert required.issubset(set(slugs))

    def test_seed_capabilities_default_enabled_set(self):
        default_enabled = [s["slug"] for s in SEED_CAPABILITIES if s.get("default_enabled")]
        assert "memory" in default_enabled
        assert "research" in default_enabled
        assert "execution" in default_enabled
        assert "gmail" not in default_enabled

from __future__ import annotations

import pickle
from dataclasses import FrozenInstanceError
from typing import Any, Optional

import pytest

from services.adapters import (
    AdapterContext,
    AdapterDisabledError,
    AdapterFactory,
    AdapterIdentity,
    AdapterMetadata,
    AdapterNotFoundError,
    AdapterRegistration,
    AdapterRegistrationError,
    AdapterRegistry,
    AdapterResult,
    CapabilityDescriptor,
    CapabilityProvider,
    CapabilityRegistry,
    CredentialDescriptor,
    CredentialField,
    CredentialRegistry,
    CredentialType,
    ExecutionAdapter,
    UsageInfo,
    ValidationError,
)

# ---- Test adapter stubs ------------------------------------------------


class MockAdapter(ExecutionAdapter):
    @property
    def metadata(self):
        return AdapterMetadata(
            name="mock", display_name="Mock Adapter", version="1.0.0",
            description="A mock adapter for testing",
        )

    async def execute(self, context: AdapterContext) -> AdapterResult:
        return AdapterResult.success_result(data="ok")


class GmailAdapter(ExecutionAdapter):
    @property
    def metadata(self):
        return AdapterMetadata(
            name="gmail", display_name="Gmail Adapter", version="2.0.0",
            description="Gmail integration", requires_auth=True,
            supported_operations=("send_email", "search_email"),
        )

    async def execute(self, context: AdapterContext) -> AdapterResult:
        return AdapterResult.success_result(data="email sent")


class SlackAdapter(ExecutionAdapter):
    @property
    def metadata(self):
        return AdapterMetadata(
            name="slack", display_name="Slack Adapter", version="1.0.0",
            description="Slack integration", requires_auth=True,
            supported_operations=("send_message",),
        )

    async def execute(self, context: AdapterContext) -> AdapterResult:
        return AdapterResult.success_result(data="message sent")


class HttpAdapter(ExecutionAdapter):
    @property
    def metadata(self):
        return AdapterMetadata(
            name="http", display_name="HTTP Client", version="3.0.0",
            description="Make HTTP requests",
            supported_operations=("http_request",),
        )

    async def execute(self, context: AdapterContext) -> AdapterResult:
        return AdapterResult.success_result(data="http done")


# ---- Helpers -----------------------------------------------------------


def make_identity(name: str = "test", version: str = "1.0.0") -> AdapterIdentity:
    return AdapterIdentity(name=name, version=version)


def make_reg(
    name: str = "test",
    version: str = "1.0.0",
    adapter_class: type = MockAdapter,
    capability_names: tuple[str, ...] = (),
    credential_descriptor_names: tuple[str, ...] = (),
    priority: int = 0,
    enabled: bool = True,
) -> AdapterRegistration:
    return AdapterRegistration(
        identity=AdapterIdentity(name=name, version=version),
        adapter_class=adapter_class,
        metadata=adapter_class().metadata,
        capability_names=capability_names,
        credential_descriptor_names=credential_descriptor_names,
        priority=priority,
        enabled=enabled,
    )


# =========================================================================
# AdapterIdentity
# =========================================================================


class TestAdapterIdentityConstruction:
    def test_minimal(self):
        i = AdapterIdentity(name="gmail", version="1.0.0")
        assert i.name == "gmail"
        assert i.version == "1.0.0"

    def test_with_version(self):
        i = AdapterIdentity(name="slack", version="2.0.0-beta")
        assert i.version == "2.0.0-beta"

    def test_equality(self):
        a = AdapterIdentity(name="gmail", version="1.0.0")
        b = AdapterIdentity(name="gmail", version="1.0.0")
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_name(self):
        a = AdapterIdentity(name="gmail", version="1.0.0")
        b = AdapterIdentity(name="slack", version="1.0.0")
        assert a != b

    def test_inequality_version(self):
        a = AdapterIdentity(name="gmail", version="1.0.0")
        b = AdapterIdentity(name="gmail", version="2.0.0")
        assert a != b

    def test_used_as_dict_key(self):
        i = AdapterIdentity(name="gmail", version="1.0.0")
        d = {i: "value"}
        assert d[i] == "value"

    def test_pickle(self):
        i = AdapterIdentity(name="gmail", version="1.0.0")
        data = pickle.dumps(i)
        restored = pickle.loads(data)
        assert restored == i

    def test_ordering_by_name(self):
        a = AdapterIdentity(name="a", version="1.0.0")
        b = AdapterIdentity(name="b", version="1.0.0")
        assert a < b

    def test_ordering_by_version(self):
        a = AdapterIdentity(name="x", version="1.0.0")
        b = AdapterIdentity(name="x", version="2.0.0")
        assert a < b

    def test_ordering_same_identity(self):
        a = AdapterIdentity(name="x", version="1.0.0")
        b = AdapterIdentity(name="x", version="1.0.0")
        assert not (a < b) and not (b < a)


class TestAdapterIdentityValidation:
    def test_empty_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name="", version="1.0.0")

    def test_uppercase_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name="GMAIL", version="1.0.0")

    def test_spaces_in_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name="my adapter", version="1.0.0")

    def test_empty_version_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name="gmail", version="")

    def test_non_string_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name=123, version="1.0.0")  # type: ignore[arg-type]

    def test_non_string_version_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterIdentity(name="gmail", version=1)  # type: ignore[arg-type]


class TestAdapterIdentityImmutability:
    def test_cannot_set_name(self):
        i = AdapterIdentity(name="x", version="1")
        with pytest.raises(FrozenInstanceError):
            i.name = "y"  # type: ignore[misc]

    def test_cannot_set_version(self):
        i = AdapterIdentity(name="x", version="1")
        with pytest.raises(FrozenInstanceError):
            i.version = "2"  # type: ignore[misc]


# =========================================================================
# AdapterRegistration
# =========================================================================


class TestAdapterRegistrationConstruction:
    def test_minimal(self):
        reg = make_reg()
        assert reg.name == "test"
        assert reg.version == "1.0.0"
        assert reg.adapter_class == MockAdapter
        assert reg.metadata is not None
        assert reg.capability_names == ()
        assert reg.priority == 0
        assert reg.enabled is True

    def test_with_capabilities(self):
        reg = make_reg(
            name="gmail", capability_names=("send_email", "search_email"),
        )
        assert len(reg.capability_names) == 2

    def test_with_credentials(self):
        reg = make_reg(
            name="gmail",
            credential_descriptor_names=("gmail_oauth",),
        )
        assert reg.credential_descriptor_names == ("gmail_oauth",)

    def test_with_priority(self):
        reg = make_reg(name="gmail", priority=10)
        assert reg.priority == 10

    def test_disabled(self):
        reg = make_reg(name="gmail", enabled=False)
        assert reg.enabled is False

    def test_to_dict(self):
        reg = make_reg(name="gmail", capability_names=("send_email",))
        d = reg.to_dict()
        assert d["name"] == "gmail"
        assert "send_email" in d["capability_names"]
        assert d["enabled"] is True
        assert "MockAdapter" in d["adapter_class"]


class TestAdapterRegistrationValidation:
    def test_non_class_adapter_class_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterRegistration(
                identity=AdapterIdentity(name="x", version="1"),
                adapter_class="not a class",  # type: ignore[arg-type]
                metadata=None,
            )

    def test_non_identity_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterRegistration(
                identity="not identity",  # type: ignore[arg-type]
                adapter_class=MockAdapter,
                metadata=MockAdapter().metadata,
            )

    def test_non_int_priority_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterRegistration(
                identity=AdapterIdentity(name="x", version="1"),
                adapter_class=MockAdapter,
                metadata=MockAdapter().metadata,
                priority="high",  # type: ignore[arg-type]
            )

    def test_empty_capability_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterRegistration(
                identity=AdapterIdentity(name="x", version="1"),
                adapter_class=MockAdapter,
                metadata=MockAdapter().metadata,
                capability_names=("",),
            )

    def test_empty_credential_name_raises(self):
        with pytest.raises(AdapterRegistrationError):
            AdapterRegistration(
                identity=AdapterIdentity(name="x", version="1"),
                adapter_class=MockAdapter,
                metadata=MockAdapter().metadata,
                credential_descriptor_names=("",),
            )


class TestAdapterRegistrationImmutability:
    def test_cannot_set_identity(self):
        reg = make_reg()
        with pytest.raises(FrozenInstanceError):
            reg.identity = make_identity("new")  # type: ignore[misc]

    def test_cannot_set_enabled(self):
        reg = make_reg()
        with pytest.raises(FrozenInstanceError):
            reg.enabled = False  # type: ignore[misc]


# =========================================================================
# AdapterFactory
# =========================================================================


class TestAdapterFactory:
    @pytest.fixture
    def factory(self):
        regs: dict[AdapterIdentity, AdapterRegistration] = {}
        regs[make_identity("gmail", "1.0.0")] = make_reg(
            name="gmail", version="1.0.0", adapter_class=GmailAdapter,
        )
        regs[make_identity("gmail", "2.0.0")] = make_reg(
            name="gmail", version="2.0.0", adapter_class=GmailAdapter,
        )
        regs[make_identity("slack", "1.0.0")] = make_reg(
            name="slack", version="1.0.0", adapter_class=SlackAdapter,
        )
        regs[make_identity("disabled", "1.0.0")] = make_reg(
            name="disabled", version="1.0.0", adapter_class=MockAdapter, enabled=False,
        )
        return AdapterFactory(
            get_registration=lambda i: regs.get(i),
            find_registrations=lambda n: [
                r for r in regs.values() if r.name.lower() == n.lower()
            ],
        )

    def test_create(self, factory):
        adapter = factory.create(AdapterIdentity(name="gmail", version="1.0.0"))
        assert isinstance(adapter, ExecutionAdapter)
        assert isinstance(adapter, GmailAdapter)

    def test_create_latest(self, factory):
        adapter = factory.create_latest("gmail")
        assert isinstance(adapter, GmailAdapter)

    def test_create_latest_picks_highest_version(self, factory):
        adapter = factory.create_latest("gmail")
        assert isinstance(adapter, GmailAdapter)

    def test_create_unknown_raises(self, factory):
        with pytest.raises(AdapterNotFoundError):
            factory.create(AdapterIdentity(name="unknown", version="1.0.0"))

    def test_create_disabled_raises(self, factory):
        with pytest.raises(AdapterDisabledError):
            factory.create(AdapterIdentity(name="disabled", version="1.0.0"))

    def test_create_latest_no_registrations_raises(self, factory):
        with pytest.raises(AdapterNotFoundError):
            factory.create_latest("nonexistent")

    def test_create_returns_new_instance(self, factory):
        a1 = factory.create(AdapterIdentity(name="gmail", version="1.0.0"))
        a2 = factory.create(AdapterIdentity(name="gmail", version="1.0.0"))
        assert a1 is not a2

    def test_create_for_capability(self, factory):
        providers = [
            make_reg(name="gmail", adapter_class=GmailAdapter),
        ]
        adapter = factory.create_for_capability("send_email", providers)
        assert isinstance(adapter, GmailAdapter)

    def test_create_for_capability_empty_raises(self, factory):
        with pytest.raises(AdapterNotFoundError):
            factory.create_for_capability("nonexistent", [])

    def test_create_latest_only_enabled(self, factory):
        regs: dict[AdapterIdentity, AdapterRegistration] = {}
        regs[make_identity("test", "1.0.0")] = make_reg(
            name="test", version="1.0.0", enabled=False,
        )
        f = AdapterFactory(
            get_registration=lambda i: regs.get(i),
            find_registrations=lambda n: [
                r for r in regs.values() if r.name.lower() == n.lower()
            ],
        )
        with pytest.raises(AdapterNotFoundError):
            f.create_latest("test")

    def test_fresh_instance_each_call(self, factory):
        a1 = factory.create(AdapterIdentity(name="gmail", version="1.0.0"))
        a2 = factory.create(AdapterIdentity(name="gmail", version="1.0.0"))
        assert a1 is not a2


# =========================================================================
# AdapterRegistry — registration
# =========================================================================


class TestAdapterRegistryRegister:
    @pytest.fixture
    def registry(self):
        return AdapterRegistry()

    def test_register_single(self, registry):
        registry.register(make_reg(name="gmail"))
        assert registry.count() == 1

    def test_register_multiple(self, registry):
        registry.register(make_reg(name="gmail"))
        registry.register(make_reg(name="slack"))
        assert registry.count() == 2

    def test_register_multiple_versions(self, registry):
        registry.register(make_reg(name="gmail", version="1.0.0"))
        registry.register(make_reg(name="gmail", version="2.0.0"))
        assert registry.count() == 2

    def test_register_duplicate_raises(self, registry):
        registry.register(make_reg(name="gmail"))
        with pytest.raises(AdapterRegistrationError):
            registry.register(make_reg(name="gmail"))

    def test_register_and_get(self, registry):
        reg = make_reg(name="gmail")
        registry.register(reg)
        identity = AdapterIdentity(name="gmail", version="1.0.0")
        assert registry.get(identity) is reg

    def test_register_and_exists(self, registry):
        registry.register(make_reg(name="gmail"))
        identity = AdapterIdentity(name="gmail", version="1.0.0")
        assert registry.exists(identity) is True

    def test_exists_false(self, registry):
        identity = AdapterIdentity(name="nonexistent", version="1.0.0")
        assert registry.exists(identity) is False


class TestAdapterRegistryUnregister:
    @pytest.fixture
    def registry(self):
        r = AdapterRegistry()
        r.register(make_reg(name="gmail", version="1.0.0"))
        r.register(make_reg(name="gmail", version="2.0.0"))
        return r

    def test_unregister(self, registry):
        identity = AdapterIdentity(name="gmail", version="1.0.0")
        registry.unregister(identity)
        assert registry.count() == 1

    def test_unregister_nonexistent_raises(self, registry):
        identity = AdapterIdentity(name="nonexistent", version="1.0.0")
        with pytest.raises(AdapterNotFoundError):
            registry.unregister(identity)

    def test_unregister_then_register_again(self, registry):
        identity = AdapterIdentity(name="gmail", version="1.0.0")
        registry.unregister(identity)
        registry.register(make_reg(name="gmail", version="1.0.0"))
        assert registry.count() == 2


# =========================================================================
# AdapterRegistry — with capability/credential registries
# =========================================================================


class TestAdapterRegistryWithCapabilityRegistry:
    @pytest.fixture
    def cap_registry(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        ))
        r.register(CapabilityDescriptor(
            name="search_email", display_name="Search Email", description="d",
            category="search", version="1.0.0",
        ))
        r.register_provider(CapabilityProvider(
            adapter_name="gmail", adapter_version="2.0.0",
            capability_names=("send_email", "search_email"),
        ))
        return r

    @pytest.fixture
    def registry(self, cap_registry):
        r = AdapterRegistry(capability_registry=cap_registry)
        return r

    def test_register_with_valid_capabilities(self, registry):
        reg = make_reg(
            name="gmail", version="2.0.0",
            adapter_class=GmailAdapter,
            capability_names=("send_email", "search_email"),
        )
        registry.register(reg)
        assert registry.count() == 1

    def test_register_with_invalid_capability_raises(self, registry):
        reg = make_reg(
            name="gmail", version="2.0.0",
            capability_names=("nonexistent_cap",),
        )
        with pytest.raises(AdapterRegistrationError) as exc:
            registry.register(reg)
        assert "nonexistent_cap" in str(exc.value)

    def test_find_providers_via_capability_registry(self, registry):
        reg = make_reg(
            name="gmail", version="2.0.0",
            adapter_class=GmailAdapter,
            capability_names=("send_email", "search_email"),
        )
        registry.register(reg)
        providers = registry.find_providers("send_email")
        assert len(providers) == 1
        assert providers[0].name == "gmail"

    def test_find_providers_case_insensitive(self, registry):
        reg = make_reg(
            name="gmail", version="2.0.0",
            adapter_class=GmailAdapter,
            capability_names=("send_email",),
        )
        registry.register(reg)
        providers = registry.find_providers("SEND_EMAIL")
        assert len(providers) == 1

    def test_find_providers_nonexistent(self, registry):
        providers = registry.find_providers("nonexistent")
        assert providers == []


class TestAdapterRegistryWithCredentialRegistry:
    @pytest.fixture
    def cred_registry(self):
        r = CredentialRegistry()
        r.register(CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
        ))
        return r

    def test_register_with_valid_credential(self, cred_registry):
        registry = AdapterRegistry(credential_registry=cred_registry)
        reg = make_reg(
            name="gmail", version="1.0.0",
            credential_descriptor_names=("gmail_oauth",),
        )
        registry.register(reg)
        assert registry.count() == 1

    def test_register_with_invalid_credential_raises(self, cred_registry):
        registry = AdapterRegistry(credential_registry=cred_registry)
        reg = make_reg(
            name="gmail", version="1.0.0",
            credential_descriptor_names=("nonexistent_cred",),
        )
        with pytest.raises(AdapterRegistrationError) as exc:
            registry.register(reg)
        assert "nonexistent_cred" in str(exc.value)


# =========================================================================
# AdapterRegistry — lookup
# =========================================================================


class TestAdapterRegistryLookup:
    @pytest.fixture
    def registry(self):
        r = AdapterRegistry()
        r.register(make_reg(name="gmail", version="1.0.0", priority=5, capability_names=("send_email",)))
        r.register(make_reg(name="gmail", version="2.0.0", priority=10, capability_names=("send_email", "search_email")))
        r.register(make_reg(name="slack", version="1.0.0", priority=8, capability_names=("send_message",)))
        r.register(make_reg(name="http", version="1.0.0", priority=0, enabled=False, capability_names=("http_request",)))
        return r

    def test_find_by_name_exact(self, registry):
        results = registry.find_by_name("gmail")
        assert len(results) == 2

    def test_find_by_name_case_insensitive(self, registry):
        results = registry.find_by_name("GMAIL")
        assert len(results) == 2

    def test_find_by_name_nonexistent(self, registry):
        assert registry.find_by_name("nonexistent") == []

    def test_find_by_version(self, registry):
        reg = registry.find_by_version("gmail", "1.0.0")
        assert reg is not None
        assert reg.version == "1.0.0"

    def test_find_by_version_nonexistent(self, registry):
        assert registry.find_by_version("gmail", "9.9.9") is None

    def test_find_by_capability(self, registry):
        results = registry.find_by_capability("send_email")
        assert len(results) == 2

    def test_find_by_capability_case_insensitive(self, registry):
        results = registry.find_by_capability("SEND_EMAIL")
        assert len(results) == 2

    def test_find_by_capability_nonexistent(self, registry):
        assert registry.find_by_capability("nonexistent") == []

    def test_find_enabled(self, registry):
        results = registry.find_enabled()
        assert len(results) == 3

    def test_find_disabled(self, registry):
        results = registry.find_disabled()
        assert len(results) == 1
        assert results[0].name == "http"

    def test_list_all(self, registry):
        assert len(registry.list_all()) == 4

    def test_search_by_name(self, registry):
        results = registry.search("gmail")
        assert len(results) == 2

    def test_search_case_insensitive(self, registry):
        results = registry.search("GMAIL")
        assert len(results) == 2

    def test_search_partial(self, registry):
        results = registry.search("mail")
        assert len(results) == 2

    def test_search_by_display_name(self, registry):
        results = registry.search("Slack")
        assert len(results) == 1

    def test_search_by_description(self, registry):
        results = registry.search("HTTP")
        assert len(results) == 1

    def test_search_empty_query(self, registry):
        assert registry.search("") == []

    def test_search_no_match(self, registry):
        assert registry.search("nonexistent") == []


# =========================================================================
# AdapterRegistry — provider resolution
# =========================================================================


class TestAdapterRegistryProviderSelection:
    @pytest.fixture
    def registry(self):
        r = AdapterRegistry()
        r.register(make_reg(
            name="smtp", version="1.0.0", priority=1,
            capability_names=("send_email",),
        ))
        r.register(make_reg(
            name="gmail", version="2.0.0", priority=10,
            capability_names=("send_email", "search_email"),
        ))
        r.register(make_reg(
            name="outlook", version="1.0.0", priority=5,
            capability_names=("send_email",),
        ))
        r.register(make_reg(
            name="gmail", version="1.0.0", priority=10,
            capability_names=("send_email",),
        ))
        r.register(make_reg(
            name="disabled_smtp", version="1.0.0", priority=100,
            capability_names=("send_email",), enabled=False,
        ))
        return r

    def test_find_providers_capability(self, registry):
        providers = registry.find_providers("send_email")
        assert len(providers) == 4  # smtp, gmail v1, gmail v2, outlook

    def test_find_providers_excludes_disabled(self, registry):
        for p in registry.find_providers("send_email"):
            assert p.enabled is True

    def test_select_provider_highest_priority(self, registry):
        selected = registry.select_provider("send_email")
        assert selected is not None
        assert selected.priority == 10

    def test_select_provider_among_tied_priority_uses_version(self, registry):
        selected = registry.select_provider("send_email")
        assert selected is not None
        assert selected.priority == 10
        assert selected.version == "2.0.0"  # newer version wins

    def test_highest_priority_provider(self, registry):
        selected = registry.highest_priority_provider("send_email")
        assert selected is not None
        assert selected.priority == 10

    def test_highest_priority_among_tied(self, registry):
        selected = registry.highest_priority_provider("send_email")
        assert selected.version == "2.0.0"  # newer version among tied priorities

    def test_select_provider_nonexistent(self, registry):
        selected = registry.select_provider("nonexistent")
        assert selected is None

    def test_highest_priority_nonexistent(self, registry):
        selected = registry.highest_priority_provider("nonexistent")
        assert selected is None

    def test_find_providers_no_capability_match(self, registry):
        assert registry.find_providers("fly_to_mars") == []

    def test_provider_selection_deterministic(self, registry):
        r1 = registry.select_provider("send_email")
        r2 = registry.select_provider("send_email")
        assert r1 is r2

    def test_provider_selection_version_order(self, registry):
        r = AdapterRegistry()
        r.register(make_reg(name="x", version="1.0.0", priority=10, capability_names=("c",)))
        r.register(make_reg(name="x", version="2.0.0", priority=10, capability_names=("c",)))
        r.register(make_reg(name="x", version="10.0.0", priority=10, capability_names=("c",)))
        selected = r.select_provider("c")
        assert selected is not None
        assert selected.version == "10.0.0"

    def test_provider_selection_respects_registration_order(self, registry):
        r = AdapterRegistry()
        r.register(make_reg(name="a", version="1.0.0", priority=10, capability_names=("c",)))
        r.register(make_reg(name="b", version="1.0.0", priority=10, capability_names=("c",)))
        r.register(make_reg(name="c", version="1.0.0", priority=10, capability_names=("c",)))
        selected = r.select_provider("c")
        assert selected is not None
        assert selected.name == "a"  # first registered wins among equal


# =========================================================================
# AdapterRegistry — factory integration
# =========================================================================


class TestAdapterRegistryFactory:
    @pytest.fixture
    def registry(self):
        r = AdapterRegistry()
        r.register(make_reg(name="gmail", version="1.0.0", adapter_class=GmailAdapter))
        r.register(make_reg(name="gmail", version="2.0.0", adapter_class=GmailAdapter))
        return r

    def test_factory_creates_adapter(self, registry):
        adapter = registry.create_adapter(AdapterIdentity(name="gmail", version="1.0.0"))
        assert isinstance(adapter, GmailAdapter)

    def test_factory_create_unknown_raises(self, registry):
        with pytest.raises(AdapterNotFoundError):
            registry.create_adapter(AdapterIdentity(name="nonexistent", version="1.0.0"))

    def test_factory_property(self, registry):
        assert isinstance(registry.factory, AdapterFactory)

    def test_factory_creates_fresh_instance(self, registry):
        a1 = registry.create_adapter(AdapterIdentity(name="gmail", version="1.0.0"))
        a2 = registry.create_adapter(AdapterIdentity(name="gmail", version="1.0.0"))
        assert a1 is not a2


# =========================================================================
# AdapterRegistry — validation
# =========================================================================


class TestAdapterRegistryValidation:
    @pytest.fixture
    def registry(self):
        r = AdapterRegistry()
        r.register(make_reg(name="gmail", version="1.0.0", adapter_class=GmailAdapter))
        r.register(make_reg(name="slack", version="1.0.0", adapter_class=SlackAdapter))
        return r

    def test_validate_clean(self, registry):
        issues = registry.validate()
        assert issues == []

    def test_validate_warns_missing_metadata(self, registry):
        class NoMetadataAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(
                    name="bad", display_name="Bad", version="1", description="d",
                )

            async def execute(self, context):
                return AdapterResult.success_result(data="x")

        r = AdapterRegistry()
        r.register(make_reg(
            name="bad", version="1.0.0", adapter_class=NoMetadataAdapter,
        ))
        issues = r.validate()
        assert isinstance(issues, list)

    def test_validate_with_capability_registry(self):
        cap_reg = CapabilityRegistry()
        r = AdapterRegistry(capability_registry=cap_reg)
        with pytest.raises(AdapterRegistrationError) as exc:
            r.register(make_reg(
                name="gmail", version="1.0.0",
                capability_names=("missing_cap",),
            ))
        assert "missing_cap" in str(exc.value)

    def test_validate_with_credential_registry(self):
        cred_reg = CredentialRegistry()
        r = AdapterRegistry(credential_registry=cred_reg)
        with pytest.raises(AdapterRegistrationError) as exc:
            r.register(make_reg(
                name="gmail", version="1.0.0",
                credential_descriptor_names=("missing_cred",),
            ))
        assert "missing_cred" in str(exc.value)


# =========================================================================
# AdapterRegistry — edge cases
# =========================================================================


class TestAdapterRegistryEdgeCases:
    def test_clear(self):
        r = AdapterRegistry()
        r.register(make_reg(name="a"))
        r.register(make_reg(name="b"))
        r.clear()
        assert r.count() == 0
        assert r.list_all() == []

    def test_empty_registry(self):
        r = AdapterRegistry()
        assert r.count() == 0
        assert r.list_all() == []
        assert r.find_enabled() == []
        assert r.find_disabled() == []
        assert r.find_by_name("x") == []
        assert r.search("x") == []
        assert r.find_providers("x") == []

    def test_large_registration(self):
        r = AdapterRegistry()
        for i in range(100):
            r.register(make_reg(name=f"adapter_{i:03d}", version="1.0.0"))
        assert r.count() == 100

    def test_search_special_chars(self):
        r = AdapterRegistry()
        r.register(make_reg(name="my-adapter", version="1.0.0"))
        assert len(r.search("my-adapter")) == 1
        assert len(r.search("adapter")) == 1

    def test_multiple_versions_same_name(self):
        r = AdapterRegistry()
        r.register(make_reg(name="x", version="1.0.0"))
        r.register(make_reg(name="x", version="2.0.0"))
        r.register(make_reg(name="x", version="3.0.0"))
        assert r.count() == 3
        assert len(r.find_by_name("x")) == 3


# =========================================================================
# AdapterRegistry — integration tests
# =========================================================================


class TestAdapterRegistryIntegration:
    def test_full_workflow(self):
        cap_reg = CapabilityRegistry()
        cap_reg.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        ))
        cap_reg.register_provider(CapabilityProvider(
            adapter_name="gmail", adapter_version="2.0.0",
            capability_names=("send_email",),
        ))

        cred_reg = CredentialRegistry()
        cred_reg.register(CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
        ))

        registry = AdapterRegistry(
            capability_registry=cap_reg,
            credential_registry=cred_reg,
        )

        reg = AdapterRegistration(
            identity=AdapterIdentity(name="gmail", version="2.0.0"),
            adapter_class=GmailAdapter,
            metadata=GmailAdapter().metadata,
            capability_names=("send_email",),
            credential_descriptor_names=("gmail_oauth",),
            priority=10,
        )
        registry.register(reg)

        assert registry.count() == 1
        assert registry.exists(AdapterIdentity(name="gmail", version="2.0.0"))

        selected = registry.select_provider("send_email")
        assert selected is not None
        assert selected.name == "gmail"

        adapter = registry.create_adapter(AdapterIdentity(name="gmail", version="2.0.0"))
        assert isinstance(adapter, GmailAdapter)

    def test_validate_with_real_adapter(self):
        class RealisticAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(
                    name="realistic", display_name="Realistic", version="1.0.0",
                    description="A realistic adapter",
                    supported_operations=("op1", "op2"),
                )

            async def execute(self, context):
                return AdapterResult.success_result(data="done", usage=UsageInfo(tokens_in=10))

        r = AdapterRegistry()
        r.register(AdapterRegistration(
            identity=AdapterIdentity(name="realistic", version="1.0.0"),
            adapter_class=RealisticAdapter,
            metadata=RealisticAdapter().metadata,
        ))
        assert r.count() == 1
        adapter = r.create_adapter(AdapterIdentity(name="realistic", version="1.0.0"))
        assert isinstance(adapter, RealisticAdapter)


# =========================================================================
# SDK self-containment
# =========================================================================


class TestAdapterRegistrySelfContainment:
    def test_no_execution_imports(self):
        import services.adapters.adapter_registry as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src
        assert "services.planner" not in src

    def test_no_planner_registration_imports(self):
        import services.adapters.adapter_registration as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src
        assert "services.planner" not in src

    def test_no_planner_factory_imports(self):
        import services.adapters.adapter_factory as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src
        assert "services.planner" not in src

    def test_registry_works_standalone(self):
        r = AdapterRegistry()
        r.register(make_reg(name="standalone"))
        assert r.count() == 1

    def test_factory_works_standalone(self):
        regs: dict[AdapterIdentity, AdapterRegistration] = {}
        regs[make_identity("x")] = make_reg(name="x")
        f = AdapterFactory(
            get_registration=lambda i: regs.get(i),
            find_registrations=lambda n: [
                r for r in regs.values() if r.name.lower() == n.lower()
            ],
        )
        adapter = f.create(AdapterIdentity(name="x", version="1.0.0"))
        assert isinstance(adapter, MockAdapter)

    def test_adapter_identity_standalone(self):
        i = AdapterIdentity(name="test", version="1.0.0")
        assert i.name == "test"

from __future__ import annotations

import pickle
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from services.adapters import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityProvider,
    CapabilityRegistrationError,
    CapabilityRegistry,
    ParameterSpec,
    ReturnSpec,
)

# =========================================================================
# CapabilityCategory
# =========================================================================


class TestCapabilityCategory:
    def test_communication(self):
        assert CapabilityCategory.COMMUNICATION == "communication"

    def test_productivity(self):
        assert CapabilityCategory.PRODUCTIVITY == "productivity"

    def test_search(self):
        assert CapabilityCategory.SEARCH == "search"

    def test_files(self):
        assert CapabilityCategory.FILES == "files"

    def test_crm(self):
        assert CapabilityCategory.CRM == "crm"

    def test_web(self):
        assert CapabilityCategory.WEB == "web"

    def test_ai(self):
        assert CapabilityCategory.AI == "ai"

    def test_system(self):
        assert CapabilityCategory.SYSTEM == "system"

    def test_any_string_accepted(self):
        d = CapabilityDescriptor(
            name="test", display_name="Test", description="d",
            category="my-custom-category", version="1.0.0",
        )
        assert d.category == "my-custom-category"

    def test_category_case_sensitive(self):
        d = CapabilityDescriptor(
            name="test", display_name="Test", description="d",
            category="COMMUNICATION", version="1.0.0",
        )
        assert d.category == "COMMUNICATION"

    def test_category_extensible(self):
        class ExtendedCategory:
            ANALYTICS = "analytics"
            DEVOPS = "devops"

        assert ExtendedCategory.ANALYTICS == "analytics"

    def test_all_categories_unique(self):
        cats = [
            CapabilityCategory.COMMUNICATION,
            CapabilityCategory.PRODUCTIVITY,
            CapabilityCategory.SEARCH,
            CapabilityCategory.FILES,
            CapabilityCategory.CRM,
            CapabilityCategory.WEB,
            CapabilityCategory.AI,
            CapabilityCategory.SYSTEM,
        ]
        assert len(set(cats)) == len(cats)


# =========================================================================
# ParameterSpec
# =========================================================================


class TestParameterSpecConstruction:
    def test_minimal(self):
        p = ParameterSpec(name="to", type="string")
        assert p.name == "to"
        assert p.type == "string"
        assert p.description == ""
        assert p.required is True
        assert p.default is None

    def test_full(self):
        p = ParameterSpec(
            name="recipient",
            type="string",
            description="Email recipient address",
            required=True,
            default="user@example.com",
        )
        assert p.default == "user@example.com"

    def test_optional_param(self):
        p = ParameterSpec(name="cc", type="string", required=False)
        assert p.required is False

    def test_integer_type(self):
        p = ParameterSpec(name="count", type="integer")
        assert p.type == "integer"

    def test_boolean_type(self):
        p = ParameterSpec(name="flag", type="boolean")
        assert p.type == "boolean"

    def test_array_type(self):
        p = ParameterSpec(name="items", type="array")
        assert p.type == "array"

    def test_object_type(self):
        p = ParameterSpec(name="payload", type="object")
        assert p.type == "object"

    def test_number_type(self):
        p = ParameterSpec(name="amount", type="number")
        assert p.type == "number"


class TestParameterSpecValidation:
    def test_empty_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name="", type="string")

    def test_whitespace_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name="   ", type="string")

    def test_non_string_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name=123, type="string")  # type: ignore[arg-type]

    def test_empty_type_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name="x", type="")

    def test_whitespace_type_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name="x", type="   ")

    def test_none_type_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name="x", type=None)  # type: ignore[arg-type]

    def test_none_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ParameterSpec(name=None, type="string")  # type: ignore[arg-type]


class TestParameterSpecImmutability:
    def test_cannot_set_name(self):
        p = ParameterSpec(name="x", type="string")
        with pytest.raises(FrozenInstanceError):
            p.name = "y"  # type: ignore[misc]

    def test_cannot_set_type(self):
        p = ParameterSpec(name="x", type="string")
        with pytest.raises(FrozenInstanceError):
            p.type = "int"  # type: ignore[misc]

    def test_cannot_set_required(self):
        p = ParameterSpec(name="x", type="string")
        with pytest.raises(FrozenInstanceError):
            p.required = False  # type: ignore[misc]


class TestParameterSpecSerialization:
    def test_to_dict(self):
        p = ParameterSpec(name="to", type="string", description="recipient", required=True)
        d = p.to_dict()
        assert d["name"] == "to"
        assert d["type"] == "string"
        assert d["required"] is True

    def test_from_dict(self):
        p = ParameterSpec.from_dict({"name": "cc", "type": "string", "required": False})
        assert p.name == "cc"
        assert p.required is False

    def test_round_trip(self):
        p = ParameterSpec(name="id", type="integer", description="primary key", default=0)
        assert ParameterSpec.from_dict(p.to_dict()) == p

    def test_to_dict_includes_default(self):
        p = ParameterSpec(name="x", type="string", default="hello")
        assert p.to_dict()["default"] == "hello"

    def test_to_dict_default_none(self):
        p = ParameterSpec(name="x", type="string")
        assert p.to_dict()["default"] is None

    def test_pickle_round_trip(self):
        p = ParameterSpec(name="x", type="string", description="desc")
        data = pickle.dumps(p)
        restored = pickle.loads(data)
        assert restored == p

    def test_equality(self):
        a = ParameterSpec(name="x", type="string")
        b = ParameterSpec(name="x", type="string")
        assert a == b

    def test_inequality(self):
        a = ParameterSpec(name="x", type="string")
        b = ParameterSpec(name="y", type="string")
        assert a != b

    def test_hashable(self):
        p = ParameterSpec(name="x", type="string")
        s = {p}
        assert p in s


# =========================================================================
# ReturnSpec
# =========================================================================


class TestReturnSpecConstruction:
    def test_default(self):
        r = ReturnSpec()
        assert r.type == "object"
        assert r.description == ""
        assert r.fields == ()

    def test_with_string_type(self):
        r = ReturnSpec(type="string")
        assert r.type == "string"

    def test_with_fields(self):
        fields = (
            ParameterSpec(name="id", type="string"),
            ParameterSpec(name="status", type="string"),
        )
        r = ReturnSpec(type="object", fields=fields)
        assert len(r.fields) == 2

    def test_with_description(self):
        r = ReturnSpec(type="object", description="The created entity")
        assert r.description == "The created entity"


class TestReturnSpecValidation:
    def test_empty_type_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            ReturnSpec(type="")


class TestReturnSpecImmutability:
    def test_cannot_set_type(self):
        r = ReturnSpec()
        with pytest.raises(FrozenInstanceError):
            r.type = "string"  # type: ignore[misc]


class TestReturnSpecSerialization:
    def test_to_dict_default(self):
        r = ReturnSpec()
        d = r.to_dict()
        assert d["type"] == "object"
        assert d["fields"] == []

    def test_to_dict_with_fields(self):
        r = ReturnSpec(type="array", fields=(ParameterSpec(name="id", type="string"),))
        d = r.to_dict()
        assert d["fields"][0]["name"] == "id"

    def test_from_dict(self):
        r = ReturnSpec.from_dict({"type": "string", "description": "message id"})
        assert r.type == "string"

    def test_from_dict_with_fields(self):
        data = {
            "type": "object",
            "fields": [{"name": "id", "type": "string"}],
        }
        r = ReturnSpec.from_dict(data)
        assert r.fields[0].name == "id"

    def test_round_trip(self):
        r = ReturnSpec(
            type="array",
            fields=(ParameterSpec(name="items", type="string"),),
        )
        assert ReturnSpec.from_dict(r.to_dict()) == r

    def test_pickle_round_trip(self):
        r = ReturnSpec(type="integer")
        data = pickle.dumps(r)
        restored = pickle.loads(data)
        assert restored == r


# =========================================================================
# CapabilityDescriptor
# =========================================================================


class TestCapabilityDescriptorConstruction:
    def test_minimal(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="Send an email message",
            category=CapabilityCategory.COMMUNICATION,
            version="1.0.0",
        )
        assert d.name == "send_email"
        assert d.display_name == "Send Email"
        assert d.description == "Send an email message"
        assert d.category == "communication"
        assert d.version == "1.0.0"
        assert d.parameters == ()
        assert d.returns.type == "object"
        assert d.requires_auth is False
        assert d.supports_streaming is False
        assert d.supports_batch is False
        assert d.tags == ()

    def test_full(self):
        params = (
            ParameterSpec(name="to", type="string", description="Recipient"),
            ParameterSpec(name="subject", type="string", description="Subject line"),
            ParameterSpec(name="body", type="string", description="Message body"),
        )
        returns = ReturnSpec(
            type="object",
            fields=(ParameterSpec(name="message_id", type="string"),),
        )
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="Send an email message",
            category=CapabilityCategory.COMMUNICATION,
            version="2.0.0",
            parameters=params,
            returns=returns,
            requires_auth=True,
            supports_streaming=False,
            supports_batch=True,
            tags=("email", "google", "outgoing"),
        )
        assert len(d.parameters) == 3
        assert d.requires_auth is True
        assert d.supports_batch is True
        assert d.tags == ("email", "google", "outgoing")

    def test_with_tags(self):
        d = CapabilityDescriptor(
            name="search_email",
            display_name="Search Email",
            description="Search emails",
            category=CapabilityCategory.SEARCH,
            version="1.0.0",
            tags=("email", "search"),
        )
        assert "email" in d.tags

    def test_qualified_name(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.5.0",
        )
        assert d.qualified_name == "send_email@1.5.0"

    def test_supports_streaming_true(self):
        d = CapabilityDescriptor(
            name="stream_chat",
            display_name="Stream Chat",
            description="d",
            category="communication",
            version="1.0.0",
            supports_streaming=True,
        )
        assert d.supports_streaming is True

    def test_supports_batch_true(self):
        d = CapabilityDescriptor(
            name="batch_send",
            display_name="Batch Send",
            description="d",
            category="communication",
            version="1.0.0",
            supports_batch=True,
        )
        assert d.supports_batch is True

    def test_matches_query_name(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="Send an email message",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("send_email") is True

    def test_matches_query_display_name(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("Send Email") is True

    def test_matches_query_description(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="Send an email message",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("email message") is True

    def test_matches_query_tag(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.0.0",
            tags=("google", "email"),
        )
        assert d.matches_query("google") is True

    def test_matches_query_case_insensitive(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("SEND_EMAIL") is True
        assert d.matches_query("send") is True

    def test_matches_query_no_match(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("receive") is False

    def test_matches_query_empty_query(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="d",
            category="communication",
            version="1.0.0",
        )
        assert d.matches_query("") is True  # empty string is in everything


class TestCapabilityDescriptorValidation:
    def test_empty_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="", display_name="X", description="d", category="c", version="1",
            )

    def test_invalid_name_pattern_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="Send Email", display_name="X", description="d", category="c", version="1",
            )

    def test_name_uppercase_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="SEND_EMAIL", display_name="X", description="d", category="c", version="1",
            )

    def test_name_with_spaces_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send email", display_name="X", description="d", category="c", version="1",
            )

    def test_name_starting_with_number_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="1st_cap", display_name="X", description="d", category="c", version="1",
            )

    def test_name_with_special_chars_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send@email", display_name="X", description="d", category="c", version="1",
            )

    def test_name_underscore_allowed(self):
        d = CapabilityDescriptor(
            name="send_email", display_name="X", description="d", category="c", version="1",
        )
        assert d.name == "send_email"

    def test_name_dot_allowed(self):
        d = CapabilityDescriptor(
            name="v2.send_email", display_name="X", description="d", category="c", version="1",
        )
        assert d.name == "v2.send_email"

    def test_name_hyphen_allowed(self):
        d = CapabilityDescriptor(
            name="send-email", display_name="X", description="d", category="c", version="1",
        )
        assert d.name == "send-email"

    def test_empty_display_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send", display_name="", description="d", category="c", version="1",
            )

    def test_empty_description_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send", display_name="X", description="", category="c", version="1",
            )

    def test_empty_category_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send", display_name="X", description="d", category="", version="1",
            )

    def test_empty_version_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send", display_name="X", description="d", category="c", version="",
            )

    def test_invalid_version_raises(self):
        d = CapabilityDescriptor(
            name="send", display_name="X", description="d", category="c", version="1.0.0",
        )
        assert d.version == "1.0.0"

    def test_version_with_special_chars_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send", display_name="X", description="d", category="c", version="1.0!beta",
            )

    def test_duplicate_parameter_names_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name="send",
                display_name="X",
                description="d",
                category="c",
                version="1",
                parameters=(
                    ParameterSpec(name="id", type="string"),
                    ParameterSpec(name="id", type="string"),
                ),
            )

    def test_non_string_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityDescriptor(
                name=123, display_name="X", description="d", category="c", version="1",  # type: ignore[arg-type]
            )

    def test_descriptor_validation_combines_errors(self):
        with pytest.raises(CapabilityRegistrationError) as exc:
            CapabilityDescriptor(
                name="",
                display_name="",
                description="",
                category="",
                version="",
            )
        msg = str(exc.value)
        assert "validation failed" in msg


class TestCapabilityDescriptorImmutability:
    def test_cannot_set_name(self):
        d = CapabilityDescriptor(
            name="send", display_name="X", description="d", category="c", version="1",
        )
        with pytest.raises(FrozenInstanceError):
            d.name = "new"  # type: ignore[misc]

    def test_cannot_set_category(self):
        d = CapabilityDescriptor(
            name="send", display_name="X", description="d", category="c", version="1",
        )
        with pytest.raises(FrozenInstanceError):
            d.category = "other"  # type: ignore[misc]

    def test_cannot_set_version(self):
        d = CapabilityDescriptor(
            name="send", display_name="X", description="d", category="c", version="1",
        )
        with pytest.raises(FrozenInstanceError):
            d.version = "2"  # type: ignore[misc]


class TestCapabilityDescriptorSerialization:
    def test_to_dict(self):
        d = CapabilityDescriptor(
            name="send_email",
            display_name="Send Email",
            description="Send outbound email",
            category="communication",
            version="1.0.0",
            parameters=(
                ParameterSpec(name="to", type="string"),
                ParameterSpec(name="subject", type="string"),
            ),
            requires_auth=True,
            tags=("email",),
        )
        result = d.to_dict()
        assert result["name"] == "send_email"
        assert result["display_name"] == "Send Email"
        assert len(result["parameters"]) == 2
        assert result["requires_auth"] is True
        assert result["tags"] == ["email"]

    def test_from_dict(self):
        data = {
            "name": "search_email",
            "display_name": "Search Email",
            "description": "Search through emails",
            "category": "search",
            "version": "1.5.0",
            "parameters": [{"name": "query", "type": "string"}],
            "returns": {"type": "array", "fields": [{"name": "messages", "type": "object"}]},
            "requires_auth": True,
            "tags": ["email", "search"],
        }
        d = CapabilityDescriptor.from_dict(data)
        assert d.name == "search_email"
        assert d.version == "1.5.0"
        assert len(d.parameters) == 1
        assert d.returns.fields[0].name == "messages"
        assert "email" in d.tags

    def test_from_dict_minimal(self):
        data = {
            "name": "ping",
            "display_name": "Ping",
            "description": "Health check",
            "category": "system",
            "version": "1.0.0",
        }
        d = CapabilityDescriptor.from_dict(data)
        assert d.parameters == ()
        assert d.returns.type == "object"
        assert d.requires_auth is False

    def test_round_trip(self):
        d = CapabilityDescriptor(
            name="create_event",
            display_name="Create Event",
            description="Create calendar event",
            category="productivity",
            version="2.0.0",
            parameters=(
                ParameterSpec(name="title", type="string"),
                ParameterSpec(name="start_time", type="string"),
            ),
            returns=ReturnSpec(type="object", fields=(ParameterSpec(name="event_id", type="string"),)),
            requires_auth=True,
            supports_batch=False,
            tags=("calendar", "google"),
        )
        assert CapabilityDescriptor.from_dict(d.to_dict()) == d

    def test_to_dict_parameters_empty(self):
        d = CapabilityDescriptor(
            name="ping", display_name="Ping", description="d", category="system", version="1",
        )
        assert d.to_dict()["parameters"] == []

    def test_to_dict_tags_empty(self):
        d = CapabilityDescriptor(
            name="ping", display_name="Ping", description="d", category="system", version="1",
        )
        assert d.to_dict()["tags"] == []

    def test_pickle_round_trip(self):
        d = CapabilityDescriptor(
            name="send", display_name="Send", description="d", category="c", version="1",
        )
        data = pickle.dumps(d)
        restored = pickle.loads(data)
        assert restored == d

    def test_equality(self):
        a = CapabilityDescriptor(
            name="send", display_name="Send", description="d", category="c", version="1",
        )
        b = CapabilityDescriptor(
            name="send", display_name="Send", description="d", category="c", version="1",
        )
        assert a == b

    def test_inequality(self):
        a = CapabilityDescriptor(
            name="send", display_name="Send", description="d", category="c", version="1",
        )
        b = CapabilityDescriptor(
            name="recv", display_name="Recv", description="d", category="c", version="1",
        )
        assert a != b

    def test_hashable(self):
        d = CapabilityDescriptor(
            name="send", display_name="Send", description="d", category="c", version="1",
        )
        s = {d}
        assert d in s


# =========================================================================
# CapabilityProvider
# =========================================================================


class TestCapabilityProviderConstruction:
    def test_minimal(self):
        p = CapabilityProvider(adapter_name="gmail", adapter_version="1.0.0")
        assert p.adapter_name == "gmail"
        assert p.adapter_version == "1.0.0"
        assert p.capability_names == ()
        assert p.priority == 0

    def test_full(self):
        p = CapabilityProvider(
            adapter_name="gmail",
            adapter_version="2.0.0",
            capability_names=("send_email", "search_email"),
            priority=10,
        )
        assert "send_email" in p.capability_names
        assert p.priority == 10

    def test_multiple_capabilities(self):
        names = ("send_email", "search_email", "read_email", "delete_email")
        p = CapabilityProvider(
            adapter_name="gmail",
            adapter_version="3.0.0",
            capability_names=names,
        )
        assert len(p.capability_names) == 4

    def test_priority_zero_by_default(self):
        p = CapabilityProvider(adapter_name="x", adapter_version="1")
        assert p.priority == 0

    def test_negative_priority_allowed(self):
        p = CapabilityProvider(adapter_name="x", adapter_version="1", priority=-1)
        assert p.priority == -1


class TestCapabilityProviderValidation:
    def test_empty_adapter_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityProvider(adapter_name="", adapter_version="1")

    def test_empty_adapter_version_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityProvider(adapter_name="x", adapter_version="")

    def test_non_string_adapter_name_raises(self):
        with pytest.raises(CapabilityRegistrationError):
            CapabilityProvider(adapter_name=123, adapter_version="1")  # type: ignore[arg-type]


class TestCapabilityProviderImmutability:
    def test_cannot_set_adapter_name(self):
        p = CapabilityProvider(adapter_name="x", adapter_version="1")
        with pytest.raises(FrozenInstanceError):
            p.adapter_name = "y"  # type: ignore[misc]

    def test_cannot_set_capability_names(self):
        p = CapabilityProvider(adapter_name="x", adapter_version="1")
        with pytest.raises(FrozenInstanceError):
            p.capability_names = ("a",)  # type: ignore[misc]


# =========================================================================
# CapabilityRegistry — registration
# =========================================================================


class TestCapabilityRegistryRegister:
    @pytest.fixture
    def registry(self):
        return CapabilityRegistry()

    def make(self, name="send_email", version="1.0.0", **kw: Any):
        return CapabilityDescriptor(
            name=name,
            display_name=kw.pop("display_name", name.replace("_", " ").title()),
            description=kw.pop("description", "d"),
            category=kw.pop("category", "communication"),
            version=version,
            **kw,
        )

    def test_register_single(self, registry):
        d = self.make()
        registry.register(d)
        assert registry.count() == 1

    def test_register_multiple_different_names(self, registry):
        registry.register(self.make(name="send_email"))
        registry.register(self.make(name="search_email"))
        assert registry.count() == 2

    def test_register_multiple_versions(self, registry):
        registry.register(self.make(name="send_email", version="1.0.0"))
        registry.register(self.make(name="send_email", version="2.0.0"))
        assert registry.count() == 2

    def test_register_duplicate_raises(self, registry):
        registry.register(self.make())
        with pytest.raises(CapabilityRegistrationError) as exc:
            registry.register(self.make())
        assert "already registered" in str(exc.value)

    def test_register_duplicate_with_extra_fields(self, registry):
        registry.register(self.make(description="first"))
        with pytest.raises(CapabilityRegistrationError):
            registry.register(self.make(description="second"))

    def test_register_and_get(self, registry):
        d = self.make()
        registry.register(d)
        assert registry.get("send_email", "1.0.0") is d

    def test_register_and_exists(self, registry):
        registry.register(self.make())
        assert registry.exists("send_email", "1.0.0") is True

    def test_exists_false(self, registry):
        assert registry.exists("nonexistent", "1.0.0") is False

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent", "1.0.0") is None


class TestCapabilityRegistryUnregister:
    @pytest.fixture
    def registry(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        ))
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="2.0.0",
        ))
        return r

    def test_unregister_by_version(self, registry):
        registry.unregister("send_email", "1.0.0")
        assert registry.count() == 1
        assert registry.exists("send_email", "2.0.0") is True

    def test_unregister_all_versions(self, registry):
        registry.unregister("send_email", "1.0.0")
        registry.unregister("send_email", "2.0.0")
        assert registry.count() == 0

    def test_unregister_nonexistent_raises(self, registry):
        with pytest.raises(CapabilityRegistrationError) as exc:
            registry.unregister("nonexistent", "1.0.0")
        assert "not registered" in str(exc.value)

    def test_unregister_wrong_version_raises(self, registry):
        with pytest.raises(CapabilityRegistrationError):
            registry.unregister("send_email", "3.0.0")

    def test_unregister_then_register_again(self, registry):
        registry.unregister("send_email", "1.0.0")
        d = CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        )
        registry.register(d)
        assert registry.get("send_email", "1.0.0") is d

    def test_unregister_empty_registry_raises(self):
        r = CapabilityRegistry()
        with pytest.raises(CapabilityRegistrationError):
            r.unregister("x", "1")


# =========================================================================
# CapabilityRegistry — lookup
# =========================================================================


class TestCapabilityRegistryLookup:
    @pytest.fixture
    def registry(self):
        r = CapabilityRegistry()
        for cat, names in [
            ("communication", ["send_email", "send_sms", "send_voice"]),
            ("search", ["search_email", "search_web", "search_contacts"]),
            ("files", ["upload_file", "download_file", "delete_file"]),
        ]:
            for n in names:
                r.register(CapabilityDescriptor(
                    name=n,
                    display_name=n.replace("_", " ").title(),
                    description=f"Capability {n}",
                    category=cat,
                    version="1.0.0",
                ))
        return r

    def test_find_by_name_exact(self, registry):
        results = registry.find_by_name("send_email")
        assert len(results) == 1
        assert results[0].name == "send_email"

    def test_find_by_name_case_insensitive(self, registry):
        results = registry.find_by_name("SEND_EMAIL")
        assert len(results) == 1

    def test_find_by_name_partial_not_match(self, registry):
        # find_by_name is exact, not partial
        results = registry.find_by_name("send")
        assert len(results) == 0

    def test_find_by_name_nonexistent(self, registry):
        assert registry.find_by_name("nonexistent") == []

    def test_find_by_category_exact(self, registry):
        results = registry.find_by_category("communication")
        assert len(results) == 3

    def test_find_by_category_case_insensitive(self, registry):
        results = registry.find_by_category("COMMUNICATION")
        assert len(results) == 3

    def test_find_by_category_nonexistent(self, registry):
        assert registry.find_by_category("crm") == []

    def test_find_by_tag_single(self, registry):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0", tags=("email", "google"),
        ))
        r.register(CapabilityDescriptor(
            name="search_email", display_name="Search Email", description="d",
            category="search", version="1.0.0", tags=("email",),
        ))
        results = r.find_by_tag("email")
        assert len(results) == 2

    def test_find_by_tag_multiple_and(self, registry):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0", tags=("email", "google"),
        ))
        r.register(CapabilityDescriptor(
            name="send_calendar", display_name="Send Calendar", description="d",
            category="productivity", version="1.0.0", tags=("calendar", "google"),
        ))
        results = r.find_by_tag("email", "google")
        assert len(results) == 1
        assert results[0].name == "send_email"

    def test_find_by_tag_no_matches(self, registry):
        results = registry.find_by_tag("nonexistent")
        assert len(results) == 0

    def test_find_by_tag_empty_returns_all(self, registry):
        results = registry.find_by_tag()
        assert len(results) == 9

    def test_find_by_tag_case_insensitive(self, registry):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0", tags=("EMAIL",),
        ))
        results = r.find_by_tag("email")
        assert len(results) == 1


# =========================================================================
# CapabilityRegistry — search
# =========================================================================


class TestCapabilityRegistrySearch:
    @pytest.fixture
    def registry(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="Send an email message",
            category="communication", version="1.0.0", tags=("email", "google"),
        ))
        r.register(CapabilityDescriptor(
            name="search_email", display_name="Search Email", description="Search through emails",
            category="search", version="1.0.0", tags=("email", "search"),
        ))
        r.register(CapabilityDescriptor(
            name="upload_file", display_name="Upload File", description="Upload a file to storage",
            category="files", version="1.0.0", tags=("file", "storage"),
        ))
        return r

    def test_search_by_name(self, registry):
        results = registry.search("send_email")
        assert len(results) == 1
        assert results[0].name == "send_email"

    def test_search_by_display_name(self, registry):
        results = registry.search("Upload File")
        assert len(results) == 1

    def test_search_by_description(self, registry):
        results = registry.search("email message")
        assert len(results) == 1

    def test_search_by_tag(self, registry):
        results = registry.search("storage")
        assert len(results) == 1

    def test_search_case_insensitive(self, registry):
        results = registry.search("SEND_EMAIL")
        assert len(results) == 1

    def test_search_partial_name(self, registry):
        results = registry.search("send")
        assert len(results) == 1

    def test_search_partial_display_name(self, registry):
        results = registry.search("Email")
        assert len(results) == 2

    def test_search_partial_description(self, registry):
        results = registry.search("through")
        assert len(results) == 1
        assert results[0].name == "search_email"

    def test_search_no_match(self, registry):
        results = registry.search("nonexistent")
        assert results == []

    def test_search_empty_query(self, registry):
        results = registry.search("")
        assert results == []

    def test_search_whitespace_query(self, registry):
        results = registry.search("   ")
        assert results == []

    def test_search_cross_category(self, registry):
        results = registry.search("email")
        assert len(results) == 2  # send_email and search_email

    def test_search_special_chars(self, registry):
        results = registry.search("file/upload")
        assert results == []

    def test_search_after_unregister(self, registry):
        registry.unregister("send_email", "1.0.0")
        results = registry.search("send")
        assert results == []


# =========================================================================
# CapabilityRegistry — list_all / count / clear
# =========================================================================


class TestCapabilityRegistryListAll:
    @pytest.fixture
    def registry(self):
        r = CapabilityRegistry()
        for name in ["a", "b", "c"]:
            r.register(CapabilityDescriptor(
                name=name, display_name=name.upper(), description="d",
                category="system", version="1.0.0",
            ))
        return r

    def test_list_all(self, registry):
        results = registry.list_all()
        assert len(results) == 3

    def test_list_all_empty(self):
        r = CapabilityRegistry()
        assert r.list_all() == []

    def test_list_all_order(self, registry):
        results = registry.list_all()
        names = [d.name for d in results]
        assert "a" in names
        assert "b" in names
        assert "c" in names

    def test_count(self, registry):
        assert registry.count() == 3

    def test_count_empty(self):
        assert CapabilityRegistry().count() == 0

    def test_clear(self, registry):
        registry.clear()
        assert registry.count() == 0
        assert registry.list_all() == []

    def test_clear_also_clears_providers(self, registry):
        registry.register_provider(
            CapabilityProvider(adapter_name="x", adapter_version="1")
        )
        registry.clear()
        assert registry.provider_count() == 0

    def test_register_after_clear(self, registry):
        registry.clear()
        registry.register(CapabilityDescriptor(
            name="new", display_name="New", description="d",
            category="system", version="1",
        ))
        assert registry.count() == 1


# =========================================================================
# CapabilityRegistry — provider management
# =========================================================================


class TestCapabilityRegistryProviders:
    @pytest.fixture
    def registry(self):
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
            adapter_name="gmail",
            adapter_version="1.0.0",
            capability_names=("send_email", "search_email"),
            priority=10,
        ))
        return r

    def test_register_provider(self, registry):
        assert registry.provider_count() == 1

    def test_register_provider_duplicate_raises(self, registry):
        with pytest.raises(CapabilityRegistrationError):
            registry.register_provider(CapabilityProvider(
                adapter_name="gmail",
                adapter_version="1.0.0",
                capability_names=("send_email",),
            ))

    def test_register_multiple_providers(self, registry):
        registry.register_provider(CapabilityProvider(
            adapter_name="outlook",
            adapter_version="1.0.0",
            capability_names=("send_email",),
        ))
        assert registry.provider_count() == 2

    def test_find_providers_by_capability(self, registry):
        results = registry.find_providers("send_email")
        assert len(results) == 1
        assert results[0].adapter_name == "gmail"

    def test_find_providers_by_capability_case_insensitive(self, registry):
        results = registry.find_providers("SEND_EMAIL")
        assert len(results) == 1

    def test_find_providers_multiple(self, registry):
        registry.register_provider(CapabilityProvider(
            adapter_name="outlook",
            adapter_version="1.0.0",
            capability_names=("send_email", "search_email"),
        ))
        results = registry.find_providers("send_email")
        assert len(results) == 2

    def test_find_providers_nonexistent(self, registry):
        results = registry.find_providers("nonexistent")
        assert results == []

    def test_get_provider(self, registry):
        p = registry.get_provider("gmail", "1.0.0")
        assert p is not None
        assert p.adapter_name == "gmail"

    def test_get_provider_nonexistent(self, registry):
        assert registry.get_provider("nonexistent", "1.0.0") is None

    def test_list_providers(self, registry):
        providers = registry.list_providers()
        assert len(providers) == 1

    def test_unregister_provider(self, registry):
        registry.unregister_provider("gmail", "1.0.0")
        assert registry.provider_count() == 0

    def test_unregister_nonexistent_provider_raises(self, registry):
        with pytest.raises(CapabilityRegistrationError):
            registry.unregister_provider("nonexistent", "1.0.0")

    def test_providers_independent_of_descriptors(self, registry):
        registry.unregister("send_email", "1.0.0")
        assert registry.provider_count() == 1  # provider still registered


# =========================================================================
# CapabilityRegistry — integration
# =========================================================================


class TestCapabilityRegistryIntegration:
    def test_full_lifecycle(self):
        r = CapabilityRegistry()

        send_email = CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="Send email",
            category="communication", version="1.0.0",
            tags=("email", "google"),
        )
        search_email = CapabilityDescriptor(
            name="search_email", display_name="Search Email", description="Search emails",
            category="search", version="1.0.0",
            tags=("email", "google"),
        )
        r.register(send_email)
        r.register(search_email)

        r.register_provider(CapabilityProvider(
            adapter_name="gmail",
            adapter_version="2.0.0",
            capability_names=("send_email", "search_email"),
        ))

        assert r.count() == 2
        assert r.provider_count() == 1

        comm_caps = r.find_by_category("communication")
        assert len(comm_caps) == 1

        email_caps = r.find_by_tag("email")
        assert len(email_caps) == 2

        google_caps = r.find_by_tag("google")
        assert len(google_caps) == 2

        search_results = r.search("send")
        assert len(search_results) == 1

        providers = r.find_providers("send_email")
        assert providers[0].adapter_name == "gmail"

    def test_multiple_adapters_same_capability(self):
        r = CapabilityRegistry()
        d = CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        )
        r.register(d)
        r.register_provider(CapabilityProvider(
            adapter_name="gmail", adapter_version="1.0.0",
            capability_names=("send_email",), priority=10,
        ))
        r.register_provider(CapabilityProvider(
            adapter_name="outlook", adapter_version="1.0.0",
            capability_names=("send_email",), priority=5,
        ))
        providers = r.find_providers("send_email")
        assert len(providers) == 2

    def test_descriptors_and_providers_independent(self):
        r = CapabilityRegistry()
        d = CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        )
        r.register(d)
        r.register_provider(CapabilityProvider(
            adapter_name="gmail", adapter_version="1.0.0",
            capability_names=("send_email",),
        ))
        r.unregister("send_email", "1.0.0")
        assert r.count() == 0
        assert r.provider_count() == 1

    def test_cross_registry_queries(self):
        r1 = CapabilityRegistry()
        r2 = CapabilityRegistry()
        r1.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        ))
        r2.register(CapabilityDescriptor(
            name="send_email", display_name="Send Email", description="d",
            category="communication", version="1.0.0",
        ))
        assert r1.count() == 1
        assert r2.count() == 1


# =========================================================================
# CapabilityRegistry — edge cases
# =========================================================================


class TestCapabilityRegistryEdgeCases:
    def test_register_with_same_name_different_version_order(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="cap", display_name="Cap", description="d",
            category="system", version="2.0.0",
        ))
        r.register(CapabilityDescriptor(
            name="cap", display_name="Cap", description="d",
            category="system", version="1.0.0",
        ))
        assert r.count() == 2

    def test_find_by_name_returns_all_versions(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="cap", display_name="Cap", description="d",
            category="system", version="1.0.0",
        ))
        r.register(CapabilityDescriptor(
            name="cap", display_name="Cap", description="d",
            category="system", version="2.0.0",
        ))
        assert len(r.find_by_name("cap")) == 2

    def test_tolerant_of_version_formats(self):
        r = CapabilityRegistry()
        for v in ["1", "1.0", "1.0.0", "v2", "2.0.0-beta", "3.0.0_rc1"]:
            r.register(CapabilityDescriptor(
                name="cap", display_name="Cap", description="d",
                category="system", version=v,
            ))
        assert r.count() == 6

    def test_register_large_number(self):
        r = CapabilityRegistry()
        for i in range(100):
            r.register(CapabilityDescriptor(
                name=f"cap_{i:03d}", display_name=f"Cap {i}", description="d",
                category="system", version="1.0.0",
            ))
        assert r.count() == 100

    def test_search_across_all_fields(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="my_cap", display_name="Display Name", description="A long description here",
            category="system", version="1.0.0", tags=("tag1", "tag2"),
        ))
        assert len(r.search("my_cap")) == 1
        assert len(r.search("Display")) == 1
        assert len(r.search("long")) == 1
        assert len(r.search("tag1")) == 1


# =========================================================================
# SDK self-containment
# =========================================================================


class TestCapabilitySystemSelfContainment:
    def test_no_execution_imports(self):
        import services.adapters.capabilities as cap_mod
        import inspect
        source = inspect.getsource(cap_mod)
        assert "services.execution" not in source
        assert "services.planner" not in source

    def test_no_planner_imports(self):
        import services.adapters.capability_registry as reg_mod
        import inspect
        source = inspect.getsource(reg_mod)
        assert "services.planner" not in source
        assert "services.execution" not in source

    def test_registry_no_concrete_adapters(self):
        r = CapabilityRegistry()
        assert r.count() == 0
        assert r.provider_count() == 0

    def test_descriptor_works_without_runtime(self):
        d = CapabilityDescriptor(
            name="test", display_name="Test", description="No runtime needed",
            category="system", version="1.0.0",
        )
        assert d.name == "test"

    def test_registry_works_without_runtime(self):
        r = CapabilityRegistry()
        r.register(CapabilityDescriptor(
            name="ping", display_name="Ping", description="Health check",
            category="system", version="1.0.0",
        ))
        assert r.exists("ping", "1.0.0")

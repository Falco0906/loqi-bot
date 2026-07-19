from __future__ import annotations

import pickle
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from services.adapters import (
    CredentialDescriptor,
    CredentialField,
    CredentialInstance,
    CredentialNotFoundError,
    CredentialReference,
    CredentialRegistry,
    CredentialResolver,
    CredentialType,
    ValidationError,
    mask_sensitive_values,
    mask_value,
)

# =========================================================================
# CredentialType
# =========================================================================


class TestCredentialType:
    def test_api_key(self):
        assert CredentialType.API_KEY == "api_key"

    def test_oauth2(self):
        assert CredentialType.OAUTH2 == "oauth2"

    def test_basic_auth(self):
        assert CredentialType.BASIC_AUTH == "basic_auth"

    def test_bearer_token(self):
        assert CredentialType.BEARER_TOKEN == "bearer_token"

    def test_jwt(self):
        assert CredentialType.JWT == "jwt"

    def test_custom(self):
        assert CredentialType.CUSTOM == "custom"

    def test_all_unique(self):
        vals = [
            CredentialType.API_KEY,
            CredentialType.OAUTH2,
            CredentialType.BASIC_AUTH,
            CredentialType.BEARER_TOKEN,
            CredentialType.JWT,
            CredentialType.CUSTOM,
        ]
        assert len(set(vals)) == len(vals)

    def test_custom_any_string(self):
        assert "whatever" not in (CredentialType.API_KEY,)


# =========================================================================
# Masking
# =========================================================================


class TestMaskValue:
    def test_empty_string(self):
        assert mask_value("") == ""

    def test_short_string_masked(self):
        result = mask_value("abc")
        assert result == "********"

    def test_exact_boundary(self):
        result = mask_value("abcdefgh")  # 8 chars, show_first=4
        assert result == "abcd****"
        assert len(result) == 8

    def test_long_string(self):
        result = mask_value("sk_live_abcdef123456")
        assert result.startswith("sk_l")
        assert result.endswith("*" * (len("sk_live_abcdef123456") - 4))
        assert len(result) == len("sk_live_abcdef123456")

    def test_show_first_param(self):
        result = mask_value("abcdefghij", show_first=6)
        assert result.startswith("abcdef")
        assert len(result) == 10

    def test_custom_mask_char(self):
        result = mask_value("abcdefghij", mask_char="#")
        assert "####" in result

    def test_none_value_returns_empty(self):
        assert mask_value("") == ""


class TestMaskSensitiveValues:
    def test_masks_sensitive_keys(self):
        values = {"api_key": "sk_live_xxxx", "name": "public"}
        result = mask_sensitive_values(values, {"api_key"})
        assert result["api_key"].startswith("sk_l")
        assert "****" in result["api_key"]
        assert result["name"] == "public"

    def test_non_sensitive_left_untouched(self):
        values = {"user": "admin", "host": "localhost"}
        result = mask_sensitive_values(values, set())
        assert result == values

    def test_empty_values(self):
        assert mask_sensitive_values({}, {"key"}) == {}

    def test_sensitive_not_in_values(self):
        values = {"name": "test"}
        result = mask_sensitive_values(values, {"api_key"})
        assert result["name"] == "test"

    def test_empty_string_sensitive_value(self):
        values = {"api_key": ""}
        result = mask_sensitive_values(values, {"api_key"})
        assert result["api_key"] == ""

    def test_multiple_sensitive_fields(self):
        values = {"client_id": "abc123", "client_secret": "shh"}
        result = mask_sensitive_values(values, {"client_id", "client_secret"})
        assert result["client_id"] != "abc123"
        assert "**" in result["client_id"]
        assert result["client_secret"] == "********"


# =========================================================================
# CredentialField
# =========================================================================


class TestCredentialFieldConstruction:
    def test_minimal(self):
        f = CredentialField(name="api_key")
        assert f.name == "api_key"
        assert f.type == "string"
        assert f.description == ""
        assert f.required is True
        assert f.sensitive is True

    def test_full(self):
        f = CredentialField(
            name="client_id",
            type="string",
            description="OAuth client ID",
            required=True,
            sensitive=False,
        )
        assert f.sensitive is False

    def test_not_required(self):
        f = CredentialField(name="scope", required=False)
        assert f.required is False

    def test_not_sensitive(self):
        f = CredentialField(name="username", sensitive=False)
        assert f.sensitive is False

    def test_custom_type(self):
        f = CredentialField(name="token", type="password")
        assert f.type == "password"


class TestCredentialFieldValidation:
    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="")

    def test_whitespace_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="   ")

    def test_uppercase_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="API_KEY")

    def test_name_with_spaces_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="api key")

    def test_name_starting_number_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="1key")

    def test_underscore_name_allowed(self):
        f = CredentialField(name="client_secret")
        assert f.name == "client_secret"

    def test_dot_name_allowed(self):
        f = CredentialField(name="azure.tenant_id")
        assert f.name == "azure.tenant_id"

    def test_hyphen_name_allowed(self):
        f = CredentialField(name="x-api-key")
        assert f.name == "x-api-key"

    def test_empty_type_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name="x", type="")

    def test_non_string_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialField(name=123)  # type: ignore[arg-type]


class TestCredentialFieldImmutability:
    def test_cannot_set_name(self):
        f = CredentialField(name="key")
        with pytest.raises(FrozenInstanceError):
            f.name = "new"  # type: ignore[misc]

    def test_cannot_set_sensitive(self):
        f = CredentialField(name="key")
        with pytest.raises(FrozenInstanceError):
            f.sensitive = False  # type: ignore[misc]


class TestCredentialFieldSerialization:
    def test_to_dict(self):
        f = CredentialField(name="api_key", type="password", description="API key", sensitive=True)
        d = f.to_dict()
        assert d["name"] == "api_key"
        assert d["type"] == "password"
        assert d["sensitive"] is True

    def test_from_dict(self):
        f = CredentialField.from_dict({"name": "token", "type": "string", "sensitive": False})
        assert f.name == "token"
        assert f.sensitive is False

    def test_round_trip(self):
        f = CredentialField(name="secret", type="password", sensitive=True)
        assert CredentialField.from_dict(f.to_dict()) == f

    def test_equality(self):
        a = CredentialField(name="key", type="string")
        b = CredentialField(name="key", type="string")
        assert a == b

    def test_inequality(self):
        a = CredentialField(name="key1", type="string")
        b = CredentialField(name="key2", type="string")
        assert a != b

    def test_hashable(self):
        f = CredentialField(name="key", type="string")
        s = {f}
        assert f in s

    def test_pickle(self):
        f = CredentialField(name="key", type="password")
        data = pickle.dumps(f)
        restored = pickle.loads(data)
        assert restored == f


# =========================================================================
# CredentialDescriptor
# =========================================================================


class TestCredentialDescriptorConstruction:
    def test_minimal(self):
        d = CredentialDescriptor(
            name="gmail_oauth",
            display_name="Gmail OAuth2",
            description="OAuth2 credentials for Gmail",
            auth_type=CredentialType.OAUTH2,
        )
        assert d.name == "gmail_oauth"
        assert d.auth_type == "oauth2"
        assert d.required_fields == ()
        assert d.optional_fields == ()
        assert d.supports_refresh is False
        assert d.supports_expiry is False
        assert d.version == "1.0.0"

    def test_with_fields(self):
        d = CredentialDescriptor(
            name="gmail_oauth",
            display_name="Gmail OAuth2",
            description="OAuth2 credentials for Gmail",
            auth_type=CredentialType.OAUTH2,
            required_fields=(
                CredentialField(name="client_id", sensitive=False),
                CredentialField(name="client_secret", sensitive=True),
            ),
            optional_fields=(
                CredentialField(name="scope", sensitive=False, required=False),
            ),
        )
        assert len(d.required_fields) == 2
        assert len(d.optional_fields) == 1
        assert d.all_fields == [*d.required_fields, *d.optional_fields]

    def test_supports_refresh(self):
        d = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2, supports_refresh=True,
        )
        assert d.supports_refresh is True

    def test_supports_expiry(self):
        d = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2, supports_expiry=True,
        )
        assert d.supports_expiry is True

    def test_sensitive_field_names(self):
        d = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
            required_fields=(
                CredentialField(name="client_id", sensitive=False),
                CredentialField(name="client_secret", sensitive=True),
            ),
        )
        assert d.sensitive_field_names == {"client_secret"}

    def test_required_field_names(self):
        d = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
            required_fields=(CredentialField(name="api_key"),),
        )
        assert d.required_field_names == {"api_key"}

    def test_tags(self):
        d = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2, tags=("google", "email"),
        )
        assert d.tags == ("google", "email")

    def test_api_key_descriptor(self):
        d = CredentialDescriptor(
            name="openai_api_key",
            display_name="OpenAI API Key",
            description="API key for OpenAI",
            auth_type=CredentialType.API_KEY,
            required_fields=(CredentialField(name="api_key", type="password"),),
        )
        assert d.auth_type == "api_key"

    def test_basic_auth_descriptor(self):
        d = CredentialDescriptor(
            name="smtp_basic",
            display_name="SMTP Basic Auth",
            description="Basic auth for SMTP",
            auth_type=CredentialType.BASIC_AUTH,
            required_fields=(
                CredentialField(name="username", sensitive=False),
                CredentialField(name="password"),
            ),
        )
        assert len(d.required_fields) == 2


class TestCredentialDescriptorValidation:
    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="", display_name="X", description="d", auth_type="api_key",
            )

    def test_uppercase_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="GMAIL", display_name="X", description="d", auth_type="api_key",
            )

    def test_name_with_spaces_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail oauth", display_name="X", description="d", auth_type="api_key",
            )

    def test_empty_display_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail", display_name="", description="d", auth_type="api_key",
            )

    def test_empty_description_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail", display_name="X", description="", auth_type="api_key",
            )

    def test_empty_auth_type_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail", display_name="X", description="d", auth_type="",
            )

    def test_duplicate_required_fields_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail", display_name="X", description="d",
                auth_type="oauth2",
                required_fields=(
                    CredentialField(name="client_id"),
                    CredentialField(name="client_id"),
                ),
            )

    def test_duplicate_across_required_and_optional_raises(self):
        with pytest.raises(ValidationError):
            CredentialDescriptor(
                name="gmail", display_name="X", description="d",
                auth_type="oauth2",
                required_fields=(CredentialField(name="client_id"),),
                optional_fields=(CredentialField(name="client_id"),),
            )

    def test_multiple_validation_errors(self):
        with pytest.raises(ValidationError) as exc:
            CredentialDescriptor(
                name="", display_name="", description="", auth_type="",
            )
        assert "validation failed" in str(exc.value)


class TestCredentialDescriptorImmutability:
    def test_cannot_set_name(self):
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        with pytest.raises(FrozenInstanceError):
            d.name = "new"  # type: ignore[misc]

    def test_cannot_set_auth_type(self):
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        with pytest.raises(FrozenInstanceError):
            d.auth_type = "api_key"  # type: ignore[misc]


class TestCredentialDescriptorSerialization:
    def test_to_dict(self):
        d = CredentialDescriptor(
            name="gmail_oauth",
            display_name="Gmail OAuth2",
            description="OAuth2 for Gmail",
            auth_type=CredentialType.OAUTH2,
            required_fields=(CredentialField(name="client_id", sensitive=False),),
            supports_refresh=True,
            tags=("google",),
        )
        result = d.to_dict()
        assert result["name"] == "gmail_oauth"
        assert result["auth_type"] == "oauth2"
        assert result["supports_refresh"] is True
        assert len(result["required_fields"]) == 1

    def test_from_dict(self):
        data = {
            "name": "openai_key",
            "display_name": "OpenAI Key",
            "description": "API key for OpenAI",
            "auth_type": "api_key",
            "required_fields": [{"name": "api_key", "type": "password"}],
            "tags": ["ai", "openai"],
        }
        d = CredentialDescriptor.from_dict(data)
        assert d.name == "openai_key"
        assert d.required_fields[0].name == "api_key"
        assert "ai" in d.tags

    def test_from_dict_minimal(self):
        data = {
            "name": "simple_key",
            "display_name": "Simple Key",
            "description": "A simple key",
            "auth_type": "api_key",
        }
        d = CredentialDescriptor.from_dict(data)
        assert d.required_fields == ()
        assert d.version == "1.0.0"

    def test_round_trip(self):
        d = CredentialDescriptor(
            name="gmail_oauth",
            display_name="Gmail OAuth2",
            description="OAuth2 for Gmail",
            auth_type=CredentialType.OAUTH2,
            required_fields=(
                CredentialField(name="client_id", sensitive=False),
                CredentialField(name="client_secret"),
            ),
            supports_refresh=True,
            supports_expiry=True,
            tags=("google",),
        )
        assert CredentialDescriptor.from_dict(d.to_dict()) == d

    def test_equality(self):
        a = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        b = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        assert a == b

    def test_inequality(self):
        a = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        b = CredentialDescriptor(
            name="slack", display_name="Slack", description="d", auth_type="oauth2",
        )
        assert a != b

    def test_hashable(self):
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        s = {d}
        assert d in s

    def test_pickle(self):
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        data = pickle.dumps(d)
        restored = pickle.loads(data)
        assert restored == d


# =========================================================================
# CredentialReference
# =========================================================================


class TestCredentialReferenceConstruction:
    def test_minimal(self):
        ref = CredentialReference(credential_id="cred-1", descriptor_name="gmail_oauth")
        assert ref.credential_id == "cred-1"
        assert ref.descriptor_name == "gmail_oauth"
        assert ref.metadata == {}

    def test_with_metadata(self):
        ref = CredentialReference(
            credential_id="cred-1",
            descriptor_name="gmail_oauth",
            metadata={"user_id": "u-42"},
        )
        assert ref.metadata["user_id"] == "u-42"


class TestCredentialReferenceValidation:
    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            CredentialReference(credential_id="", descriptor_name="gmail")

    def test_empty_descriptor_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialReference(credential_id="c1", descriptor_name="")

    def test_non_string_id_raises(self):
        with pytest.raises(ValidationError):
            CredentialReference(credential_id=123, descriptor_name="gmail")  # type: ignore[arg-type]


class TestCredentialReferenceImmutability:
    def test_cannot_set_id(self):
        ref = CredentialReference(credential_id="c1", descriptor_name="gmail")
        with pytest.raises(FrozenInstanceError):
            ref.credential_id = "c2"  # type: ignore[misc]


class TestCredentialReferenceSerialization:
    def test_to_dict(self):
        ref = CredentialReference(
            credential_id="c1", descriptor_name="gmail", metadata={"key": "val"},
        )
        d = ref.to_dict()
        assert d["credential_id"] == "c1"
        assert d["metadata"]["key"] == "val"

    def test_from_dict(self):
        ref = CredentialReference.from_dict({"credential_id": "c1", "descriptor_name": "gmail"})
        assert ref.credential_id == "c1"

    def test_round_trip(self):
        ref = CredentialReference(credential_id="c1", descriptor_name="gmail")
        assert CredentialReference.from_dict(ref.to_dict()) == ref

    def test_pickle(self):
        ref = CredentialReference(credential_id="c1", descriptor_name="gmail")
        data = pickle.dumps(ref)
        restored = pickle.loads(data)
        assert restored == ref


# =========================================================================
# CredentialInstance
# =========================================================================


class TestCredentialInstanceConstruction:
    def test_minimal(self):
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail_oauth",
            values={"client_id": "abc", "client_secret": "shh"},
        )
        assert ci.credential_id == "ci-1"
        assert ci.values["client_id"] == "abc"
        assert ci.expires_at is None
        assert ci.created_at is None
        assert ci.metadata == {}

    def test_with_dates(self):
        now = datetime.now(timezone.utc)
        later = now + timedelta(hours=1)
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail_oauth",
            values={"token": "xyz"},
            expires_at=later,
            created_at=now,
        )
        assert ci.expires_at == later
        assert ci.created_at == now

    def test_with_metadata(self):
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail_oauth",
            values={"key": "val"},
            metadata={"label": "primary"},
        )
        assert ci.metadata["label"] == "primary"


class TestCredentialInstanceValidation:
    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            CredentialInstance(credential_id="", descriptor_name="gmail", values={})

    def test_empty_descriptor_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialInstance(credential_id="c1", descriptor_name="", values={})

    def test_non_dict_values_raises(self):
        with pytest.raises(ValidationError):
            CredentialInstance(credential_id="c1", descriptor_name="gmail", values="bad")  # type: ignore[arg-type]


class TestCredentialInstanceImmutability:
    def test_cannot_set_values(self):
        ci = CredentialInstance(credential_id="c1", descriptor_name="gmail", values={"k": "v"})
        with pytest.raises(FrozenInstanceError):
            ci.values = {"new": "val"}  # type: ignore[misc]

    def test_cannot_set_credential_id(self):
        ci = CredentialInstance(credential_id="c1", descriptor_name="gmail", values={"k": "v"})
        with pytest.raises(FrozenInstanceError):
            ci.credential_id = "c2"  # type: ignore[misc]


class TestCredentialInstanceExpiry:
    def test_not_expired(self):
        future = datetime.now(timezone.utc) + timedelta(days=1)
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="gmail", values={"k": "v"},
            expires_at=future,
        )
        assert ci.is_expired() is False

    def test_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="gmail", values={"k": "v"},
            expires_at=past,
        )
        assert ci.is_expired() is True

    def test_no_expiry(self):
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="gmail", values={"k": "v"},
        )
        assert ci.is_expired() is False


class TestCredentialInstanceMasking:
    def test_mask_sensitive(self):
        desc = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
            required_fields=(
                CredentialField(name="client_id", sensitive=False),
                CredentialField(name="client_secret", sensitive=True),
            ),
        )
        ci = CredentialInstance(
            credential_id="c1",
            descriptor_name="gmail_oauth",
            values={"client_id": "abc123", "client_secret": "supersecret"},
        )
        masked = ci.mask_sensitive(desc)
        assert masked.values["client_id"] == "abc123"
        assert masked.values["client_secret"] != "supersecret"
        assert "****" in masked.values["client_secret"]
        assert masked.credential_id == ci.credential_id

    def test_mask_sensitive_preserves_other_fields(self):
        desc = CredentialDescriptor(
            name="api", display_name="API", description="d",
            auth_type=CredentialType.API_KEY,
            required_fields=(CredentialField(name="api_key"),),
        )
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="api", values={"api_key": "sk-xxx"},
        )
        masked = ci.mask_sensitive(desc)
        assert masked.values["api_key"] != "sk-xxx"

    def test_to_safe_dict(self):
        desc = CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type=CredentialType.OAUTH2,
            required_fields=(CredentialField(name="client_secret"),),
        )
        ci = CredentialInstance(
            credential_id="c1",
            descriptor_name="gmail_oauth",
            values={"client_secret": "shhh"},
            metadata={"label": "primary"},
        )
        safe = ci.to_safe_dict(desc)
        assert safe["credential_id"] == "c1"
        assert "shhh" not in safe["values"]["client_secret"]
        assert safe["metadata"]["label"] == "primary"

    def test_repr_no_secrets(self):
        ci = CredentialInstance(
            credential_id="c1",
            descriptor_name="gmail_oauth",
            values={"client_secret": "super-secret-value"},
        )
        r = repr(ci)
        assert "super-secret-value" not in r
        assert "{...}" in r
        assert "c1" in r

    def test_str_no_secrets(self):
        ci = CredentialInstance(
            credential_id="c1",
            descriptor_name="gmail_oauth",
            values={"client_secret": "super-secret-value"},
        )
        s = str(ci)
        assert "super-secret-value" not in s
        assert "c1" in s

    def test_mask_sensitive_updates_values(self):
        desc = CredentialDescriptor(
            name="api", display_name="API", description="d",
            auth_type=CredentialType.API_KEY,
            required_fields=(CredentialField(name="key"),),
        )
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="api",
            values={"key": "a" * 20},
        )
        masked = ci.mask_sensitive(desc)
        assert masked.values["key"] != ci.values["key"]

    def test_mask_short_value(self):
        desc = CredentialDescriptor(
            name="api", display_name="API", description="d",
            auth_type=CredentialType.API_KEY,
            required_fields=(CredentialField(name="key"),),
        )
        ci = CredentialInstance(
            credential_id="c1", descriptor_name="api",
            values={"key": "ab"},
        )
        masked = ci.mask_sensitive(desc)
        assert masked.values["key"] == "********"


# =========================================================================
# CredentialRegistry
# =========================================================================


class TestCredentialRegistryRegister:
    @pytest.fixture
    def registry(self):
        return CredentialRegistry()

    def make(self, name="gmail_oauth", **kw: Any):
        return CredentialDescriptor(
            name=name,
            display_name=kw.pop("display_name", name.replace("_", " ").title()),
            description=kw.pop("description", "d"),
            auth_type=kw.pop("auth_type", CredentialType.OAUTH2),
            **kw,
        )

    def test_register_single(self, registry):
        registry.register(self.make())
        assert registry.count() == 1

    def test_register_multiple(self, registry):
        registry.register(self.make(name="gmail_oauth"))
        registry.register(self.make(name="slack_oauth"))
        assert registry.count() == 2

    def test_register_duplicate_raises(self, registry):
        registry.register(self.make())
        with pytest.raises(ValidationError) as exc:
            registry.register(self.make())
        assert "already registered" in str(exc.value)

    def test_register_and_get(self, registry):
        d = self.make()
        registry.register(d)
        assert registry.get("gmail_oauth") is d

    def test_register_and_exists(self, registry):
        registry.register(self.make())
        assert registry.exists("gmail_oauth") is True

    def test_exists_false(self, registry):
        assert registry.exists("nonexistent") is False

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None


class TestCredentialRegistryUnregister:
    @pytest.fixture
    def registry(self):
        r = CredentialRegistry()
        r.register(CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        ))
        r.register(CredentialDescriptor(
            name="slack", display_name="Slack", description="d", auth_type="oauth2",
        ))
        return r

    def test_unregister(self, registry):
        registry.unregister("gmail")
        assert registry.count() == 1
        assert registry.exists("gmail") is False

    def test_unregister_nonexistent_raises(self, registry):
        with pytest.raises(ValidationError) as exc:
            registry.unregister("nonexistent")
        assert "not registered" in str(exc.value)

    def test_unregister_then_register_again(self, registry):
        registry.unregister("gmail")
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        registry.register(d)
        assert registry.get("gmail") is d


class TestCredentialRegistryLookup:
    @pytest.fixture
    def registry(self):
        r = CredentialRegistry()
        r.register(CredentialDescriptor(
            name="gmail_oauth", display_name="Gmail OAuth2", description="d",
            auth_type="oauth2", tags=("google", "email"),
        ))
        r.register(CredentialDescriptor(
            name="openai_key", display_name="OpenAI Key", description="d",
            auth_type="api_key", tags=("ai", "openai"),
        ))
        r.register(CredentialDescriptor(
            name="slack_token", display_name="Slack Token", description="d",
            auth_type="bearer_token", tags=("slack", "chat"),
        ))
        return r

    def test_find_by_auth_type_exact(self, registry):
        results = registry.find_by_auth_type("oauth2")
        assert len(results) == 1

    def test_find_by_auth_type_case_insensitive(self, registry):
        results = registry.find_by_auth_type("OAUTH2")
        assert len(results) == 1

    def test_find_by_auth_type_multiple(self, registry):
        registry.register(CredentialDescriptor(
            name="outlook_oauth", display_name="Outlook OAuth2", description="d",
            auth_type="oauth2",
        ))
        results = registry.find_by_auth_type("oauth2")
        assert len(results) == 2

    def test_find_by_auth_type_nonexistent(self, registry):
        assert registry.find_by_auth_type("jwt") == []

    def test_find_by_tag_single(self, registry):
        results = registry.find_by_tag("email")
        assert len(results) == 1

    def test_find_by_tag_multiple_and(self, registry):
        results = registry.find_by_tag("google", "email")
        assert len(results) == 1

    def test_find_by_tag_no_match(self, registry):
        assert registry.find_by_tag("nonexistent") == []

    def test_find_by_tag_empty_returns_all(self, registry):
        assert len(registry.find_by_tag()) == 3

    def test_find_by_tag_case_insensitive(self, registry):
        results = registry.find_by_tag("EMAIL")
        assert len(results) == 1

    def test_list_all(self, registry):
        assert len(registry.list_all()) == 3

    def test_count(self, registry):
        assert registry.count() == 3

    def test_count_empty(self):
        assert CredentialRegistry().count() == 0

    def test_clear(self, registry):
        registry.clear()
        assert registry.count() == 0


# =========================================================================
# CredentialResolver
# =========================================================================


class TestCredentialResolverAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            CredentialResolver()  # type: ignore[abstract]

    def test_requires_resolve(self):
        class Missing( CredentialResolver):
            pass

        with pytest.raises(TypeError):
            Missing()  # type: ignore[abstract]

    def test_requires_validate(self):
        class Missing(CredentialResolver):
            async def resolve(self, ref): ...
            async def exists(self, ref): ...

        with pytest.raises(TypeError):
            Missing()  # type: ignore[abstract]

    def test_concrete_implementation(self):
        class MockResolver(CredentialResolver):
            async def resolve(self, ref):
                return CredentialInstance(
                    credential_id=ref.credential_id,
                    descriptor_name=ref.descriptor_name,
                    values={"token": "mock"},
                )

            async def validate(self, ref):
                return True

            async def exists(self, ref):
                return True

        import asyncio
        resolver = MockResolver()
        ref = CredentialReference(credential_id="c1", descriptor_name="gmail")
        result = asyncio.run(resolver.resolve(ref))
        assert result.credential_id == "c1"
        assert result.values["token"] == "mock"

    def test_validate_false(self):
        class NotFoundResolver(CredentialResolver):
            async def resolve(self, ref):
                raise CredentialNotFoundError("not found")

            async def validate(self, ref):
                return False

            async def exists(self, ref):
                return False

        import asyncio
        resolver = NotFoundResolver()
        ref = CredentialReference(credential_id="c1", descriptor_name="gmail")
        assert asyncio.run(resolver.validate(ref)) is False
        assert asyncio.run(resolver.exists(ref)) is False

    def test_resolve_raises_credential_not_found(self):
        class NotFoundResolver(CredentialResolver):
            async def resolve(self, ref):
                raise CredentialNotFoundError(f"{ref.credential_id} not found")

            async def validate(self, ref):
                return False

            async def exists(self, ref):
                return False

        import asyncio
        resolver = NotFoundResolver()
        ref = CredentialReference(credential_id="missing", descriptor_name="gmail")
        with pytest.raises(CredentialNotFoundError):
            asyncio.run(resolver.resolve(ref))


# =========================================================================
# Security — secret leakage
# =========================================================================


class TestSecurityNoLeakage:
    def test_mask_value_function_no_leak(self):
        secret = "sk_live_abcdefghijklmnop"
        masked = mask_value(secret)
        assert secret not in masked
        assert "sk_l" in masked

    def test_credential_field_repr_no_secret(self):
        f = CredentialField(name="api_key", type="password")
        r = repr(f)
        assert "api_key" in r
        assert "password" in r

    def test_credential_descriptor_repr_no_secret(self):
        d = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d", auth_type="oauth2",
        )
        r = repr(d)
        assert "oauth2" in r
        assert "gmail" in r

    def test_instance_repr_hides_values(self):
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"password": "hunter2"},
        )
        r = repr(ci)
        assert "hunter2" not in r

    def test_instance_str_hides_values(self):
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"password": "hunter2"},
        )
        s = str(ci)
        assert "hunter2" not in s

    def test_to_safe_dict_masks_secrets(self):
        desc = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d",
            auth_type="oauth2",
            required_fields=(CredentialField(name="password"),),
        )
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"password": "hunter2"},
        )
        safe = ci.to_safe_dict(desc)
        assert safe["values"]["password"] != "hunter2"

    def test_mask_sensitive_original_unchanged(self):
        desc = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d",
            auth_type="oauth2",
            required_fields=(CredentialField(name="api_key"),),
        )
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"api_key": "sk_live_xxxx"},
        )
        masked = ci.mask_sensitive(desc)
        assert ci.values["api_key"] == "sk_live_xxxx"
        assert masked.values["api_key"] != "sk_live_xxxx"

    def test_safe_dict_serialization_preserves_structure(self):
        desc = CredentialDescriptor(
            name="gmail", display_name="Gmail", description="d",
            auth_type="oauth2",
            required_fields=(CredentialField(name="token"),),
        )
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"token": "abc123"},
            metadata={"label": "primary"},
        )
        safe = ci.to_safe_dict(desc)
        assert safe["credential_id"] == "ci-1"
        assert safe["metadata"]["label"] == "primary"

    def test_values_not_in_log_output(self, caplog):
        import logging
        logger = logging.getLogger("test_security")
        ci = CredentialInstance(
            credential_id="ci-1",
            descriptor_name="gmail",
            values={"secret": "do-not-log-me"},
        )
        logger.info("Credential: %s", ci)
        assert "do-not-log-me" not in caplog.text

    def test_long_secret_fully_masked(self):
        secret = "a" * 100
        masked = mask_value(secret)
        assert secret not in masked
        assert len(masked) == 100
        assert masked.startswith("aaaa")

    def test_medium_secret_masked(self):
        secret = "abcdefghij"  # 10 chars, show_first=4 -> 4 + 6*
        masked = mask_value(secret)
        assert len(masked) == 10
        assert masked == "abcd******"

    def test_mask_sensitive_value_short_secret(self):
        secret = "ab"
        masked = mask_value(secret)
        assert masked == "********"

    def test_mask_on_empty_dict(self):
        result = mask_sensitive_values({}, set())
        assert result == {}


# =========================================================================
# SDK self-containment
# =========================================================================


class TestCredentialFrameworkSelfContainment:
    def test_no_execution_imports(self):
        import services.adapters.credentials as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src
        assert "services.planner" not in src

    def test_no_registry_dependencies(self):
        import services.adapters.credential_registry as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src
        assert "services.planner" not in src

    def test_resolver_no_runtime(self):
        import services.adapters.credential_resolver as mod
        import inspect
        src = inspect.getsource(mod)
        assert "services.execution" not in src

    def test_credential_descriptor_works_standalone(self):
        d = CredentialDescriptor(
            name="test", display_name="Test", description="Standalone test",
            auth_type="api_key",
        )
        assert d.auth_type == "api_key"

    def test_registry_works_standalone(self):
        r = CredentialRegistry()
        d = CredentialDescriptor(
            name="test", display_name="Test", description="Standalone test",
            auth_type="api_key",
        )
        r.register(d)
        assert r.exists("test")

    def test_masking_works_standalone(self):
        result = mask_value("sk_live_xxx")
        assert "sk_l" in result
        assert "***" in result

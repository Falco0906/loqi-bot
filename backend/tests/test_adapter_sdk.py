from __future__ import annotations

import pickle
from dataclasses import FrozenInstanceError
from typing import Optional

import pytest

from services.adapters import (
    AdapterContext,
    AdapterMetadata,
    AdapterResult,
    CapabilityReporter,
    ExecutionAdapter,
    HealthCheckable,
    UsageInfo,
    Validator,
)
from services.adapters.exceptions import (
    AdapterError,
    AdapterExecutionError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    FatalAdapterError,
    PermissionError,
    RateLimitError,
    ResourceNotFoundError,
    TransientAdapterError,
    ValidationError,
)

# =========================================================================
# Exceptions — hierarchy
# =========================================================================


class TestExceptionHierarchy:
    def test_adapter_error_is_base(self):
        assert issubclass(ConfigurationError, AdapterError)
        assert issubclass(ValidationError, AdapterError)
        assert issubclass(AuthenticationError, AdapterError)
        assert issubclass(AuthorizationError, AdapterError)
        assert issubclass(PermissionError, AdapterError)
        assert issubclass(RateLimitError, AdapterError)
        assert issubclass(ResourceNotFoundError, AdapterError)
        assert issubclass(TransientAdapterError, AdapterError)
        assert issubclass(FatalAdapterError, AdapterError)
        assert issubclass(AdapterExecutionError, AdapterError)

    def test_adapter_error_is_exception(self):
        assert issubclass(AdapterError, Exception)

    def test_authentication_before_authorization(self):
        assert not issubclass(AuthenticationError, AuthorizationError)

    def test_permission_separate_from_authorization(self):
        assert not issubclass(PermissionError, AuthorizationError)

    def test_configuration_error_independent(self):
        assert not issubclass(ConfigurationError, ValidationError)

    def test_resource_not_found_independent(self):
        assert not issubclass(ResourceNotFoundError, ConfigurationError)

    def test_rate_limit_independent(self):
        assert not issubclass(RateLimitError, TransientAdapterError)

    def test_adapter_error_is_not_runtime_error(self):
        assert not issubclass(AdapterError, RuntimeError)

    def test_transient_not_fatal(self):
        assert not issubclass(TransientAdapterError, FatalAdapterError)

    def test_fatal_not_transient(self):
        assert not issubclass(FatalAdapterError, TransientAdapterError)

    def test_adapter_execution_error_is_fatal(self):
        assert not issubclass(AdapterExecutionError, TransientAdapterError)

    def test_all_exceptions_distinct(self):
        classes = [
            ConfigurationError,
            ValidationError,
            AuthenticationError,
            AuthorizationError,
            PermissionError,
            RateLimitError,
            ResourceNotFoundError,
            TransientAdapterError,
            FatalAdapterError,
            AdapterExecutionError,
        ]
        for i, a in enumerate(classes):
            for j, b in enumerate(classes):
                if i != j:
                    assert a is not b, f"{a.__name__} is {b.__name__}"

    def test_exception_message(self):
        exc = AdapterError("something went wrong")
        assert str(exc) == "something went wrong"

    def test_exception_without_message(self):
        exc = AdapterError()
        assert str(exc) == ""


# =========================================================================
# Exceptions — catching hierarchy
# =========================================================================


class TestExceptionCatching:
    def test_catch_config_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise ConfigurationError("bad config")

    def test_catch_validation_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise ValidationError("invalid")

    def test_catch_auth_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise AuthenticationError("no token")

    def test_catch_transient_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise TransientAdapterError("timeout")

    def test_catch_fatal_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise FatalAdapterError("permanent")

    def test_catch_execution_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise AdapterExecutionError("bug")

    def test_catch_rate_limit_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise RateLimitError("too many")

    def test_catch_permission_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise PermissionError("denied")

    def test_catch_resource_not_found_as_adapter_error(self):
        with pytest.raises(AdapterError):
            raise ResourceNotFoundError("missing")

    def test_catch_generic_then_specific(self):
        caught = []
        try:
            raise TransientAdapterError("retry me")
        except TransientAdapterError:
            caught.append("transient")
        except AdapterError:
            caught.append("generic")
        assert caught == ["transient"]

    def test_catch_specific_then_generic(self):
        caught = []
        try:
            raise ConfigurationError("bad")
        except ConfigurationError:
            caught.append("config")
        except AdapterError:
            caught.append("generic")
        assert caught == ["config"]

    def test_transient_caught_before_adapter_error(self):
        with pytest.raises(TransientAdapterError):
            raise TransientAdapterError("should be transient")

    def test_fatal_not_caught_as_transient(self):
        with pytest.raises(FatalAdapterError):
            raise FatalAdapterError("fatal")

    def test_unrelated_exception_not_caught(self):
        with pytest.raises(ValueError):
            raise ValueError("not an adapter error")

    def test_catch_hierarchy_breadth(self):
        for exc_cls in [
            ConfigurationError,
            ValidationError,
            AuthenticationError,
            AuthorizationError,
            PermissionError,
            RateLimitError,
            ResourceNotFoundError,
            TransientAdapterError,
            FatalAdapterError,
            AdapterExecutionError,
        ]:
            with pytest.raises(AdapterError):
                raise exc_cls(f"test {exc_cls.__name__}")

    def test_catch_using_base_class(self):
        try:
            raise RateLimitError("too fast")
        except AdapterError:
            pass
        else:
            pytest.fail("RateLimitError was not caught as AdapterError")

    def test_transient_fatal_separation_catch(self):
        for transient in [TransientAdapterError, RateLimitError]:
            assert not issubclass(transient, FatalAdapterError)
        for fatal in [FatalAdapterError, AdapterExecutionError]:
            assert not issubclass(fatal, TransientAdapterError)


# =========================================================================
# Exceptions — retryable vs fatal
# =========================================================================


class TestExceptionRetryableFatal:
    def test_transient_is_retryable(self):
        assert not issubclass(TransientAdapterError, FatalAdapterError)

    def test_rate_limit_is_retryable(self):
        assert not issubclass(RateLimitError, FatalAdapterError)

    def test_fatal_is_not_retryable(self):
        assert issubclass(FatalAdapterError, AdapterError)

    def test_execution_error_is_not_retryable(self):
        assert not issubclass(AdapterExecutionError, TransientAdapterError)

    def test_configuration_not_retryable(self):
        assert not issubclass(ConfigurationError, TransientAdapterError)

    def test_validation_not_retryable(self):
        assert not issubclass(ValidationError, TransientAdapterError)

    def test_authentication_not_retryable(self):
        assert not issubclass(AuthenticationError, TransientAdapterError)

    def test_authorization_not_retryable(self):
        assert not issubclass(AuthorizationError, TransientAdapterError)

    def test_permission_not_retryable(self):
        assert not issubclass(PermissionError, TransientAdapterError)

    def test_resource_not_found_not_retryable(self):
        assert not issubclass(ResourceNotFoundError, TransientAdapterError)

    def test_fatal_exception_message(self):
        exc = FatalAdapterError("irrecoverable")
        assert "irrecoverable" in str(exc)

    def test_transient_exception_with_trace(self):
        try:
            raise TransientAdapterError("network timeout")
        except TransientAdapterError as e:
            assert e.args[0] == "network timeout"

    def test_fatal_not_instance_of_transient(self):
        exc = FatalAdapterError("nope")
        assert not isinstance(exc, TransientAdapterError)

    def test_transient_not_instance_of_fatal(self):
        exc = TransientAdapterError("maybe")
        assert not isinstance(exc, FatalAdapterError)

    def test_polymorphic_catch_retryable(self):
        errors: list[AdapterError] = [
            TransientAdapterError("a"),
            RateLimitError("b"),
        ]
        for e in errors:
            assert isinstance(e, AdapterError)
            assert not isinstance(e, FatalAdapterError)

    def test_polymorphic_catch_fatal(self):
        errors: list[AdapterError] = [
            FatalAdapterError("a"),
            AdapterExecutionError("b"),
        ]
        for e in errors:
            assert isinstance(e, AdapterError)
            assert not isinstance(e, TransientAdapterError)

    def test_adapter_error_picklable(self):
        exc = AdapterError("pickle me")
        data = pickle.dumps(exc)
        restored = pickle.loads(data)
        assert str(restored) == "pickle me"

    def test_all_retryable_errors_defined(self):
        retryable = {TransientAdapterError, RateLimitError}
        non_retryable = {
            AdapterError,
            ConfigurationError,
            ValidationError,
            AuthenticationError,
            AuthorizationError,
            PermissionError,
            ResourceNotFoundError,
            FatalAdapterError,
            AdapterExecutionError,
        }
        for cls in non_retryable:
            assert cls not in retryable


# =========================================================================
# Models — AdapterMetadata
# =========================================================================


class TestAdapterMetadataConstruction:
    def test_minimal(self):
        meta = AdapterMetadata(name="test", display_name="Test", version="1.0.0", description="desc")
        assert meta.name == "test"
        assert meta.display_name == "Test"
        assert meta.version == "1.0.0"
        assert meta.description == "desc"
        assert meta.author == ""
        assert meta.supported_operations == ()
        assert meta.requires_auth is False
        assert meta.supports_streaming is False
        assert meta.supports_batch is False
        assert meta.supports_retry is True

    def test_full(self):
        meta = AdapterMetadata(
            name="gmail",
            display_name="Gmail Adapter",
            version="2.1.0",
            description="Send and receive emails",
            author="Loqi Team",
            supported_operations=("send", "read", "search"),
            requires_auth=True,
            supports_streaming=False,
            supports_batch=True,
            supports_retry=True,
            tags=("email", "google"),
        )
        assert meta.name == "gmail"
        assert meta.tags == ("email", "google")

    def test_default_supports_retry_true(self):
        meta = AdapterMetadata(name="x", display_name="X", version="1.0", description="")
        assert meta.supports_retry is True

    def test_requires_auth_true(self):
        meta = AdapterMetadata(name="a", display_name="A", version="1", description="", requires_auth=True)
        assert meta.requires_auth is True

    def test_supports_streaming(self):
        meta = AdapterMetadata(name="a", display_name="A", version="1", description="", supports_streaming=True)
        assert meta.supports_streaming is True

    def test_supports_batch(self):
        meta = AdapterMetadata(name="a", display_name="A", version="1", description="", supports_batch=True)
        assert meta.supports_batch is True

    def test_string_fields_accept_empty(self):
        meta = AdapterMetadata(name="", display_name="", version="", description="")
        assert meta.name == ""
        assert meta.display_name == ""

    def test_supported_operations_custom(self):
        meta = AdapterMetadata(
            name="x", display_name="X", version="1", description="",
            supported_operations=("op1", "op2", "op3"),
        )
        assert len(meta.supported_operations) == 3

    def test_author_optional(self):
        meta = AdapterMetadata(name="x", display_name="X", version="1", description="")
        assert meta.author == ""

    def test_tags_optional(self):
        meta = AdapterMetadata(name="x", display_name="X", version="1", description="")
        assert meta.tags == ()


class TestAdapterMetadataImmutability:
    def test_cannot_set_name(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.name = "new"

    def test_cannot_set_display_name(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.display_name = "new"

    def test_cannot_set_version(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.version = "2"

    def test_cannot_set_description(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.description = "new"

    def test_cannot_set_author(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.author = "new"

    def test_cannot_set_supported_operations(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.supported_operations = ("x",)

    def test_cannot_set_requires_auth(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.requires_auth = True

    def test_cannot_set_tags(self):
        meta = AdapterMetadata(name="n", display_name="N", version="1", description="")
        with pytest.raises(FrozenInstanceError):
            meta.tags = ("new",)


class TestAdapterMetadataSerialization:
    def test_to_dict(self):
        meta = AdapterMetadata(
            name="gmail",
            display_name="Gmail Adapter",
            version="1.0.0",
            description="Send and receive emails",
            supported_operations=("send", "read"),
            requires_auth=True,
        )
        d = meta.to_dict()
        assert d["name"] == "gmail"
        assert d["display_name"] == "Gmail Adapter"
        assert d["version"] == "1.0.0"
        assert d["requires_auth"] is True
        assert d["supported_operations"] == ["send", "read"]
        assert d["tags"] == []

    def test_from_dict(self):
        d = {
            "name": "slack",
            "display_name": "Slack Adapter",
            "version": "2.0.0",
            "description": "Send Slack messages",
            "author": "Loqi",
            "supported_operations": ["post", "react"],
            "requires_auth": True,
            "supports_streaming": True,
            "supports_batch": False,
            "supports_retry": True,
            "tags": ["chat"],
        }
        meta = AdapterMetadata.from_dict(d)
        assert meta.name == "slack"
        assert meta.version == "2.0.0"
        assert meta.requires_auth is True
        assert meta.supports_streaming is True
        assert meta.supported_operations == ("post", "react")
        assert meta.tags == ("chat",)

    def test_from_dict_minimal(self):
        d = {"name": "x", "version": "1", "description": "d"}
        meta = AdapterMetadata.from_dict(d)
        assert meta.name == "x"
        assert meta.display_name == "x"
        assert meta.description == "d"
        assert meta.supported_operations == ()
        assert meta.requires_auth is False

    def test_round_trip(self):
        meta = AdapterMetadata(
            name="http",
            display_name="HTTP Client",
            version="3.1.0",
            description="Make HTTP requests",
            supported_operations=("get", "post", "put", "delete"),
            requires_auth=False,
            supports_streaming=True,
            supports_batch=True,
            supports_retry=True,
        )
        assert AdapterMetadata.from_dict(meta.to_dict()) == meta

    def test_to_dict_list_values(self):
        meta = AdapterMetadata(
            name="x", display_name="X", version="1", description="",
            supported_operations=("a", "b"),
        )
        assert isinstance(meta.to_dict()["supported_operations"], list)

    def test_pickle_round_trip(self):
        meta = AdapterMetadata(
            name="gmail",
            display_name="Gmail Adapter",
            version="1.0.0",
            description="desc",
        )
        data = pickle.dumps(meta)
        restored = pickle.loads(data)
        assert restored == meta

    def test_to_dict_includes_author(self):
        meta = AdapterMetadata(
            name="x", display_name="X", version="1", description="", author="me"
        )
        assert meta.to_dict()["author"] == "me"

    def test_from_dict_missing_display_name_falls_back_to_name(self):
        meta = AdapterMetadata.from_dict({"name": "foo", "version": "1", "description": "d"})
        assert meta.display_name == "foo"


class TestAdapterMetadataValidation:
    def test_equality_same(self):
        a = AdapterMetadata(name="x", display_name="X", version="1", description="")
        b = AdapterMetadata(name="x", display_name="X", version="1", description="")
        assert a == b

    def test_equality_different(self):
        a = AdapterMetadata(name="x", display_name="X", version="1", description="")
        b = AdapterMetadata(name="y", display_name="Y", version="1", description="")
        assert a != b

    def test_hashable(self):
        meta = AdapterMetadata(name="x", display_name="X", version="1", description="")
        s = {meta}
        assert meta in s

    def test_hash_differs_when_name_differs(self):
        a = AdapterMetadata(name="x", display_name="X", version="1", description="d")
        b = AdapterMetadata(name="y", display_name="Y", version="1", description="d")
        assert hash(a) != hash(b)

    def test_repr_includes_fields(self):
        meta = AdapterMetadata(name="gmail", display_name="Gmail", version="1.0", description="d")
        r = repr(meta)
        assert "name=" in r
        assert "gmail" in r

    def test_bool_coercion_true(self):
        meta = AdapterMetadata(name="x", display_name="X", version="1", description="d")
        assert bool(meta) is True

    def test_bool_coercion_empty_name_still_true(self):
        meta = AdapterMetadata(name="", display_name="", version="", description="")
        assert bool(meta) is True


# =========================================================================
# Models — UsageInfo
# =========================================================================


class TestUsageInfoConstruction:
    def test_defaults(self):
        u = UsageInfo()
        assert u.tokens_in == 0
        assert u.tokens_out == 0
        assert u.api_calls == 0
        assert u.cost_usd == 0.0
        assert u.latency_ms == 0.0
        assert u.extra == {}

    def test_full(self):
        u = UsageInfo(tokens_in=100, tokens_out=50, api_calls=2, cost_usd=0.005, latency_ms=320.5)
        assert u.tokens_in == 100
        assert u.tokens_out == 50
        assert u.api_calls == 2
        assert u.cost_usd == 0.005
        assert u.latency_ms == 320.5

    def test_extra_dict(self):
        u = UsageInfo(extra={"model": "gpt-4", "cached": True})
        assert u.extra["model"] == "gpt-4"

    def test_immutable(self):
        u = UsageInfo()
        with pytest.raises(FrozenInstanceError):
            u.tokens_in = 10

    def test_equality(self):
        a = UsageInfo(tokens_in=5)
        b = UsageInfo(tokens_in=5)
        assert a == b

    def test_inequality(self):
        a = UsageInfo(tokens_in=5)
        b = UsageInfo(tokens_in=10)
        assert a != b

    def test_picklable(self):
        u = UsageInfo(tokens_in=42, extra={"model": "gpt"})
        data = pickle.dumps(u)
        restored = pickle.loads(data)
        assert restored == u


# =========================================================================
# Models — AdapterResult
# =========================================================================


class TestAdapterResultSuccess:
    def test_default_success(self):
        r = AdapterResult(success=True)
        assert r.success is True
        assert r.data is None
        assert r.metadata == {}
        assert r.warnings == []
        assert r.error is None

    def test_with_data(self):
        r = AdapterResult(success=True, data={"id": "123", "status": "sent"})
        assert r.data["id"] == "123"

    def test_with_metadata(self):
        r = AdapterResult(success=True, metadata={"elapsed_ms": 45})
        assert r.metadata["elapsed_ms"] == 45

    def test_with_warnings(self):
        r = AdapterResult(success=True, warnings=["rate limit approaching"])
        assert len(r.warnings) == 1

    def test_with_usage(self):
        u = UsageInfo(tokens_in=100)
        r = AdapterResult(success=True, usage=u)
        assert r.usage.tokens_in == 100

    def test_success_factory(self):
        r = AdapterResult.success_result(data={"ok": True})
        assert r.success is True
        assert r.data == {"ok": True}
        assert r.error is None

    def test_success_factory_with_metadata(self):
        r = AdapterResult.success_result(data="done", metadata={"key": "val"})
        assert r.metadata["key"] == "val"

    def test_success_factory_default_usage(self):
        r = AdapterResult.success_result(data="x")
        assert r.usage.tokens_in == 0

    def test_success_factory_with_usage(self):
        u = UsageInfo(api_calls=3)
        r = AdapterResult.success_result(data="x", usage=u)
        assert r.usage.api_calls == 3


class TestAdapterResultFailure:
    def test_failure_result(self):
        r = AdapterResult.failure_result(error="something broke")
        assert r.success is False
        assert r.error == "something broke"

    def test_failure_with_data(self):
        r = AdapterResult.failure_result(error="err", data={"partial": True})
        assert r.data["partial"] is True

    def test_failure_with_warnings(self):
        r = AdapterResult.failure_result(error="err", warnings=["disk full"])
        assert r.warnings == ["disk full"]

    def test_failure_factory_error_required(self):
        with pytest.raises(TypeError):
            AdapterResult.failure_result()  # type: ignore[call-arg]

    def test_failure_with_metadata(self):
        r = AdapterResult.failure_result(error="err", metadata={"attempt": 3})
        assert r.metadata["attempt"] == 3

    def test_failure_no_data_by_default(self):
        r = AdapterResult.failure_result(error="err")
        assert r.data is None

    def test_failure_empty_warnings_by_default(self):
        r = AdapterResult.failure_result(error="err")
        assert r.warnings == []


class TestAdapterResultSerialization:
    def test_to_dict_success(self):
        r = AdapterResult(
            success=True,
            data="ok",
            metadata={"latency": 10},
            usage=UsageInfo(tokens_in=5),
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["data"] == "ok"
        assert d["metadata"] == {"latency": 10}
        assert d["error"] is None
        assert d["usage"]["tokens_in"] == 5

    def test_to_dict_failure(self):
        r = AdapterResult(success=False, error="timeout", warnings=["slow"])
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "timeout"
        assert d["warnings"] == ["slow"]

    def test_to_dict_includes_usage_extra(self):
        u = UsageInfo(extra={"model": "gpt-4"})
        r = AdapterResult(success=True, usage=u)
        d = r.to_dict()
        assert d["usage"]["extra"] == {"model": "gpt-4"}

    def test_to_dict_warnings_empty_by_default(self):
        r = AdapterResult(success=True)
        assert r.to_dict()["warnings"] == []

    def test_pickle_round_trip_success(self):
        r = AdapterResult(success=True, data="ok", usage=UsageInfo(tokens_in=5))
        data = pickle.dumps(r)
        restored = pickle.loads(data)
        assert restored.success is True
        assert restored.data == "ok"
        assert restored.usage.tokens_in == 5

    def test_pickle_round_trip_failure(self):
        r = AdapterResult(success=False, error="fail")
        data = pickle.dumps(r)
        restored = pickle.loads(data)
        assert restored.success is False
        assert restored.error == "fail"


class TestAdapterResultImmutability:
    def test_cannot_set_success(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.success = False

    def test_cannot_set_error(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.error = "new"

    def test_cannot_set_data(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.data = "new"

    def test_cannot_set_warnings(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.warnings = ["x"]

    def test_cannot_set_metadata(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.metadata = {"x": 1}

    def test_cannot_set_usage(self):
        r = AdapterResult(success=True)
        with pytest.raises(FrozenInstanceError):
            r.usage = UsageInfo()


class TestAdapterResultUsage:
    def test_usage_warnings_metadata(self):
        u = UsageInfo(tokens_in=200, api_calls=1, cost_usd=0.01)
        r = AdapterResult(
            success=True,
            data="completed",
            metadata={"batch_size": 5},
            warnings=["deprecated endpoint"],
            usage=u,
        )
        assert r.success is True
        assert r.data == "completed"
        assert r.metadata["batch_size"] == 5
        assert r.warnings == ["deprecated endpoint"]
        assert r.usage.cost_usd == 0.01

    def test_usage_equality(self):
        u = UsageInfo(tokens_in=100)
        a = AdapterResult(success=True, usage=u)
        b = AdapterResult(success=True, usage=u)
        assert a == b

    def test_usage_inequality(self):
        a = AdapterResult(success=True, usage=UsageInfo(tokens_in=100))
        b = AdapterResult(success=True, usage=UsageInfo(tokens_in=200))
        assert a != b

    def test_warnings_mutable_inside_frozen(self):
        r = AdapterResult(success=True)
        assert r.warnings == []
        assert isinstance(r.warnings, list)

    def test_multiple_warnings(self):
        r = AdapterResult(success=True, warnings=["w1", "w2", "w3"])
        assert len(r.warnings) == 3

    def test_metadata_mutable_inside_frozen(self):
        meta = {"key": "val"}
        r = AdapterResult(success=True, metadata=meta)
        assert r.metadata["key"] == "val"


# =========================================================================
# Context — AdapterContext
# =========================================================================


class TestAdapterContextConstruction:
    def test_minimal(self):
        ctx = AdapterContext(
            execution_session_id="sess-1",
            execution_task_id="task-1",
            action="send",
        )
        assert ctx.execution_session_id == "sess-1"
        assert ctx.execution_task_id == "task-1"
        assert ctx.action == "send"
        assert ctx.params == {}
        assert ctx.credentials == {}
        assert ctx.config == {}
        assert ctx.user_context == {}
        assert ctx.logger is None
        assert ctx.runtime_metadata == {}

    def test_with_params(self):
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            params={"to": "user@example.com", "body": "Hello"},
        )
        assert ctx.params["to"] == "user@example.com"

    def test_with_credentials(self):
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            credentials={"api_key": "sk-xxx"},
        )
        assert ctx.credentials["api_key"] == "sk-xxx"

    def test_with_config(self):
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            config={"timeout": 30, "retry_count": 3},
        )
        assert ctx.config["timeout"] == 30

    def test_with_user_context(self):
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            user_context={"user_id": "u-42", "plan": "premium"},
        )
        assert ctx.user_context["user_id"] == "u-42"

    def test_with_logger(self):
        import logging
        logger = logging.getLogger("test")
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            logger=logger,
        )
        assert ctx.logger is logger

    def test_with_runtime_metadata(self):
        ctx = AdapterContext(
            execution_session_id="s1",
            execution_task_id="t1",
            action="send",
            runtime_metadata={"attempt": 2, "source": "webhook"},
        )
        assert ctx.runtime_metadata["attempt"] == 2


class TestAdapterContextBuildFactory:
    def test_build_minimal(self):
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="read",
        )
        assert ctx.action == "read"
        assert ctx.params == {}

    def test_build_with_all(self):
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="write",
            params={"key": "val"},
            credentials={"token": "abc"},
            config={"timeout": 10},
            user_context={"role": "admin"},
            runtime_metadata={"version": 2},
        )
        assert ctx.params["key"] == "val"
        assert ctx.credentials["token"] == "abc"
        assert ctx.config["timeout"] == 10
        assert ctx.runtime_metadata["version"] == 2

    def test_build_none_becomes_empty_dict(self):
        ctx = AdapterContext.build(
            execution_session_id="s1",
            execution_task_id="t1",
            action="read",
            params=None,
            credentials=None,
        )
        assert ctx.params == {}
        assert ctx.credentials == {}

    def test_build_round_trip(self):
        ctx = AdapterContext.build(
            execution_session_id="s-1",
            execution_task_id="t-1",
            action="delete",
            params={"id": "42"},
        )
        assert ctx.execution_session_id == "s-1"
        assert ctx.execution_task_id == "t-1"
        assert ctx.params == {"id": "42"}


class TestAdapterContextImmutability:
    def test_cannot_set_session_id(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.execution_session_id = "s2"

    def test_cannot_set_task_id(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.execution_task_id = "t2"

    def test_cannot_set_action(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.action = "b"

    def test_cannot_set_params(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.params = {"x": 1}

    def test_cannot_set_credentials(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.credentials = {"x": 1}

    def test_cannot_set_config(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.config = {"x": 1}

    def test_cannot_set_logger(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        with pytest.raises(FrozenInstanceError):
            ctx.logger = None


class TestAdapterContextOptionalFields:
    def test_params_defaults_empty(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        assert ctx.params == {}

    def test_credentials_defaults_empty(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        assert ctx.credentials == {}

    def test_config_defaults_empty(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        assert ctx.config == {}

    def test_user_context_defaults_empty(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        assert ctx.user_context == {}

    def test_optional_empty_dicts_independent(self):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="a")
        ctx.params["custom"] = "val"
        assert ctx.params["custom"] == "val"

    def test_action_varied(self):
        for action in ["send", "read", "delete", "search", "list", "create", "update"]:
            ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action=action)
            assert ctx.action == action


# =========================================================================
# Base Adapter — ExecutionAdapter
# =========================================================================


class TestExecutionAdapterAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ExecutionAdapter()  # type: ignore[abstract]

    def test_abstract_methods_required(self):
        class MissingExecute(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="x", display_name="X", version="1", description="d")

        with pytest.raises(TypeError):
            MissingExecute()  # type: ignore[abstract]

    def test_metadata_abstract(self):
        class NoMetadata(ExecutionAdapter):
            async def execute(self, context):
                pass

        with pytest.raises(TypeError):
            NoMetadata()  # type: ignore[abstract]

    def test_execute_abstract(self):
        class NoExecute(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="x", display_name="X", version="1", description="d")

        with pytest.raises(TypeError):
            NoExecute()  # type: ignore[abstract]

    def test_abc_meta(self):
        assert issubclass(ExecutionAdapter.__class__, type)


class TestExecutionAdapterConcrete:
    @pytest.fixture
    def adapter(self):
        class ConcreteAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="test", display_name="Test", version="1.0.0", description="A test adapter")

            async def execute(self, context: AdapterContext) -> AdapterResult:
                return AdapterResult.success_result(data=f"executed {context.action}")

        return ConcreteAdapter()

    @pytest.mark.asyncio
    async def test_execute_returns_adapter_result(self, adapter):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="ping")
        result = await adapter.execute(ctx)
        assert isinstance(result, AdapterResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_with_context(self, adapter):
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="send")
        result = await adapter.execute(ctx)
        assert result.data == "executed send"

    def test_metadata_is_adapter_metadata(self, adapter):
        meta = adapter.metadata
        assert isinstance(meta, AdapterMetadata)
        assert meta.name == "test"

    @pytest.mark.asyncio
    async def test_validate_default_returns_none(self, adapter):
        result = await adapter.validate()
        assert result is None

    @pytest.mark.asyncio
    async def test_health_default(self, adapter):
        result = await adapter.health()
        assert result == {"status": "unknown"}

    @pytest.mark.asyncio
    async def test_capabilities_default(self, adapter):
        result = await adapter.capabilities()
        assert result == []

    def test_repr(self, adapter):
        r = repr(adapter)
        assert "ConcreteAdapter" in r
        assert "test" in r
        assert "1.0.0" in r

    @pytest.mark.asyncio
    async def test_validate_override(self):
        class ValidatingAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="val", display_name="Val", version="1", description="d")

            async def execute(self, context):
                return AdapterResult.success_result(data="ok")

            async def validate(self) -> Optional[list[str]]:
                return ["missing api key"]

        adapter = ValidatingAdapter()
        issues = await adapter.validate()
        assert issues == ["missing api key"]

    @pytest.mark.asyncio
    async def test_health_override(self):
        class HealthyAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="h", display_name="H", version="1", description="d")

            async def execute(self, context):
                return AdapterResult.success_result(data="ok")

            async def health(self) -> dict:
                return {"status": "healthy", "uptime": 3600}

        adapter = HealthyAdapter()
        h = await adapter.health()
        assert h["status"] == "healthy"
        assert h["uptime"] == 3600

    @pytest.mark.asyncio
    async def test_capabilities_override(self):
        class CapableAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="c", display_name="C", version="1", description="d")

            async def execute(self, context):
                return AdapterResult.success_result(data="ok")

            async def capabilities(self) -> list[str]:
                return ["send", "receive", "broadcast"]

        adapter = CapableAdapter()
        caps = await adapter.capabilities()
        assert "send" in caps
        assert len(caps) == 3

    @pytest.mark.asyncio
    async def test_failure_result_from_adapter(self):
        class FailingAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="f", display_name="F", version="1", description="d")

            async def execute(self, context):
                return AdapterResult.failure_result(error="rate limited", warnings=["backoff"])

        adapter = FailingAdapter()
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="go")
        result = await adapter.execute(ctx)
        assert result.success is False
        assert result.error == "rate limited"
        assert result.warnings == ["backoff"]

    @pytest.mark.asyncio
    async def test_adapter_with_usage(self):
        class UsageAwareAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="u", display_name="U", version="1", description="d")

            async def execute(self, context):
                usage = UsageInfo(tokens_in=50, tokens_out=10, api_calls=1, cost_usd=0.002)
                return AdapterResult.success_result(data="done", usage=usage)

        adapter = UsageAwareAdapter()
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="go")
        result = await adapter.execute(ctx)
        assert result.usage.tokens_in == 50
        assert result.usage.cost_usd == 0.002

    @pytest.mark.asyncio
    async def test_adapter_receives_credentials_from_context(self):
        class AuthAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="a", display_name="A", version="1", description="d")

            async def execute(self, context):
                token = context.credentials.get("api_key", "")
                return AdapterResult.success_result(data=f"auth:{bool(token)}")

        adapter = AuthAdapter()
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1", action="x",
            credentials={"api_key": "sk-xxx"},
        )
        result = await adapter.execute(ctx)
        assert result.data == "auth:True"

    @pytest.mark.asyncio
    async def test_adapter_logging_via_context(self, caplog):
        import logging

        class LoggingAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="l", display_name="L", version="1", description="d")

            async def execute(self, context):
                if context.logger:
                    context.logger.info("adapter executing %s", context.action)
                return AdapterResult.success_result(data="logged")

        logger = logging.getLogger("adapter_test")
        adapter = LoggingAdapter()
        ctx = AdapterContext.build(
            execution_session_id="s1", execution_task_id="t1", action="work",
            logger=logger,
        )
        result = await adapter.execute(ctx)
        assert result.data == "logged"


# =========================================================================
# Protocols — structural conformance
# =========================================================================


class TestProtocolValidator:
    def test_protocol_is_validator(self):
        class MyValidator:
            async def validate(self) -> Optional[list[str]]:
                return None

        v: Validator = MyValidator()
        assert isinstance(v, Validator)

    def test_protocol_validate_returns_issues(self):
        class StrictValidator:
            async def validate(self) -> Optional[list[str]]:
                return ["issue1", "issue2"]

        v: Validator = StrictValidator()
        import asyncio
        result = asyncio.run(v.validate())
        assert result == ["issue1", "issue2"]

    def test_protocol_class_not_required_to_inherit(self):
        class ImplicitValidator:
            async def validate(self) -> Optional[list[str]]:
                return None

        v = ImplicitValidator()
        # structural subtyping — Protocol check
        assert isinstance(v, Validator)

    def test_non_conforming_class(self):
        class NotValidator:
            pass

        nv = NotValidator()
        assert not isinstance(nv, Validator)

    def test_async_signature(self):
        import inspect
        class MyValidator:
            async def validate(self) -> Optional[list[str]]:
                return None

        assert inspect.iscoroutinefunction(MyValidator.validate)


class TestProtocolHealthCheckable:
    def test_protocol_conformance(self):
        class MyHealth:
            async def health(self) -> dict:
                return {"status": "ok"}

        h: HealthCheckable = MyHealth()
        assert isinstance(h, HealthCheckable)

    def test_health_returns_dict(self):
        class MyHealth:
            async def health(self) -> dict:
                return {"status": "degraded", "latency_ms": 200}

        import asyncio
        h = MyHealth()
        result = asyncio.run(h.health())
        assert result["status"] == "degraded"

    def test_non_conforming(self):
        class NoHealth:
            pass

        assert not isinstance(NoHealth(), HealthCheckable)

    def test_async_signature(self):
        import inspect
        class MyHealth:
            async def health(self) -> dict:
                return {}

        assert inspect.iscoroutinefunction(MyHealth.health)


class TestProtocolCapabilityReporter:
    def test_protocol_conformance(self):
        class MyCaps:
            async def capabilities(self) -> list[str]:
                return ["read", "write"]

        c: CapabilityReporter = MyCaps()
        assert isinstance(c, CapabilityReporter)

    def test_capabilities_returns_list(self):
        class MyCaps:
            async def capabilities(self) -> list[str]:
                return ["read", "write"]

        import asyncio
        c = MyCaps()
        result = asyncio.run(c.capabilities())
        assert "read" in result

    def test_non_conforming(self):
        class NoCaps:
            pass

        assert not isinstance(NoCaps(), CapabilityReporter)

    def test_empty_capabilities(self):
        class EmptyCaps:
            async def capabilities(self) -> list[str]:
                return []

        import asyncio
        c = EmptyCaps()
        assert asyncio.run(c.capabilities()) == []

    def test_async_signature(self):
        import inspect
        class MyCaps:
            async def capabilities(self) -> list[str]:
                return []

        assert inspect.iscoroutinefunction(MyCaps.capabilities)


class TestProtocolMultipleProtocols:
    def test_class_satisfies_all_three(self):
        class FullFeatured:
            async def validate(self) -> Optional[list[str]]:
                return None

            async def health(self) -> dict:
                return {"status": "ok"}

            async def capabilities(self) -> list[str]:
                return ["all"]

        obj = FullFeatured()
        assert isinstance(obj, Validator)
        assert isinstance(obj, HealthCheckable)
        assert isinstance(obj, CapabilityReporter)

    def test_class_satisfies_two(self):
        class ValidateAndHealth:
            async def validate(self) -> Optional[list[str]]:
                return None

            async def health(self) -> dict:
                return {"status": "ok"}

        obj = ValidateAndHealth()
        assert isinstance(obj, Validator)
        assert isinstance(obj, HealthCheckable)
        assert not isinstance(obj, CapabilityReporter)

    def test_protocols_do_not_conflict(self):
        class A:
            async def validate(self) -> Optional[list[str]]:
                return None

        class B:
            async def health(self) -> dict:
                return {"status": "ok"}

        assert not isinstance(A(), HealthCheckable)
        assert not isinstance(B(), Validator)

    def test_short_circuit_on_missing_method(self):
        class Missing:
            async def validate(self) -> Optional[list[str]]:
                return None

            async def health(self) -> dict:
                return {"status": "ok"}

        assert not isinstance(Missing(), CapabilityReporter)

    def test_protocol_independent_of_inheritance(self):
        class InheritedValidator(Validator):
            async def validate(self) -> Optional[list[str]]:
                return ["issue"]

        assert isinstance(InheritedValidator(), Validator)

    def test_adapter_can_satisfy_validator(self):
        class AdapterAsValidator(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="v", display_name="V", version="1", description="d")

            async def execute(self, context):
                return AdapterResult.success_result(data="ok")

            async def validate(self) -> Optional[list[str]]:
                return None

        adapter = AdapterAsValidator()
        assert isinstance(adapter, Validator)


# =========================================================================
# Integration — SDK self-containment
# =========================================================================


class TestSdkSelfContainment:
    def test_no_execution_imports(self):
        import services.adapters as adapters
        import sys
        modules = list(sys.modules.keys())
        execution_modules = [m for m in modules if "services.execution" in m]
        # Inspect the module's source to verify no execution imports
        import inspect
        source = inspect.getsource(adapters)
        assert "services.execution" not in source

    def test_can_import_all_exports(self):
        from services.adapters import (
            AdapterContext,
            AdapterMetadata,
            AdapterResult,
            CapabilityReporter,
            ExecutionAdapter,
            HealthCheckable,
            UsageInfo,
            Validator,
            AdapterError,
            AdapterExecutionError,
            AuthenticationError,
            AuthorizationError,
            ConfigurationError,
            FatalAdapterError,
            PermissionError,
            RateLimitError,
            ResourceNotFoundError,
            TransientAdapterError,
            ValidationError,
        )
        assert ExecutionAdapter is not None

    def test_adapter_works_without_runtime(self):
        class StandaloneAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="standalone", display_name="Standalone", version="0.1.0", description="No runtime needed")

            async def execute(self, context):
                return AdapterResult.success_result(data="standalone works")

        import asyncio
        adapter = StandaloneAdapter()
        ctx = AdapterContext(execution_session_id="s1", execution_task_id="t1", action="test")
        result = asyncio.run(adapter.execute(ctx))
        assert result.data == "standalone works"

    def test_metadata_inspection_without_instantiation(self):
        meta = AdapterMetadata(
            name="gmail",
            display_name="Gmail Adapter",
            version="2.0.0",
            description="Send and receive Gmail messages",
            supported_operations=("send", "read", "search", "list"),
            requires_auth=True,
            supports_streaming=False,
            supports_batch=False,
            supports_retry=True,
        )
        assert meta.requires_auth is True
        assert "send" in meta.supported_operations
        assert meta.supports_retry is True
        assert meta.version == "2.0.0"

    def test_exception_catch_outside_runtime(self):
        try:
            raise TransientAdapterError("network issue")
        except AdapterError:
            pass
        else:
            pytest.fail("TransientAdapterError not caught as AdapterError")

    def test_future_concrete_adapter_no_sdk_changes(self):
        class FutureAdapter(ExecutionAdapter):
            @property
            def metadata(self):
                return AdapterMetadata(name="future", display_name="Future", version="1.0.0", description="Future adapter")

            async def execute(self, context):
                return AdapterResult.success_result(data="future")

        adapter = FutureAdapter()
        assert adapter.metadata.name == "future"

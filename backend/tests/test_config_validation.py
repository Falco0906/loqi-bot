"""PR10.2 — environment/configuration validation tests.

Uses a plain dict as the environment (no real credentials, no secrets).
Every error must reference only the config key, never the value.
"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.config_validation import (
    is_production,
    validate_config,
    assert_valid_startup_config,
)


VALID_PRODUCTION = {
    "ENVIRONMENT": "production",
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_KEY": "service-key",
    "OPENAI_API_KEY": "sk-test",
    "GOOGLE_CLIENT_ID": "client",
    "GOOGLE_CLIENT_SECRET": "secret",
    "PORT": "10000",
    "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
}


def _errors(env):
    errors, _ = validate_config(env)
    return errors


class TestProductionRequired:
    def test_missing_required_fails_with_key_name(self):
        env = {**VALID_PRODUCTION}
        del env["SUPABASE_URL"]
        errors = _errors(env)
        assert any("SUPABASE_URL" in error for error in errors)

    def test_valid_production_has_no_errors(self):
        assert _errors(VALID_PRODUCTION) == []

    def test_secrets_never_appear_in_errors(self):
        env = {**VALID_PRODUCTION, "OPENAI_API_KEY": "", "SUPABASE_KEY": "super-secret-value"}
        errors = _errors(env)
        for error in errors:
            assert "super-secret-value" not in error
            assert "sk-test" not in error


class TestFormatValidation:
    def test_invalid_url(self):
        env = {**VALID_PRODUCTION, "SUPABASE_URL": "not-a-url"}
        assert any("SUPABASE_URL" in e for e in _errors(env))

    def test_invalid_port(self):
        env = {**VALID_PRODUCTION, "PORT": "abc"}
        assert any("PORT" in e for e in _errors(env))

    def test_out_of_range_port(self):
        env = {**VALID_PRODUCTION, "PORT": "99999"}
        assert any("PORT" in e for e in _errors(env))

    def test_invalid_interval(self):
        env = {**VALID_PRODUCTION, "INBOX_SYNC_INTERVAL_SECONDS": "-5"}
        assert any("INBOX_SYNC_INTERVAL_SECONDS" in e for e in _errors(env))

    def test_invalid_boolean(self):
        env = {**VALID_PRODUCTION, "SIMULATE_REPLIES": "maybe"}
        assert any("SIMULATE_REPLIES" in e for e in _errors(env))

    def test_known_boolean_values_accepted(self):
        # Use development so safety checks don't mask format validation.
        base = {"ENVIRONMENT": "development", "PORT": "10000"}
        for value in ("true", "false", "1", "0", "on", "off", "yes", "no"):
            env = {**base, "SIMULATE_REPLIES": value}
            assert all("SIMULATE_REPLIES" not in e for e in _errors(env))

    def test_unknown_lead_provider(self):
        env = {**VALID_PRODUCTION, "LEAD_PROVIDER": "nonexistent"}
        assert any("LEAD_PROVIDER" in e for e in _errors(env))

    def test_unknown_email_provider(self):
        env = {**VALID_PRODUCTION, "EMAIL_PROVIDER": "mailchimp"}
        assert any("EMAIL_PROVIDER" in e for e in _errors(env))


class TestProductionSafety:
    def test_test_recipient_override_forbidden_in_production(self):
        env = {**VALID_PRODUCTION, "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE": "true"}
        assert any("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE" in e for e in _errors(env))

    def test_simulate_replies_forbidden_in_production(self):
        env = {**VALID_PRODUCTION, "SIMULATE_REPLIES": "true"}
        assert any("SIMULATE_REPLIES" in e for e in _errors(env))

    def test_simulate_accelerated_forbidden_in_production(self):
        env = {**VALID_PRODUCTION, "SIMULATE_ACCELERATED": "true"}
        assert any("SIMULATE_ACCELERATED" in e for e in _errors(env))

    def test_billing_mock_forbidden_in_production(self):
        env = {**VALID_PRODUCTION, "BILLING_PROVIDER_MODE": "mock"}
        assert any("BILLING_PROVIDER_MODE" in e for e in _errors(env))

    def test_same_flags_allowed_in_development(self):
        env = {
            "ENVIRONMENT": "development",
            "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE": "true",
            "SIMULATE_REPLIES": "true",
            "BILLING_PROVIDER_MODE": "mock",
        }
        assert _errors(env) == []


class TestOptionalIntegration:
    def test_development_without_external_services_is_valid(self):
        env = {"ENVIRONMENT": "development", "PORT": "10000"}
        assert _errors(env) == []

    def test_resend_requires_key_in_production(self):
        env = {**VALID_PRODUCTION, "EMAIL_PROVIDER": "resend", "RESEND_API_KEY": ""}
        assert any("RESEND_API_KEY" in e for e in _errors(env))

    def test_resend_missing_key_in_development_is_warning_only(self):
        env = {"ENVIRONMENT": "development", "EMAIL_PROVIDER": "resend"}
        errors, warnings = validate_config(env)
        assert errors == []
        assert any("RESEND_API_KEY" in w for w in warnings)


class TestEnvironmentIndicator:
    def test_production_detected_from_environment(self):
        assert is_production({"ENVIRONMENT": "production"}) is True

    def test_production_detected_from_app_env(self):
        assert is_production({"APP_ENV": "production"}) is True

    def test_development_default(self):
        assert is_production({}) is False


class TestStartupGate:
    def test_assert_raises_on_invalid(self, monkeypatch):
        monkeypatch.setattr("services.config_validation.validate_config", lambda env=None: (["SUPABASE_URL is required in production and is not set"], []))
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            assert_valid_startup_config()

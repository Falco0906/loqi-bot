"""PR10.7 — Gmail OAuth hardening + credential encryption at rest tests.

Uses a deterministic sentinel; never real credentials.
"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.config_validation import validate_config
from services import credential_crypto
from services import oauth_state

SENTINEL = "PR10_7_SENTINEL_SECRET_DO_NOT_LEAK"


def _key() -> str:
    return "ab" * 32  # 64 hex chars


class TestConfigValidation:
    def test_production_requires_key(self):
        env = {
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
        }
        errors, _ = validate_config(env)
        assert any("LOQI_CREDENTIAL_ENCRYPTION_KEY is required" in e for e in errors)

    def test_invalid_key_rejected(self):
        env = {"ENVIRONMENT": "development", "LOQI_CREDENTIAL_ENCRYPTION_KEY": "not-hex!"}
        errors, _ = validate_config(env)
        assert any("LOQI_CREDENTIAL_ENCRYPTION_KEY" in e for e in errors)

    def test_placeholder_key_rejected_in_production(self):
        env = {
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "LOQI_CREDENTIAL_ENCRYPTION_KEY": "0" * 64,
        }
        errors, _ = validate_config(env)
        assert any("placeholder" in e for e in errors)

    def test_development_valid_without_key(self):
        errors, _ = validate_config({"ENVIRONMENT": "development", "PORT": "10000"})
        assert errors == []

    def test_development_valid_with_key(self):
        errors, _ = validate_config({"ENVIRONMENT": "development", "LOQI_CREDENTIAL_ENCRYPTION_KEY": _key()})
        assert errors == []


class TestCredentialCrypto:
    def test_round_trip(self, monkeypatch):
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        cipher = credential_crypto.encrypt_token(SENTINEL)
        assert credential_crypto.is_encrypted(cipher)
        assert SENTINEL not in cipher
        assert credential_crypto.decrypt_token(cipher) == SENTINEL

    def test_tampered_ciphertext_rejected(self, monkeypatch):
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        cipher = credential_crypto.encrypt_token(SENTINEL)
        tampered = cipher[:-1] + ("A" if cipher[-1] != "A" else "B")
        with pytest.raises(credential_crypto.CredentialDecryptionError):
            credential_crypto.decrypt_token(tampered)

    def test_wrong_key_rejected(self, monkeypatch):
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        cipher = credential_crypto.encrypt_token(SENTINEL)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "cd" * 32)
        with pytest.raises(credential_crypto.CredentialDecryptionError):
            credential_crypto.decrypt_token(cipher)

    def test_previous_key_rotation(self, monkeypatch):
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "ab" * 32)
        cipher = credential_crypto.encrypt_token(SENTINEL)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", "cd" * 32)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS", "ab" * 32)
        assert credential_crypto.decrypt_token(cipher) == SENTINEL

    def test_plaintext_passes_through_when_not_encrypted(self):
        assert credential_crypto.decrypt_token(SENTINEL) == SENTINEL


class TestFieldHelpers:
    def test_encrypt_field_stores_ciphertext(self, monkeypatch):
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        import services.supabase as supabase_module
        cipher = supabase_module._encrypt_credential_field(SENTINEL)
        assert credential_crypto.is_encrypted(cipher)
        assert SENTINEL not in cipher
        assert supabase_module._decrypt_credential_field(cipher) == SENTINEL

    def test_no_key_plaintext_dev_only(self, monkeypatch):
        monkeypatch.delenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", raising=False)
        import services.supabase as supabase_module
        assert supabase_module._encrypt_credential_field(SENTINEL) == SENTINEL


class TestPersistenceIntegration:
    class FakeRepo:
        def __init__(self):
            self.accounts = {}

        async def find_for_user(self, user_id, provider):
            return self.accounts.get((user_id, provider))

        async def save(self, entity):
            self.accounts[(entity.user_id, entity.provider)] = entity
            return entity

    def _install_repo(self, monkeypatch):
        repo = self.FakeRepo()
        monkeypatch.setattr(
            "services.persistence.launch.ConnectedAccountRepository",
            lambda: repo,
        )
        return repo

    def test_encrypted_credential_persisted_instead_of_plaintext(self, monkeypatch):
        from services.persistence.launch import ConnectedAccount
        repo = self._install_repo(monkeypatch)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        import services.supabase as supabase_module

        ok = supabase_module.sync_connected_account(
            "user-1", provider="google", email="a@b.com",
            access_token=SENTINEL, refresh_token=SENTINEL, token_expiry="2026-12-31T00:00:00+00:00",
        )
        assert ok is True
        entity = repo.accounts[("user-1", "google")]
        assert credential_crypto.is_encrypted(entity.access_token)
        assert credential_crypto.is_encrypted(entity.refresh_token)
        assert SENTINEL not in (entity.access_token or "") + (entity.refresh_token or "")

    def test_decrypt_only_internal_load_path(self, monkeypatch):
        from services.persistence.launch import ConnectedAccount
        repo = self._install_repo(monkeypatch)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        repo.accounts[("user-1", "google")] = ConnectedAccount(
            user_id="user-1", provider="google", email="a@b.com",
            access_token=credential_crypto.encrypt_token(SENTINEL),
            refresh_token=credential_crypto.encrypt_token(SENTINEL),
        )
        import services.supabase as supabase_module
        creds = supabase_module.get_google_credentials("user-1")
        assert creds is not None
        assert creds["access_token"] == SENTINEL
        assert creds["refresh_token"] == SENTINEL
        # Stored value stays encrypted (no plaintext write-back on read).
        assert credential_crypto.is_encrypted(repo.accounts[("user-1", "google")].access_token)

    def test_legacy_plaintext_migrated_on_write(self, monkeypatch):
        from services.persistence.launch import ConnectedAccount
        repo = self._install_repo(monkeypatch)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        repo.accounts[("user-1", "google")] = ConnectedAccount(
            user_id="user-1", provider="google", email="a@b.com",
            access_token=SENTINEL, refresh_token=SENTINEL,
        )
        import services.supabase as supabase_module
        creds = supabase_module.get_google_credentials("user-1")
        assert creds["access_token"] == SENTINEL
        entity = repo.accounts[("user-1", "google")]
        assert credential_crypto.is_encrypted(entity.access_token)
        assert credential_crypto.is_encrypted(entity.refresh_token)

    def test_encrypted_credential_recognized_after_reload(self, monkeypatch):
        from services.persistence.launch import ConnectedAccount
        repo = self._install_repo(monkeypatch)
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        repo.accounts[("user-1", "google")] = ConnectedAccount(
            user_id="user-1", provider="google", email="a@b.com",
            access_token=credential_crypto.encrypt_token(SENTINEL),
            refresh_token=credential_crypto.encrypt_token(SENTINEL),
        )
        import services.supabase as supabase_module
        # Fresh read (simulates restart/reload) resolves the encrypted value.
        creds = supabase_module.get_google_credentials("user-1")
        assert creds["refresh_token"] == SENTINEL


class TestOAuthState:
    def test_issue_and_consume(self):
        token = oauth_state.issue_state("user-1")
        assert token and "user-1" not in token
        assert oauth_state.consume_state(token) == "user-1"

    def test_missing_state_rejected(self):
        assert oauth_state.consume_state("") is None

    def test_invalid_state_rejected(self):
        assert oauth_state.consume_state("not-a-real-state") is None

    def test_state_is_single_use(self):
        token = oauth_state.issue_state("user-1")
        assert oauth_state.consume_state(token) == "user-1"
        assert oauth_state.consume_state(token) is None

    def test_resolve_requires_issued_state(self):
        import main as main_module
        assert main_module._resolve_oauth_state_user("dev_providers:user-1") == ""
        assert main_module._resolve_oauth_state_user("") == ""

    def test_callback_state_flow(self):
        token = oauth_state.issue_state("user-1")
        import main as main_module
        assert main_module._resolve_oauth_state_user(token) == "user-1"


class TestNoSecretLeakage:
    def test_encryption_logs_contain_no_sentinel(self, monkeypatch, caplog):
        import logging
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        import services.supabase as supabase_module
        with caplog.at_level(logging.WARNING):
            cipher = supabase_module._encrypt_credential_field(SENTINEL)
            supabase_module._decrypt_credential_field(cipher)
        assert SENTINEL not in caplog.text

    def test_decrypt_failure_logs_no_token(self, monkeypatch, caplog):
        import logging
        monkeypatch.setenv("LOQI_CREDENTIAL_ENCRYPTION_KEY", _key())
        import services.supabase as supabase_module
        with caplog.at_level(logging.WARNING):
            # Tampered ciphertext -> decryption failure path (generic message).
            supabase_module._decrypt_credential_field("encv1.aaaa.bbbbbbbbbbbb")
        assert SENTINEL not in caplog.text
        assert "token" not in caplog.text.lower() or "credential" in caplog.text.lower()

    def test_oauth_state_never_contains_subject(self):
        token = oauth_state.issue_state("user-1")
        assert "user-1" not in token

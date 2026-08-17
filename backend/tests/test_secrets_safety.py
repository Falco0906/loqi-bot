"""PR10.3 — secrets safety tests.

Static + behavioral guards proving secret values never reach logs, validation
errors, API responses, git, Docker build context, or the frontend bundle.
Uses a distinctive sentinel value; never real credentials.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.config_validation import validate_config

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SENTINEL = "PR10_3_SUPER_SECRET_SENTINEL_VALUE"

VALID_PRODUCTION = {
    "ENVIRONMENT": "production",
    "SUPABASE_URL": "https://abc.supabase.co",
    "SUPABASE_KEY": SENTINEL,
    "OPENAI_API_KEY": SENTINEL,
    "GOOGLE_CLIENT_ID": "client",
    "GOOGLE_CLIENT_SECRET": SENTINEL,
    "GOOGLE_REDIRECT_URI": "https://app.tryloqi.com/api/auth/gmail/callback",
    "FRONTEND_URL": "https://app.tryloqi.com",
    "IDENTITY_PEPPER": "p" * 32,
    "IDENTITY_SIGNING_KEY_DEFAULT": "k" * 32,
    "PORT": "10000",
    "LOQI_CREDENTIAL_ENCRYPTION_KEY": "ab" * 32,
}


class TestValidationNeverExposesSecrets:
    def test_validation_errors_never_contain_secret_values(self):
        env = {**VALID_PRODUCTION, "SUPABASE_URL": "not-a-url", "PORT": "abc"}
        errors, _ = validate_config(env)
        for error in errors:
            assert SENTINEL not in error

    def test_valid_production_still_passes(self):
        errors, _ = validate_config(VALID_PRODUCTION)
        assert errors == []

    def test_unsafe_production_still_rejected(self):
        env = {**VALID_PRODUCTION, "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE": "true"}
        errors, _ = validate_config(env)
        assert any("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE" in e for e in errors)


class TestApiNeverReturnsSecrets:
    def test_health_response_contains_no_secret_values(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_KEY", SENTINEL)
        from fastapi.testclient import TestClient
        import main as main_module

        client = TestClient(main_module.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert SENTINEL not in response.text


class TestGitIgnore:
    @pytest.mark.parametrize(
        "path",
        [
            "backend/.env",
            "frontend/.env",
            ".env",
        ],
    )
    def test_env_files_are_ignored(self, path):
        result = subprocess.run(
            ["git", "check-ignore", "-q", os.path.join(REPO_ROOT, path)],
            capture_output=True,
        )
        assert result.returncode == 0, f"{path} must be gitignored"

    def test_env_examples_remain_tracked(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", os.path.join(REPO_ROOT, "backend/.env.example")],
            capture_output=True,
        )
        assert result.returncode != 0, "backend/.env.example must NOT be ignored"


class TestDockerBuildContext:
    def test_backend_dockerignore_excludes_env(self):
        text = _read("backend/.dockerignore")
        assert re.search(r"^\.env$", text, re.M)
        assert re.search(r"^\.env\.\*$", text, re.M)

    def test_frontend_dockerignore_excludes_env(self):
        text = _read("frontend/.dockerignore")
        assert re.search(r"^\.env$", text, re.M)


class TestComposeSafety:
    def test_compose_uses_env_file_and_no_hardcoded_secrets(self):
        text = _read("compose.yaml")
        assert "env_file" in text and "backend/.env" in text
        # No literal secret assignments in the compose file.
        assert "=sk-" not in text
        assert "=your_" not in text
        for key in ("SUPABASE_KEY", "OPENAI_API_KEY", "GOOGLE_CLIENT_SECRET", "RESEND_API_KEY"):
            # Keys must appear only via env_file, never with an inline value.
            for line in text.splitlines():
                if key in line and "=" in line and not line.strip().startswith("#"):
                    assert key not in line or "env_file" in line

    def test_production_safety_overrides_remain(self):
        text = _read("compose.yaml")
        assert "LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE=false" in text
        assert "SIMULATE_REPLIES=false" in text


class TestFrontendSecrets:
    def test_only_public_vars_are_next_public(self):
        allowed = {"NEXT_PUBLIC_LOQI_API_BASE_URL", "NEXT_PUBLIC_DEV_MODE"}
        found = set()
        frontend_src = os.path.join(REPO_ROOT, "frontend")
        for root, _dirs, files in os.walk(frontend_src):
            if "node_modules" in root or ".next" in root:
                continue
            for name in files:
                if not name.endswith((".ts", ".tsx")):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    continue
                found.update(re.findall(r"NEXT_PUBLIC_[A-Z0-9_]+", text))
        assert found <= allowed, f"Unexpected NEXT_PUBLIC_* variables: {found - allowed}"

    def test_frontend_example_has_no_private_secrets(self):
        text = _read("frontend/.env.example")
        assert "NEXT_PUBLIC_LOQI_API_BASE_URL" in text
        assert SENTINEL not in text


class TestSourceHasNoTokenLogging:
    def test_gmail_provider_does_not_log_token_prefixes(self):
        text = _read("services/communication/gmail_provider.py")
        assert "token_prefix" not in text
        assert "[:20]" not in text


def _read(relative: str) -> str:
    for candidate in (
        os.path.join(REPO_ROOT, relative),
        os.path.join(REPO_ROOT, "backend", relative),
    ):
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                return fh.read()
    raise FileNotFoundError(relative)

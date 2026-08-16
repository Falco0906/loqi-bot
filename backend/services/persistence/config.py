from __future__ import annotations

from enum import Enum
import os


class RepositoryProvider(str, Enum):
    IN_MEMORY = "in_memory"
    SUPABASE = "supabase"


_configured_provider = os.getenv("REPOSITORY_PROVIDER", "").strip().lower()
if _configured_provider:
    REPOSITORY_PROVIDER = RepositoryProvider(_configured_provider)
else:
    # The identity User aggregate (identity_users) is always persisted
    # through Supabase regardless of this provider. The remaining identity
    # repositories follow this selection until their tables are applied.
    # Match config_validation.is_production: ENVIRONMENT OR APP_ENV decides
    # production, so a deployment that only sets ENVIRONMENT=production still
    # gets the Supabase-backed provider (not a silent in-memory fallback).
    _production = (
        os.getenv("ENVIRONMENT", "").strip().lower() == "production"
        or os.getenv("APP_ENV", "").strip().lower() == "production"
    )
    REPOSITORY_PROVIDER = (
        RepositoryProvider.SUPABASE if _production else RepositoryProvider.IN_MEMORY
    )


def get_repository_provider() -> RepositoryProvider:
    global REPOSITORY_PROVIDER
    return REPOSITORY_PROVIDER


def set_repository_provider(provider: RepositoryProvider) -> None:
    global REPOSITORY_PROVIDER
    REPOSITORY_PROVIDER = provider


def reset_repository_provider() -> None:
    global REPOSITORY_PROVIDER
    REPOSITORY_PROVIDER = RepositoryProvider.IN_MEMORY

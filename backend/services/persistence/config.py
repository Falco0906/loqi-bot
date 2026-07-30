from __future__ import annotations

from enum import Enum


class RepositoryProvider(str, Enum):
    IN_MEMORY = "in_memory"
    SUPABASE = "supabase"


REPOSITORY_PROVIDER: RepositoryProvider = RepositoryProvider.IN_MEMORY


def get_repository_provider() -> RepositoryProvider:
    global REPOSITORY_PROVIDER
    return REPOSITORY_PROVIDER


def set_repository_provider(provider: RepositoryProvider) -> None:
    global REPOSITORY_PROVIDER
    REPOSITORY_PROVIDER = provider


def reset_repository_provider() -> None:
    global REPOSITORY_PROVIDER
    REPOSITORY_PROVIDER = RepositoryProvider.IN_MEMORY

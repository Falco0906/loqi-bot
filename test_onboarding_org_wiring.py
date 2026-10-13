"""Regression: onboarding's organization service must always be Supabase-
backed, independent of the global REPOSITORY_PROVIDER setting.

The live bug: create_workspace_and_finalize() creates/reuses an organization
through its injected org_service, then immediately calls ensure_workspace()
and workspaces_for_user() — both hardcoded to Supabase with no
REPOSITORY_PROVIDER branching. Before this fix, main.py wired onboarding's
org_service from _org_deps.org_service, which DOES follow REPOSITORY_PROVIDER
(in-memory by default outside production). So in a typical local dev setup
(ENVIRONMENT=development, REPOSITORY_PROVIDER unset), onboarding created an
organization Supabase's own membership check could never find, and
create_workspace_and_finalize() failed with "Workspace creation could not be
confirmed" (503) — reproduced live, see the 2026-10-12 session logs.

This test imports main.py fresh with REPOSITORY_PROVIDER forced to
"in_memory" (the exact broken local-dev condition) and asserts the onboarding
service's org_service is still backed by the Supabase repositories, not the
in-memory ones that the rest of the organizations API would get in that same
configuration.
"""
from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def fresh_main_with_in_memory_repository_provider(monkeypatch):
    """Reload main.py with REPOSITORY_PROVIDER forced to in_memory, mirroring
    local dev (ENVIRONMENT=development, REPOSITORY_PROVIDER unset resolves
    the same way). Restores the real module afterward.
    """
    monkeypatch.setenv("REPOSITORY_PROVIDER", "in_memory")
    for name in list(sys.modules):
        if name == "services.persistence.config" or name.startswith("services.persistence.config"):
            del sys.modules[name]
        if name == "services.organizations.api":
            del sys.modules[name]
        if name == "main":
            del sys.modules[name]
    import services.identity.dependencies as idep
    async def fake_resolve(request):
        return "test-user", "test-token"
    monkeypatch.setattr(idep, "resolve_web_session", fake_resolve)
    main = importlib.import_module("main")
    try:
        yield main
    finally:
        for name in list(sys.modules):
            if name == "main":
                del sys.modules[name]


def test_onboarding_org_service_is_supabase_backed_even_when_repository_provider_is_in_memory(
    fresh_main_with_in_memory_repository_provider,
):
    from services.persistence.repositories import (
        SupabaseMembershipRepository,
        SupabaseOrganizationRepository,
    )
    from services.organizations.repositories import (
        InMemoryMembershipRepository,
        InMemoryOrganizationRepository,
    )

    main = fresh_main_with_in_memory_repository_provider

    # Sanity check: the fixture genuinely reproduces the broken condition —
    # the rest of the organizations API DOES get in-memory repos here.
    assert isinstance(main._org_deps.org_service._org_repo, InMemoryOrganizationRepository)
    assert isinstance(main._org_deps.org_service._membership_repo, InMemoryMembershipRepository)

    # The fix: onboarding's org_service must not follow that same switch —
    # it must always be Supabase-backed, matching ensure_workspace() and
    # workspaces_for_user(), which it feeds into immediately afterward.
    onboarding_org_service = main._onboarding_svc._org_service
    assert isinstance(onboarding_org_service._org_repo, SupabaseOrganizationRepository)
    assert isinstance(onboarding_org_service._membership_repo, SupabaseMembershipRepository)

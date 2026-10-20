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

This test imports main.py in a fresh child process with REPOSITORY_PROVIDER forced to
"in_memory" (the exact broken local-dev condition) and asserts the onboarding
service's org_service is still backed by the Supabase repositories, not the
in-memory ones that the rest of the organizations API would get in that same
configuration.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys


def test_onboarding_org_service_is_supabase_backed_even_when_repository_provider_is_in_memory(
):
    """Fresh composition must not evict shared modules or replace suite globals."""
    code = """
import sys
import dotenv
dotenv.load_dotenv = lambda *_args, **_kwargs: False
from services.platform.test_runtime import activate_test_runtime
activate_test_runtime()
def audit(event, args):
    if event in {'socket.connect', 'socket.sendto', 'socket.sendmsg', 'subprocess.Popen', 'os.system', 'os.posix_spawn',
                 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'}:
        raise RuntimeError('No network or child processes in the wiring probe')
sys.addaudithook(audit)
import main
from services.persistence.repositories import SupabaseMembershipRepository, SupabaseOrganizationRepository
from services.organizations.repositories import InMemoryMembershipRepository, InMemoryOrganizationRepository
assert isinstance(main._org_deps.org_service._org_repo, InMemoryOrganizationRepository)
assert isinstance(main._org_deps.org_service._membership_repo, InMemoryMembershipRepository)
onboarding_org_service = main._onboarding_svc._org_service
assert isinstance(onboarding_org_service._org_repo, SupabaseOrganizationRepository)
assert isinstance(onboarding_org_service._membership_repo, SupabaseMembershipRepository)
print('onboarding-wiring-isolated')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env={"PATH": os.defpath, "LANG": "C", "LOQI_TEST_MODE": "1", "REPOSITORY_PROVIDER": "in_memory"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "onboarding-wiring-isolated" in result.stdout


def test_wiring_probe_preserves_shared_provider_module_identity():
    """Dynamic readers and the shared teardown must own the same provider state."""
    from services.persistence import reset_repository_provider
    config = importlib.import_module("services.persistence.config")
    assert reset_repository_provider.__globals__ is vars(config)

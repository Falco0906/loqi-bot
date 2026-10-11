"""Mock-only regressions for process, target, startup, and pytest boundaries."""
from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import replace

import pytest

from services.platform import test_runtime as runtime
from tests.supabase_test_safety import validate_supabase_test_configuration


def _env(**overrides):
    values = {
        "LOQI_TEST_SUPABASE_URL": "https://test-project.supabase.co",
        "LOQI_TEST_SUPABASE_KEY": "sentinel-do-not-log",
        "LOQI_TEST_SUPABASE_PROJECT_REF": "test-project",
        "LOQI_ALLOWED_TEST_SUPABASE_PROJECT_REFS": "test-project",
    }
    values.update(overrides)
    return values


@pytest.fixture
def sdk(monkeypatch):
    """Replace the SDK class and factory; no real client is constructed."""
    import supabase

    class Client:
        def __init__(self, url, key):
            self.supabase_url, self.supabase_key = url, key

    calls = []

    def factory(url, key):
        calls.append(url)
        return Client(url, key)

    monkeypatch.setattr(supabase, "Client", Client)
    monkeypatch.setattr(supabase, "create_client", factory)
    return Client, calls


def test_bootstrap_guard_survives_environment_deletion_and_changes(monkeypatch, sdk):
    from services.platform import supabase as module
    from services.persistence.database import SupabaseConnectionManager

    assert runtime.is_test_runtime()
    for value in (None, "0", "production"):
        if value is None:
            monkeypatch.delenv("LOQI_TEST_MODE", raising=False)
        else:
            monkeypatch.setenv("LOQI_TEST_MODE", value)
        monkeypatch.setattr(module, "SUPABASE_URL", "https://production.supabase.co")
        monkeypatch.setattr(module, "SUPABASE_KEY", "application-secret")
        assert module.get_supabase_client() is None
        assert SupabaseConnectionManager().get_client() is None
        assert runtime.is_test_runtime()
    assert sdk[1] == []


def test_arbitrary_manager_url_key_cannot_create_client(sdk):
    from services.persistence.database import SupabaseConnectionManager

    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        SupabaseConnectionManager(url="https://arbitrary.supabase.co", key="secret")
    assert sdk[1] == []


@pytest.mark.parametrize("values", [
    {}, _env(LOQI_TEST_SUPABASE_KEY=""),
    _env(LOQI_TEST_SUPABASE_PROJECT_REF="unknown"),
    _env(LOQI_TEST_SUPABASE_URL="https://unknown.supabase.co"),
    _env(LOQI_TEST_SUPABASE_URL="https://llckvmpwmovhchfpjnsa.supabase.co"),
    _env(LOQI_TEST_SUPABASE_URL="https://llckvmpwmovhchfpjnsa.supabase.co",
         LOQI_TEST_SUPABASE_PROJECT_REF="llckvmpwmovhchfpjnsa",
         LOQI_ALLOWED_TEST_SUPABASE_PROJECT_REFS="llckvmpwmovhchfpjnsa"),
    _env(LOQI_TEST_SUPABASE_URL="https://test-project.supabase.co/another-path"),
])
def test_unapproved_or_missing_config_fails_before_client_creation(values, sdk):
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration) as caught:
        authorization = validate_supabase_test_configuration(values)
        runtime.create_supabase_client(authorization.url, authorization.key, authorization=authorization)
    assert sdk[1] == []
    assert "sentinel-do-not-log" not in str(caught.value)


def test_approved_project_creates_client_only_through_authorized_factory(sdk):
    authorization = validate_supabase_test_configuration(_env())
    client = runtime.create_supabase_client(authorization.url, authorization.key, authorization=authorization)
    assert runtime.validate_supabase_client(client, authorization)
    assert sdk[1] == [authorization.url]
    assert "sentinel-do-not-log" not in repr(authorization)


def test_authorization_cannot_be_reused_for_another_url_or_credential(sdk):
    authorization = validate_supabase_test_configuration(_env())
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        runtime.create_supabase_client("https://other.supabase.co", authorization.key, authorization=authorization)
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        runtime.create_supabase_client(authorization.url, "different-key", authorization=authorization)
    assert sdk[1] == []


def test_modified_or_manually_constructed_authorization_is_rejected(sdk):
    authorization = validate_supabase_test_configuration(_env())
    forged = runtime.TestDatabaseAuthorization(authorization.url, authorization.key, authorization.project_ref, object())
    for capability in (forged, replace(authorization, url="https://other.supabase.co")):
        with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
            runtime.create_supabase_client(capability.url, capability.key, authorization=capability)
    assert sdk[1] == []


def test_client_installation_and_retrieval_verify_actual_target(sdk):
    from services.platform import supabase as module

    authorization = validate_supabase_test_configuration(_env())
    wrong = sdk[0]("https://other.supabase.co", authorization.key)
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        module.install_validated_test_client(wrong, authorization)
    assert module.get_supabase_client() is None
    client = sdk[0](authorization.url, authorization.key)
    module.install_validated_test_client(client, authorization)
    assert module.get_supabase_client() is client
    client.supabase_url = "https://other.supabase.co"
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        module.get_supabase_client()


def test_fake_clients_remain_explicitly_injectable_and_sdk_cannot_use_fake_path(sdk):
    from services.platform import supabase as module
    from services.persistence.database import SupabaseConnectionManager, set_connection_manager

    fake = object()
    module.install_test_double(fake)
    assert module.get_supabase_client() is fake
    manager = SupabaseConnectionManager(client=fake)
    set_connection_manager(manager)
    assert manager.get_client() is fake
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        module.install_test_double(sdk[0]("https://unknown.supabase.co", "key"))
    assert sdk[1] == []


def test_authorized_connection_manager_remains_bound_to_its_client_target(sdk):
    from services.persistence.database import SupabaseConnectionManager, set_connection_manager

    authorization = validate_supabase_test_configuration(_env())
    manager = SupabaseConnectionManager(authorization=authorization)
    set_connection_manager(manager)
    client = manager.get_client()
    assert sdk[1] == [authorization.url]
    assert manager.get_client() is client
    client.supabase_url = "https://other.supabase.co"
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration): manager.get_client()


def test_connection_manager_rejects_authorized_target_mismatch_before_construction(sdk):
    from services.persistence.database import SupabaseConnectionManager

    authorization = validate_supabase_test_configuration(_env())
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        SupabaseConnectionManager(url="https://other.supabase.co", key=authorization.key, authorization=authorization)
    assert sdk[1] == []


def test_async_sdk_clients_cannot_bypass_the_fake_client_path(monkeypatch, sdk):
    import supabase
    from services.persistence.database import SupabaseConnectionManager
    from services.platform.supabase import install_test_double

    class AsyncClient(sdk[0]):
        pass
    monkeypatch.setattr(supabase, "AsyncClient", AsyncClient)
    client = AsyncClient("https://unknown.supabase.co", "key")
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration): SupabaseConnectionManager(client=client)
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration): install_test_double(client)
    assert sdk[1] == []


def test_missing_test_credentials_never_fall_back_to_application_secrets(monkeypatch, sdk):
    monkeypatch.setenv("SUPABASE_URL", "https://production.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "application-secret")
    with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
        validate_supabase_test_configuration(_env(LOQI_TEST_SUPABASE_KEY=""))
    assert sdk[1] == []


def test_direct_migration_guard_precedes_database_probe_after_environment_removed(monkeypatch):
    from services.platform import migration

    monkeypatch.delenv("LOQI_TEST_MODE", raising=False)
    monkeypatch.setattr(migration, "_check_table_exists", lambda: pytest.fail("database probe called"))
    assert migration.apply_migrations() is False


def test_startup_skips_provider_recovery_and_worker_work_after_environment_removed(monkeypatch):
    import main

    monkeypatch.delenv("LOQI_TEST_MODE", raising=False)
    for name in ("begin_startup", "initialize_runtime_services", "recover_persisted_workflows",
                 "start_generation_recovery", "recover_search_and_start_due_jobs"):
        monkeypatch.setattr(main.app_lifespan, name, lambda *_: pytest.fail("production startup entered"))
    monkeypatch.setattr(main.provider_startup, "initialize_gmail_runtime", lambda: pytest.fail("provider restored"))

    async def check():
        async with main.lifespan(main.app):
            assert runtime.is_test_runtime()
    asyncio.run(check())


def test_direct_runtime_initialization_refuses_external_work(monkeypatch):
    from app import lifespan

    monkeypatch.delenv("LOQI_TEST_MODE", raising=False)
    monkeypatch.setattr(lifespan, "register_outbound_providers", lambda: pytest.fail("provider initialized"))
    with pytest.raises(RuntimeError, match="disabled in test runtime"):
        lifespan.begin_startup(object())
    with pytest.raises(RuntimeError, match="disabled in test runtime"):
        lifespan.initialize_runtime_services(object())


def test_offline_network_guard_refuses_connection_before_transport():
    with pytest.raises(RuntimeError, match="disabled for offline tests"):
        socket.create_connection(("unreachable.invalid", 443))


@pytest.mark.parametrize("marker", ["requires_db", "integration"])
def test_database_and_external_markers_are_skipped_by_default(monkeypatch, marker):
    from tests import conftest

    monkeypatch.delenv("LOQI_RUN_DB_INTEGRATION", raising=False)
    monkeypatch.delenv("LOQI_RUN_EXTERNAL_INTEGRATION", raising=False)
    class Item:
        def __init__(self): self.marks = []
        def get_closest_marker(self, name): return name == marker
        def add_marker(self, mark): self.marks.append(mark)
    item = Item()
    conftest.pytest_collection_modifyitems(None, [item])
    assert len(item.marks) == 1 and item.marks[0].name == "skip"


def test_validation_errors_do_not_log_credentials(caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(runtime.UnsafeTestDatabaseConfiguration):
            validate_supabase_test_configuration(_env(LOQI_TEST_SUPABASE_PROJECT_REF="wrong"))
    assert "sentinel-do-not-log" not in caplog.text

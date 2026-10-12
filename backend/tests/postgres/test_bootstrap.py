"""Fresh-database bootstrap test, run separately before installing Migration 048."""
import os
import json
from pathlib import Path

import pytest

from tests.postgres.harness import apply_prerequisites, authorize_local_target, connect_local, require_migration_approval, sha256
from tests.postgres.catalog_contract import verify_campaign_prerequisites
from tests.postgres.schema import capture_local

pytestmark = pytest.mark.requires_local_postgres


def test_fresh_prerequisite_bootstrap():
    if os.getenv("LOQI_TEST_POSTGRES_ENABLED") != "1":
        pytest.skip("Local test database opt-in required")
    plan = require_migration_approval()
    target = authorize_local_target()
    apply_prerequisites(target)
    with connect_local(target) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_schema='public' AND table_name='campaigns' AND column_name='discovery_id'")
        assert cursor.fetchall() == [("discovery_id", "uuid")]
        cursor.execute("SELECT to_regprocedure('public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)')")
        assert cursor.fetchone()[0] is None
        verify_campaign_prerequisites(cursor)
    # Execute this test separately against TWO fresh, independently approved
    # targets, then compare observed artifacts offline. No second target bypass
    # or session lease swap is introduced. Output creation is explicit/private.
    output = os.getenv("LOQI_TEST_POSTGRES_BOOTSTRAP_SNAPSHOT")
    if output:
        path = Path(output)
        if not path.is_absolute():
            pytest.fail("Bootstrap snapshot output requires an absolute path")
        artifact = {"database": target.database, "run_id": target.run_id,
            "manifest_sha256": sha256(plan.manifest_bytes), "snapshot": capture_local(target)}
        with path.open("x", opener=lambda name, flags: os.open(name, flags, 0o600)) as destination:
            json.dump(artifact, destination, indent=2)

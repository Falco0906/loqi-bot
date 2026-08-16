"""Structural validation of the 021 identity session/token migration.

Verifies mechanically that the additive migration (supabase/migrations/
021_identity_sessions.sql) defines exactly the columns the identity models
require and supporting indexes for the Supabase repository queries. Pure
text-based parsing — no database or extra dependencies.

Read-only: never connects to Supabase; never mutates application code.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

from services.identity.models import (
    PasswordResetRequest,
    RefreshToken,
    Session,
    VerificationToken,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "supabase/migrations/021_identity_sessions.sql"
)

TABLES = {
    "sessions": Session,
    "refresh_tokens": RefreshToken,
    "verification_tokens": VerificationToken,
    "password_reset_requests": PasswordResetRequest,
}

MODEL_FIELDS: dict[str, set[str]] = {
    name: {f.name for f in fields(cls)}
    for name, cls in TABLES.items()
}


def _table_blocks(sql: str) -> dict[str, list[str]]:
    """Split SQL into per-table statement blocks."""
    blocks: dict[str, list[str]] = {}
    current = None
    for raw in sql.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        m = re.search(r"create table if not exists (\w+)", stmt)
        if m:
            current = m.group(1)
            blocks.setdefault(current, [])
        if current:
            blocks[current].append(stmt)
    return blocks


def _columns_of(block: str) -> set[str]:
    cols = set()
    for line in block.splitlines():
        m = re.match(r"^\s{2}([a-z_]+)\s", line)
        if m:
            cols.add(m.group(1))
    return cols


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION_PATH.read_text()


@pytest.fixture(scope="module")
def blocks(sql: str) -> dict[str, list[str]]:
    return _table_blocks(sql)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_table_exists(table: str, blocks: dict[str, list[str]]) -> None:
    assert table in blocks, (
        f"migration does not define `create table if not exists {table}`"
    )


@pytest.mark.parametrize("table", sorted(TABLES))
def test_all_model_fields_have_columns(
    table: str, blocks: dict[str, list[str]]
) -> None:
    cols = set()
    for block in blocks[table]:
        cols |= _columns_of(block)
    missing = MODEL_FIELDS[table] - cols
    assert not missing, (
        f"{table}: model fields missing from migration columns: {sorted(missing)}"
    )


@pytest.mark.parametrize("table", sorted(TABLES))
def test_primary_key_present(table: str, blocks: dict[str, list[str]]) -> None:
    create = blocks[table][0]
    assert "id uuid primary key" in create, (
        f"{table}: expected `id uuid primary key` in create table"
    )


def test_sessions_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["sessions"])
    assert "sessions_user_created_idx" in stmts
    assert "sessions_user_active_idx" in stmts
    assert "sessions_org_active_idx" in stmts
    assert "create table if not exists sessions" in stmts


def test_refresh_tokens_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["refresh_tokens"])
    assert "refresh_tokens_session_active_idx" in stmts
    assert "refresh_tokens_family_seq_idx" in stmts
    assert "refresh_tokens_token_hash_uidx" in stmts


def test_verification_tokens_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["verification_tokens"])
    assert "verification_tokens_target_purpose_active_idx" in stmts
    assert "verification_tokens_target_created_idx" in stmts
    assert "verification_tokens_token_hash_uidx" in stmts
    assert "verify_email" in stmts


def test_password_reset_request_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["password_reset_requests"])
    assert "password_reset_requests_user_active_idx" in stmts
    assert "password_reset_requests_token_hash_uidx" in stmts


def test_no_workflow_sessions_touched(sql: str) -> None:
    executable = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    assert "workflow_sessions" not in executable


def test_idempotent_guards(sql: str) -> None:
    assert sql.count("create table if not exists") == 4
    assert sql.count("create index if not exists") >= 8
    assert sql.count("create unique index if not exists") == 3
    assert not re.search(r"\b(drop|truncate|rename|alter)\b", sql, re.IGNORECASE), (
        "migration must be additive — found destructive keywords"
    )


def test_repo_query_columns_covered() -> None:
    """Every column used by the Supabase repositories must exist in the schema."""
    sql = MIGRATION_PATH.read_text()
    blocks = _table_blocks(sql)
    cover = {
        "sessions": {
            "user_id", "created_at", "revoked_at", "expires_at", "organization_id", "id",
        },
        "refresh_tokens": {
            "session_id", "revoked_at", "expires_at", "family", "sequence", "token_hash", "id",
        },
        "verification_tokens": {
            "target", "purpose", "used_at", "expires_at", "token_hash", "created_at", "id",
        },
        "password_reset_requests": {
            "user_id", "used_at", "expires_at", "token_hash", "id",
        },
    }
    for table, cols in cover.items():
        declared = set()
        for block in blocks[table]:
            declared |= _columns_of(block)
        missing = cols - declared
        assert not missing, f"{table}: repo query columns missing: {sorted(missing)}"
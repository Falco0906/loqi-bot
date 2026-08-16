"""Structural validation of the 022 identity auth persistence migration.

Verifies the SaaS-1.2 closure migration (supabase/migrations/
022_identity_auth_persistence.sql): email_identities, password_credentials,
registration_sessions, and the refresh-token family-active unique index.
Mirrors the 021 test style: pure text-based parsing, no database access.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

from services.identity.models import (
    EmailIdentity,
    PasswordCredential,
    RegistrationSession,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "supabase/migrations/022_identity_auth_persistence.sql"
)

TABLES = {
    "email_identities": EmailIdentity,
    "password_credentials": PasswordCredential,
    "registration_sessions": RegistrationSession,
}

MODEL_FIELDS = {name: {f.name for f in fields(cls)} for name, cls in TABLES.items()}


def _table_blocks(sql: str) -> dict[str, list[str]]:
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
        if line.strip().startswith("constraint"):
            continue
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
    assert table in blocks, f"migration does not define `create table if not exists {table}`"


@pytest.mark.parametrize("table", sorted(TABLES))
def test_all_model_fields_have_columns(table: str, blocks: dict[str, list[str]]) -> None:
    declared = _columns_of(blocks[table][0])
    missing = MODEL_FIELDS[table] - declared
    assert not missing, f"{table}: model fields missing from migration: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(TABLES))
def test_id_uuid_pk(table: str, blocks: dict[str, list[str]]) -> None:
    assert re.search(r"^\s{2}id uuid primary key", blocks[table][0], re.M), (
        f"{table}: expected `id uuid primary key`"
    )


def test_email_identities_contract(blocks: dict[str, list[str]]) -> None:
    create = blocks["email_identities"][0]
    assert re.search(r"^\s{2}email text not null default ''", create, re.M)
    assert re.search(r"^\s{2}is_verified boolean not null default false", create, re.M)
    assert re.search(r"^\s{2}is_primary boolean not null default false", create, re.M)
    assert re.search(r"^\s{2}verified_at timestamptz", create, re.M)
    stmts = "\n".join(blocks["email_identities"])
    assert "email_identities_email_uidx" in stmts
    assert "email_identities_user_id_idx" in stmts
    assert "email_identities_primary_idx" in stmts


def test_password_credentials_contract(blocks: dict[str, list[str]]) -> None:
    create = blocks["password_credentials"][0]
    assert re.search(r"^\s{2}user_id text not null default ''", create, re.M)
    assert re.search(r"^\s{2}password_hash text not null default ''", create, re.M)
    assert re.search(r"^\s{2}last_changed_at timestamptz not null default now\(\)", create, re.M)
    assert "password_credentials_user_id_uidx" in "\n".join(blocks["password_credentials"])


def test_registration_sessions_contract(blocks: dict[str, list[str]]) -> None:
    create = blocks["registration_sessions"][0]
    assert "registration_sessions_status_check" in create
    assert "check (status in ('pending', 'verified', 'completed', 'expired'))" in create
    stmts = "\n".join(blocks["registration_sessions"])
    assert "registration_sessions_email_status_idx" in stmts
    assert "registration_sessions_status_expiry_idx" in stmts


def test_refresh_family_active_unique_index(sql: str) -> None:
    assert re.search(
        r"create unique index if not exists refresh_tokens_family_active_uidx\s*\n?\s*"
        r"on refresh_tokens\(family\)\s*where revoked_at is null",
        sql, re.M,
    ), "expected partial unique index refresh_tokens_family_active_uidx"


def test_additive_and_idempotent(sql: str) -> None:
    assert not re.search(r"\b(drop|truncate|rename|alter)\b", sql, re.IGNORECASE)
    assert sql.count("create table if not exists") == 3


def test_no_workflow_sessions_touched(sql: str) -> None:
    executable = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "workflow_sessions" not in executable


def test_no_raw_token_columns(blocks: dict[str, list[str]]) -> None:
    for table in TABLES:
        create = blocks[table][0]
        for line in create.splitlines():
            m = re.match(r"^\s{2}([a-z_]+)\s", line)
            if m:
                col = m.group(1)
                assert "raw" not in col and "plaintext" not in col, (
                    f"{table}: suspicious raw-token column {col}"
                )


@pytest.mark.parametrize("table", sorted(TABLES))
def test_serialized_columns_match_migration(table: str, blocks: dict[str, list[str]]) -> None:
    from services.persistence.base_repository import _serialize

    cls = TABLES[table]
    kwargs: dict[str, object] = {"id": "00000000-0000-4000-8000-000000000000"}
    for f in fields(cls):
        if f.name == "id":
            continue
        if f.name in ("is_verified", "is_primary"):
            kwargs[f.name] = True
        elif f.name == "email":
            from services.identity.types import EmailAddress
            kwargs[f.name] = EmailAddress("user@example.com")
        elif f.name == "password_hash":
            from services.identity.types import PasswordHash
            kwargs[f.name] = PasswordHash("hashed")
        else:
            kwargs[f.name] = "x"
    row = _serialize(cls(**kwargs))
    declared = _columns_of(blocks[table][0])
    assert set(row.keys()) == declared, (
        f"{table}: serialized {sorted(row)} != migration {sorted(declared)}"
    )
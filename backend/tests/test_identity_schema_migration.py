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


# ─── DB-contract regression tests (SaaS-1.1 audit closure) ──────────────

NULLABLE_MODEL_FIELDS = {
    "sessions": {"revoked_at"},
    "refresh_tokens": {"revoked_at"},
    "verification_tokens": {"used_at"},
    "password_reset_requests": {"used_at"},
}


def _create_block(blocks: dict[str, list[str]], table: str) -> str:
    return blocks[table][0]


@pytest.mark.parametrize("table", sorted(TABLES))
def test_model_nullable_fields_are_nullable(table: str, blocks: dict[str, list[str]]) -> None:
    create = _create_block(blocks, table)
    for col in NULLABLE_MODEL_FIELDS.get(table, set()):
        lines = [l for l in create.splitlines() if re.match(rf"^\s{{2}}{re.escape(col)}\s", l)]
        assert lines, f"{table}.{col}: column not found"
        assert "not null" not in lines[0], f"{table}.{col}: model-nullable field is NOT NULL"


@pytest.mark.parametrize("table", sorted(TABLES))
def test_id_uuid_pk_and_timestamp_types(table: str, blocks: dict[str, list[str]]) -> None:
    create = _create_block(blocks, table)
    assert re.search(r"^\s{2}id uuid primary key", create, re.M), f"{table}: id must be uuid pk"
    for col in ("created_at", "expires_at"):
        assert re.search(
            rf"^\s{{2}}{col} timestamptz not null default now\(\)", create, re.M,
        ), f"{table}.{col}: must be timestamptz not null default now()"
    if "last_activity_at" in create:
        assert re.search(
            r"^\s{2}last_activity_at timestamptz not null default now\(\)", create, re.M,
        ), f"{table}.last_activity_at type mismatch"
    if "sequence" in create:
        assert re.search(
            r"^\s{2}sequence integer not null default 1", create, re.M,
        ), f"{table}.sequence must be integer not null default 1"


@pytest.mark.parametrize("table", sorted(TABLES))
def test_serialized_columns_exactly_match_migration(
    table: str, blocks: dict[str, list[str]],
) -> None:
    """The repository serializer writes every dataclass field; the migration
    must declare exactly those columns (no missing, no extra required)."""
    from services.persistence.base_repository import _serialize
    from datetime import datetime, timedelta, timezone

    cls = TABLES[table]
    kwargs: dict[str, object] = {}
    for f in fields(cls):
        if f.name == "id":
            kwargs[f.name] = "00000000-0000-4000-8000-000000000000"
        elif f.name == "sequence":
            kwargs[f.name] = 2
        elif f.name in ("expires_at", "last_activity_at", "created_at"):
            kwargs[f.name] = datetime.now(timezone.utc)
        elif f.name == "purpose":
            from services.identity.models import VerificationTokenPurpose
            kwargs[f.name] = VerificationTokenPurpose.VERIFY_EMAIL
        elif f.name == "token_hash":
            from services.identity.types import TokenHash
            kwargs[f.name] = TokenHash("aa")
        else:
            kwargs[f.name] = "x" if f.name != "revoked_at" and f.name != "used_at" else None

    row = _serialize(cls(**kwargs))
    declared = _columns_of(blocks[table][0])
    assert set(row.keys()) == declared, (
        f"{table}: serialized columns {sorted(row)} != migration columns {sorted(declared)}"
    )


def _repo_query_literals(path: str) -> dict[str, set[str]]:
    """Extract column literals used by the Supabase repository queries."""
    source = MIGRATION_PATH.parent.parent.parent / "services" / "persistence" / "repositories" / path
    text = source.read_text()
    by_method: dict[str, set[str]] = {}
    for m in re.finditer(r"async def (\w+)\(([^)]*)\):", text):
        name = m.group(1)
        body = text[m.end():]
        nxt = re.search(r"(?m)^    async def |^class ", body)
        body = body[: nxt.start()] if nxt else body
        cols = set()
        for cm in re.finditer(r'\.(eq|gt|lt|is_|in_|order)\(\s*"([a-z_]+)"', body):
            cols.add(cm.group(2))
        if cols:
            by_method[name] = cols
    return by_method


def test_repo_query_literals_exist_in_migration(blocks: dict[str, list[str]]) -> None:
    """Every filter column literally used by the Supabase repositories must be
    declared in the matching migration table."""
    sources = {
        "sessions": "session_repository.py",
        "refresh_tokens": "token_repositories.py",
        "verification_tokens": "token_repositories.py",
        "password_reset_requests": "token_repositories.py",
    }
    for table, src in sources.items():
        declared = set()
        for block in blocks[table]:
            declared |= _columns_of(block)
        for method, cols in _repo_query_literals(src).items():
            missing = cols - declared
            assert not missing, (
                f"{table}.{method}: query columns not in migration: {sorted(missing)}"
            )


def test_token_hash_unique_indexes_are_partial(blocks: dict[str, list[str]]) -> None:
    """token_hash uniqueness must be partial so default '' rows never collide."""
    for table in ("refresh_tokens", "verification_tokens", "password_reset_requests"):
        stmts = "\n".join(blocks[table])
        assert re.search(
            rf"create unique index if not exists {table}_token_hash_uidx\s*\n?\s*"
            rf"on {table}\(token_hash\)\s*where token_hash <> ''",
            stmts, re.M,
        ), f"{table}: expected partial unique index on token_hash where <> ''"


def test_active_row_indexes_have_revoked_used_predicates(blocks: dict[str, list[str]]) -> None:
    pairs = {
        "sessions": ("sessions_user_active_idx", "revoked_at is null"),
        "refresh_tokens": ("refresh_tokens_session_active_idx", "revoked_at is null"),
        "verification_tokens": ("verification_tokens_target_purpose_active_idx", "used_at is null"),
        "password_reset_requests": ("password_reset_requests_user_active_idx", "used_at is null"),
    }
    for table, (idx, pred) in pairs.items():
        stmts = "\n".join(blocks[table])
        assert idx in stmts, f"{table}: missing {idx}"
        assert pred in stmts, f"{table}: {idx} missing partial predicate {pred!r}"


def test_no_raw_token_columns(sql: str) -> None:
    """The migration must never store raw tokens — only hash columns."""
    for table in TABLES:
        create = _create_block(_table_blocks(sql), table)
        for line in create.splitlines():
            col = re.match(r"^\s{2}([a-z_]+)\s", line)
            if col:
                assert "raw" not in col.group(1) and "plaintext" not in col.group(1), (
                    f"{table}: suspicious raw-token column {col.group(1)}"
                )
"""Structural validation of the SaaS-1.7 migrations 025/026.

Verifies memberships, invitations, and the billing_* tables declared in
025_organization_persistence.sql / 026_billing_persistence.sql against the
org-platform and billing dataclass models and the repository query columns.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.organizations.models import Invitation, Membership
from services.billing.models import (
    BillingEvent,
    CheckoutSession,
    Customer,
    Invoice,
    Plan,
    Subscription,
)

MIG_DIR = Path(__file__).resolve().parents[1] / "supabase/migrations"

MODEL_TABLES = {
    "memberships": Membership,
    "invitations": Invitation,
    "billing_plans": Plan,
    "billing_customers": Customer,
    "billing_subscriptions": Subscription,
    "billing_checkout_sessions": CheckoutSession,
    "billing_invoices": Invoice,
    "billing_events": BillingEvent,
}

TABLE_FILES = {
    "memberships": "025_organization_persistence.sql",
    "invitations": "025_organization_persistence.sql",
    "billing_plans": "026_billing_persistence.sql",
    "billing_customers": "026_billing_persistence.sql",
    "billing_subscriptions": "026_billing_persistence.sql",
    "billing_checkout_sessions": "026_billing_persistence.sql",
    "billing_invoices": "026_billing_persistence.sql",
    "billing_events": "026_billing_persistence.sql",
}


def _sql() -> str:
    out = []
    for f in ("025_organization_persistence.sql", "026_billing_persistence.sql"):
        out.append((MIG_DIR / f).read_text())
    return "\n".join(out)


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
def blocks():
    return _table_blocks(_sql())


@pytest.mark.parametrize("table", sorted(MODEL_TABLES))
def test_model_fields_have_columns(table: str, blocks: dict[str, list[str]]) -> None:
    from dataclasses import fields
    assert table in blocks, f"{table} not declared"
    declared = _columns_of(blocks[table][0])
    model_fields = {f.name for f in fields(MODEL_TABLES[table])}
    missing = model_fields - declared
    assert not missing, f"{table}: model fields missing columns: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(MODEL_TABLES))
def test_id_uuid_pk_and_idempotent_create(table: str, blocks: dict[str, list[str]]) -> None:
    assert re.search(r"^\s{2}id uuid primary key", blocks[table][0], re.M), (
        f"{table}: expected id uuid primary key"
    )


def test_memberships_constraints_and_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["memberships"])
    assert "memberships_role_check" in stmts and "'owner'" in stmts and "'admin'" in stmts
    assert "memberships_user_org_uidx" in stmts
    assert "memberships_org_idx" in stmts
    assert "memberships_user_status_idx" in stmts


def test_invitations_constraints_and_indexes(blocks: dict[str, list[str]]) -> None:
    stmts = "\n".join(blocks["invitations"])
    assert "invitations_token_uidx" in stmts
    assert "invitations_org_idx" in stmts
    assert "invitations_email_status_idx" in stmts


def test_billing_unique_and_lookup_indexes(blocks: dict[str, list[str]]) -> None:
    for table, idx in {
        "billing_plans": ("billing_plans_code_uidx",),
        "billing_customers": ("billing_customers_org_idx", "billing_customers_provider_customer_uidx"),
        "billing_subscriptions": ("billing_subscriptions_org_idx", "billing_subscriptions_provider_uidx", "billing_subscriptions_active_idx"),
        "billing_checkout_sessions": ("billing_checkouts_org_idx", "billing_checkouts_provider_uidx"),
        "billing_invoices": ("billing_invoices_org_idx", "billing_invoices_provider_uidx"),
        "billing_events": ("billing_events_provider_event_uidx", "billing_events_idempotency_uidx"),
    }.items():
        stmts = "\n".join(blocks[table])
        for name in idx:
            assert name in stmts, f"{table}: missing index {name}"


def test_migrations_are_additive_and_idempotent() -> None:
    sql = _sql()
    assert not re.search(r"\b(drop|truncate|rename)\b", sql, re.IGNORECASE)
    assert sql.count("create table if not exists") == 8
    assert sql.count("create unique index if not exists") >= 8
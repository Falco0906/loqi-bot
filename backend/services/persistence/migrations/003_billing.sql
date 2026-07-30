-- M2.3 — Billing Platform Schema
-- Supabase PostgreSQL migration

-- ─── Plans ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_plans (
    id              TEXT PRIMARY KEY,
    code            TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    billing_interval TEXT NOT NULL DEFAULT 'monthly',
    currency        TEXT NOT NULL DEFAULT 'usd',
    price           INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_plans_code ON billing_plans (code);

-- ─── Customers ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_customers (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL,
    provider            TEXT NOT NULL DEFAULT '',
    provider_customer_id TEXT NOT NULL DEFAULT '',
    email               TEXT NOT NULL DEFAULT '',
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_customers_org ON billing_customers (organization_id);
CREATE INDEX IF NOT EXISTS idx_billing_customers_provider ON billing_customers (provider_customer_id);

-- ─── Subscriptions ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id                      TEXT PRIMARY KEY,
    organization_id         TEXT NOT NULL,
    customer_id             TEXT NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,
    provider_subscription_id TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'incomplete',
    plan_id                 TEXT NOT NULL DEFAULT '',
    trial_ends_at           TIMESTAMPTZ,
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    cancel_at_period_end    BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_subs_org ON billing_subscriptions (organization_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_customer ON billing_subscriptions (customer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_subs_provider ON billing_subscriptions (provider_subscription_id);

-- ─── Checkout Sessions ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_checkout_sessions (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL,
    customer_id         TEXT NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,
    provider_checkout_id TEXT NOT NULL DEFAULT '',
    plan_id             TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'open',
    url                 TEXT NOT NULL DEFAULT '',
    mode                TEXT NOT NULL DEFAULT 'subscription',
    success_url         TEXT NOT NULL DEFAULT '',
    cancel_url          TEXT NOT NULL DEFAULT '',
    trial_days          INTEGER NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_billing_checkout_org ON billing_checkout_sessions (organization_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_checkout_provider ON billing_checkout_sessions (provider_checkout_id);

-- ─── Invoices ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_invoices (
    id                  TEXT PRIMARY KEY,
    organization_id     TEXT NOT NULL,
    customer_id         TEXT NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,
    subscription_id     TEXT NOT NULL REFERENCES billing_subscriptions(id) ON DELETE CASCADE,
    provider_invoice_id TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'draft',
    amount_due          INTEGER NOT NULL DEFAULT 0,
    amount_paid         INTEGER NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'usd',
    period_start        TIMESTAMPTZ,
    period_end          TIMESTAMPTZ,
    paid_at             TIMESTAMPTZ,
    hosted_url          TEXT NOT NULL DEFAULT '',
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_org ON billing_invoices (organization_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_sub ON billing_invoices (subscription_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_invoices_provider ON billing_invoices (provider_invoice_id);

-- ─── Billing Events (idempotency) ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS billing_events (
    id                TEXT PRIMARY KEY,
    event_type        TEXT NOT NULL DEFAULT '',
    provider_event_id TEXT NOT NULL DEFAULT '',
    provider          TEXT NOT NULL DEFAULT '',
    organization_id   TEXT NOT NULL DEFAULT '',
    data              JSONB NOT NULL DEFAULT '{}',
    idempotency_key   TEXT NOT NULL DEFAULT '',
    processed         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at      TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_events_provider_event ON billing_events (provider_event_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_events_idempotency ON billing_events (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_billing_events_org ON billing_events (organization_id);

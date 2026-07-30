-- M2.2 — Organization Platform Schema
-- Supabase PostgreSQL migration

-- ─── Organizations ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS organizations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    avatar_url      TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    metadata        JSONB NOT NULL DEFAULT '{}',
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug ON organizations (slug) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_name ON organizations (name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_organizations_created_by ON organizations (created_by);
CREATE INDEX IF NOT EXISTS idx_organizations_deleted_at ON organizations (deleted_at) WHERE deleted_at IS NOT NULL;

-- ─── Memberships ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS memberships (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    status          TEXT NOT NULL DEFAULT 'active',
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    invited_by      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_memberships_organization_id ON memberships (organization_id);
CREATE INDEX IF NOT EXISTS idx_memberships_user_id ON memberships (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memberships_user_org ON memberships (user_id, organization_id);

-- ─── Invitations ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS invitations (
    id              TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    token           TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_by      TEXT NOT NULL DEFAULT '',
    accepted_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invitations_organization_id ON invitations (organization_id);
CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations (email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invitations_token ON invitations (token);
CREATE INDEX IF NOT EXISTS idx_invitations_status ON invitations (status);

-- 025 Organization persistence closure (SaaS-1.7).
--
-- SaaS-1.4 established the organization authorization boundary at the API
-- and service layers, but the org-platform Supabase repositories
-- (SupabaseMembershipRepository, SupabaseInvitationRepository) target
-- `memberships` and `invitations`, which no migration created. This closes
-- that gap so the hardened boundary is backed by durable tables.
--
-- Column names/types/nullability mirror the org-platform dataclass models
-- (services/organizations/models.py) and the serializers in
-- services/persistence/repositories/organization_repositories.py. Role and
-- status are text with CHECK constraints matching their enums.
--
-- Additive and idempotent; safe to re-run; no destructive operations; no
-- foreign keys (the existing organization/identity tables use loose text ids
-- and 006's `organizations` has a text primary key).

create table if not exists memberships (
  id uuid primary key,
  organization_id text not null default '',
  user_id text not null default '',
  role text not null default 'member',
  status text not null default 'active',
  joined_at timestamptz not null default now(),
  invited_by text not null default '',
  constraint memberships_role_check
    check (role in ('owner', 'admin', 'member')),
  constraint memberships_status_check
    check (status in ('pending', 'active', 'removed', 'left'))
);

-- One membership row per (user, organization); a removed/left member is
-- reactivated in place by add_member, never duplicated.
create unique index if not exists memberships_user_org_uidx
  on memberships(user_id, organization_id);
create index if not exists memberships_org_idx on memberships(organization_id);
create index if not exists memberships_user_status_idx on memberships(user_id, status);

create table if not exists invitations (
  id uuid primary key,
  organization_id text not null default '',
  email text not null default '',
  role text not null default 'member',
  token text not null default '',
  expires_at timestamptz not null default now(),
  status text not null default 'pending',
  created_by text not null default '',
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  constraint invitations_role_check
    check (role in ('owner', 'admin', 'member')),
  constraint invitations_status_check
    check (status in ('pending', 'accepted', 'revoked', 'expired'))
);

create unique index if not exists invitations_token_uidx
  on invitations(token) where token <> '';
create index if not exists invitations_org_idx on invitations(organization_id);
create index if not exists invitations_email_status_idx on invitations(email, status);
-- 011 Launch Foundation — Immutable provider payload archive.
-- Apply AFTER 008_campaigns.sql.
--
-- Raw JSON returned by Apollo / PDL / Hunter / Clay is archived here exactly
-- as received, keyed by provider + entity id so each payload is stored once.
-- This is an immutable append-only archive: rows are never updated or deleted,
-- so when a provider starts returning new fields (technologies_used, hiring
-- signals, ...) the archived payloads can be re-parsed and backfilled without
-- re-querying and re-paying the provider.
--
-- lead_sources links to the archived payload via payload_id so acquisition
-- provenance and the raw archive stay consistent.

create table if not exists provider_payloads (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  entity_type text not null default 'lead' check (entity_type in ('lead', 'company')),
  entity_id text not null default '',
  payload jsonb not null default '{}'::jsonb,
  retrieved_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create unique index if not exists provider_payloads_provider_entity_uidx
  on provider_payloads(provider, entity_type, entity_id) where entity_id <> '';
create index if not exists provider_payloads_entity_idx
  on provider_payloads(entity_type, entity_id);
create index if not exists provider_payloads_retrieved_idx
  on provider_payloads(provider, retrieved_at desc);
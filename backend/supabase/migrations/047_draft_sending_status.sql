-- The durable Draft send claim uses ``sending`` as its in-flight ownership
-- boundary.  Migration 008 predates that state (and scheduled sends), so its
-- narrower check constraint rejects valid canonical lifecycle transitions.
--
-- Keep every legacy persisted value and admit the lifecycle values currently
-- written by the canonical outbound service.  This is intentionally a
-- constraint-only migration: it does not mutate any draft rows.

alter table drafts drop constraint if exists drafts_status_check;

alter table drafts
  add constraint drafts_status_check
  check (
    status in (
      'draft',
      'pending',
      'generating',
      'approved',
      'rejected',
      'sending',
      'sent',
      'delivered',
      'failed',
      'scheduled',
      'cancelled',
      'archived'
    )
  );

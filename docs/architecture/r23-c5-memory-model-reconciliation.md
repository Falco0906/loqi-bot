# R23-C-5: Conversation memory and model reconciliation

## Status

This document records the characterization and identity decision required
before durable conversation-memory work begins. C5b added the durable
record and C5c moved canonical Gmail analysis and workspace reads to it.
Raw compatibility analysis without a trusted canonical conversation and
stable source-message ID remains transient by design.

## Current representations

| Representation | Current owner | Identity | Durability | Purpose |
| --- | --- | --- | --- | --- |
| Legacy `ConversationMemory` | `services.conversation_memory` | caller-supplied `conversation_id` | process-local | communication compatibility projection |
| Enhanced facts | `services.conversation_intelligence.conversation_memory` | `lead_id` + fact key | process-local | raw fact extraction for `IntelligencePipeline` |
| Generic memory | `services.memory` | generic memory record identity | provider-dependent; in-memory by default | organization/agent memory |
| Inbox conversation | `services.conversations` | canonical `conversation_id` | durable `conversation_snapshots` | Inbox messages, threads, and timeline |

These contracts are not interchangeable. In particular, a lead can have
multiple Inbox conversations, and some legacy analysis callers supply an ID
that is not a canonical Inbox conversation at all.

## Identity rules for the durable cutover

1. Durable conversation intelligence must be keyed by a canonical Inbox
   `conversation_id` only.
2. The owner and workspace must be derived from that canonical conversation;
   they must never be accepted from an analysis request as authoritative
   identity.
3. A `lead_id` may be stored as a relationship of a durable conversation, but
   must not replace `conversation_id` as the primary key.
4. A source message identifier is required for idempotent updates. Replaying a
   provider message must not duplicate facts, memory entries, or events.
5. Analysis supplied with a non-canonical ID remains compatibility-only and
   non-durable. It may return its existing analysis envelope, but it must not
   create durable Inbox intelligence state.

## Restart baseline

The current legacy and enhanced conversation-memory stores are process-local
and do not recover after restart. The durable Inbox snapshot recovers
conversations, messages, and timeline events, but not legacy memory or
enhanced facts. A future cutover must add explicit durable persistence and
rehydration; it must not imply that the current stores already provide it.

## Planned implementation order

1. Add a durable per-conversation intelligence record with optimistic/versioned
   writes and source-message idempotency.
2. Add a Conversations-owned read/write operation that authorizes the
   canonical conversation before accessing that record.
3. Migrate communication, Gmail sync, workspace context, and the legacy reply
   projection to that operation.
4. Prove restart, replay, cross-workspace, and non-canonical-ID behavior.
5. Delete the process-local legacy memory store only after runtime proof that
   no caller depends on it.

The enhanced fact extractor and generic organizational-memory provider stay
separate unless a later design proves a shared durable contract is correct.

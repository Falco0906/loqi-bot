# ADR-001: Job Engine for AI Workflows

**Status:** Accepted  
**Date:** 2026-07-12  
**Driver:** Lead search timeout — Discovery search blocked for 15s+ per request

## Context

Loqi executes expensive multi-step AI workflows (lead search, campaign planning, draft generation, intelligence refresh). Each workflow makes 1–3 sequential OpenAI calls at 5–20s per call.

Originally, all workflows were tunneled through a conversational messaging API (`POST /api/web/session/{token}/messages`). This worked for chat turns but broke for long-running operations:

- Frontend timeout (10s default) fired before the backend responded (~15s)
- Backend workers were blocked holding HTTP connections
- No progress feedback — users stared at a generic spinner
- Browser refresh destroyed in-flight work
- Chat overhead (session management, intent classification, conversation logging) was paid for every search

## Decision

Introduce a unified Job Engine. Every expensive AI operation becomes a persistent Job with a stable API contract.

```
POST /api/jobs/search  →  { job_id }           (returns immediately)
GET  /api/jobs/{id}    →  { status, progress }  (poll for updates)
GET  /api/jobs/{id}/results → { leads }         (fetch when complete)
```

Jobs run as background `asyncio.create_task` tasks in the existing FastAPI process, with a pluggable runner interface that can be swapped for Celery/RQ/Temporal later.

## Consequences

### Positive

- **No blocking HTTP requests** — workers are freed immediately, connection pool is not exhausted
- **Progress is visible** — frontend shows "Extracting ICP...", "Searching...", "Ranking..." instead of a spinner
- **Survives refresh** — active jobs are persisted in Supabase; polling resumes on page reload
- **Unified API contract** — every workflow uses `POST/GET /api/jobs/{type}`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/results`
- **Works without a queue** — `asyncio.create_task` is zero-infra and sufficient for single-process deployment
- **Queue-ready** — replace `runner.py` with a Celery/RQ adapter; the API contract and storage remain unchanged
- **Reuses existing business logic** — the WorkflowDispatcher calls `search_with_expansion`, `campaign_planner`, etc. directly; no logic is duplicated

### Negative

- **New infrastructure** — a `jobs` table, 5 new backend modules, 1 new frontend hook
- **Background task lifecycle** — single-process asyncio tasks are lost on server restart (acceptable for now; Celery migration will fix this)
- **Polling overhead** — 1 GET request per active job per second; mitigated by exponential backoff (1s → 2s → 4s → 6s → max 8s)

## Alternatives Considered

| Option | Why Rejected |
|--------|-------------|
| Increase `sendMessage` timeout to 30s | Quick hack; blocks workers, no progress, no refresh recovery, doesn't scale |
| WebSocket-only push | Requires sticky sessions or Redis pub/sub; over-engineering for single-process stage; polling migration path is simpler |
| Keep everything synchronous | Violates the core requirement: Loqi has outgrown synchronous AI requests |

## Migration Path

1. Lead Search (this phase)
2. Campaign Planning
3. Draft Generation
4. Bulk Draft Refinement
5. Campaign Intelligence Refresh
6. CSV Export
7. Future: CRM Sync, enrichment, etc.

Each migration follows the same pattern: register the workflow type in `JobRegistry`, create its results table, implement the runner function, swap the frontend call.

## Status

Phase 3.0 delivers the Job Engine infrastructure + Lead Search migration. Remaining workflows are migrated in subsequent phases.

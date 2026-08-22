# Redis Configuration (PR-3A)

Redis is Loqi's **ephemeral shared-state layer**. Supabase remains the only
durable source of truth for users, orgs/workspaces, campaigns, leads,
drafts, messages, connected accounts and provider credentials.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `REDIS_URL` | no | *(unset → all Redis features degrade)* | e.g. `redis://default:<password>@host:6379/0`. Use `rediss://` for TLS. Never commit real URLs. |
| `REDIS_KEY_PREFIX` | no | `loqi` | Namespace root for every key. |
| `REDIS_KEY_SALT` | no | key prefix value | Salt for hashed token/user cache keys. Set a distinct private value in production so leaked key names cannot be correlated. |
| `REDIS_TIMEOUT_SECONDS` | no | `2.0` | Per-operation + connect timeout. |
| `SESSION_IDENTITY_TTL_SECONDS` | no | `15` | TTL of cached session identity. |
| `RATE_LIMIT_FORCE_LOCAL` | no | unset | Ops escape hatch: force the process-local limiter even when Redis is healthy. |

Render/production example:
    REDIS_URL=${{REDIS_URL}}        # from your Redis addon; mark as secret

## What lives in Redis

| Domain | Key pattern | TTL | Invalidation |
|---|---|---|---|
| Session identity | `loqi:v1:session:identity:{sha256(salt:token)[:32]}` | 15s | `invalidate_user()` on Gmail connect/disconnect + session revocation; `invalidate_token()` on known-bearer logout |
| Web-session binding | `loqi:v1:session:binding:{sha256(salt:token)}` | 10s | TTL only — authority stays in `touch_session` (revocation enforced immediately regardless of cache) |
| Rate-limit windows | `loqi:v1:rate:{category}:{sha256(identity)}:{window}` | window (60s) | automatic expiry |
| Event channels | `loqi:v1:events:user:{sha256(user_id)}` | pub/sub (no storage) | n/a |

Raw bearer tokens / user ids are never part of key names.

## Failure behavior (contract)

- **CACHE miss/failure** → caller falls back to Supabase (source of truth).
- **SESSION** → durable auth semantics unchanged; Redis only accelerates.
  Revocation is enforced by `touch_session`, which still runs per request
  for bound sessions.
- **RATE LIMIT** → falls back to the process-local limiter (fail-safe:
  enforcement continues on every instance; never disabled).
- **PUB/SUB** → best-effort delivery. Producers never fail on publish
  errors; durable state changes are always written to Supabase first, and
  clients recover state via REST.

## Frontend integration boundary

An SSE/WebSocket gateway should subscribe to
`loqi:v1:events:user:{hash}` for the authenticated user and forward JSON
events (`{"type":"job.progress","job_id":…,"status":…,"progress":…}`).
Until it ships, the frontend continues polling — nothing breaks.

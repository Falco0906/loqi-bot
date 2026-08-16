# SaaS-1 — Loqi SaaS Identity Boundary

This document describes the enforceable identity/security boundary for the
Loqi SaaS backend. It is written against the implemented code
(`backend/services/identity/`, `backend/services/organizations/`,
`backend/main.py`) — do not treat aspirational features as present.

Related: `backend/docs/ADR-0012_AUTHENTICATION_FLOWS.md`,
`backend/supabase/migrations/021_identity_sessions.sql`,
`backend/docs/ROLLBACK_RECOVERY.md`.

---

## 1. Authentication architecture

### Credential model (current, implemented)

- **Access tokens are opaque session ids.** The value minted at login /
  signup-completion is the identity `sessions.id` (a UUID), NOT a JWT.
- **TTLs (configured, enforced by the session service):**
  - Access token / session TTL: **15 minutes** (`session_ttl_seconds = 900`),
    sliding on activity when `extend_on_activity` is enabled.
  - Refresh token TTL: **30 days** (`refresh_token_ttl_seconds = 2592000`).
  - Verification token TTL: **15 minutes**; password-reset token TTL:
    **15 minutes**.
- **Refresh tokens are stored as SHA-256 hashes**, never plaintext
  (`CryptoService.hash_token`). The raw token is returned to the client once.
  At most one **active** refresh token may exist per family
  (`refresh_tokens_family_active_uidx`, migration 022); a concurrent rotation
  of the same token is treated as replay and revokes the family + session.
- **Passwords** are hashed with **Argon2id** (`argon2-cffi`); hashes are
  never returned by any endpoint and never logged.
- **Emails** are normalized to lowercase (case-insensitive) before lookup and
  storage, and must be verified before an account can activate. Email
  identities, password credentials, and registration sessions are persisted
  in Supabase (migration 022) so the signup→login lifecycle survives restarts
  and multi-instance operation; login requires a verified primary email
  identity and an active organization membership.

### Canonical authentication dependency

There is ONE way for a protected route to learn the caller:

```python
from services.identity.dependencies import get_current_auth

@router.get("/protected")
async def protected(auth: AuthContext = Depends(get_current_auth)):
    return {"user_id": auth.user_id, "session_id": auth.session_id}
```

`get_current_auth` (and `get_current_user_id`) enforce:
- missing `Authorization` header → 401
- malformed header (non-`Bearer` scheme / empty token) → 401
- invalid / expired access token → 401
- revoked session → 401

Routes must **never** trust a client-supplied `user_id` /
`organization_id` when identity can be derived from the token. Where a query
param was previously accepted (`/me?user_id=`, `/sessions?user_id=`,
strategic-intelligence `user_id`), the value is ignored and the caller's
identity is used instead.

**Canonical rule:** authenticated identity is derived from the validated
authentication context; client-supplied identity fields are not trusted for
actor identity.

---

## 2. Public vs protected routes

### Intentionally public

| Group | Routes |
|---|---|
| Ops / liveness / readiness | `GET /health`, `GET /ready`, `GET /version` |
| Auth entry points | `/api/v1/auth/signup/email`, `/signup/email/verify`, `/signup/email/complete`, `/signup/email/status/{id}`, `/login`, `/refresh`, `/logout`, `/password-reset/request`, `/password-reset/confirm` |
| OAuth entry | `/api/v1/auth/oauth/google`, `/api/v1/auth/oauth/google/callback` |
| Gmail connect | `/api/auth/gmail/url`, `/api/auth/gmail/callback` |
| Callback / webhook | `POST /webhook` (Telegram; secret-authenticated when `TELEGRAM_WEBHOOK_SECRET` is set), `/api/v1/billing/webhooks/stripe` |
| Public catalogs | `/api/v1/billing/plans`, `/api/v1/capabilities` (definition catalog only) |
| Web-session bootstrap | `POST /api/web/session` |

### Require authentication (protected)

| Group | Enforcement |
|---|---|
| `/api/v1/auth/me` | canonical dependency |
| `/api/v1/auth/sessions`, `/api/v1/auth/sessions/{id}` | canonical dependency + ownership check |
| `/api/v1/auth/password/change` | canonical dependency |
| `/api/v1/organizations/*` | canonical dependency + org membership / role boundary |
| `/api/v1/organizations/{id}/capabilities...` | canonical dependency + org membership; enable/disable require OWNER/ADMIN |
| `/api/v1/onboarding/*` | canonical dependency in production (dev keeps legacy user_id contract) |
| `/api/v1/strategic-intelligence/generate`, `/profile/{user_id}` | canonical dependency; actor derived from token |
| `/api/v1/billing/subscription`, `/checkout`, `/customer-portal`, `/cancel`, `/resume` | canonical dependency + actor must be a member of the target organization |
| `/api/jobs/*`, `/api/discoveries/*` | web-session auth (identity or web-session bearer) |
| `/api/web/session/*` (except bootstrap) | bearer middleware (`main.py: require_web_session_auth`) |

Rate limiting is applied globally (per-IP for auth endpoints,
per-user where a web-session user is resolvable) and is **not** bypassed by
auth routes.

---

## 3. Token lifecycle

1. **Login / signup completion** → `AuthService` creates a session (access
   token = `session.id`) and an initial refresh token (family `F`, sequence 1).
2. **Refresh** (`POST /api/v1/auth/refresh`) rotates the token:
   - the presented refresh token is marked revoked,
   - a new refresh token in the **same family** is minted with
     `sequence + 1`,
   - the session's `last_activity_at` / `expires_at` are touched.
3. **Replay detection**: presenting an already-rotated (revoked) refresh
   token is treated as theft — the **entire family** and the **session** are
   revoked.
4. **Logout** revokes the session and the whole refresh family for that
   session.

Sensitive tokens are never logged (request bodies are not logged; paths are
redacted via `RequestLoggingMiddleware`).

---

## 4. Session lifecycle

- Created on login/signup-completion/OAuth; capped at
  `max_active_sessions_per_user = 25`.
- Expiry enforced server-side on every access-token validation; an expired
  session is revoked at that point.
- Revocation propagates to refresh tokens for that session.
- `GET /api/v1/auth/sessions` lists the authenticated caller's active
  sessions; `DELETE /api/v1/auth/sessions/{id}` revokes only a session the
  caller owns (cross-user revocation returns 404).
- Password change revokes **all other** sessions (current session survives).
- Password reset revokes **all** sessions and tokens for the user.

### 4.1 Session authority (SaaS-1.6 — web-session consolidation)

The canonical SaaS identity session is the **single authoritative session
model**. The legacy web-session boundary (`/api/web/session/*`, jobs,
discoveries, providers) is a **compatibility surface that resolves through
the canonical model**:

- When the web-session bootstrap is invoked with a valid canonical access
  token, the issued web-session token is durably bound to the canonical user
  and canonical session (`web_session_bindings`, migration 024).
- A bound web-session resolves the actor to the **canonical user id** (never
  to a synthetic legacy user), and is authorized **only while that canonical
  session remains valid** (`main._resolve_session_context` touches the
  canonical session on use; revoked/expired → 401).
- Therefore logout, password change, and password reset (which revoke the
  canonical session) **invalidate the bound web-session** — the web-session
  cannot outlive the canonical session it was created from.
- Unbound (anonymous/pre-auth) web-sessions keep legacy behavior and do not
  represent an authenticated SaaS identity.
- Workspace/jobs/discoveries/provider routes receive the same actor identity
  resolved from the token (identity access token **or** bound web-session);
  a client-supplied `user_id`/`workspace_id` never overrides it.
- OAuth callback results are **not cached in memory** (no token-bearing
  replay cache); a consumed OAuth state is rejected on replay (401).

There is a single session persistence path (identity `SessionRepository` /
`021_identity_sessions.sessions`); no duplicate session store is used by the
identity boundary.

---

## 5. Password & password reset

- Argon2id hashing; policy enforced server-side (min length 12, upper/lower,
  digit, special).
- `POST /api/v1/auth/password/change` (authenticated): verifies the current
  password, sets the new hash, revokes other sessions/tokens.
- `POST /api/v1/auth/password-reset/request`: sends a single-use,
  15-minute expiring token. The response is identical whether or not the
  account exists (no enumeration).
- `POST /api/v1/auth/password-reset/confirm`: validates email + token hash,
  marks the request used, invalidates all pending reset requests for the
  user, sets the new password, and revokes **all** sessions/tokens.

---

## 6. User & organization isolation

### User isolation (IDOR/BOLA)

- Caller identity always comes from the token.
- `/me` returns the token owner's profile regardless of any client-supplied
  `user_id`.
- `/sessions` returns only the token owner's sessions.
- `/sessions/{id}` verifies the session belongs to the token owner.
- Regression-tested: User A cannot list/read/revoke User B's sessions or
  read User B's `/me`.

### Organization boundary

- Every org-scoped route (`/api/v1/organizations/{org_id}...`) enforces a
  membership check derived from the token (404 for non-members — avoids
  disclosing whether an org exists).
- Privileged mutations require the caller to be an **OWNER or ADMIN** member
  (role/store changes, member removal, invitations); deleting/transferring
  an org requires **OWNER**.
- Materialized access is enforced at the API boundary AND in the
  organization services (defense in depth).
- Capabilities: org-scoped capability reads require membership; enable/disable
  require OWNER/ADMIN (`/api/v1/organizations/{id}/capabilities...`).
- Billing: subscription/checkout/portal/cancel/resume require the actor to be
  an active member of the target organization (client-supplied
  `organization_id` cannot select another tenant's billing state).
- Invitation tokens are returned on create (inviter) but are **redacted** in
  the members-only list endpoint.
- Regression-tested: a non-member cannot read another org, its members, or
  its invitations; unauthenticated org reads are rejected; cross-org
  capability/billing targeting is rejected; MEMBER cannot perform ADMIN/OWNER
  actions.

---

## 6.5 OAuth identity boundary

- **Routes**: identity OAuth login (`/api/v1/auth/oauth/google` +
  `/oauth/google/callback`) is a public login entry point; Gmail connect
  (`/api/auth/gmail/url` + `/api/auth/gmail/callback`) resolves the actor from
  an `Authorization` header when present; the legacy Telegram flow
  (`/google/callback` + `conversation_engine.get_gmail_connect_url`) uses
  server-issued state. `/google/callback` never trusts a client-constructed
  `user_id`.
- **State**: every OAuth flow uses server-issued, cryptographically random,
  single-use, expiring state tokens. State is persisted in `oauth_sessions`
  (migration 023) under the SUPABASE provider so a callback landing on another
  instance or after a restart still validates. `used_at` enforces single-use;
  `expires_at` enforces the 10-minute TTL; `user_id` binds the state to the
  initiating identity/context.
- **Callback ownership**: the callback derives the owning identity from the
  validated state (and, where initiated from an authenticated session, the
  canonical access token). A state for user A cannot be replayed, expired, or
  reinterpreted for user B.
- **External identity mapping**: Google `sub` → `external_identities`
  (migration 005). Resolution falls back to the durable store when the
  in-process repository misses, so a Google identity is reused rather than
  duplicated after a restart. Ambiguous matches fail safely (no merging by
  email alone beyond the existing email-identity linking rule).
- **Connected accounts**: owned by the state-bound user; provider records are
  scoped per user and never become global credentials.
- **Provider tokens**: raw access/refresh tokens are AES-256-GCM encrypted at
  rest (credential_crypto) and never returned in responses or logs.

---

## 7. Security assumptions

- The access token is a bearer credential: possession is authenticity.
  Clients must store it in memory / secure storage and must never put it in
  URLs, logs, or third-party analytics.
- Refresh tokens live in storage on the client; the server only ever holds
  their SHA-256 hash and the raw value is issued once.
- Rate limiting is **per-instance, in-memory**; multi-instance deployments
  need a shared store (documented limitation — not a hidden claim).
- Initiation of the identity session is a server-side random UUID; it is not
  a JWT with a signature, so there is no rollback of the validation model —
  expiry/revocation are enforced against the sessions table.
- `IDENTITY_PEPPER` / `IDENTITY_SIGNING_KEY_*` default to development values
  when unset; production must set real values (see
  `services/config_validation.py`).

---

## 8. Frontend client authentication guide

1. **Signup** → collect email → `POST /api/v1/auth/signup/email`.
2. The user follows the emailed verification link (or submits the token) →
   `POST /api/v1/auth/signup/email/verify`. Poll status with
   `GET /api/v1/auth/signup/email/status/{registration_session_id}`.
3. After verification → `POST /api/v1/auth/signup/email/complete` with
   `{registration_session_id, display_name, password, organization_name}`.
   Store `access_token` and `refresh_token` securely.
4. **Login** → `POST /api/v1/auth/login` → store tokens.
5. **Authenticated requests**:
   ```
   Authorization: Bearer <access_token>
   ```
6. **Refresh** (when you get 401, or proactively before the 15-minute TTL):
   `POST /api/v1/auth/refresh` with `{refresh_token}` → replace both tokens.
   A revoked / replayed refresh response means the user must log in again.
7. **Logout** → `POST /api/v1/auth/logout` with `{refresh_token}` → discard
   local tokens.
8. **Session management UI** → `GET /api/v1/auth/sessions`,
   `DELETE /api/v1/auth/sessions/{session_id}`.
9. **Password** → `POST /api/v1/auth/password/change` (while logged in),
   `POST /api/v1/auth/password-reset/request` and
   `POST /api/v1/auth/password-reset/confirm` (while logged out).

OAuth (Google): redirect to `GET /api/v1/auth/oauth/google`, then complete
the flow at the callback; the returned tokens replace credentials.

Never pass `user_id` to prove identity — the server derives it from the
token.
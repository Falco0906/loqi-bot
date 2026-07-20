# ADR-0013 — Security Architecture

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **DRAFT** |

---

## Decision

The Security Platform is established as a modular subsystem responsible for all authorization and security enforcement.

Security determines WHAT a user may do. Identity determines WHO a user is. The two platforms are separate but interdependent: Security consumes `IdentityContext` produced by Identity.

---

## Rationale

Security concerns scattered across business logic create:

- Inconsistent authorization checks
- Missing audit trails
- Hard-to-review permission models
- Difficult security hardening

A centralized Security Platform provides a single enforcement layer between authenticated identity and business operations.

---

## Security Principles

### Security by default

Every endpoint denies access unless explicitly permitted. New features require explicit authorization rules.

### Least privilege

Users and services receive the minimum permissions necessary. No default admin access. No elevated permissions without justification.

### Defense in depth

Multiple independent security layers: transport security → authentication → authorization → rate limiting → audit → threat detection. A failure in one layer is caught by another.

### Fail securely

On error, the Security Platform denies access. No fallback to permissive mode. Authorization failures return 403, never 500 with sensitive details.

### Tenant isolation

Data from different Organizations is never accessible from another Organization's context. Organization ID is an immutable filter on every query.

### Secrets never hardcoded

All secrets (API keys, OAuth client secrets, encryption keys, database credentials) are stored in a secrets manager. Code references secrets by identifier, not by value.

### Sensitive operations audited

Every authentication event, authorization decision, role change, and security-sensitive operation produces an audit record. Audit logs are append-only and immutable.

### Cryptography centralized

All cryptographic operations (hashing, encryption, signing, random token generation) go through a single `CryptoService`. No ad-hoc cryptographic code in business logic.

### Authorization centralized

All authorization decisions go through a single `AuthorizationService`. Business logic calls `authorize(identity, action, resource)` and does not implement permission checks.

### Secure defaults

All defaults are secure. Session expiry defaults to conservative values. Token lifetimes are short. Rate limits are on by default. CORS is restrictive by default.

---

## Relationship with Identity

```
┌────────────────────────────────────────────────────┐
│                    Request                          │
└────────────────────┬───────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────┐
│              Identity Platform                       │
│  Authenticates → produces IdentityContext            │
│  {user_id, org_id, session_id, roles}               │
└────────────────────┬───────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────┐
│              Security Platform                       │
│  Authorizes → enforces policy                        │
│  Rate limits → protects resources                    │
│  Audits → records decisions                          │
└────────────────────┬───────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────┐
│              Business Logic                          │
│  Receives authorized IdentityContext                 │
│  Operates within org-scoped boundary                 │
└────────────────────────────────────────────────────┘
```

Identity authenticates. Security authorizes. Business logic executes.

---

## Security Modules

### Authentication

Responsibility: Validate authentication tokens and produce `IdentityContext`.

Not a full authentication system — that is Identity's role. This module:

- Validates access token signatures and expiry
- Extracts `user_id`, `org_id`, `session_id`, `roles` from token claims
- Rejects expired, malformed, or revoked tokens
- Rejects tokens from revoked sessions
- Produces `IdentityContext` for downstream use

### Authorization

Responsibility: Centralized decision engine for all access control.

```
authorize(
    identity: IdentityContext,
    action: str,          // "campaign.create", "conversation.read", etc.
    resource: Resource    // { type: "campaign", id: "uuid" }
) -> AuthorizationResult  // { allowed: bool, reason: str }
```

- All authorization decisions go through this single function
- No inline permission checks in business code
- Roles are resolved from Membership + Role definitions
- Resource ownership is verified (resource.org_id == identity.org_id)

Enforcement points:

| Layer | Mechanism |
|---|---|
| API Gateway / Middleware | Route-level auth (authenticated required, optional, none) |
| Service layer | Resource-level auth via `AuthorizationService` |
| Data layer | Org-scoped query filters (never removed) |

### Encryption

Responsibility: Manage data encryption at rest and in transit.

- TLS 1.3 for all network communication
- AES-256-GCM for data at rest (database-level + field-level for sensitive fields)
- Field-level encryption for: OAuth access tokens, OAuth refresh tokens, user emails (at rest), session tokens (at rest)
- Encryption keys managed by central `CryptoService`
- Key rotation supported via key versioning

### Cryptography

Responsibility: Centralized cryptographic operations.

```
CryptoService {
    hash_password(plaintext) -> hash        // Argon2id
    verify_password(plaintext, hash) -> bool
    encrypt(plaintext, context) -> ciphertext
    decrypt(ciphertext, context) -> plaintext
    sign(data, key_id) -> signature
    verify(data, signature, key_id) -> bool
    random_token(length) -> token           // cryptographically secure
    generate_key() -> key
}
```

- Only `CryptoService` performs cryptographic operations
- Password hashing uses Argon2id with configurable memory/time/parallelism
- Token generation uses `secrets.token_urlsafe` (cryptographically secure)
- No business code imports `hashlib`, `cryptography`, or `secrets` directly

### Audit

Responsibility: Immutable record of security-sensitive events.

Audited events:

| Event Type | Trigger | Data captured |
|---|---|---|
| `user.login` | Successful authentication | user_id, session_id, ip, user_agent, provider |
| `user.login.failed` | Failed authentication | attempted_email, ip, reason |
| `user.logout` | Session end | user_id, session_id |
| `user.logout.all` | Bulk session end | user_id, revoked_session_count |
| `user.password.change` | Password updated | user_id |
| `user.password.reset` | Password reset completed | user_id |
| `session.refresh` | Token rotation | user_id, session_id, old_sequence, new_sequence |
| `session.revoke` | Session revoked | user_id, session_id, revoker_id |
| `authorization.deny` | Access denied | identity, action, resource, reason |
| `authorization.grant` | Access granted (for high-risk actions) | identity, action, resource |
| `org.member.add` | Member added to org | org_id, new_member_id, added_by |
| `org.member.remove` | Member removed from org | org_id, removed_member_id, removed_by |
| `org.member.role.change` | Role changed | org_id, member_id, old_role, new_role, changed_by |
| `invitation.create` | Invitation sent | org_id, invitee_email, invited_by |
| `invitation.accept` | Invitation accepted | org_id, user_id, invitation_id |

Audit records are:

- Append-only (no UPDATE, no DELETE)
- Time-ordered
- Tamper-evident (chain hashes for future implementation)
- Retained per compliance requirements

### Rate Limiting

Responsibility: Protect resources from abuse.

| Endpoint | Rate limit | Window | Burst |
|---|---|---|---|
| `POST /auth/login` | 5 | 60s | — |
| `POST /auth/signup/email` | 3 | 300s | — |
| `POST /auth/signup/email/verify` | 5 | 300s | — |
| `POST /auth/password-reset/request` | 3 | 300s | — |
| `POST /auth/password-reset/complete` | 3 | 300s | — |
| `POST /auth/refresh` | 10 | 60s | — |
| All other endpoints | 100 | 60s | 20 |

Rate limits are keyed by:

- IP address (unauthenticated)
- user_id (authenticated)
- org_id (authenticated, org-scoped)

### Secret Management

Responsibility: Secure storage and retrieval of secrets.

- All secrets stored in a secrets manager (environment variables for self-hosted, Secrets Manager for cloud)
- Code references secrets by environment variable name or secret identifier
- Secrets never appear in logs, error messages, or stack traces
- Secrets never committed to version control
- Secret rotation supported without code changes
- Access to secrets audited

Secret categories:

| Category | Examples |
|---|---|
| Database | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` |
| Encryption | `ENCRYPTION_KEY`, `TOKEN_SIGNING_KEY` |
| API Keys | `OPENAI_API_KEY`, `APOLLO_API_KEY`, `SERP_API_KEY` |
| Email | `SMTP_PASSWORD`, `SENDGRID_API_KEY` |

### Session Security

Responsibility: Protect session integrity.

- Access tokens: short-lived (15min default), JWT or opaque
- Refresh tokens: longer-lived (30d default), opaque, rotation-enabled
- Refresh token rotation: single-use, family-based, theft detection
- Session tracking: all active sessions tracked for device management
- Session revocation: individual or bulk, immediate effect
- No session tokens in URLs
- HttpOnly + Secure + SameSite=Strict cookies for browser clients
- CSRF tokens for state-changing requests (when using cookie-based auth)

### Threat Detection

Responsibility: Detect and respond to security threats.

Detection scenarios (planned, future implementation):

| Scenario | Detection | Response |
|---|---|---|
| Brute force login | Consecutive failed logins (5 within 60s) | Rate limit + temporary IP ban |
| Credential stuffing | Failed logins from different IPs for same user | Account lockout + notification |
| Token theft | Revoked refresh token presented | Revoke entire family, notify user |
| Session hijacking | Geographic anomaly (login from different continent within 1min) | Session revocation + notification |
| API abuse | Unusual request rate from single user/org | Rate limit escalation + notification |
| Enumeration attack | Sequential access attempts on user IDs | Rate limit + IP ban |

### Middleware

Responsibility: Request-level security enforcement.

Middleware chain (applied in order):

1. **TLS termination** — HTTPS enforced (production only)
2. **CORS** — Restricted to configured origins. No `Access-Control-Allow-Origin: *` in production.
3. **Rate limiting** — Per-IP and per-user rate limits enforced
4. **Authentication** — Token extraction and validation. Produces `IdentityContext`.
5. **Request validation** — Input sanitization, content-type validation, size limits
6. **Authorization** — Route-level access control (authenticated required/optional)
7. **Audit** — Record security-relevant events
8. **Business logic** — Downstream handlers receive `IdentityContext`

### Validation

Responsibility: Input validation and sanitization.

- All request input validated against schema
- Email format validated server-side (not just client-side)
- Password policy enforced server-side
- SQL injection prevented via parameterized queries (Supabase client handles this)
- No eval() or dynamic code execution from user input
- Content-Type enforced per endpoint
- Request size limits enforced

### Future enterprise policies

The Security Platform architecture supports future enterprise features:

| Feature | Integration point |
|---|---|
| IP whitelisting | Middleware layer, org-scoped configuration |
 | Device compliance | Session metadata + middleware check |
| MFA enforcement | Authorization module: require MFA for sensitive actions |
| SSO enforcement | Identity platform: restrict to configured IdP |
| Data residency | Encryption module: region-tagged encryption keys |
| Just-in-time access | Authorization module: time-bound role grants |
| Approval workflows | Audit + Authorization: require second approval for sensitive actions |
| SIEM integration | Audit module: structured log export (JSON, CEF, Syslog) |

---

## Security Guarantees

| Guarantee | Mechanism |
|---|---|
| **Organization isolation** | Every query includes org_id filter. AuthorizationService verifies resource ownership. No cross-org data access. |
| **Refresh token rotation** | Single-use refresh tokens. Family-based rotation. Theft detection on reused tokens. |
| **HttpOnly cookies** | Session tokens stored in HttpOnly, Secure, SameSite cookies. Not accessible via JavaScript. |
| **PKCE** | All OAuth flows use Proof Key for Code Exchange. Authorization code interception attack prevented. |
| **Replay protection** | OAuth authorization codes single-use. Refresh tokens single-use. State parameters random and single-use. |
| **Single-use verification links** | Email verification, password reset, invitation tokens one-time use. Expire after 15 minutes. |
| **Password hashing** | Argon2id with configurable memory (64MB), time (3 iterations), parallelism (4). Salted per password. |
| **Audit logging** | All security-sensitive events recorded. Append-only, immutable, tamper-evident. |
| **Session revocation** | Individual session revocation. Bulk revocation (user-level, org-level). Immediate effect. |
| **Rate limiting** | Per-IP and per-user rate limits on auth endpoints. Escalation on abuse. |
| **Secrets management** | No hardcoded secrets. All secrets in secrets manager. Rotation without code changes. |
| **CORS restrictions** | Whitelist-only origins. No wildcard in production. |
| **TLS enforcement** | TLS 1.3 required for all API communication. HSTS in production. |
| **Input validation** | All input validated against schema. Content-Type enforced. Size limits applied. |

---

## References

- ADR-0011 — Identity Platform (identity boundaries, IdentityContext)
- ADR-0012 — Authentication Flows (rate limit specifics, session refresh details)

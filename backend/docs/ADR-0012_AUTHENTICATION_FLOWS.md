# ADR-0012 — Authentication Flows

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **DRAFT** |

---

## Decision

All authentication journeys follow a uniform orchestration pattern. Each flow is a sequence of well-defined transitions managed by the Identity Platform. No business logic participates in authentication.

This ADR documents every supported authentication journey and its transitions.

---

## Rationale

Authentication flows are the most security-sensitive code in the system. Documenting each flow before implementation ensures:

- Consistent security guarantees across all flows
- No missed edge cases (expired tokens, partial registration, concurrent sessions)
- Clear contracts for frontend and backend teams
- Auditable flow definitions for security review

---

## Flow Patterns

Every authentication flow follows one of two patterns:

### Pattern A: Provider-initiated (OAuth)

```
Client → POST /auth/signup/{provider}
         → Identity Platform stores state (PKCE, anti-forgery)
         → Returns provider authorize URL + state
Client → Redirect to provider
Provider → Callback to POST /auth/signup/{provider}/callback
         → Identity Platform validates state, exchanges code for tokens
         → Resolves or creates ExternalIdentity
         → Resolves or creates User
         → Creates Session + RefreshToken
         → Returns session tokens
```

### Pattern B: Multi-step registration (Email)

```
Client → POST /auth/signup/email { email }
         → Identity Platform creates VerificationToken
         → Sends verification email
Client → POST /auth/signup/email/verify { token }
         → Identity Platform validates token, marks email verified
         → EmailIdentity created
Client → POST /auth/signup/email/complete { name, password, org_name }
         → Identity Platform creates User, PasswordCredential, Organization
         → Creates Session + RefreshToken
         → Returns session tokens
```

---

## Flow: Email Signup

### State machine

```
[Start] → Submit email
         → [AwaitingVerification] → Verify link clicked
         → [EmailVerified] → Submit name + password + org
         → [Registered] → Session created
         → [Dashboard]
```

### Transitions

| # | Step | Action | Validation |
|---|---|---|---|
| 1 | Submit email | `POST /auth/signup/email` | Email format valid. Not already registered. |
| 2 | Send verification | System creates `VerificationToken` (purpose=verify_email, target=email, expires=15min). Sends email with link containing token. | — |
| 3 | Verify | `POST /auth/signup/email/verify` with token | Token exists. Token not expired. Token not used. Token matches target email. |
| 4 | Mark verified | `EmailIdentity` created with `is_verified=true`. Token marked `used_at=now`. | — |
| 5 | Complete registration | `POST /auth/signup/email/complete` with name, password, org_name | Email is verified. Name non-empty. Password meets policy (min 12 chars, complexity). Org name non-empty. |
| 6 | Create user | `User` record created. | — |
| 7 | Hash password | `PasswordCredential` created with Argon2id hash. | — |
| 8 | Create org | `Organization` created with user as owner. `Membership` created with owner role. | — |
| 9 | Create session | `Session` created with device info. `RefreshToken` created (family sequence=1). | — |
| 10 | Return tokens | Access token + refresh token returned. | — |

### Edge cases

| Scenario | Behavior |
|---|---|
| Email already registered | Return error on step 1. Allow login instead. |
| Expired verification link | Step 3 rejects. User may request new token (rate-limited). |
| Verification link used twice | Step 3 rejects. Token already marked used. |
| User closes browser after verification | Step 5 accepts within token expiry (15min). After expiry, user must restart from step 1. |
| Concurrent registration same email | First to verify wins. Second verification attempt rejected. |
| Password too weak | Step 5 rejects with policy requirements. |

---

## Flow: Google Sign-In

### State machine

```
[Start] → Click "Sign in with Google"
         → [OAuthRedirect] → Google consent screen
         → [OAuthCallback] → Identity resolved
         → [FirstLogin] → Org creation
         → [Dashboard]
         → [Returning] → [Dashboard]
```

### Transitions

| # | Step | Action | Validation |
|---|---|---|---|
| 1 | Initiate | `POST /auth/signup/google` | — |
| 2 | Generate state | Identity Platform creates PKCE challenge + anti-forgery state. Stores temporarily. | — |
| 3 | Redirect | Returns Google authorize URL with state + code_challenge. | — |
| 4 | User consents | Google shows consent screen. User approves. | — |
| 5 | Callback | `POST /auth/signup/google/callback` with code + state. | State matches stored value. State not expired (10min). |
| 6 | Exchange code | Server exchanges code for tokens via Google API. | Google validates code. |
| 7 | Resolve identity | Extract sub, email, name, avatar from id_token. | Email verified by Google. |
| 8 | Check existing | Look up `ExternalIdentity` by provider + sub. | — |
| 9a | New user | Create User + ExternalIdentity + Organization + Membership + Session. | — |
| 9b | Returning user | Resolve User from ExternalIdentity. Activate Membership for current org (or use default). Create Session. | — |
| 10 | Return tokens | Access token + refresh token returned. | — |

### Edge cases

| Scenario | Behavior |
|---|---|
| Google email already used for email signup | Return error: account exists with different provider. Allow user to login via email instead. |
| State parameter tampered | Step 5 rejects. State mismatch. |
| Authorization code reused | Google rejects on second exchange. Token replay prevented. |
| User cancels on Google consent | No callback received. Frontend timeout returns user to login. |
| Google email changed | Identity updated. Link remains valid via Google sub. |
| Delegated Google account | Treated as standard Google identity. |

---

## Flow: Microsoft Sign-In

Same architecture as Google Sign-In.

### Differences

| Aspect | Google | Microsoft |
|---|---|---|
| Provider type | `google` | `microsoft` |
| OAuth endpoints | Google Identity Platform | Microsoft Entra ID |
| Token issuer | `accounts.google.com` | `login.microsoftonline.com` |
| Tenant | Consumer | Consumer or enterprise tenant |
| Scope | `openid profile email` | `openid profile email User.Read` |

### Enterprise Microsoft accounts

When a user authenticates with a Microsoft Entra ID (work/school) account, the Identity Platform records the tenant ID in the `ExternalIdentity` record. This enables future enterprise SSO scenarios where an Organization can restrict membership to a specific tenant.

### Transitions

Identical to Google flow with `microsoft` as the provider type.

---

## Flow: Password Reset

### State machine

```
[Login] → Click "Forgot password"
         → [RequestReset] → Email sent
         → [AwaitingReset] → Click reset link
         → [Resetting] → Submit new password
         → [Complete] → Sessions invalidated
         → [Login]
```

### Transitions

| # | Step | Action | Validation |
|---|---|---|---|
| 1 | Request | `POST /auth/password-reset/request` with email | Email has registered User. |
| 2 | Create token | `PasswordResetRequest` created with token (expires=15min). | — |
| 3 | Send email | Email sent with reset link containing token. | — |
| 4 | Verify token | `POST /auth/password-reset/complete` with token + new password | Token exists. Token not expired. Token not used. Token matches user. |
| 5 | Hash password | `PasswordCredential` updated with new Argon2id hash. | Password meets policy. |
| 6 | Invalidate sessions | All `Session` records for user revoked. All `RefreshToken` records in all families revoked. | — |
| 7 | Return success | User redirected to login. | — |

### Edge cases

| Scenario | Behavior |
|---|---|
| Email not registered | Step 1 returns success (prevent enumeration). Email not sent. |
| Expired reset link | Step 4 rejects. User must request new reset. |
| Reset link used twice | Step 4 rejects. Token already marked used. |
| Reset during active session | Session still valid until password changes. Step 6 invalidates all sessions (including current). |
| Attacker requests reset for victim | Victim receives email. No account compromise possible without email access. |
| Rate limiting | Max 1 reset request per email per 60s. Max 5 per email per 24h. |

---

## Flow: Session Refresh

### State machine

```
[Active] → Access token expires
         → [TokenExpired] → Send refresh token
         → [TokenRotated] → New access token issued
         → [Active]
```

### Transitions

| # | Step | Action | Validation |
|---|---|---|---|
| 1 | Detect expiry | Client detects 401 or pre-emptive expiry check. | — |
| 2 | Send refresh | `POST /auth/refresh` with current refresh token. | Token exists. Token not expired. Token not revoked. Token belongs to active session. Session not revoked. |
| 3 | Rotate | Current `RefreshToken` marked revoked. New `RefreshToken` created with same `family`, incremented `sequence`. | — |
| 4 | Issue | New access token + new refresh token returned. Old tokens invalidated. | — |

### Refresh token rotation

- Each refresh creates a new refresh token and revokes the previous one
- Refresh tokens are single-use by design
- A stolen refresh token can be used at most once (race window mitigated below)
- Each refresh increments `sequence` within a `family`

### Race window mitigation

If an attacker and legitimate user both present the same refresh token concurrently:

1. First request succeeds: token N revoked, token N+1 issued
2. Second request fails: token N already revoked
3. The Session is flagged for potential token theft

Detection: if a revoked refresh token is presented, the entire Session family is revoked and the User is notified.

### Edge cases

| Scenario | Behavior |
|---|---|
| Refresh token expired | Step 2 rejects. User must re-authenticate. |
| Session revoked | Step 2 rejects. User must re-authenticate. |
| Refresh token stolen | First use succeeds. Second use detected as theft. Session revoked. |
| Long idle period | Session expires after configured TTL (default 30d). User must re-authenticate. |
| Concurrent refresh requests | First wins. Second fails with token_revoked. |

---

## Flow: Logout

### Single session logout

| # | Step | Action |
|---|---|---|
| 1 | Client sends | `POST /auth/logout` with current refresh token |
| 2 | Revoke token | Current `RefreshToken` marked revoked |
| 3 | Revoke session | `Session` marked revoked_at = now |
| 4 | Clear client | Client discards stored tokens |

### Logout all sessions

| # | Step | Action |
|---|---|---|
| 1 | Client sends | `POST /auth/logout/all` with current refresh token (authenticates request) |
| 2 | Revoke all tokens | All `RefreshToken` records for user (all families) marked revoked |
| 3 | Revoke all sessions | All `Session` records for user marked revoked_at = now |
| 4 | Clear client | Client discards stored tokens |

### Edge cases

| Scenario | Behavior |
|---|---|
| Logout with expired token | Accept. Invalid tokens still identify the session (via session_id claim). |
| Logout all from unknown device | All sessions revoked, including the requesting one. User must re-authenticate everywhere. |
| Session already revoked | Idempotent. Return success. |

---

## Flow: Device Management

### List sessions

| # | Step | Action |
|---|---|---|
| 1 | Authenticate | Request carries refresh token or access token |
| 2 | List | `GET /auth/sessions` returns all active sessions for user (device, last activity, created) |
| 3 | Display | Client shows session list for user review |

### Revoke specific device

| # | Step | Action |
|---|---|---|
| 1 | Authenticate | Request carries current session token |
| 2 | Verify ownership | Target session belongs to requesting user (or user has admin role) |
| 3 | Revoke | `DELETE /auth/sessions/{id}` revokes target session + all its refresh tokens |
| 4 | Notify | Optional: email notification of new device login (planned future capability) |

---

## Cross-Cutting Guarantees

| Guarantee | Applies to |
|---|---|
| All verification/reset tokens single-use | Email signup, password reset, invitations |
| All tokens expire (max 15min) | Verification tokens, reset tokens, OAuth state |
| Refresh tokens rotate on every use | Session refresh |
| Sessions revocable individually or in bulk | Logout, device management, password reset |
| Rate limiting on sensitive endpoints | Signup, login, password reset, email verification |
| No user enumeration via error messages | Login, password reset, signup |
| PKCE for all OAuth flows | Google, Microsoft, future providers |
| HttpOnly, Secure, SameSite cookies for token storage | All flows |
| CSRF protection for cookie-based auth | All browser flows |
| Audit events for sensitive transitions | All flows (login, logout, password change, role change) |

---

## References

- ADR-0011 — Identity Platform (domain models, provider contract)
- ADR-0013 — Security Architecture (rate limiting, audit, session security)

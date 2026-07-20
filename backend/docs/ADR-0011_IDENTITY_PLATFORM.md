# ADR-0011 — Identity Platform

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-19 |
| **Status** | **DRAFT** |

---

## Decision

The Identity Platform is established as a modular subsystem responsible for all identity concerns: user registration, authentication, session management, provider integration, and organization membership.

Identity is separated from Security. Identity determines WHO a user is. Security determines WHAT a user may do.

---

## Rationale

Loqi has grown through five platform phases without a formal identity layer. Continuing to build business features without identity contracts creates technical debt: scattered authentication logic, inconsistent session handling, and tight coupling between identity and product code.

A formal Identity Platform provides:

- A single source of truth for user identity
- Clear ownership boundaries between identity and business logic
- Pluggable provider architecture for future authentication methods
- Organization-scoped resource isolation

---

## Goals

- Provide a single, consistent identity subsystem for all Loqi interfaces (Telegram, Web, API, future WhatsApp, Mobile, Slack)
- Support multiple authentication providers through a uniform abstraction
- Enable organization-scoped multi-tenancy
- Provide session management with refresh token rotation
- Support invitation-based organization membership
- Maintain a clean separation between identity and business logic

## Non-Goals

- Authorization policies or role-based access control (owned by Security Platform)
- API key management or service-to-service auth
- Password strength policies or passwordless flow design (may be added later)
- Enterprise SSO configuration UI (pluggable later via IdentityProvider)
- User profile data beyond identity essentials (name, email, avatar URL)
- Email delivery infrastructure for verification/reset emails

---

## Core Principles

1. **Identity is separate from Security.** Identity authenticates. Security authorizes. Never conflate the two.

2. **Everything after authentication belongs to an Organization.** Every resource — campaigns, conversations, contacts, workflows, memory — is scoped to an Organization. A User accesses resources through a Membership.

3. **Identity does not know business logic.** The Identity Platform has no concept of campaigns, outreach, leads, or any Loqi product feature. It manages users, sessions, and organization membership only.

4. **Business platforms never authenticate users themselves.** Authentication is the Identity Platform's sole responsibility. Business code receives an authenticated identity (user_id + org_id) or rejects the request.

5. **Providers are pluggable.** New authentication methods (Google, Microsoft, GitHub, SAML, OIDC, Passkeys) are added by implementing the IdentityProvider contract — never by modifying authentication flow orchestration.

6. **Sessions are revocable.** Every session and refresh token can be individually revoked. Bulk revocation (user-level, org-level) is supported.

---

## Relationship to the Security Platform

| Concern | Owner |
|---|---|
| Who is this user? | Identity |
| Is this user who they claim to be? | Identity |
| Can this user perform this action? | Security |
| Is this request tampered with? | Security |
| Should this request be rate-limited? | Security |
| What organization does this user belong to? | Identity |
| What roles does this user have in this org? | Security |
| Should this operation be audited? | Security |

Identity produces a verified `IdentityContext`. Security consumes it to enforce authorization.

---

## Identity Boundaries

### Identity owns

- User records
- Email identity verification
- Password hashing and verification
- Session creation and lifecycle
- Refresh token issuance, rotation, and revocation
- Identity provider integration (OAuth callbacks, token exchange)
- Organization creation
- Membership management (invite, accept, remove)
- Verification token generation and validation
- Password reset flows

### Identity does NOT own

- Authorization policies
- Role definitions or role assignments
- API rate limiting
- Request validation beyond identity tokens
- Audit logging (but may emit audit events)
- Encryption at rest or in transit
- Secrets management
- Business logic of any kind

---

## Public Interfaces

The Identity Platform exposes three interface categories:

### 1. API Endpoints (HTTP)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/signup/email` | Begin email registration |
| POST | `/auth/signup/email/verify` | Verify email with token |
| POST | `/auth/signup/email/complete` | Complete registration (name + password + org) |
| POST | `/auth/signup/google` | Begin Google OAuth |
| POST | `/auth/signup/google/callback` | Complete Google OAuth |
| POST | `/auth/signup/microsoft` | Begin Microsoft OAuth |
| POST | `/auth/signup/microsoft/callback` | Complete Microsoft OAuth |
| POST | `/auth/login` | Authenticate and receive session |
| POST | `/auth/refresh` | Rotate refresh token |
| POST | `/auth/logout` | End current session |
| POST | `/auth/logout/all` | End all sessions for user |
| GET | `/auth/sessions` | List active sessions |
| DELETE | `/auth/sessions/{id}` | Revoke specific session |
| POST | `/auth/password-reset/request` | Request password reset |
| POST | `/auth/password-reset/complete` | Complete password reset |
| POST | `/orgs` | Create organization |
| GET | `/orgs/{id}/members` | List members |
| POST | `/orgs/{id}/invite` | Invite user to organization |
| POST | `/orgs/invite/accept` | Accept invitation |
| DELETE | `/orgs/{id}/members/{userId}` | Remove member |

### 2. IdentityContext (internal contract)

Every authenticated request produces an `IdentityContext`:

```
IdentityContext {
    user_id: UUID
    org_id: UUID
    session_id: UUID
    roles: List[Role]
    issued_at: DateTime
    expires_at: DateTime
}
```

This context is passed to Security Platform for authorization and forwarded to business logic as the authenticated identity.

### 3. IdentityProvider (pluggable contract)

```
IdentityProvider {
    provider_type: ProviderType  // email, google, microsoft, github, etc.
    initiate_auth(redirect_uri) -> AuthRequest
    handle_callback(code, state) -> ExternalIdentity
    link(user_id, external_identity) -> LinkResult
    unlink(user_id, provider_type) -> UnlinkResult
}
```

---

## Platform Responsibilities

1. **User lifecycle:** registration, verification, profile updates, account deletion
2. **Session lifecycle:** creation, validation, refresh, revocation
3. **Provider orchestration:** uniform flow for any auth provider
4. **Organization lifecycle:** creation, membership management, deletion
5. **Invitation lifecycle:** create, send, accept, expire
6. **Password management:** hashing (Argon2id), reset flow, change
7. **Verification token management:** generate, validate, expire

---

## Core Domain Objects

### User

The central identity record. Created during registration. May belong to multiple Organizations through Memberships.

Fields: `id`, `display_name`, `avatar_url`, `locale`, `created_at`, `updated_at`, `deleted_at`

### EmailIdentity

Represents a verified email address for a User. A User may have multiple EmailIdentities but one is designated as primary.

Fields: `id`, `user_id`, `email`, `is_verified`, `is_primary`, `verified_at`, `created_at`

### PasswordCredential

A hashed password bound to a User. Currently the only credential type for email-based auth. Future types may include Passkeys.

Fields: `id`, `user_id`, `password_hash` (Argon2id), `created_at`, `last_changed_at`

### IdentityProvider

An external authentication provider configuration. Each provider instance represents a configured OAuth app (e.g., "Loqi Google OAuth", "Loqi Microsoft OAuth").

Fields: `id`, `provider_type` (google, microsoft, github, etc.), `client_id` (reference to secret), `enabled`, `config` (provider-specific JSON), `created_at`

### Organization

The top-level resource container. Everything after authentication belongs to an Organization.

Fields: `id`, `name`, `slug`, `owner_id`, `created_at`, `updated_at`, `deleted_at`

### Membership

Links a User to an Organization. Contains role assignments (delegated to Security Platform).

Fields: `id`, `user_id`, `organization_id`, `role` (ref to Security role), `status` (active, invited, suspended), `invited_by`, `invited_at`, `accepted_at`

### Session

An authenticated browser/client session. Tracked for device management and revocation.

Fields: `id`, `user_id`, `organization_id`, `provider_type`, `device_info`, `ip_address`, `user_agent`, `last_activity_at`, `expires_at`, `revoked_at`, `created_at`

### RefreshToken

A rotating token bound to a Session. Used to obtain new access tokens without re-authentication.

Fields: `id`, `session_id`, `token_hash`, `family` (rotation chain identifier), `sequence` (rotation sequence number), `expires_at`, `revoked_at`, `created_at`

### VerificationToken

A single-use token for email verification, invitation acceptance, or similar one-time confirmation flows.

Fields: `id`, `purpose` (verify_email, accept_invite, etc.), `target` (email, membership_id), `token_hash`, `expires_at`, `used_at`, `created_at`

### Invitation

Represents a pending invitation for a User to join an Organization.

Fields: `id`, `organization_id`, `invited_by_user_id`, `invitee_email`, `status` (pending, accepted, expired, revoked), `role`, `expires_at`, `accepted_at`, `created_at`

### PasswordResetRequest

A time-limited request to reset a User's password.

Fields: `id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `created_at`

---

## Ownership Rules

| Rule | Description |
|---|---|
| **Org ownership** | An Organization has exactly one `owner_id`. The owner may transfer ownership to another member. |
| **User self-ownership** | A User owns their own identity data. They may update their display name, avatar, and primary email. |
| **Session ownership** | A Session belongs to the User who created it. Only that User (or an org admin) may revoke it. |
| **Membership scoping** | A User's access to Organization resources is determined by their Membership(s). A User without a Membership in the target Organization has no access. |
| **Invitation authority** | Any active Member may invite new users to the Organization. Invitation acceptance creates a Membership. |
| **Data isolation** | No identity data is shared across Organizations. A User's presence in multiple Organizations means separate Memberships with potentially separate roles. |

---

## Extension Points

### IdentityProvider

The primary extension point. New authentication providers implement the `IdentityProvider` contract:

- **Email** — built-in, password-based with verification
- **Google** — OAuth 2.0 with OpenID Connect
- **Microsoft** — OAuth 2.0 with Entra ID
- **GitHub** — OAuth 2.0
- **Passkeys** — WebAuthn-based
- **SAML** — enterprise SAML 2.0
- **OIDC** — generic OpenID Connect
- **Okta** — Okta-specific OIDC
- **Azure AD** — Microsoft Entra ID OIDC

Registration of a new provider requires: implementing the provider contract, adding a `ProviderType` enum member, and configuring the provider in the Identity Platform's provider registry.

### VerificationToken purposes

New verification flows add a `VerificationTokenPurpose` enum member. No orchestration changes needed.

### Future: Identity federation

The `IdentityProvider` abstraction allows future federation scenarios where an Organization configures their own IdP (SAML/OIDC) for all members.

---

## Future Extensibility

| Capability | Path |
|---|---|
| New OAuth provider | Implement `IdentityProvider` contract + register |
| Enterprise SAML/SSO | `IdentityProvider` contract handles SAML assertions |
| Passkeys/WebAuthn | New `Credential` subtype alongside `PasswordCredential` |
| MFA/TOTP | New credential type + session requirement flag |
| Identity federation | Org-scoped `IdentityProvider` configuration |
| SCIM provisioning | New integration outside core Identity Platform |
| Account linking | Merge `EmailIdentity` records across providers for same User |

---

## References

- ADR-0012 — Authentication Flows (flow-level journey details)
- ADR-0013 — Security Architecture (authorization boundaries)

# Email Composition Engine v1.0 — Freeze Declaration

**Status:** FROZEN — No modifications permitted without explicit platform phase approval.

## Scope

| Element | Status |
|---------|--------|
| `backend/services/email/__init__.py` | FROZEN |
| `backend/services/email/models.py` | FROZEN |
| `backend/services/email/exceptions.py` | FROZEN |
| `backend/services/email/branding.py` | FROZEN |
| `backend/services/email/mailbox.py` | FROZEN |
| `backend/services/email/attachments.py` | FROZEN |
| `backend/services/email/templates.py` | FROZEN |
| `backend/services/email/template_registry.py` | FROZEN |
| `backend/services/email/renderer.py` | FROZEN |
| `backend/services/email/draft.py` | FROZEN |
| `backend/services/email/composer.py` | FROZEN |
| `backend/tests/test_email_composition_engine.py` | FROZEN |

## Dependencies (upstream, all frozen)

| Component | Status |
|-----------|--------|
| Execution Runtime | FROZEN (Platform v1.0) |
| Adapter SDK | FROZEN (Platform v1.0) |
| Capability System | FROZEN (Platform v1.0) |
| Credential Framework | FROZEN (Platform v1.0) |
| Adapter Registry | FROZEN (Platform v1.0) |
| HTTP Adapter | FROZEN (Platform v1.1) |
| Google API Base Adapter | FROZEN (Platform v1.1) |
| Gmail Adapter | FROZEN (Platform v1.1) |

## Rationale

The Email Composition Engine v1.0 provides a provider-agnostic email composition layer that prepares fully rendered, branded email drafts. Freezing it ensures a stable foundation for higher-level services (campaign management, AI reply generation, multi-provider support) without risk of regressions from layer changes.

## What is NOT frozen

- Building higher-level services on top of `EmailComposer`
- Adding new mail providers (Outlook, SMTP, SendGrid) that consume `EmailDraft`
- Adding new template functions (extending `TEMPLATE_FUNCTIONS`)
- Improving test coverage with new tests referencing frozen code

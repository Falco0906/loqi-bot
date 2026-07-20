# Gmail Adapter v1.0 — Freeze Declaration

**Status:** FROZEN — No modifications permitted without explicit platform phase approval.

## Scope

| Element | Status |
|---------|--------|
| `backend/services/adapters/google/gmail/__init__.py` | FROZEN |
| `backend/services/adapters/google/gmail/errors.py` | FROZEN |
| `backend/services/adapters/google/gmail/gmail_adapter.py` | FROZEN |
| `backend/services/adapters/google/gmail/mime.py` | FROZEN |
| `backend/services/adapters/google/gmail/models.py` | FROZEN |
| `backend/services/adapters/google/gmail/queries.py` | FROZEN |
| `backend/tests/test_gmail_adapter.py` | FROZEN |

## Dependencies

| Component | Dependency Type | Status |
|-----------|----------------|--------|
| `services.adapters` | Adapter SDK | FROZEN (Platform v1.0) |
| `services.adapters.http` | HTTP Adapter v1.0 | FROZEN (Platform v1.1) |
| `services.adapters.google` | Google API Base Adapter v1.0 | FROZEN (Platform v1.1) |

## Rationale

The Gmail Adapter v1.0 provides the minimum viable Gmail integration for Loqi's outbound email orchestration. Freezing it ensures a stable foundation for higher-level services (email sending, inbox sync, reply detection) without risk of regressions from layer changes.

## What is NOT frozen

- Extending test coverage (new tests referencing frozen code)
- Building higher-level services on top of this adapter
- Adding new adapters (Calendar, Drive) via `GoogleApiAdapter`

"""Global product capability policy for the Loqi Beta release.

This extends the existing product-capability package rather than introducing
workspace-local flags. The policy is intentionally process-wide: Beta is a
product mode, not an organization entitlement. API adapters use this module
to reject deferred operations, and the frontend reads the same policy through
the capabilities API for discoverability.
"""
from __future__ import annotations

from services.capabilities.config import BETA_FEATURES


def beta_features() -> dict[str, bool]:
    """Return a copy suitable for an API response; callers cannot mutate policy."""
    return dict(BETA_FEATURES)


def beta_feature_enabled(feature: str) -> bool:
    """Fail closed for unknown capabilities and deferred Beta operations."""
    return BETA_FEATURES.get(feature, False)


def beta_feature_unavailable_message(feature: str) -> str:
    """Return the user-safe reason an intentionally deferred operation is blocked."""
    messages = {
        "autonomous_lead_sourcing": "Lead sourcing is not available in Loqi Beta. Use your existing lead data.",
        "outbound_delivery": "Email delivery is not available in Loqi Beta. Review, copy, or export outreach instead.",
        "automated_followups": "Automated follow-ups are not available in Loqi Beta.",
        "autonomous_workflows": "Autonomous workflow execution is not available in Loqi Beta.",
    }
    return messages.get(feature, "This capability is not available in Loqi Beta.")

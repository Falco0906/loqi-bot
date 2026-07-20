from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BillingConfig:
    provider: str = "stripe"
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    trial_duration_days: int = 14
    portal_return_url: str = "http://localhost:3000/settings/billing"
    checkout_success_url: str = "http://localhost:3000/settings/billing?success=true"
    checkout_cancel_url: str = "http://localhost:3000/settings/billing?canceled=true"
    plans: list[dict] = field(default_factory=list)

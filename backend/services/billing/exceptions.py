from __future__ import annotations


class BillingException(Exception):
    def __init__(self, message: str = "A billing error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class CustomerNotFound(BillingException):
    def __init__(self, message: str = "Customer not found") -> None:
        super().__init__(message)


class CustomerAlreadyExists(BillingException):
    def __init__(self, organization_id: str = "") -> None:
        msg = f"Customer already exists for organization {organization_id}"
        super().__init__(msg)
        self.organization_id = organization_id


class PlanNotFound(BillingException):
    def __init__(self, plan_id: str = "") -> None:
        msg = f"Plan not found: {plan_id}" if plan_id else "Plan not found"
        super().__init__(msg)
        self.plan_id = plan_id


class SubscriptionNotFound(BillingException):
    def __init__(self, message: str = "Subscription not found") -> None:
        super().__init__(message)


class CheckoutSessionNotFound(BillingException):
    def __init__(self, message: str = "Checkout session not found") -> None:
        super().__init__(message)


class InvoiceNotFound(BillingException):
    def __init__(self, message: str = "Invoice not found") -> None:
        super().__init__(message)


class ProviderError(BillingException):
    def __init__(self, message: str = "Provider error") -> None:
        super().__init__(message)


class WebhookSignatureInvalid(BillingException):
    def __init__(self, message: str = "Webhook signature verification failed") -> None:
        super().__init__(message)


class DuplicateWebhookEvent(BillingException):
    def __init__(self, event_id: str = "") -> None:
        msg = f"Duplicate webhook event: {event_id}" if event_id else "Duplicate webhook event"
        super().__init__(msg)
        self.event_id = event_id


class OrganizationNotConfigured(BillingException):
    def __init__(self, organization_id: str = "") -> None:
        msg = f"Organization has no billing customer: {organization_id}" if organization_id else "Organization not configured for billing"
        super().__init__(msg)
        self.organization_id = organization_id


class NoActiveSubscription(BillingException):
    def __init__(self, organization_id: str = "") -> None:
        msg = f"No active subscription for organization {organization_id}" if organization_id else "No active subscription"
        super().__init__(msg)
        self.organization_id = organization_id

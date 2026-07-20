from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    billing_interval: str
    currency: str
    price: int
    display_price: str
    metadata: dict[str, Any]


class PlansListResponse(BaseModel):
    plans: list[PlanResponse]


class SubscriptionResponse(BaseModel):
    id: str
    organization_id: str
    plan_id: str
    status: str
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    created_at: datetime
    updated_at: datetime


class CustomerResponse(BaseModel):
    id: str
    organization_id: str
    email: str
    provider: str
    created_at: datetime


class CreateCheckoutRequest(BaseModel):
    organization_id: str
    plan_id: str
    email: str
    success_url: str | None = None
    cancel_url: str | None = None
    trial_days: int | None = None


class CheckoutResponse(BaseModel):
    id: str
    url: str
    organization_id: str
    plan_id: str
    status: str


class CustomerPortalRequest(BaseModel):
    organization_id: str
    return_url: str | None = None


class CustomerPortalResponse(BaseModel):
    url: str


class CancelSubscriptionRequest(BaseModel):
    organization_id: str
    at_period_end: bool = True


class CancelSubscriptionResponse(BaseModel):
    subscription: SubscriptionResponse
    message: str


class ResumeSubscriptionResponse(BaseModel):
    subscription: SubscriptionResponse

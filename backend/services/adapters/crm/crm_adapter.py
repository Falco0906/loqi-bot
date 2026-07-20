from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult
from services.adapters.crm.models import (
    Contact,
    Company,
    Opportunity,
    Activity,
    Note,
    CrmOwner,
    ContactSearchResult,
    CompanySearchResult,
)

CRM_METADATA = AdapterMetadata(
    name="crm",
    display_name="CRM Adapter",
    version="1.0.0",
    description="Canonical CRM adapter — find, create, and update contacts, "
    "companies, opportunities, activities, and notes. "
    "Abstracts provider-specific (HubSpot, Salesforce, etc.) details.",
    author="Loqi",
    supported_operations=(
        "find_contact",
        "create_contact",
        "update_contact",
        "find_company",
        "create_company",
        "create_opportunity",
        "update_opportunity",
        "create_activity",
        "create_note",
        "assign_owner",
    ),
    requires_auth=False,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("crm", "sales", "hubspot", "salesforce", "contacts", "opportunities"),
)

FIND_CONTACT = "find_contact"
CREATE_CONTACT = "create_contact"
UPDATE_CONTACT = "update_contact"
FIND_COMPANY = "find_company"
CREATE_COMPANY = "create_company"
CREATE_OPPORTUNITY = "create_opportunity"
UPDATE_OPPORTUNITY = "update_opportunity"
CREATE_ACTIVITY = "create_activity"
CREATE_NOTE = "create_note"
ASSIGN_OWNER = "assign_owner"

ACTION_METHOD_MAP: dict[str, str] = {
    FIND_CONTACT: "find_contact",
    CREATE_CONTACT: "create_contact",
    UPDATE_CONTACT: "update_contact",
    FIND_COMPANY: "find_company",
    CREATE_COMPANY: "create_company",
    CREATE_OPPORTUNITY: "create_opportunity",
    UPDATE_OPPORTUNITY: "update_opportunity",
    CREATE_ACTIVITY: "create_activity",
    CREATE_NOTE: "create_note",
    ASSIGN_OWNER: "assign_owner",
}


class CrmAdapter(ExecutionAdapter):

    @property
    def metadata(self) -> AdapterMetadata:
        return CRM_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        action = context.action
        method_name = ACTION_METHOD_MAP.get(action)
        if not method_name:
            return AdapterResult.failure_result(
                error=f"Unknown CRM action: {action}",
                metadata={"action": action},
            )

        method = getattr(self, method_name, None)
        if not method:
            return AdapterResult.failure_result(
                error=f"No handler for CRM action: {action}",
                metadata={"action": action},
            )

        try:
            result = await method(context.params)
            return AdapterResult.success_result(
                data=result,
                metadata={"action": action},
            )
        except Exception as e:
            return AdapterResult.failure_result(
                error=str(e),
                metadata={"action": action, "error_type": type(e).__name__},
            )

    async def find_contact(self, params: dict[str, Any]) -> dict[str, Any]:
        email = params.get("email", "")
        company_domain = params.get("company_domain", "")
        name = params.get("name", "")
        result = ContactSearchResult(
            contacts=[],
            total=0,
            query=email or company_domain or name,
        )
        return {
            "ok": True,
            "contacts": [c.__dict__ for c in result.contacts],
            "total": result.total,
            "query": result.query,
        }

    async def create_contact(self, params: dict[str, Any]) -> dict[str, Any]:
        contact = Contact(
            email=params.get("email", ""),
            first_name=params.get("first_name", ""),
            last_name=params.get("last_name", ""),
            phone=params.get("phone", ""),
            title=params.get("title", ""),
            company_id=params.get("company_id", ""),
            lifecycle_stage=params.get("lifecycle_stage", "lead"),
        )
        return {
            "ok": True,
            "contact": contact.__dict__,
            "action": "create_contact",
        }

    async def update_contact(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "contact_id": params.get("contact_id", ""),
            "updated_fields": params.get("fields", {}),
            "action": "update_contact",
        }

    async def find_company(self, params: dict[str, Any]) -> dict[str, Any]:
        domain = params.get("domain", "")
        name = params.get("name", "")
        result = CompanySearchResult(
            companies=[],
            total=0,
            query=domain or name,
        )
        return {
            "ok": True,
            "companies": [c.__dict__ for c in result.companies],
            "total": result.total,
            "query": result.query,
        }

    async def create_company(self, params: dict[str, Any]) -> dict[str, Any]:
        company = Company(
            name=params.get("name", ""),
            domain=params.get("domain", ""),
            industry=params.get("industry", ""),
            size=params.get("size", ""),
            website=params.get("website", ""),
            phone=params.get("phone", ""),
        )
        return {
            "ok": True,
            "company": company.__dict__,
            "action": "create_company",
        }

    async def create_opportunity(self, params: dict[str, Any]) -> dict[str, Any]:
        opp = Opportunity(
            name=params.get("name", ""),
            company_id=params.get("company_id", ""),
            contact_id=params.get("contact_id", ""),
            amount=params.get("amount", 0.0),
            stage=params.get("stage", "discovery"),
            pipeline=params.get("pipeline", "default"),
        )
        return {
            "ok": True,
            "opportunity": opp.__dict__,
            "action": "create_opportunity",
        }

    async def update_opportunity(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "opportunity_id": params.get("opportunity_id", ""),
            "stage": params.get("stage", ""),
            "amount": params.get("amount", 0.0),
            "close_date": params.get("close_date", ""),
            "action": "update_opportunity",
        }

    async def create_activity(self, params: dict[str, Any]) -> dict[str, Any]:
        activity = Activity(
            type=params.get("type", "email"),
            subject=params.get("subject", ""),
            body=params.get("body", ""),
            contact_id=params.get("contact_id", ""),
            company_id=params.get("company_id", ""),
            opportunity_id=params.get("opportunity_id", ""),
            due_date=params.get("due_date", ""),
        )
        return {
            "ok": True,
            "activity": activity.__dict__,
            "action": "create_activity",
        }

    async def create_note(self, params: dict[str, Any]) -> dict[str, Any]:
        note = Note(
            body=params.get("body", ""),
            contact_id=params.get("contact_id", ""),
            company_id=params.get("company_id", ""),
            opportunity_id=params.get("opportunity_id", ""),
        )
        return {
            "ok": True,
            "note": note.__dict__,
            "action": "create_note",
        }

    async def assign_owner(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "owner_email": params.get("owner_email", ""),
            "contact_id": params.get("contact_id", ""),
            "company_id": params.get("company_id", ""),
            "opportunity_id": params.get("opportunity_id", ""),
            "action": "assign_owner",
        }

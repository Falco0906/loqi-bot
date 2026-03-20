from services.apollo import MOCK_LEADS_ON_403, format_leads_message, search_leads
from services.supabase import store_leads


def generate_leads(input: dict) -> dict:
    query = input.get("target") or ""
    user_id = input.get("user_id")

    result = search_leads(query)
    leads = result.get("leads", [])

    if not leads:
        leads = [dict(lead) for lead in MOCK_LEADS_ON_403]
        result = {
            "ok": True,
            "source": "mock",
            "leads": leads,
            "error": result.get("error") or "apollo_failed",
        }

    stored_leads = store_leads(user_id, leads) if user_id else []

    return {
        "ok": True,
        "type": "generate_leads",
        "source": result.get("source"),
        "leads": leads,
        "stored_leads": stored_leads,
        "message": format_leads_message(leads),
        "error": result.get("error"),
    }


def draft_message(input: dict) -> dict:
    lead = input.get("lead") or {}
    service = input.get("service") or "what we do"
    target = input.get("target") or "this space"
    lead_name = lead.get("name") or "there"
    company = lead.get("company") or "your team"

    message = (
        f"Hey {lead_name} — saw you're working on {target} at {company}. "
        f"We help with {service}. Worth a quick chat?"
    )

    return {
        "ok": True,
        "type": "draft_message",
        "message": message,
        "lead": lead,
    }


def run_workflow(input: dict) -> dict:
    workflow_type = input.get("type")

    if workflow_type == "generate_leads":
        return generate_leads(input)

    if workflow_type == "draft_message":
        return draft_message(input)

    return {
        "ok": False,
        "type": workflow_type,
        "message": "Unknown workflow.",
        "error": "unknown_workflow",
    }

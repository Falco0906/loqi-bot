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
    service = input.get("service") or "automate hiring workflows and reduce manual effort"
    lead_name = (lead.get("first_name") or "").strip() or (lead.get("name") or "there").split()[0]
    title = lead.get("title") or (input.get("target") or "this role")
    company = lead.get("company") or "your team"
    edit_request = (input.get("edit_request") or "").strip()

    service_line = f"We help companies {service}."
    connect_line = "Would love to connect."
    if edit_request:
        service_line = f"We help companies {service}. {edit_request}"
        connect_line = "Happy to adjust this further if needed."

    message = (
        "Here’s your outreach message:\n\n"
        "---\n"
        f"Hey {lead_name} — saw you're working as an {title} at {company}.\n\n"
        f"{service_line}\n\n"
        f"{connect_line}\n"
        "---"
    )

    return {
        "ok": True,
        "type": "draft_message",
        "message": message,
        "lead": lead,
        "edit_request": edit_request,
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

from services.apollo import MOCK_LEADS_ON_403, format_leads_message, search_leads
from services.ai import generate_message, rewrite_message
from services.supabase import store_leads


VALID_TONES = {"casual", "formal", "aggressive", "friendly"}
VALID_LENGTHS = {"short", "medium", "long"}


def _infer_tone(input: dict) -> str:
    explicit_tone = (input.get("tone") or "").strip().lower()
    if explicit_tone in VALID_TONES:
        return explicit_tone

    combined_text = " ".join(
        part for part in [
            input.get("edit_request") or "",
            " ".join(input.get("conversation_context") or []),
        ]
        if part
    ).lower()

    if "aggressive" in combined_text or "stronger" in combined_text or "hard sell" in combined_text:
        return "aggressive"
    if "formal" in combined_text or "professional" in combined_text:
        return "formal"
    if "casual" in combined_text or "relaxed" in combined_text:
        return "casual"
    return "friendly"


def _infer_length(input: dict) -> str:
    explicit_length = (input.get("length") or "").strip().lower()
    if explicit_length in VALID_LENGTHS:
        return explicit_length

    combined_text = " ".join(
        part for part in [
            input.get("edit_request") or "",
            " ".join(input.get("conversation_context") or []),
        ]
        if part
    ).lower()

    if "shorter" in combined_text or "short" in combined_text:
        return "short"
    if "longer" in combined_text or "long" in combined_text:
        return "long"
    return "medium"


def _normalize_edit_request(edit_request: str) -> str:
    normalized = edit_request.strip()
    lowered = normalized.lower()

    if lowered == "rewrite":
        return "Rewrite the message from scratch using the same goal."
    if "add urgency" in lowered:
        return "Add urgency and make the call to action more time-sensitive."
    return normalized


def _build_fallback_draft(
    *,
    lead_name: str,
    title: str,
    company: str,
    service: str,
) -> str:
    return (
        "Here’s your outreach message:\n\n"
        "---\n"
        f"Hey {lead_name} — saw you're working as an {title} at {company}.\n\n"
        f"We help companies {service}.\n\n"
        "Would love to connect.\n"
        "---"
    )


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
    edit_request = _normalize_edit_request((input.get("edit_request") or "").strip())
    tone = _infer_tone(input)
    length = _infer_length(input)
    conversation_context = input.get("conversation_context") or []
    previous_message = input.get("previous_message") or ""

    if edit_request and previous_message:
        llm_message = rewrite_message(edit_request, previous_message)
    else:
        llm_message = generate_message(
            {
                "lead_name": lead_name,
                "lead_title": title,
                "company": company,
                "user_service": service,
                "tone": tone,
                "length": length,
                "conversation_context": conversation_context,
            }
        )

    if llm_message:
        message = f"Here’s your outreach message:\n\n---\n{llm_message}\n---"
    else:
        message = _build_fallback_draft(
            lead_name=lead_name,
            title=title,
            company=company,
            service=service,
        )

    return {
        "ok": True,
        "type": "draft_message",
        "message": message,
        "lead": lead,
        "edit_request": edit_request,
        "tone": tone,
        "length": length,
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

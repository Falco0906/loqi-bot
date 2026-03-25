from services.apollo import format_leads_message
from services.ai import rewrite_message
from services.lead_provider import get_leads
from services.supabase import store_leads


VALID_TONES = {"casual", "formal", "aggressive", "friendly"}
VALID_LENGTHS = {"short", "medium", "long"}


def _infer_tone(input: dict) -> str:
    explicit_tone = (input.get("tone") or "").strip().lower()
    if explicit_tone in VALID_TONES:
        return explicit_tone

    text_parts = [
        input.get("edit_request") or "",
        * (input.get("conversation_context") or []),
    ]
    combined_text = " ".join(
        part for part in [
            *text_parts,
        ]
        if part
    ).lower()
    word_count = len(combined_text.split())

    if any(word in combined_text for word in ["sir", "madam", "regards", "sincerely", "professional", "formal"]):
        return "formal"
    if word_count and word_count <= 3:
        return "aggressive"
    if "aggressive" in combined_text or "stronger" in combined_text or "hard sell" in combined_text:
        return "aggressive"
    return "casual"


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
) -> str:
    title_phrase = f" as {title.lower()}" if title else ""
    company_phrase = f" at {company}" if company else ""
    return (
        "Draft ready:\n\n"
        "---\n"
        f"Hey {lead_name} — noticed you're working{title_phrase}{company_phrase}.\n\n"
        "We help companies automate lead generation and outbound.\n\n"
        "Worth a quick chat?\n"
        "---"
    )


def _clean_lead_title(lead_title: str) -> str:
    return lead_title.replace("|", "").replace("  ", " ").strip()


def _simplify_lead_title(lead_title: str) -> str:
    normalized = _clean_lead_title(lead_title)
    lowered = normalized.lower()

    if "people operations" in lowered:
        return "leading people operations"
    if "talent acquisition" in lowered:
        return "leading talent acquisition"

    return normalized


def generate_leads(input: dict) -> dict:
    service = input.get("service") or ""
    target = input.get("target") or ""
    user_id = input.get("user_id")
    result = get_leads(service, target)
    leads = result.get("leads", [])

    if not result.get("ok") or not leads:
        error = result.get("error") or "unknown_error"
        return {
            "ok": False,
            "type": "generate_leads",
            "source": result.get("source", "lead_provider"),
            "leads": [],
            "stored_leads": [],
            "message": f"Lead search failed: {error}",
            "error": error,
        }

    stored_leads = store_leads(user_id, leads) if user_id else []

    return {
        "ok": True,
        "type": "generate_leads",
        "source": result.get("source", "lead_provider"),
        "leads": leads,
        "stored_leads": stored_leads,
        "message": format_leads_message(leads),
        "error": None,
    }


def draft_message(input: dict) -> dict:
    lead = input.get("lead") or {}
    lead_name = ((lead.get("name") or "there").split() or ["there"])[0]
    title = _clean_lead_title(lead.get("title") or "")
    company = (lead.get("company") or "").strip()
    edit_request = _normalize_edit_request((input.get("edit_request") or "").strip())
    tone = _infer_tone(input)
    length = _infer_length(input)
    previous_message = input.get("previous_message") or ""

    if edit_request and previous_message:
        llm_message = rewrite_message(edit_request, previous_message)
    else:
        llm_message = None

    if llm_message:
        message = f"Draft ready:\n\n---\n{llm_message}\n---"
    else:
        simplified_title = _simplify_lead_title(title)
        message = _build_fallback_draft(
            lead_name=lead_name,
            title=simplified_title,
            company=company,
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

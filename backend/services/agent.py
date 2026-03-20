from services.ai import classify_intent
from services.telegram import send_message
from services.supabase import (
    clear_session_context,
    get_lead_by_id,
    get_or_create_user,
    get_session_context,
    log_conversation,
    select_lead,
)
from workflows import run_workflow

POSITIVE_RESPONSES = ["yes", "y", "ok", "sure", "yeah", "yep", "send", "go"]
TWEAK_EXAMPLES = (
    "Say things like:\n"
    "- make it shorter\n"
    "- more aggressive\n"
    "- rewrite for founders"
)


def _send_and_log(chat_id: int, user_id: str, text: str) -> None:
    send_message(chat_id, text)
    log_conversation(user_id, "assistant", text)


def _format_selected_lead(lead: dict) -> str:
    name = (lead.get("name") or "Unknown").strip()
    title = (lead.get("title") or "").strip()
    company = (lead.get("company") or "Unknown Company").strip()
    role_part = f" — {title}" if title else ""
    return f"Selected: {name}{role_part} @ {company}"


def _send_draft_follow_up(chat_id: int, user_id: str) -> None:
    _send_and_log(chat_id, user_id, "Want to tweak it or send?")
    _send_and_log(chat_id, user_id, TWEAK_EXAMPLES)


def _extract_previous_outreach(assistant_messages: list[str]) -> str:
    for message in reversed(assistant_messages):
        if "Draft ready:" not in message or "---" not in message:
            continue

        parts = message.split("---")
        if len(parts) < 3:
            continue

        return parts[1].strip()

    return ""


def _fallback_classify_intent(
    user_message: str,
    *,
    has_draft: bool,
) -> str:
    lowered = user_message.lower().strip()

    if any(word in lowered for word in POSITIVE_RESPONSES):
        return "send"
    if lowered.isdigit():
        return "select_lead"
    if has_draft:
        return "refine_message"
    return "new_search"

def process_message(
    chat_id: int,
    telegram_id: str,
    text: str,
    username: str | None = None,
) -> None:
    user = get_or_create_user(telegram_id, username=username)
    if user is None:
        send_message(chat_id, "Couldn't process that right now. Try again.")
        return

    user_id = user["id"]
    normalized_text = text.strip()
    existing_context = get_session_context(user_id)

    if normalized_text.lower() == "/restart":
        clear_session_context(user_id, since_timestamp=existing_context.get("started_at"))
        log_conversation(user_id, "user", normalized_text)
        _send_and_log(chat_id, user_id, "Hey — I’m Loqi. I’ll help you find leads and run outreach.")
        _send_and_log(chat_id, user_id, "What do you sell?")
        return

    if normalized_text.lower() == "/start":
        log_conversation(user_id, "user", normalized_text)
        _send_and_log(chat_id, user_id, "Hey — I’m Loqi. I’ll help you find leads and run outreach.")

        if existing_context["service"] and existing_context["target"]:
            workflow_result = run_workflow(
                {
                    "type": "generate_leads",
                    "service": existing_context["service"],
                    "target": existing_context["target"],
                    "user_id": user_id,
                }
            )
            _send_and_log(chat_id, user_id, workflow_result["message"])
            return

        if existing_context["service"]:
            _send_and_log(chat_id, user_id, "Who do you want to reach?")
            return

        _send_and_log(chat_id, user_id, "What do you sell?")
        return

    log_conversation(user_id, "user", normalized_text)

    context = get_session_context(user_id)
    user_messages = context["user_messages"]
    assistant_messages = context.get("assistant_messages", [])
    conversation_context = (user_messages + assistant_messages)[-10:]
    last_assistant_message = context["last_assistant_message"]
    service = context["service"]
    target = context["target"]
    started_at = context["started_at"]
    selected_lead_id = context.get("selected_lead_id")
    previous_message = _extract_previous_outreach(assistant_messages)
    has_draft = bool(previous_message)

    if not service:
        _send_and_log(chat_id, user_id, "What do you sell?")
        return

    if not target:
        _send_and_log(chat_id, user_id, "Who do you want to reach?")
        return

    classified_intent = classify_intent(
        normalized_text,
        {
            "service": service,
            "target": target,
            "selected_lead_id": selected_lead_id,
            "has_draft": has_draft,
            "user_message_count": len(user_messages),
        },
    ) or _fallback_classify_intent(normalized_text, has_draft=has_draft)

    if classified_intent == "send":
        _send_and_log(chat_id, user_id, "Sent ✅ (mock)")
        _send_and_log(chat_id, user_id, "Type /start when you are ready to reach out to more leads.")
        return

    if classified_intent == "select_lead":
        selected_lead = select_lead(
            user_id,
            normalized_text,
            since_timestamp=started_at,
        )
        if selected_lead is None:
            _send_and_log(chat_id, user_id, "Reply with a lead number.")
            return

        _send_and_log(chat_id, user_id, _format_selected_lead(selected_lead))
        workflow_result = run_workflow(
            {
                "type": "draft_message",
                "service": service,
                "target": target,
                "lead": selected_lead,
                "conversation_context": conversation_context,
            }
        )
        _send_and_log(chat_id, user_id, workflow_result["message"])
        _send_draft_follow_up(chat_id, user_id)
        return

    if classified_intent == "new_search":
        clear_session_context(user_id, since_timestamp=started_at)
        if service:
            workflow_result = run_workflow(
                {
                    "type": "generate_leads",
                    "service": service,
                    "target": normalized_text,
                    "user_id": user_id,
                }
            )
            _send_and_log(chat_id, user_id, workflow_result["message"])
            return

        _send_and_log(chat_id, user_id, "What do you sell?")
        return

    if classified_intent == "refine_message" and previous_message:
        selected_lead = get_lead_by_id(selected_lead_id) if selected_lead_id else None
        if selected_lead is None:
            _send_and_log(chat_id, user_id, "Couldn't find that lead. Try again.")
            return

        workflow_result = run_workflow(
            {
                "type": "draft_message",
                "service": service,
                "target": target,
                "lead": selected_lead,
                "edit_request": normalized_text,
                "previous_message": previous_message,
                "conversation_context": conversation_context,
            }
        )
        _send_and_log(chat_id, user_id, workflow_result["message"])
        _send_draft_follow_up(chat_id, user_id)
        return

    _send_and_log(chat_id, user_id, "Operation cancelled. Type /start to try again.")

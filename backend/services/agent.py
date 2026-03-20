from services.telegram import send_message
from services.supabase import (
    get_or_create_user,
    get_selected_lead,
    get_session_context,
    log_conversation,
    select_lead,
)
from workflows import run_workflow

POSITIVE_RESPONSES = ["yes", "y", "ok", "sure", "yeah", "yep", "send", "go"]
EDIT_HINTS = [
    "casual",
    "formal",
    "aggressive",
    "friendly",
    "shorter",
    "longer",
    "short",
    "long",
    "urgency",
    "urgent",
    "rewrite",
]


def _send_and_log(chat_id: int, user_id: str, text: str) -> None:
    send_message(chat_id, text)
    log_conversation(user_id, "assistant", text)


def _format_selected_lead(lead: dict) -> str:
    return f"Selected: {lead['name']} — {lead['title']} @ {lead['company']}"


def _extract_previous_outreach(last_assistant_message: str | None) -> str:
    if not last_assistant_message or "---" not in last_assistant_message:
        return ""

    parts = last_assistant_message.split("---")
    if len(parts) < 3:
        return ""

    return parts[1].strip()

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

    if len(user_messages) == 1:
        _send_and_log(chat_id, user_id, "Who do you want to reach?")
        return

    if len(user_messages) == 2:
        workflow_result = run_workflow(
            {
                "type": "generate_leads",
                "service": service,
                "target": target or normalized_text,
                "user_id": user_id,
            }
        )
        _send_and_log(chat_id, user_id, workflow_result["message"])
        return

    if len(user_messages) == 3:
        selected_lead = select_lead(
            user_id,
            normalized_text,
            since_timestamp=started_at,
        )
        if selected_lead is None:
            _send_and_log(chat_id, user_id, "Couldn't find that lead. Try again.")
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
        _send_and_log(chat_id, user_id, "Want to tweak it or send?")
        return

    if normalized_text.lower() == "edit":
        _send_and_log(chat_id, user_id, "What should I change?")
        return

    if last_assistant_message == "What should I change?" or any(
        hint in normalized_text.lower() for hint in EDIT_HINTS
    ):
        selected_lead = get_selected_lead(user_id, since_timestamp=started_at)
        if selected_lead is None:
            _send_and_log(chat_id, user_id, "Couldn't find that lead. Try again.")
            return

        previous_message = _extract_previous_outreach(last_assistant_message)
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
        _send_and_log(chat_id, user_id, "Want to tweak it or send?")
        return

    if any(word in normalized_text.lower() for word in POSITIVE_RESPONSES):
        _send_and_log(chat_id, user_id, "Sent ✅ (mock)")
        _send_and_log(chat_id, user_id, "Type /start when you are ready to reach out to more leads.")
        return

    _send_and_log(chat_id, user_id, "Operation cancelled. Type /start to try again.")

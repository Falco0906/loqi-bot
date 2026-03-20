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


def _send_and_log(chat_id: int, user_id: str, text: str) -> None:
    send_message(chat_id, text)
    log_conversation(user_id, "assistant", text)


def _format_selected_lead(lead: dict) -> str:
    return f"Selected: {lead['name']} — {lead['title']} @ {lead['company']}"

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
            }
        )
        _send_and_log(chat_id, user_id, workflow_result["message"])
        _send_and_log(chat_id, user_id, "Send this?")
        return

    if normalized_text.lower() == "edit":
        _send_and_log(chat_id, user_id, "What should I change?")
        return

    if last_assistant_message == "What should I change?":
        selected_lead = get_selected_lead(user_id, since_timestamp=started_at)
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
            }
        )
        _send_and_log(chat_id, user_id, workflow_result["message"])
        _send_and_log(chat_id, user_id, "Send this?")
        return

    if any(word in normalized_text.lower() for word in POSITIVE_RESPONSES):
        _send_and_log(chat_id, user_id, "Sent ✅ (mock)")
        _send_and_log(chat_id, user_id, "Type /start when you are ready to reach out to more leads.")
        return

    _send_and_log(chat_id, user_id, "Operation cancelled. Type /start to try again.")

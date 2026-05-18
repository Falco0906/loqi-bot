from datetime import datetime, timezone
from uuid import uuid4

from services.ai import classify_intent, OpenAIError
from services.conversation_store import (
    create_lightweight_web_session,
    ensure_workflow_session,
    get_channel_user,
    get_or_create_channel_user,
    get_web_session,
    list_conversation_messages,
    list_workflow_sessions,
    record_workflow_event,
    record_workflow_message,
    touch_workflow_session,
)
from services.google_auth import get_google_auth_url
from services.supabase import (
    clear_session_context,
    get_lead_by_id,
    get_session_context,
    log_conversation,
    select_lead,
    update_user_telegram_chat_id,
)
from workflows import run_workflow

POSITIVE_RESPONSES = ["yes", "y", "ok", "sure", "yeah", "yep", "send", "go"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message(
    *,
    role: str,
    message_type: str,
    text: str,
    data: dict | None = None,
) -> dict:
    return {
        "id": str(uuid4()),
        "role": role,
        "type": message_type,
        "text": text,
        "data": data or {},
        "created_at": _utc_now(),
    }


def _extract_previous_outreach(assistant_messages: list[str]) -> str:
    for message in reversed(assistant_messages):
        if "Draft ready:" not in message or "---" not in message:
            continue

        parts = message.split("---")
        if len(parts) < 3:
            continue

        return parts[1].strip()

    return ""


def _parse_draft_message(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None

    parts = message.split("---")
    if len(parts) < 3:
        return None

    return parts[1].strip()


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


def _format_selected_lead(lead: dict) -> str:
    name = (lead.get("name") or "Unknown").strip()
    title = (lead.get("title") or "").strip()
    company = (lead.get("company") or "Unknown Company").strip()
    role_part = f" — {title}" if title else ""
    return f"Selected: {name}{role_part} @ {company}"


def _assistant_bundle(
    *,
    workflow_session_id: str,
    text: str,
    message_type: str = "text",
    data: dict | None = None,
) -> list[dict]:
    message = _message(role="assistant", message_type=message_type, text=text, data=data)
    record_workflow_message(
        session_id=workflow_session_id,
        role="assistant",
        message_type=message_type,
        content=text,
        metadata=data,
    )
    return [message]


class ConversationEngine:
    def _finish_response(
        self,
        *,
        user_id: str,
        messages: list[dict],
        events: list[dict],
    ) -> dict:
        for message in messages:
            if message.get("role") != "assistant":
                continue
            text = (message.get("text") or "").strip()
            if not text:
                continue
            log_conversation(user_id, "assistant", text)

        return {"ok": True, "messages": messages, "events": events}

    def create_web_session(self, display_name: str | None = None) -> dict:
        created = create_lightweight_web_session(display_name=display_name)
        if created is None:
            raise ValueError("Unable to create web session")

        user = created["user"]
        workflow_session_id = ensure_workflow_session(
            user_id=user["id"],
            channel="web",
            session_key=created["session_token"],
        )
        record_workflow_event(
            session_id=workflow_session_id,
            event_type="session.created",
            payload={"channel": "web"},
        )
        
        welcome_message = _message(
            role="assistant",
            message_type="text",
            text="Hi! I'm Loqi, your AI outbound assistant. I'll help you find leads and send personalized outreach.",
        )
        record_workflow_message(
            session_id=workflow_session_id,
            role="assistant",
            message_type="text",
            content=welcome_message["text"],
        )
        
        prompt_message = _message(
            role="assistant",
            message_type="prompt",
            text="What do you sell?",
        )
        record_workflow_message(
            session_id=workflow_session_id,
            role="assistant",
            message_type="prompt",
            content=prompt_message["text"],
        )
        
        log_conversation(user["id"], "assistant", welcome_message["text"])
        log_conversation(user["id"], "assistant", prompt_message["text"])
        
        return {
            "ok": True,
            "session_token": created["session_token"],
            "user_id": user["id"],
            "display_name": user.get("username"),
            "gmail_connected": bool(user.get("google_refresh_token")),
            "initial_messages": [welcome_message, prompt_message],
        }

    def get_web_session_summary(self, session_token: str) -> dict | None:
        user = get_web_session(session_token)
        if user is None:
            return None

        session_key = session_token
        sessions = list_workflow_sessions(user["id"], "web", session_key)
        messages = self.list_messages(channel="web", external_user_id=session_token)
        return {
            "ok": True,
            "session_token": session_token,
            "user_id": user["id"],
            "display_name": user.get("username"),
            "gmail_connected": bool(user.get("google_refresh_token")),
            "workflow_sessions": sessions,
            "messages": messages,
        }

    def list_messages(self, *, channel: str, external_user_id: str) -> list[dict]:
        user = get_channel_user(channel=channel, external_user_id=external_user_id)
        if user is None:
            return []

        rows = list_conversation_messages(user["id"])
        return [
            _message(
                role=row.get("role") or "assistant",
                message_type="text",
                text=(row.get("message") or "").strip(),
                data={"created_at": row.get("created_at")},
            )
            for row in rows
            if (row.get("message") or "").strip()
        ]

    def get_gmail_connect_url(self, *, channel: str, external_user_id: str) -> str:
        user = get_channel_user(channel=channel, external_user_id=external_user_id)
        if user is None:
            raise ValueError("Session not found")

        state = f"{channel}:{user['id']}:{external_user_id}"
        return get_google_auth_url(state=state)

    def handle_message(
        self,
        *,
        channel: str,
        external_user_id: str,
        text: str,
        username: str | None = None,
        transport_metadata: dict | None = None,
    ) -> dict:
        user = get_or_create_channel_user(
            channel=channel,
            external_user_id=external_user_id,
            username=username,
        )
        if user is None:
            return {
                "ok": False,
                "messages": [
                    _message(
                        role="assistant",
                        message_type="error",
                        text="Couldn't process that right now. Try again.",
                    )
                ],
                "events": [],
            }

        if channel == "telegram":
            chat_id = (transport_metadata or {}).get("chat_id")
            if chat_id is not None:
                update_user_telegram_chat_id(user["id"], int(chat_id))

        workflow_session_id = ensure_workflow_session(
            user_id=user["id"],
            channel=channel,
            session_key=external_user_id,
        )
        touch_workflow_session(workflow_session_id)

        normalized_text = text.strip()
        existing_context = get_session_context(user["id"])
        log_conversation(user["id"], "user", normalized_text)
        record_workflow_message(
            session_id=workflow_session_id,
            role="user",
            message_type="text",
            content=normalized_text,
            metadata={"channel": channel},
        )
        outputs: list[dict] = []
        events: list[dict] = []

        if normalized_text.lower() == "/restart":
            clear_session_context(user["id"], since_timestamp=existing_context.get("started_at"))
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Hey — I’m Loqi. I’ll help you find leads and run outreach.",
                )
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="What do you sell?",
                    message_type="prompt",
                )
            )
            events.append({"type": "session.reset"})
            record_workflow_event(
                session_id=workflow_session_id,
                event_type="session.reset",
                payload={},
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if normalized_text.lower() == "/connect":
            auth_url = self.get_gmail_connect_url(
                channel=channel,
                external_user_id=external_user_id,
            )
            connect_text = f"Connect your Gmail here:\n{auth_url}"
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=connect_text,
                    message_type="action",
                    data={"label": "Connect Gmail", "url": auth_url},
                )
            )
            events.append({"type": "gmail.connect.requested", "url": auth_url})
            record_workflow_event(
                session_id=workflow_session_id,
                event_type="gmail.connect.requested",
                payload={"url": auth_url},
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if normalized_text.lower() == "/start":
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Hey — I’m Loqi. I’ll help you find leads and run outreach.",
                )
            )
            if existing_context["service"] and existing_context["target"]:
                workflow_result = run_workflow(
                    {
                        "type": "generate_leads",
                        "service": existing_context["service"],
                        "target": existing_context["target"],
                        "user_id": user["id"],
                        "workflow_session_id": workflow_session_id,
                    }
                )
                outputs.extend(
                    self._render_workflow_result(
                        workflow_session_id=workflow_session_id,
                        workflow_result=workflow_result,
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

            if existing_context["service"]:
                outputs.extend(
                    _assistant_bundle(
                        workflow_session_id=workflow_session_id,
                        text="Who do you want to reach?",
                        message_type="prompt",
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="What do you sell?",
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        context = get_session_context(user["id"])
        user_messages = context["user_messages"]
        assistant_messages = context.get("assistant_messages", [])
        conversation_context = (user_messages + assistant_messages)[-10:]
        service = context["service"]
        target = context["target"]
        started_at = context["started_at"]
        selected_lead_id = context.get("selected_lead_id")
        previous_message = _extract_previous_outreach(assistant_messages)
        has_draft = bool(previous_message)

        print(f"[DEBUG] selected_lead_id={selected_lead_id}, normalized_text={normalized_text}, has_draft={has_draft}")

        if not service:
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="What do you sell?",
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if not target:
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Who do you want to reach?",
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if selected_lead_id:
            print(f"[WORKFLOW] selected_lead_id={selected_lead_id} — skipping lead search pipeline")
            if normalized_text.isdigit():
                print(f"[WORKFLOW] numeric reply with selected_lead — treating as lead re-selection")
            else:
                print(f"[WORKFLOW] non-numeric reply with selected_lead — proceeding to intent classification")
        elif not normalized_text.isdigit():
            print(f"[WORKFLOW] no selected_lead and non-numeric text — triggering lead search")
            workflow_result = run_workflow(
                {
                    "type": "generate_leads",
                    "service": service,
                    "target": target,
                    "user_id": user["id"],
                    "workflow_session_id": workflow_session_id,
                }
            )
            outputs.extend(
                self._render_workflow_result(
                    workflow_session_id=workflow_session_id,
                    workflow_result=workflow_result,
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        try:
            lead_list_active = (
                assistant_messages
                and "Search for leads in" in (assistant_messages[-1] or "")
            )
            classified_intent = classify_intent(
                normalized_text,
                {
                    "service": service,
                    "target": target,
                    "selected_lead_id": selected_lead_id,
                    "lead_list_active": lead_list_active,
                    "has_draft": has_draft,
                    "user_message_count": len(user_messages),
                },
            )
        except OpenAIError as e:
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=f"AI service unavailable: {e}. Please try again later.",
                    message_type="error",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if not classified_intent:
            classified_intent = _fallback_classify_intent(normalized_text, has_draft=has_draft)
            print(f"[WORKFLOW] AI classifier returned no intent — using fallback: {classified_intent}")

        print(f"[WORKFLOW] intent classified: '{classified_intent}' (user_input='{normalized_text}', has_selected_lead={bool(selected_lead_id)}, has_draft={has_draft})")

        if classified_intent == "send":
            selected_lead = get_lead_by_id(selected_lead_id) if selected_lead_id else None
            if selected_lead is None:
                outputs.extend(
                    _assistant_bundle(
                        workflow_session_id=workflow_session_id,
                        text="Couldn't find that lead. Try again.",
                        message_type="error",
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

            workflow_result = run_workflow(
                {
                    "type": "send_outreach",
                    "lead": selected_lead,
                    "user_id": user["id"],
                }
            )
            outputs.extend(
                self._render_workflow_result(
                    workflow_session_id=workflow_session_id,
                    workflow_result=workflow_result,
                )
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Type /start when you are ready to reach out to more leads.",
                    message_type="status",
                )
            )
            events.append({"type": "outreach.sent"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "select_lead":
            selected_lead = select_lead(
                user["id"],
                normalized_text,
                since_timestamp=started_at,
            )
            if selected_lead is None:
                print(f"[WORKFLOW] select_lead returned None — regenerating lead list")
                workflow_result = run_workflow(
                    {
                        "type": "generate_leads",
                        "service": service,
                        "target": target,
                        "user_id": user["id"],
                        "workflow_session_id": workflow_session_id,
                    }
                )
                outputs.extend(
                    self._render_workflow_result(
                        workflow_session_id=workflow_session_id,
                        workflow_result=workflow_result,
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

            print(f"[WORKFLOW] lead selected: id={selected_lead.get('id')}, name={selected_lead.get('name')}, company={selected_lead.get('company')}")

            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=_format_selected_lead(selected_lead),
                    message_type="lead_selected",
                    data={"lead": selected_lead},
                )
            )
            print(f"[WORKFLOW] transitioning to draft_generation for lead_id={selected_lead.get('id')}")
            workflow_result = run_workflow(
                {
                    "type": "draft_message",
                    "service": service,
                    "target": target,
                    "lead": selected_lead,
                    "conversation_context": conversation_context,
                }
            )
            print(f"[WORKFLOW] draft_generation complete: ok={workflow_result.get('ok')}")
            outputs.extend(
                self._render_workflow_result(
                    workflow_session_id=workflow_session_id,
                    workflow_result=workflow_result,
                )
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Reply 'send' to continue or pick another lead.",
                    message_type="status",
                )
            )
            events.append({"type": "lead.selected", "lead_id": selected_lead.get("id")})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "new_search":
            clear_session_context(user["id"], since_timestamp=started_at)
            workflow_result = run_workflow(
                {
                    "type": "generate_leads",
                    "service": service,
                    "target": normalized_text,
                    "user_id": user["id"],
                    "workflow_session_id": workflow_session_id,
                }
            )
            outputs.extend(
                self._render_workflow_result(
                    workflow_session_id=workflow_session_id,
                    workflow_result=workflow_result,
                )
            )
            events.append({"type": "lead_search.ran"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "refine_message" and previous_message:
            selected_lead = get_lead_by_id(selected_lead_id) if selected_lead_id else None
            if selected_lead is None:
                outputs.extend(
                    _assistant_bundle(
                        workflow_session_id=workflow_session_id,
                        text="Couldn't find that lead. Try again.",
                        message_type="error",
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

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
            outputs.extend(
                self._render_workflow_result(
                    workflow_session_id=workflow_session_id,
                    workflow_result=workflow_result,
                )
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="Reply 'send' to continue or pick another lead.",
                    message_type="status",
                )
            )
            events.append({"type": "draft.refined"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "refine_message":
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="The backend will generate the email when you send it. Reply 'send' to continue.",
                    message_type="status",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        outputs.extend(
            _assistant_bundle(
                workflow_session_id=workflow_session_id,
                text="Operation cancelled. Type /start to try again.",
                message_type="error",
            )
        )
        return self._finish_response(user_id=user["id"], messages=outputs, events=events)

    def _render_workflow_result(
        self,
        *,
        workflow_session_id: str,
        workflow_result: dict,
    ) -> list[dict]:
        output: list[dict] = []
        workflow_ok = workflow_result.get("ok", True)
        message_text = workflow_result.get("message", "")
        workflow_type = workflow_result.get("type", "workflow")
        workflow_error = workflow_result.get("error")

        if not workflow_ok:
            output.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=message_text or "Operation failed. Please try again.",
                    message_type="error",
                    data={"error": workflow_error},
                )
            )
            return output

        if workflow_type == "generate_leads":
            output.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=message_text,
                    message_type="lead_list",
                    data={
                        "leads": workflow_result.get("leads", []),
                        "source": workflow_result.get("source"),
                    },
                )
            )
            return output

        if workflow_type == "draft_message":
            draft_body = _parse_draft_message(message_text)
            message_type = "draft_preview" if draft_body else "send_confirmation"
            output.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=message_text,
                    message_type=message_type,
                    data={
                        "lead": workflow_result.get("lead"),
                        "draft": draft_body,
                        "tone": workflow_result.get("tone"),
                        "length": workflow_result.get("length"),
                    },
                )
            )
            return output

        if workflow_type == "send_outreach":
            output.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=message_text,
                    message_type="send_result",
                    data=workflow_result.get("result") or {},
                )
            )
            return output

        output.extend(
            _assistant_bundle(
                workflow_session_id=workflow_session_id,
                text=message_text,
                message_type="text",
                data=workflow_result,
            )
        )
        return output

from datetime import datetime, timezone
from uuid import uuid4
import random

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
    get_selected_lead,
    get_session_context,
    log_conversation,
    select_lead,
    update_user_telegram_chat_id,
    get_user_preferences,
    save_user_preference,
)
from workflows import run_workflow
from services.conversational_response_generator import (
    generate_conversational_response,
    detect_preferences_from_refinement,
    build_classification_context,
    _classify_natural_action as classify_natural_action,
    _extract_single_message_fields as extract_single_message_fields,
    _get_service_prompt_variation,
    _get_target_prompt_variation,
    _get_after_leads_variation,
    _get_after_draft_variation,
    _get_after_send_variation,
    _get_refine_options_variation,
)


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

        welcome_text = generate_conversational_response(
            user_message="",
            stage="session_start",
            context={"user_id": user["id"]},
            recent_assistant_messages=[],
        )

        welcome_message = _message(
            role="assistant",
            message_type="text",
            text=welcome_text,
        )
        record_workflow_message(
            session_id=workflow_session_id,
            role="assistant",
            message_type="text",
            content=welcome_message["text"],
        )

        prompt_text = _get_service_prompt_variation([])

        prompt_message = _message(
            role="assistant",
            message_type="prompt",
            text=prompt_text,
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

    def _get_dynamic_prompt(
        self,
        stage: str,
        context: dict,
        recent_messages: list[str],
        service: str | None = None,
        user_preferences: dict | None = None,
    ) -> str:
        """Get dynamic conversational prompt based on stage and context."""
        prefs = user_preferences or {}

        if stage == "ask_service":
            return _get_service_prompt_variation(recent_messages)

        if stage == "ask_target":
            return _get_target_prompt_variation(recent_messages, service or "")

        if stage == "after_leads":
            lead_count = context.get("lead_count", 0)
            return _get_after_leads_variation(recent_messages, lead_count)

        if stage == "after_draft":
            lead_name = context.get("lead_name", "")
            return _get_after_draft_variation(recent_messages, lead_name, prefs)

        if stage == "after_send":
            return _get_after_send_variation()

        if stage == "refining":
            return _get_refine_options_variation()

        return generate_conversational_response(
            user_message="",
            stage=stage,
            context=context,
            recent_assistant_messages=recent_messages,
        )

    def _parse_natural_send_intent(self, user_message: str) -> bool:
        """Check if message indicates sending intent in natural language."""
        msg = user_message.lower().strip()

        send_phrases = [
            "send it", "send", "go", "go ahead", "do it", "yes", "yeah", "yep",
            "sure", "ok", "fire", "ship", "drop it", "hit send", "dispatch",
            "looks good", "this works", "good enough", "that works", "perfect",
            "works for me", "send as is", "send as-is",
        ]

        if msg in send_phrases:
            return True

        for phrase in send_phrases:
            if phrase in msg and len(msg) < 50:
                return True

        return False

    def _parse_natural_refine_intent(self, user_message: str) -> tuple[bool, str]:
        """Check if message indicates refinement intent. Returns (is_refine, instruction)."""
        msg = user_message.lower().strip()

        refine_indicators = [
            "shorter", "longer", "more casual", "less salesy", "more formal",
            "different", "try again", "change", "tweak", "adjust", "rewrite",
            "make it", "keep it", "less", "more",
        ]

        for indicator in refine_indicators:
            if indicator in msg:
                return True, user_message

        if any(word in msg for word in ["refine", "edit", "modify", "revise"]):
            return True, user_message

        return False, ""

    def _is_greeting(self, user_message: str) -> bool:
        """Check if message is a greeting or casual opener."""
        msg = user_message.lower().strip()

        pure_greetings = ["hi", "hello", "hey", "yo", "sup", "hiya", "greetings"]
        if msg in pure_greetings:
            return True

        greeting_prefixes = [
            "hi ", "hi,", "hi.", "hi!", "hello ", "hello,", "hello.",
            "hey ", "hey,", "hey.", "hey!", "yo ", "yo,",
            "good morning", "good afternoon", "good evening",
            "good day", "greetings", "howdy", "what's up", "whassup",
            "wassup", "wazzup", "how's it going", "how are you",
        ]
        for prefix in greeting_prefixes:
            if msg.startswith(prefix):
                return True

        casual_acknowledgements = [
            "thanks", "thank you", "thank u", "thx", "ty",
            "cool", "nice", "okay", "ok", "alright", "alrighty",
            "sure", "sounds good", "great", "perfect", "awesome",
            "no problem", "np", "no worries", "cheers",
            "got it", "understood", "understood.",
        ]
        if msg in casual_acknowledgements:
            return True

        short_social = ["ok", "cool", "nice", "sure", "yeah", "yep", "nah"]
        if len(msg) <= 5 and msg in short_social:
            return True

        return False

    def _get_greeting_response(self, recent_messages: list[str]) -> str:
        """Get a natural greeting response with variation."""
        pool = RESPONSE_VARIATIONS.get("greeting", [])
        recent_lower = [m.lower() for m in (recent_messages or [])]
        available = [p for p in pool if p.lower() not in recent_lower]
        if available:
            return random.choice(available)
        return pool[0] if pool else "Hey — what are you looking to promote today?"

    def _get_onboarding_prompt(self, recent_messages: list[str]) -> str:
        """Get a conversational onboarding prompt."""
        pool = RESPONSE_VARIATIONS.get("onboarding", [])
        recent_lower = [m.lower() for m in (recent_messages or [])]
        available = [p for p in pool if p.lower() not in recent_lower]
        if available:
            return random.choice(available)
        return pool[0] if pool else "Who are you trying to reach?"

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
            welcome_text = generate_conversational_response(
                user_message="",
                stage="session_start",
                context={"user_id": user["id"]},
                recent_assistant_messages=[],
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=welcome_text,
                )
            )
            prompt_text = _get_service_prompt_variation([])
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=prompt_text,
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
                    text="Hey — I'm Loqi. I'll help you find leads and run outreach.",
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
                prompt_text = _get_target_prompt_variation([], existing_context["service"])
                outputs.extend(
                    _assistant_bundle(
                        workflow_session_id=workflow_session_id,
                        text=prompt_text,
                        message_type="prompt",
                    )
                )
                return self._finish_response(user_id=user["id"], messages=outputs, events=events)

            prompt_text = _get_service_prompt_variation([])
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=prompt_text,
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

        user_prefs = get_user_preferences(user["id"]) or {}

        print(f"[DEBUG] service={service}, target={target}, selected_lead_id={selected_lead_id}, has_draft={has_draft}")

        parsed_service, parsed_target, signals = extract_single_message_fields(normalized_text)
        print(f"[DEBUG] parsed_service={parsed_service}, parsed_target={parsed_target}, signals={signals}")

        if self._is_greeting(normalized_text) and not parsed_service and not parsed_target:
            print(f"[GREETING] Casual message detected — responding conversationally")
            greeting_response = self._get_greeting_response(assistant_messages[-3:])
            onboarding_prompt = self._get_onboarding_prompt(assistant_messages[-3:])
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=greeting_response,
                )
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=onboarding_prompt,
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if parsed_service and not service:
            service = parsed_service
            print(f"[CONTEXT] Inferred service from single message: {service}")
            if parsed_target:
                target = parsed_target
                print(f"[CONTEXT] Inferred target from single message: {target}")

        if parsed_target and not target and service:
            target = parsed_target
            print(f"[CONTEXT] Inferred target from single message: {target}")

        if parsed_service and parsed_target and not service:
            print(f"[CONTEXT] Combined message detected — skipping redundant questions")

        if not service:
            prompt_text = self._get_dynamic_prompt(
                stage="ask_service",
                context=context,
                recent_messages=assistant_messages[-3:],
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=prompt_text,
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if not target:
            prompt_text = self._get_dynamic_prompt(
                stage="ask_target",
                context=context,
                recent_messages=assistant_messages[-3:],
                service=service,
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=prompt_text,
                    message_type="prompt",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        lead_list_active = (
            assistant_messages
            and "Search for leads in" in (assistant_messages[-1] or "")
        )

        is_send_intent = self._parse_natural_send_intent(normalized_text)
        is_refine, refine_instruction = self._parse_natural_refine_intent(normalized_text)

        if is_send_intent and selected_lead_id:
            print(f"[INTENT] Natural send intent detected from: {normalized_text}")
            selected_lead = get_lead_by_id(selected_lead_id)
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
            next_text = _get_after_send_variation()
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
                    message_type="status",
                )
            )
            events.append({"type": "outreach.sent"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if is_refine and previous_message:
            prefs_from_refine = detect_preferences_from_refinement(normalized_text)
            for key, value in prefs_from_refine.items():
                save_user_preference(user["id"], key, value)
            print(f"[PREFERENCES] Detected from refinement: {prefs_from_refine}")

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
                    "edit_request": refine_instruction,
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
            next_text = self._get_dynamic_prompt(
                stage="after_draft",
                context={"lead_name": selected_lead.get("name", "")},
                recent_messages=assistant_messages[-3:],
                user_preferences=prefs_from_refine,
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
                    message_type="status",
                )
            )
            events.append({"type": "draft.refined"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if is_refine and not previous_message:
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text="No draft to refine yet. Let me draft something first.",
                    message_type="status",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if selected_lead_id:
            print(f"[WORKFLOW] selected_lead_id={selected_lead_id} — skipping lead search pipeline")
            if normalized_text.isdigit():
                print(f"[WORKFLOW] numeric reply with selected_lead — treating as lead re-selection")
        elif not normalized_text.isdigit() and not is_send_intent:
            print(f"[WORKFLOW] no selected_lead and non-send text — triggering lead search")
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
            from services.ai import classify_intent, OpenAIError

            enriched_context = build_classification_context(
                user_message=normalized_text,
                session_context=context,
                workflow_state={"stage": "awaiting_action"},
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
        except Exception as e:
            print(f"[WORKFLOW] Intent classification failed: {e} — using natural action parsing")
            action, detail = classify_natural_action(
                normalized_text,
                {
                    "service": service,
                    "target": target,
                    "selected_lead_id": selected_lead_id,
                    "has_draft": has_draft,
                },
            )

            if action in ("send", "send_it"):
                classified_intent = "send"
            elif action in ("select_number", "select_recent"):
                classified_intent = "select_lead"
            elif action in ("refine", "refine_shorter", "refine_longer", "refine_casual", "refine_another"):
                classified_intent = "refine_message"
            elif action == "new_search":
                classified_intent = "new_search"
            elif action == "defer":
                classified_intent = "defer"
            else:
                classified_intent = "unknown"

            print(f"[WORKFLOW] Natural action parsed: '{action}', detail='{detail}'")

        print(f"[WORKFLOW] intent classified: '{classified_intent}' (user_input='{normalized_text}')")

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
            next_text = _get_after_send_variation()
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
                    message_type="status",
                )
            )
            events.append({"type": "outreach.sent"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "select_lead" or normalized_text.isdigit():
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

            print(f"[WORKFLOW] lead selected: id={selected_lead.get('id')}, name={selected_lead.get('name')}")

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
            next_text = self._get_dynamic_prompt(
                stage="after_draft",
                context={"lead_name": selected_lead.get("name", "")},
                recent_messages=assistant_messages[-3:],
                user_preferences=user_prefs,
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
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

            prefs_from_refine = detect_preferences_from_refinement(normalized_text)
            for key, value in prefs_from_refine.items():
                save_user_preference(user["id"], key, value)

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
            next_text = self._get_dynamic_prompt(
                stage="after_draft",
                context={"lead_name": selected_lead.get("name", "")},
                recent_messages=assistant_messages[-3:],
                user_preferences=prefs_from_refine,
            )
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
                    message_type="status",
                )
            )
            events.append({"type": "draft.refined"})
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        if classified_intent == "refine_message":
            next_text = _get_refine_options_variation()
            outputs.extend(
                _assistant_bundle(
                    workflow_session_id=workflow_session_id,
                    text=next_text,
                    message_type="status",
                )
            )
            return self._finish_response(user_id=user["id"], messages=outputs, events=events)

        outputs.extend(
            _assistant_bundle(
                workflow_session_id=workflow_session_id,
                text="I'm not sure what you meant. Try picking a lead number, saying 'send', or telling me what to change.",
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
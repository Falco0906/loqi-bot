import json
import os
import random
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[conversational_ai] {message}")


def _send_openai_request(system_text: str, user_text: str, timeout: int = 30) -> str | None:
    """Send request to OpenAI API. Returns the response text or None on failure."""
    if not OPENAI_API_KEY:
        _log("OPENAI_API_KEY not configured")
        return None

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_text}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if response.status_code >= 400:
            _log(f"OpenAI API error: {response.status_code}")
            return None

        data = response.json()
        try:
            return data["output"][0]["content"][0]["text"].strip()
        except Exception:
            return data.get("output_text", "").strip() or None

    except Exception as e:
        _log(f"OpenAI request failed: {e}")
        return None


RESPONSE_VARIATIONS = {
    "greeting": [
        "Hey — what are you looking to promote today?",
        "Hi! Who are you trying to reach?",
        "Hey, tell me a bit about what you're selling.",
        "Hey there — what kind of outreach are you running?",
        "Hi! What are you looking to sell or promote?",
        "Hey — who are we trying to connect with?",
        "Hello! What does your outbound look like?",
        "Hey — what's the target for today?",
    ],
    "onboarding": [
        "What are you looking to promote?",
        "Who are you trying to reach?",
        "What does your ideal customer look like?",
        "What kind of outreach are you running?",
        "What's the target for today?",
        "What are you selling?",
    ],
    "ask_service": [
        "What do you sell?",
        "What's your product or service?",
        "What are you offering?",
        "Tell me what you're selling.",
        "What does your business do?",
    ],
    "ask_target": [
        "Who are you trying to reach?",
        "What kind of businesses or people are you targeting?",
        "Who makes sense to contact?",
        "What's your ideal customer look like?",
        "Who should I look for?",
    ],
    "after_lead_list": [
        "Any of these jump out at you?",
        "Want me to draft outreach for one of these?",
        "Which lead should we focus on?",
        "See anyone worth reaching out to?",
        "Pick one and I'll prepare a personalized message.",
        "Want me to start drafting for any of these?",
        "Should we prioritize one of these?",
        "Let me know if you want me to draft for any of these.",
        "Which one interests you most?",
    ],
    "after_draft": [
        "Here's a draft for you. Want me to refine it, or should I send it as-is?",
        "Draft's ready. Sound good, or want me to tweak it?",
        "I've drafted something personalized. Should I send it or make some changes?",
        "This is what I'm thinking — want me to adjust the tone, make it shorter, or send as-is?",
        "Here's a draft. Just say what you'd like to change or tell me to send it.",
        "Draft is ready. Want me to make it shorter, more casual, or less salesy? Or just send it?",
        "Here's what I'd send. Let me know if you want adjustments or if you're ready to go.",
    ],
    "confirming_send": [
        "Ready to send this?",
        "Want me to go ahead and send it?",
        "Should I fire this off?",
        "All set to send?",
        "Ready when you are.",
    ],
    "select_lead_confirm": [
        "Got it — drafting now.",
        "On it.",
        "Selecting that lead and drafting outreach.",
        "Perfect, let me pull together something personalized.",
        "Alright, getting a draft ready for them.",
    ],
    "session_start": [
        "Hey — I'm Loqi. I help you find leads and run personalized outreach.",
        "Hi! I'm Loqi, your outbound assistant.",
        "Welcome! I help find leads and craft personalized messages.",
    ],
    "refine_options": [
        "Want me to try a different angle?",
        "I can adjust the length, tone, or make it more casual.",
        "What would you like to change?",
        "Tell me what to tweak — shorter, longer, different tone?",
    ],
}

NEGATIVE_RESPONSES = [
    "no", "nope", "nah", "not yet", "not really", "wait", "hold on",
    "actually", "maybe later", "skip", "never mind", "cancel",
]

REFINE_KEYWORDS = [
    "longer", "shorter", "more", "less", "casual", "formal",
    "aggressive", "softer", "friendly", "professional", "breezier",
    "salesy", "personal", "quick", "concise", "detailed",
    "different", "another", "try", "change", "tweak", "adjust",
    "rewrite", "rephrase", "tone", "style",
]

SEND_KEYWORDS = [
    "send", "go", "go ahead", "send it", "do it", "yes", "yeah", "yep", "sure", "ok",
    "fire", "fire it", "ship it", "hit it", "send it", "dispatch", "launch",
    "go for it", "let's go", "send it out", "email", "mail it", "drop it",
]

SELECT_KEYWORDS = [
    "that one", "this one", "first", "second", "third", "pick", "select", "choose",
    "number", "option", "lead", "them", "him", "her", "that person", "this person",
]

SELECT_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "a": "1", "the": "1",
}

REFINE_SHORT_PHRASES = [
    "shorter", "make it shorter", "keep it short", "more concise",
    "less", "make it less", "cut it down",
    "longer", "make it longer", "expand it", "more detail",
    "casual", "more casual", "less formal", "friendlier",
    "formal", "more formal", "professional",
    "salesy", "less salesy", "not so salesy", "softer",
    "breezy", "less intense", "lighter tone",
]

SEND_SHORT_PHRASES = [
    "send it", "go ahead", "send", "go", "do it", "yes", "yeah",
    "fire", "ship", "drop it", "hit send", "send now",
]

REFINE_SEND_PHRASES = [
    ("send", "send"),
    ("send it", "send"),
    ("send as is", "send"),
    ("looks good", "send"),
    ("this works", "send"),
    ("good enough", "send"),
    ("that works", "send"),
    ("perfect", "send"),
    ("works for me", "send"),
    ("shorter", "refine_shorter"),
    ("make it shorter", "refine_shorter"),
    ("longer", "refine_longer"),
    ("more casual", "refine_casual"),
    ("less salesy", "refine_casual"),
    ("try again", "refine_another"),
    ("different", "refine_another"),
    ("another version", "refine_another"),
]

LEAD_INDICATORS = {
    "service_verbs": ["sell", "selling", "offer", "offering", "provide", "providing",
                      "build", "building", "make", "making", "create", "creating",
                      "have", "do", "help", "for"],
    "target_verbs": ["for", "targeting", "to", "helping", "serving"],
    "target_nouns": ["restaurants", "restaurant", "hotels", "hotel", "businesses",
                     "companies", "firms", "teams", "ops", "owners", "operators",
                     "managers", "franchise", "chains", "groups", "practices",
                     "clinics", "spas", "salons", "gyms", "retail", "stores"],
}


def _extract_single_message_fields(user_message: str) -> tuple[str | None, str | None, list[str]]:
    """
    Parse a single user message to extract service and target.
    Returns (service, target, signals).
    """
    msg = (user_message or "").strip()
    if not msg:
        return None, None, []

    msg_lower = msg.lower()
    signals = []

    has_service_verb = any(verb in msg_lower for verb in LEAD_INDICATORS["service_verbs"])
    has_target_verb = any(verb in msg_lower for verb in LEAD_INDICATORS["target_verbs"])
    has_target_noun = any(noun in msg_lower for noun in LEAD_INDICATORS["target_nouns"])

    if has_service_verb and has_target_noun:
        signals.append("combined_message")

    separators = [" for ", " to ", " targeting ", " helping ", " serving "]

    for sep in separators:
        if sep in msg_lower:
            parts = msg.split(sep, 1)
            if len(parts) == 2:
                service_candidate = parts[0].strip()
                target_candidate = parts[1].strip()

                service_clean = service_candidate.strip(".,!?")
                target_clean = target_candidate.strip(".,!?")

                if len(service_clean) > 2 and len(target_clean) > 2:
                    return service_clean, target_clean, ["separated_format"]

    service_fragments = ["we ", "i ", "my ", "our "]
    for frag in service_fragments:
        if msg_lower.startswith(frag):
            potential = msg[len(frag):].strip()
            if potential and len(potential) > 3:
                first_word = potential.split()[0] if potential.split() else ""
                if first_word and first_word not in ["sell", "offer", "provide", "build", "help"]:
                    return potential, None, ["starts_with_service"]

    if "?" not in msg and len(msg.split()) > 2:
        return msg, None, ["freeform_message"]

    return None, None, []


def _classify_natural_action(user_message: str, context: dict) -> tuple[str, Optional[str]]:
    """
    Classify natural language into workflow actions with nuance.
    Returns (action, detail).
    """
    msg = user_message.strip()
    msg_lower = msg.lower()

    for phrase, action in REFINE_SEND_PHRASES:
        if phrase in msg_lower:
            return action, phrase

    if msg_lower in ["shorter", "make it shorter", "keep it short", "more concise", "cut it"]:
        return "refine_shorter", None
    if msg_lower in ["longer", "make it longer", "expand it", "more detail", "more content"]:
        return "refine_longer", None
    if any(phrase in msg_lower for phrase in ["more casual", "less formal", "friendlier", "breezy"]):
        return "refine_casual", None
    if any(phrase in msg_lower for phrase in ["more formal", "less casual", "professional"]):
        return "refine_formal", None
    if any(phrase in msg_lower for phrase in ["less salesy", "not so salesy", "softer", "subtle"]):
        return "refine_casual", None
    if any(phrase in msg_lower for phrase in ["different", "another", "try again", "rethink"]):
        return "refine_another", None

    if any(word in msg_lower for word in SEND_KEYWORDS):
        return "send", None

    for number_word, number_str in SELECT_NUMBER_WORDS.items():
        if number_word in msg_lower:
            return "select_number", number_str

    if "that one" in msg_lower or "this one" in msg_lower or "pick" in msg_lower:
        return "select_recent", None

    if any(word in msg_lower for word in NEGATIVE_RESPONSES):
        return "defer", None

    if any(kw in msg_lower for kw in REFINE_KEYWORDS):
        return "refine", msg

    if "new" in msg_lower and ("search" in msg_lower or "look" in msg_lower):
        return "new_search", None

    return "unknown", None


def get_context_aware_prompt(
    stage: str,
    context: dict,
    recent_assistant_messages: list[str],
) -> str:
    """
    Generate context-aware system prompt for response generation.
    """
    service = context.get("service", "")
    target = context.get("target", "")
    selected_lead = context.get("selected_lead")
    has_draft = context.get("has_draft", False)
    lead_count = context.get("lead_count", 0)
    user_preferences = context.get("user_preferences", {})

    system = (
        "You are Loqi, an AI SDR assistant that sounds like a smart, friendly colleague.\n"
        "You are NOT a chatbot. You are NOT a form. You think and adapt.\n\n"
        "Rules:\n"
        "- NEVER repeat the same phrasing the assistant just used\n"
        "- If there's already a lead list shown, don't say 'here are leads' again\n"
        "- If the user already provided service and target, don't ask redundant questions\n"
        "- Keep responses short, natural, and conversational\n"
        "- Never be overly formal or robotic\n"
        "- Ask ONE question at a time max\n"
        "- Be direct when there's no ambiguity\n\n"
    )

    if stage == "initial":
        system += (
            "The user just started. Respond with a brief welcome and ask ONE natural question.\n"
            "Do NOT say 'What do you sell?' in the same way twice.\n"
        )
    elif stage == "need_service":
        system += (
            "Missing service. Ask naturally in ONE way only.\n"
            f"Recent assistant messages to avoid repeating: {recent_assistant_messages[-3:]}\n"
        )
    elif stage == "need_target":
        system += (
            "Service is known but target is missing. Ask ONE question about who they want to reach.\n"
            f"Service known: {service}\n"
            f"Recent phrases to avoid: {recent_assistant_messages[-3:]}\n"
        )
    elif stage == "after_leads":
        system += (
            "Lead list was just shown. Help the user decide what to do next.\n"
            f"Lead count: {lead_count}\n"
            f"Recent phrasing to avoid: {recent_assistant_messages[-2:]}\n"
        )
    elif stage == "after_draft":
        system += (
            "A draft was just created. Give the user one clear option to send, refine, or move on.\n"
            f"Lead: {selected_lead.get('name', 'unknown') if selected_lead else 'unknown'}\n"
            f"User preferences: {user_preferences}\n"
            f"Recent phrasing to avoid: {recent_assistant_messages[-2:]}\n"
        )
    elif stage == "after_send":
        system += (
            "Email was just sent. Offer a natural next step — more leads, refinement, or close.\n"
        )
    elif stage == "refining":
        system += (
            "User wants to refine. Acknowledge and apply their feedback naturally.\n"
        )
    else:
        system += "Respond naturally based on the context."

    return system


def generate_conversational_response(
    user_message: str,
    stage: str,
    context: dict,
    recent_assistant_messages: list[str],
) -> str:
    """
    Generate AI-powered conversational response.
    Falls back to variation pools if AI fails.
    """
    system_prompt = get_context_aware_prompt(stage, context, recent_assistant_messages)

    user_text = (
        f"User said: {user_message}\n"
        f"Current stage: {stage}\n"
        f"Service known: {context.get('service', 'unknown')}\n"
        f"Target known: {context.get('target', 'unknown')}\n"
        f"Has draft: {context.get('has_draft', False)}\n"
        f"Lead count: {context.get('lead_count', 0)}\n"
        f"User message count: {context.get('user_message_count', 0)}\n\n"
        "Generate ONE short response (1-2 sentences max). No formalities."
    )

    response = _send_openai_request(system_prompt, user_text, timeout=20)

    if response and len(response.strip()) > 0:
        _log(f"AI response generated: {response[:80]}")
        return response.strip()

    return _get_fallback_variation(stage, recent_assistant_messages)


def _get_fallback_variation(stage: str, recent_messages: list[str]) -> str:
    """Get a variation from pools, avoiding recent repetitions."""
    pool = RESPONSE_VARIATIONS.get(stage, ["What would you like to do next?"])

    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if not available:
        available = pool

    return random.choice(available)


def _get_service_prompt_variation(recent_messages: list[str]) -> str:
    """Get a fresh 'what do you sell' variant."""
    pool = RESPONSE_VARIATIONS["ask_service"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]
    return random.choice(available if available else pool)


def _get_target_prompt_variation(recent_messages: list[str], service: str) -> str:
    """Get a fresh 'who do you want to reach' variant."""
    pool = RESPONSE_VARIATIONS["ask_target"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if available and random.random() > 0.7:
        return random.choice(available)

    short_variants = [
        f"Who should I look for?",
        f"Got it. Who are you targeting?",
        f"Perfect. Who's your ideal customer?",
        f"And who are you trying to reach?",
        f"Who makes sense to contact here?",
    ]
    return random.choice(short_variants)


def _get_after_leads_variation(recent_messages: list[str], lead_count: int) -> str:
    """Get a fresh 'after lead list' variant."""
    pool = RESPONSE_VARIATIONS["after_lead_list"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if not available:
        available = pool

    return random.choice(available)


def _get_after_draft_variation(recent_messages: list[str], lead_name: str, preferences: dict) -> str:
    """Get a fresh 'after draft' variant with awareness of user preferences."""
    pool = RESPONSE_VARIATIONS["after_draft"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if not available:
        available = pool

    base = random.choice(available)

    if preferences.get("tone") == "casual":
        base = base.replace("Sound good", "Sound good?").replace("Should I", "Want me to")

    return base


def _get_after_send_variation() -> str:
    """Get a fresh 'after send' variant."""
    return random.choice([
        "Sent! Want to do another one?",
        "Done. Should I find another lead?",
        "Email is on its way. Ready for another?",
        "Sent. Want me to look for more leads?",
        "All sent. I can find more leads if you want.",
    ])


def _get_refine_options_variation() -> str:
    """Get a fresh refinement prompt."""
    return random.choice([
        "What would you like to change?",
        "How should I adjust it?",
        "What should be different?",
        "Tell me what to tweak.",
    ])


def detect_preferences_from_refinement(user_message: str) -> dict:
    """
    Extract user preferences from refinement messages.
    """
    msg = user_message.lower()
    prefs = {}

    if any(kw in msg for kw in ["shorter", "concise", "brief", "quick"]):
        prefs["length"] = "short"
    elif any(kw in msg for kw in ["longer", "more detail", "expand", "deeper"]):
        prefs["length"] = "long"

    if any(kw in msg for kw in ["casual", "friendly", "breezy", "less formal", "chill"]):
        prefs["tone"] = "casual"
    elif any(kw in msg for kw in ["formal", "professional", "corporate"]):
        prefs["tone"] = "formal"

    if any(kw in msg for kw in ["less salesy", "not salesy", "softer", "subtle", "natural"]):
        prefs["style"] = "soft_sales"

    return prefs


def build_classification_context(
    user_message: str,
    session_context: dict,
    workflow_state: dict,
) -> dict:
    """
    Build enriched context for intent classification including:
    - parsed single-message fields
    - workflow stage
    - user preferences
    - conversation history summary
    """
    user_messages = session_context.get("user_messages", [])
    assistant_messages = session_context.get("assistant_messages", [])
    recent = (user_messages + assistant_messages)[-5:]

    service, target, signals = _extract_single_message_fields(user_message)

    action, detail = _classify_natural_action(user_message, {
        "service": session_context.get("service"),
        "target": session_context.get("target"),
        "has_draft": bool(session_context.get("selected_lead_id")),
    })

    context = {
        "user_message": user_message,
        "service": service or session_context.get("service"),
        "target": target or session_context.get("target"),
        "selected_lead_id": session_context.get("selected_lead_id"),
        "has_draft": bool(session_context.get("selected_lead_id")),
        "user_message_count": len(user_messages),
        "recent_signals": signals,
        "parsed_action": action,
        "parsed_action_detail": detail,
        "lead_list_active": (
            "Search for leads in" in (assistant_messages[-1] or "")
            if assistant_messages else False
        ),
        "recent_conversation": recent[-3:],
        "workflow_stage": workflow_state.get("stage", "unknown"),
    }

    return context


def should_skip_question(
    user_message: str,
    session_context: dict,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if the user already provided sufficient info to skip questions.
    Returns (should_skip, service, target).
    """
    service, target, signals = _extract_single_message_fields(user_message)

    existing_service = session_context.get("service")
    existing_target = session_context.get("target")

    combined_message = "combined_message" in signals

    if combined_message and service and target:
        return True, service, target

    if service and not existing_service and not existing_target:
        if len(user_message.split()) > 3:
            return True, service, None

    return False, None, None


def suggest_next_action(
    stage: str,
    context: dict,
) -> str:
    """
    AI-guided suggestion for the next action.
    """
    system = (
        "You suggest ONE immediate next action for a B2B sales assistant.\n"
        "Be direct, concise, and actionable.\n"
        "Return only the action text, no explanation.\n"
        "Examples:\n"
        "- 'Draft outreach for [name]'\n"
        "- 'Send the email'\n"
        "- 'Find restaurant operators in [area]'\n"
        "- 'Refine the message'\n"
        "- 'Look for more leads'\n"
    )

    user_text = f"Stage: {stage}\nContext: {context}"

    result = _send_openai_request(system, user_text, timeout=15)

    if result and len(result) > 0 and len(result) < 100:
        return result.strip()

    return _suggest_fallback_action(stage, context)


def _suggest_fallback_action(stage: str, context: dict) -> str:
    """Fallback action suggestions based on stage."""
    suggestions = {
        "need_service": "Ask what they sell",
        "need_target": "Ask who they want to reach",
        "leads_ready": "Let them pick a lead",
        "draft_ready": "Ask if they want to send or refine",
        "refining": "Apply their feedback",
        "sending": "Send the email",
        "complete": "Offer to find more leads",
    }
    return suggestions.get(stage, "Continue the conversation")
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
        "What are you offering? Describe it however feels natural.",
        "What does your product or service do?",
        "Tell me what you're bringing to market.",
        "What are you looking to promote?",
        "What do you offer? Give me a quick description.",
    ],
    "ask_target": [
        "Who would your ideal buyer be?",
        "What kind of businesses or roles are you targeting?",
        "Who do you want me to find for you?",
        "Describe your ideal customer — industry, role, or company type.",
        "What does the right buyer look like for this?",
    ],
    "after_lead_list": [
        "These are ranked by buying potential. Pick a lead and I'll draft a personalized message, or tell me to draft for multiple.",
        "I've scored these by fit and buying signals. Which one should we focus on first?",
        "Here are the strongest matches. Reply with the number you want to start with.",
        "These are sorted by relevance. Which lead stands out to you?",
        "I've ranked these by who's most likely to engage. Pick one to begin outreach.",
    ],
    "after_draft": [
        "I've drafted something personalized based on what I know about the company. Take a look.\n\nIf you'd like, I can:\n• make it shorter\n• sound more casual\n• make it more direct\n• regenerate it\n\nOr just tell me to send it as-is.",
        "Here's what I'd send to this contact. It's grounded in their business profile.\n\nOptions if you want changes:\n• shorter or longer\n• more casual or formal\n• different angle\n\nOr say 'send it' and I'll fire it off.",
        "I've tailored this message to their specific situation. Let me know what you think.\n\nI can:\n• tighten it up\n• make it friendlier\n• make it more direct\n• start over\n\nOr just say 'go ahead' and I'll send it.",
        "Take a look at the draft. It's written with their company context in mind.\n\nWant me to:\n• shorten it\n• make it less salesy\n• use a stronger tone\n• try something different\n\nOr tell me to send as-is.",
    ],
    "confirming_send": [
        "Ready to send this?",
        "Want me to go ahead and send it?",
        "Should I fire this off?",
        "All set to send?",
        "Ready when you are.",
    ],
    "select_lead_confirm": [
        "I'm putting together a personalized first message based on their profile...",
        "I'm tailoring this specifically for their business context...",
        "Let me draft something grounded in what I know about them...",
        "Perfect — I'm writing a message that fits their situation...",
        "Working on a custom outreach for this lead...",
    ],
    "session_start": [
        "Hey! I'm Loqi — I help you find the right buyers and craft outreach that actually sounds like you.\n\nTo get started, just tell me what you're offering and who you want to reach. Something like:\n• \"I sell AI sales tools for SaaS companies\"\n• \"My agency builds websites for dental clinics\"\n• \"I offer bookkeeping for restaurant groups\"",
        "Hi there! I'm Loqi. I find promising leads and help you reach out with messages that feel personal, not templated.\n\nTo start, tell me what you do and who you're after. For example:\n• \"We provide HR software for construction firms\"\n• \"I do lead generation for real estate agents\"\n• \"My product automates hiring for healthcare\"",
        "Welcome to Loqi. Think of me as your SDR — I find the right people and help you start real conversations.\n\nJust describe what you're selling and who you're targeting:\n• \"CRM for boutique real estate agencies\"\n• \"Safety training for manufacturing plants\"\n• \"Dev tools for growing SaaS teams\"",
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
    if not available:
        available = pool
    return random.choice(available)


def _get_target_prompt_variation(recent_messages: list[str], service: str) -> str:
    """Get a fresh 'who do you want to reach' variant."""
    pool = RESPONSE_VARIATIONS["ask_target"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if not available:
        available = pool

    if available and random.random() > 0.5:
        return random.choice(available)

    short_variants = [
        f"Who should I look for?",
        f"Nice. Who would you like to reach with {service}?",
        f"Great. What kind of businesses are you targeting with {service}?",
        f"Perfect. Who's the right audience for {service}?",
        f"Who makes sense to contact for {service}?",
    ]
    return random.choice(short_variants)


def _get_after_leads_variation(recent_messages: list[str], lead_count: int) -> str:
    """Get a fresh 'after lead list' variant with ranking context."""
    if lead_count > 0:
        intro = random.choice([
            f"I found **{lead_count} promising matches** sorted by buying potential.",
            f"I've ranked **{lead_count} leads** by fit and engagement signals.",
            f"Here are **{lead_count} potential buyers** — ranked by relevance.",
        ])
    else:
        intro = ""

    pool = RESPONSE_VARIATIONS["after_lead_list"]
    recent_lower = [m.lower() for m in (recent_messages or [])]
    available = [p for p in pool if p.lower() not in recent_lower]

    if not available:
        available = pool

    prompt = random.choice(available)
    if intro:
        return f"{intro}\n\n{prompt}"
    return prompt


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


def _get_pre_lead_search_transition() -> str:
    """Transition message before searching for leads."""
    return random.choice([
        "Looking through potential buyers that match your criteria...",
        "Searching for businesses that fit your ICP...",
        "I'm scanning for the strongest opportunities...",
        "Let me find companies that match what you described...",
        "Searching for the right leads in this space...",
    ])


def _get_pre_draft_transition() -> str:
    """Transition message before drafting."""
    return random.choice([
        "I'm putting together a personalized first message...",
        "Tailoring this based on their business profile...",
        "Let me write something grounded in their context...",
        "Crafting a message that fits their specific situation...",
        "Working on a custom draft for this lead...",
    ])


def _get_refine_confirmation(instruction: str) -> str:
    """Natural acknowledgment when user asks for refinement."""
    msg = instruction.lower().strip()
    if any(kw in msg for kw in ["shorter", "concise", "brief"]):
        return random.choice([
            "Done — I tightened it up.",
            "Made it more concise.",
            "Trimmed it down for you.",
        ])
    if any(kw in msg for kw in ["longer", "more detail", "expand"]):
        return random.choice([
            "Done — I expanded it with more context.",
            "Added more substance to it.",
            "Made it a bit more detailed.",
        ])
    if any(kw in msg for kw in ["casual", "friendly", "less formal", "breezy"]):
        return random.choice([
            "Made it more conversational.",
            "I loosened it up a bit.",
            "Less formal, more natural.",
        ])
    if any(kw in msg for kw in ["formal", "professional"]):
        return random.choice([
            "Made it more professional.",
            "I polished the tone.",
            "Sounds more formal now.",
        ])
    if any(kw in msg for kw in ["less salesy", "softer", "subtle"]):
        return random.choice([
            "Removed most of the sales language.",
            "Made it less pushy.",
            "Softened the pitch significantly.",
        ])
    if any(kw in msg for kw in ["direct", "confident", "stronger"]):
        return random.choice([
            "Made it more direct.",
            "I gave it a stronger tone.",
            "More confident, less hedging.",
        ])
    return random.choice([
        "Got it — applying that feedback now.",
        "Let me adjust it based on that.",
        "Made the change you asked for.",
    ])


def _get_after_send_variation() -> str:
    """Get a fresh 'after send' variant."""
    return random.choice([
        "Sent! Want to find another lead to reach out to?",
        "Done. Should I look for more people in this space?",
        "Email's on its way. Ready for the next one?",
        "Sent. I can find more leads or we can refine a different one.",
        "All sent. Tell me if you want to continue with more leads.",
        "Done. Want me to search for another batch or refine someone else?",
    ])


def _get_refine_options_variation() -> str:
    """Get a fresh refinement prompt."""
    return random.choice([
        "Want me to try a different angle?",
        "I can adjust the length, tone, or make it more casual.",
        "What would you like to change?",
        "Tell me what to tweak — shorter, longer, different tone?",
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
            "Reply with a number to pick one" in (assistant_messages[-1] or "")
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


def generate_copilot_response(
    user_message: str,
    copilot_context: dict | None = None,
    context: dict | None = None,
) -> str:
    """Generate a response for the Copilot.

    The frontend sends structured data. This function merges the system prompt,
    page context, workspace snapshot, workspace analysis, conversation history,
    and user message before calling the LLM.
    """
    ctx = copilot_context or {}
    current_page = ctx.get("current_page", "unknown")
    page_context = ctx.get("page_context") or {}
    available_actions = ctx.get("available_actions") or []
    message_history = ctx.get("message_history") or []

    system = (
        "You are Loqi OS — an AI sales operator. You do not answer questions. You operate the workspace.\n\n"
        "Core principles:\n"
        "- Answer directly, then keep thinking: after answering, reason about the next logical step.\n"
        "- Notice things proactively: scan the workspace for patterns, bottlenecks, or opportunities the user hasn't asked about.\n"
        "- Never say \"There are\", \"The workspace contains\", \"Please provide more context\", or \"How can I help you today?\".\n"
        "- Chain work: when the user asks about one thing, offer to do the next step too.\n"
        "- Speak like an experienced operator: \"I'd focus on...\", \"The quickest win is...\", \"You're ready to...\", \"I also noticed...\"\n"
        "- After you answer, include 2-4 specific follow-up options as action buttons. Never ask \"Can you clarify?\" — instead offer concrete choices.\n"
        "- Keep responses concise (2-5 sentences). Use short paragraphs.\n"
        "- When user says \"this\" or \"it\", infer the referent from context or the last thing you discussed.\n\n"
        f"Page-aware behavior:\n"
        f"- When on Campaign page: talk about drafts, personalization quality, readiness to launch, lead sources.\n"
        f"- When on Draft Review page: act like a senior SDR writing coach. Identify problems, explain why they matter, and only rewrite when asked. Never start by saying you rewrote the draft. Start with observation and reasoning. Use the Draft Intelligence data to explain what to improve and why.\n"
        f"- When discussing drafts, think strategically: reference the buyer persona, company context, messaging strategy, predicted objections, and recommended CTA from Draft Intelligence. Ask questions like 'Would a CTO care about this?' or 'Should we address the budget concern?'\n"
        f"- Use buyer psychology to explain WHY a change matters, not just WHAT changed.\n"
        f"- When on Discovery page: talk about searches, lead quality, industries, campaign ideas.\n"
        f"- When on Mission Control: talk about overall priorities, health, next actions, cross-campaign insights.\n"
        f"- When on Campaign Intelligence: talk about performance, trends, what to optimize.\n"
        f"Current page: {current_page}\n"
        f"- Tailor everything to this page. If the user is on a Campaign page, do NOT talk about Discovery search results.\n"
        f"- If the user is on Draft Review, do NOT talk about finding leads.\n"
        f"- Reference things visible on the current page first, then mention related things elsewhere.\n\n"
        f"Action format: <<action:label:action_type>> (e.g. <<action:Select All:select_all>>)\n"
        f"Navigation format: <<action:label:/path>> (e.g. <<action:Discovery:/discovery>>)\n"
        f"Include 2-4 specific action or navigation buttons at the end of your response.\n"
        f"Good navigation targets: /campaigns, /draft, /discovery, /mission-control, /campaign-intelligence, /campaigns/{{id}}\n"
        f"Good action types: generate_strategy, launch_campaign, view_drafts, open_campaign, duplicate_campaign, delete_campaign, add_leads, approve_all, generate_drafts, select_all, search\n"
    )

    if available_actions:
        system += "\nAvailable actions on this page:\n"
        for a in available_actions:
            system += f"- {a}\n"

    if page_context:
        system += f"\nPage context:\n{json.dumps(page_context, indent=2)}\n"

    wc = ctx.get("workspace_context", {})
    snapshot = wc.get("snapshot", {})
    analysis = wc.get("analysis", {})

    if snapshot:
        campaigns = snapshot.get("campaigns", [])
        drafts = snapshot.get("drafts", {})
        timeline = snapshot.get("timeline", [])
        memory = snapshot.get("memory", {})
        jobs = snapshot.get("jobs", {})

        system += f"\n--- Workspace Snapshot ---\n"
        system += f"Total campaigns: {snapshot.get('campaign_count', 0)}\n"
        if campaigns:
            system += "Campaigns:\n"
            for c in campaigns:
                status_display = c.get("status", "?").replace("_", " ")
                system += (
                    f"  - {c.get('name', '?')} ({status_display}): "
                    f"{c.get('lead_count', 0)} leads, "
                    f"{c.get('pending_drafts', 0)} pending, "
                    f"{c.get('approved_drafts', 0)} approved\n"
                )
        system += f"Drafts: {drafts.get('total', 0)} total, {drafts.get('pending', 0)} pending, {drafts.get('approved', 0)} approved\n"
        system += f"Running jobs: {len(jobs.get('running', []))}\n"
        if timeline:
            system += "Recent activity:\n"
            for e in timeline[:5]:
                system += f"  - {e.get('text', '')}\n"
        if memory:
            system += f"Last action: {memory.get('last_action', 'none')}\n"
            if memory.get("last_campaign_name"):
                system += f"Last campaign: {memory['last_campaign_name']}\n"

    if analysis:
        cf = analysis.get("current_focus")
        if cf:
            system += f"\nCurrent focus: {cf.get('focus', 'unknown')}\n"
        rna = analysis.get("recommended_next_action")
        if rna:
            system += f"Recommended: {rna.get('title', '')}\n"
        priorities = analysis.get("campaign_priorities", [])
        if priorities:
            system += "Campaign priorities (highest first):\n"
            for cp in priorities[:5]:
                rank_label = cp.get("label", f"#{cp.get('rank', '?')}")
                system += f"  {rank_label}: {cp.get('name', '?')} ({', '.join(cp.get('reasons', []))})\n"
        wc_obj = analysis.get("workflow_continuation")
        if wc_obj:
            system += f"Next step: {wc_obj.get('where', 'Start something new')}\n"
        insights = analysis.get("cross_campaign_insights", [])
        if insights:
            system += "Cross-campaign insights:\n"
            for ins in insights:
                system += f"  - {ins.get('insight', '')}\n"
        attention = analysis.get("attention_items", [])
        if attention:
            system += "Items needing attention:\n"
            for a_item in attention[:3]:
                system += f"  - {a_item.get('title', '')}: {a_item.get('reason', '')}\n"

    current_draft = wc.get("current_draft")
    if current_draft:
        system += "\n--- Current Draft ---\n"
        system += f"Subject: {current_draft.get('subject', 'N/A')}\n"
        system += f"Recipient: {current_draft.get('lead_name', 'Unknown')} at {current_draft.get('lead_company', 'Unknown')}\n"
        system += f"Preview: {current_draft.get('text_preview', '')}...\n"
        intelligence = current_draft.get("draft_intelligence")
        if intelligence:
            system += "\nDraft Intelligence:\n"
            for cat_key in ["opening_strength", "personalization_quality", "pain_alignment", "relevance", "credibility", "cta_strength", "readability", "length", "tone", "confidence"]:
                cat = intelligence.get(cat_key)
                if cat:
                    label = cat.get("label", "N/A")
                    reason = cat.get("reason", "")
                    system += f"  {cat_key}: {label} — {reason}\n"
            if intelligence.get("patterns"):
                system += f"  Patterns: {', '.join(intelligence['patterns'][:5])}\n"
            if intelligence.get("strengths"):
                system += f"  Strengths: {'; '.join(intelligence['strengths'][:3])}\n"
            if intelligence.get("weaknesses"):
                system += f"  Weaknesses: {'; '.join(intelligence['weaknesses'][:3])}\n"
            if intelligence.get("opportunities"):
                system += f"  Opportunities: {'; '.join(intelligence['opportunities'][:3])}\n"

            persona = intelligence.get("persona")
            if persona:
                system += f"\n  Buyer Persona: {persona.get('role', 'unknown')} ({persona.get('seniority', 'unknown')})\n"
                system += f"  Goals: {'; '.join(persona.get('primary_goals', [])[:2])}\n"
                system += f"  Fears: {'; '.join(persona.get('primary_fears', [])[:2])}\n"
                system += f"  Communication: {', '.join(persona.get('communication_preferences', [])[:2])}\n"

            cc = intelligence.get("company_context")
            if cc:
                system += f"\n  Company: {cc.get('maturity', 'unknown')} — {cc.get('competitive_position', '')}\n"
                system += f"  Pain areas: {'; '.join(cc.get('potential_pain_areas', [])[:2])}\n"

            msg_strategy = intelligence.get("messaging_strategy")
            if msg_strategy:
                system += f"\n  Messaging angle: {msg_strategy.get('primary_angle', '')}\n"
                system += f"  Reasoning: {msg_strategy.get('reasoning', '')}\n"

            cta_rec = intelligence.get("cta_recommendation")
            if cta_rec:
                system += f"\n  Recommended CTA: {cta_rec.get('cta_type', '')}\n"

            objections = intelligence.get("objection_predictions", [])
            if objections:
                system += "\n  Predicted objections:\n"
                for o in objections[:2]:
                    system += f"    - {o.get('objection', '')} ({o.get('likelihood', '')})\n"

            framework = intelligence.get("framework_recommendation")
            if framework:
                system += f"\n  Framework: {framework.get('framework', '')}\n"
        rewrite_history = current_draft.get("rewrite_history", [])
        if rewrite_history:
            system += "\nRecent rewrites:\n"
            for entry in rewrite_history[:3]:
                summary = "; ".join(entry.get("change_summary", []))
                system += f"  - [{entry.get('strategy', 'custom')}] {summary}\n"

    if message_history:
        system += "\n--- Conversation History ---\n"
        for msg in message_history[-6:]:
            role = msg.get("role", "unknown")
            text = msg.get("text", "")[:200]
            system += f"{role}: {text}\n"

    conversation_intel = wc.get("conversation_intelligence")
    if conversation_intel:
        system += "\n--- Communication Intelligence ---\n"
        system += f"Stage: {conversation_intel.get('current_stage', 'unknown')}\n"
        system += f"Summary: {conversation_intel.get('summary', '')}\n"
        if conversation_intel.get('open_questions'):
            system += f"Open questions: {'; '.join(conversation_intel['open_questions'][:3])}\n"
        if conversation_intel.get('outstanding_objections'):
            system += f"Objections: {'; '.join(conversation_intel['outstanding_objections'][:3])}\n"
        if conversation_intel.get('pain_points'):
            system += f"Pain points: {'; '.join(conversation_intel['pain_points'][:3])}\n"
        if conversation_intel.get('business_goals'):
            system += f"Business goals: {'; '.join(conversation_intel['business_goals'][:3])}\n"
        if conversation_intel.get('buying_signals'):
            system += f"Buying signals: {'; '.join(conversation_intel['buying_signals'][:3])}\n"
        if conversation_intel.get('key_risks'):
            system += f"Risks: {'; '.join(conversation_intel['key_risks'][:3])}\n"
        if conversation_intel.get('key_opportunities'):
            system += f"Opportunities: {'; '.join(conversation_intel['key_opportunities'][:3])}\n"
        if conversation_intel.get('competitor_mentioned'):
            system += f"Competitor: {conversation_intel['competitor_mentioned']}\n"
        if conversation_intel.get('decision_confidence'):
            system += f"Decision confidence: {conversation_intel['decision_confidence']}/100\n"
        if conversation_intel.get('urgency'):
            system += f"Urgency: {conversation_intel['urgency']}\n"
        system += "\nWhen discussing conversations, reason like a Senior SDR. Don't just repeat what the lead said — interpret it. For example, instead of 'They asked about pricing', say 'Pricing requests usually indicate active evaluation rather than casual curiosity. Combined with the implementation questions, I'd classify this as a strong buying signal.' Use the structured intelligence above to provide strategic reasoning.\n"

    providers = wc.get("providers", [])
    if providers:
        system += "\n--- Connected Providers ---\n"
        for p in providers:
            system += f"  - {p.get('provider_type', '?')} ({p.get('status', '?')})"
            if p.get('email'):
                system += f" — {p['email']}"
            if p.get('last_sync'):
                system += f", last sync: {p['last_sync']}"
            system += "\n"
        ps = wc.get("provider_summary", {})
        if ps:
            system += f"Provider health: {ps.get('healthy', 0)} healthy, {ps.get('offline', 0)} offline\n"
        system += "You can discuss provider health, sync status, and connected accounts.\n"

    user_text = f"User message: {user_message.strip()}"

    _log(f"Copilot request: page={current_page}, campaigns={snapshot.get('campaign_count', 0)}, focus={analysis.get('current_focus', {}).get('focus', 'none') if analysis else 'none'}, history_len={len(message_history)}")
    response = _send_openai_request(system, user_text, timeout=20)

    if response and len(response.strip()) > 0:
        _log(f"Copilot response generated: {response[:80]}")
        return response.strip()

    return "I understand what you're looking at. What would you like me to do?"
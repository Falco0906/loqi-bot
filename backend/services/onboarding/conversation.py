"""Grounded wording for the deterministic onboarding question sequence.

The user's saved wizard answers own state. The model may phrase an acknowledgement;
it cannot choose the next field, change an answer, or claim external research.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from services.intelligence.ai import OpenAIError, _parse_json_result, _send_openai_request


log = logging.getLogger(__name__)

QUESTIONS = {
    "companyDescription": "What does your company do, and who is it for?",
    "idealCustomer": "Who usually decides to buy from you?",
    "differentiation": "What do customers choose you for over an alternative?",
    "annualGoal": "What would meaningful progress look like over the next year?",
    "biggestObstacle": "What is the biggest obstacle to that goal right now?",
}
FIELDS = tuple(QUESTIONS)
_WEBSITE_URL = re.compile(r"https?://[^\s,;)]+")

_SYSTEM_PROMPT = (
    "You are Loqi during a B2B company's onboarding. Respond to the user's "
    "latest answer like a thoughtful, concise colleague. Return JSON with "
    "exactly two strings: acknowledgement (one grounded sentence) and "
    "next_question (one natural, context-aware question about the provided "
    "next_topic, or an empty string if next_topic is null). The next_topic is "
    "chosen by the application; do not change its intent. Use only facts the "
    "user supplied. Do not praise unverified claims, invent company facts, "
    "claim to have researched a website, or offer a strategy. If an answer is "
    "unclear, acknowledge that plainly. Keep the whole reply short."
)


def _next_field(data: dict[str, Any]) -> str | None:
    return next((field for field in FIELDS if not str(data.get(field) or "").strip()), None)


def _guided_reply(next_field: str | None) -> str:
    prefix = "Loqi's AI reply is unavailable right now. Your answer was saved."
    return f"{prefix} {QUESTIONS[next_field]}" if next_field else prefix


async def answer_turn(service: Any, user_id: str, field: str, answer: str) -> dict[str, Any]:
    """Save an answer before optional AI wording; never repeat completed turns."""
    answer = answer.strip()
    if field not in QUESTIONS or not answer:
        raise ValueError("Choose a question and provide an answer")
    data = await service.get_wizard_data_strict(user_id)
    current = _next_field(data)
    turns = data.get("onboardingConversation")
    turns = list(turns) if isinstance(turns, list) else []

    if field != current:
        if data.get(field) != answer:
            raise ValueError("This answer is out of date. Reload onboarding to continue.")
        previous = next((turn for turn in turns if isinstance(turn, dict) and turn.get("field") == field), None)
        next_field = FIELDS[FIELDS.index(field) + 1] if field != FIELDS[-1] else None
        if previous and previous.get("reply"):
            return {
                "field": field, "answer": answer, "reply": previous["reply"],
                "mode": previous.get("mode", "guided"), "next_field": next_field,
                "complete": next_field is None,
            }
        return {
            "field": field, "answer": answer, "reply": _guided_reply(next_field),
            "mode": "guided", "next_field": next_field, "complete": next_field is None,
        }

    # The saved answer, not the model response, advances the question sequence.
    next_field = FIELDS[FIELDS.index(field) + 1] if field != FIELDS[-1] else None
    website = _WEBSITE_URL.search(answer)
    saved: dict[str, Any] = {
        field: answer,
        "onboardingConversation": [*turns, {"field": field, "answer": answer}],
        "onboarding_step": "conversational-discovery",
    }
    if website:
        saved["website"] = website.group(0)
    await service.save_wizard_data(user_id, saved)

    context = {key: data.get(key) for key in FIELDS if isinstance(data.get(key), str)}
    try:
        content = await asyncio.to_thread(
            _send_openai_request,
            _SYSTEM_PROMPT,
            json.dumps({
                "previous_answers": context, "latest_field": field,
                "latest_answer": answer, "next_topic": QUESTIONS[next_field] if next_field else None,
            }),
        )
        try:
            wording = _parse_json_result(content)
        except json.JSONDecodeError as error:
            raise OpenAIError("Invalid onboarding response", kind="invalid_output") from error
        acknowledgement = wording.get("acknowledgement") if isinstance(wording, dict) else None
        question = wording.get("next_question") if isinstance(wording, dict) else None
        if (not isinstance(acknowledgement, str) or not acknowledgement.strip()
                or not isinstance(question, str)
                or (next_field and (not question.strip() or "?" not in question))
                or (not next_field and question.strip())):
            raise OpenAIError("Invalid onboarding response", kind="invalid_output")
        reply = f"{acknowledgement.strip()} {question.strip()}".strip()
        if len(reply) > 400:
            raise OpenAIError("Invalid onboarding response", kind="invalid_output")
        mode = "ai"
    except OpenAIError as error:
        log.warning("onboarding_ai_reply_unavailable error_type=%s kind=%s", type(error).__name__, error.kind)
        mode = "guided"
        reply = _guided_reply(next_field)

    await service.save_wizard_data(user_id, {
        "onboardingConversation": [*turns, {
            "field": field, "answer": answer, "reply": reply, "mode": mode,
        }],
    })
    return {
        "field": field, "answer": answer, "reply": reply, "mode": mode,
        "next_field": next_field, "complete": next_field is None,
    }

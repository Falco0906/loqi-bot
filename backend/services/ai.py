import os

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[ai] {message}")


def _extract_response_text(data: dict) -> str | None:
    try:
        return data["output"][0]["content"][0]["text"].strip()
    except Exception:
        output_text = data.get("output_text")
        if output_text:
            return output_text.strip()
        return None


def _send_openai_request(system_text: str, user_text: str) -> str | None:
    if not OPENAI_API_KEY:
        _log("_send_openai_request error: missing OPENAI_API_KEY")
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
        _log(f"_send_openai_request payload: {payload}")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        data = response.json()
        _log(f"_send_openai_request status: {response.status_code}")
        _log(f"_send_openai_request response: {data}")
        response.raise_for_status()

        output_text = _extract_response_text(data)
        if output_text:
            return output_text.strip()

        _log("_send_openai_request error: missing output_text")
        return None
    except Exception as error:
        body = response.text if "response" in locals() else None
        _log(f"_send_openai_request error: {error}")
        _log(f"_send_openai_request exact response body: {body}")
        return None


def classify_intent(user_message: str, context: dict) -> str | None:
    _log(f"classify_intent called: user_message={user_message}, context={context}")
    system_text = (
        "Classify the user's intent into exactly one label.\n"
        "Allowed labels only:\n"
        "- new_search\n"
        "- refine_message\n"
        "- select_lead\n"
        "- send\n\n"
        "Return only the label. No explanation."
    )
    user_text = (
        f"User message: {user_message}\n"
        f"Context: {context}\n\n"
        "Choose the best label."
    )
    result = _send_openai_request(system_text, user_text)
    if not result:
        return None

    normalized = result.strip().lower()
    if normalized in {"new_search", "refine_message", "select_lead", "send"}:
        return normalized

    _log(f"classify_intent error: unexpected model output {normalized}")
    return None

def rewrite_message(instruction: str, previous_message: str) -> str | None:
    print("[AI INPUT]:", previous_message)
    print("[AI INSTRUCTION]:", instruction)
    system_text = (
        "You rewrite cold outreach messages strictly following the instruction.\n"
        "If the instruction says 'make it longer', you MUST expand the message.\n"
        "If the instruction says 'shorter', you MUST shorten it.\n"
        "Always modify the message meaningfully."
    )
    user_text = (
        "Rewrite the following cold outreach message based on the instruction.\n\n"
        f"Instruction: {instruction}\n\n"
        "Message:\n"
        f"{previous_message}\n\n"
        "Rules:\n"
        "- Maintain personalization\n"
        "- Improve clarity and impact\n"
        "- Only change length if instruction asks\n\n"
        "Return only the rewritten message."
    )
    rewritten = _send_openai_request(system_text, user_text)
    print("[AI OUTPUT]:", rewritten)

    if not rewritten or rewritten.strip() == previous_message.strip():
        return f"(rewrite failed)\n\n{previous_message}"

    return rewritten

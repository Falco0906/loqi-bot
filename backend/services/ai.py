import json
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


class OpenAIError(Exception):
    """Raised when OpenAI fails and should not return fake data"""
    pass


def _send_openai_request(system_text: str, user_text: str) -> str:
    """Send request to OpenAI API. Returns the response text or raises OpenAIError."""
    if not OPENAI_API_KEY:
        raise OpenAIError("OPENAI_API_KEY not configured. AI unavailable.")

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
        
        # Handle HTTP errors
        if response.status_code == 401:
            raise OpenAIError("OpenAI API key is invalid")
        if response.status_code == 429:
            raise OpenAIError("OpenAI API quota exceeded")
        if response.status_code >= 500:
            raise OpenAIError(f"OpenAI API server error: {response.status_code}")
            
        response.raise_for_status()
        
        data = response.json()
        _log(f"_send_openai_request status: {response.status_code}")
        
        output_text = _extract_response_text(data)
        if output_text:
            return output_text.strip()

        raise OpenAIError("OpenAI response missing output text")
        
    except requests.Timeout:
        raise OpenAIError("OpenAI request timed out")
    except requests.ConnectionError as e:
        raise OpenAIError(f"OpenAI connection failed: {e}")
    except OpenAIError:
        raise
    except Exception as error:
        body = response.text if 'response' in dir() else None
        _log(f"_send_openai_request error: {error}")
        _log(f"_send_openai_request exact response body: {body}")
        raise OpenAIError(f"OpenAI request failed: {error}")


def classify_intent(user_message: str, context: dict) -> str:
    """Classify user intent. Returns intent string or raises OpenAIError."""
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

    normalized = result.strip().lower()
    if normalized in {"new_search", "refine_message", "select_lead", "send"}:
        return normalized

    _log(f"classify_intent error: unexpected model output {normalized}")
    raise OpenAIError(f"Unexpected intent classification: {normalized}")


def rewrite_message(instruction: str, previous_message: str) -> str:
    """Rewrite a message based on instruction. Returns rewritten text or raises OpenAIError."""
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
        raise OpenAIError("Message rewrite produced no meaningful changes")

    return rewritten


def generate_outreach_email(lead: dict) -> dict:
    """Generate a personalized outreach email. Returns email dict or raises OpenAIError."""
    _log(f"generate_outreach_email called: lead={lead}")

    first_name = ((lead.get("name") or "").split() or [""])[0]
    company = (lead.get("company") or "").strip()
    title = (lead.get("title") or "").strip()
    pain_points = lead.get("pain_points") or (
        "manual outbound, low reply rates, poor personalization"
    )

    system_text = (
        "You write short personalized cold emails.\n"
        "Return valid JSON only with exactly these keys:\n"
        "{\"subject\":\"...\",\"body\":\"...\"}\n\n"
        "Rules:\n"
        "- Keep the email concise and natural\n"
        "- Do not use markdown\n"
        "- Do not invent detailed facts about the recipient\n"
        "- Mention one believable pain point\n"
        "- End with a simple low-friction call to action"
    )
    user_text = (
        "Write a cold outreach email for this lead.\n\n"
        f"First name: {first_name or 'there'}\n"
        f"Title: {title or 'unknown'}\n"
        f"Company: {company or 'unknown company'}\n"
        f"Pain points: {pain_points}\n"
    )

    result = _send_openai_request(system_text, user_text)

    try:
        data = json.loads(result)
    except json.JSONDecodeError as error:
        _log(f"generate_outreach_email parse error: {error}")
        _log(f"generate_outreach_email raw result: {result}")
        raise OpenAIError(f"Failed to parse AI response as JSON: {error}")

    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not subject or not body:
        raise OpenAIError("AI response missing subject or body")

    return {"subject": subject, "body": body}
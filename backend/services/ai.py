import os

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[ai] {message}")


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

        output_text = data.get("output_text")
        if output_text:
            return output_text.strip()

        _log("_send_openai_request error: missing output_text")
        return None
    except Exception as error:
        body = response.text if "response" in locals() else None
        _log(f"_send_openai_request error: {error}")
        _log(f"_send_openai_request exact response body: {body}")
        return None


def generate_message(context: dict) -> str | None:
    _log(f"generate_message called: {context}")
    system_text = (
        "You are an elite B2B SDR who writes highly personalized cold outreach messages that get replies.\n\n"
        "Rules:\n"
        "- Never sound like AI\n"
        "- Avoid generic phrases like 'I hope you're doing well'\n"
        "- Be direct and concise\n"
        "- Personalize using role + company\n"
        "- Focus on value, not features\n"
        "- Keep it under 3-5 lines\n"
        "- End with a soft CTA (not pushy)\n"
        "- Make it feel human and slightly informal\n\n"
        "Tone options:\n"
        "- casual: friendly, conversational\n"
        "- formal: clean and professional\n"
        "- aggressive: direct, confident, slightly bold\n\n"
        "Output only the message. No explanations."
    )
    user_text = (
        "Write an outreach message body only.\n"
        f"Lead first name: {context.get('lead_name', 'there')}\n"
        f"Lead title: {context.get('lead_title', 'this role')}\n"
        f"Lead company: {context.get('company', 'their company')}\n"
        f"What the user sells: {context.get('user_service', 'our service')}\n"
        f"Tone: {context.get('tone', 'friendly') or 'friendly'}\n"
        f"Length: {context.get('length', 'medium') or 'medium'}\n"
        f"Conversation context:\n{chr(10).join(context.get('conversation_context', [])) or 'none'}\n\n"
        "Return only the message text with short paragraphs."
    )
    return _send_openai_request(system_text, user_text)


def rewrite_message(instruction: str, previous_message: str) -> str | None:
    _log(
        "rewrite_message called: "
        f"instruction={instruction}, previous_message={previous_message}"
    )
    system_text = "You rewrite cold outreach messages."
    user_text = (
        "Rewrite the following cold outreach message based on the instruction.\n\n"
        f"Instruction: {instruction}\n\n"
        "Message:\n"
        f"{previous_message}\n\n"
        "Rules:\n"
        "- Keep it concise\n"
        "- Maintain personalization\n"
        "- Improve clarity and impact\n"
        "- Do not make it longer unless asked\n\n"
        "Return only the rewritten message."
    )
    return _send_openai_request(system_text, user_text)

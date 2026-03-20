import os

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _log(message: str) -> None:
    print(f"[openai] {message}")


def generate_outreach_message(
    *,
    service: str,
    lead_name: str,
    title: str,
    company: str,
    tone: str,
    length: str,
    edit_request: str,
    conversation_context: list[str] | None = None,
) -> str | None:
    _log(
        "generate_outreach_message called: "
        f"lead_name={lead_name}, title={title}, company={company}, tone={tone}, length={length}, "
        f"edit_request={edit_request}"
    )

    if not OPENAI_API_KEY:
        _log("generate_outreach_message error: missing OPENAI_API_KEY")
        return None

    context_text = "\n".join(conversation_context or [])
    user_prompt = (
        "Write a hiring outreach message.\n"
        f"Recipient first name: {lead_name}\n"
        f"Recipient title: {title}\n"
        f"Recipient company: {company}\n"
        f"Service being offered: {service}\n"
        f"Tone: {tone}\n"
        f"Length: {length}\n"
        f"Edit request: {edit_request or 'none'}\n"
        f"Conversation context:\n{context_text or 'none'}\n\n"
        "Return only the outreach message body with short paragraphs. "
        "Do not include markdown fences, labels, or quotation marks."
    )

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You write concise B2B outreach messages for Telegram users. "
                            "Keep it natural and specific. Respect requested tone and length."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_prompt,
                    }
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        _log(f"generate_outreach_message request payload: {payload}")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        _log(f"generate_outreach_message response status: {response.status_code}")
        data = response.json()
        _log(f"generate_outreach_message response json: {data}")
        response.raise_for_status()

        output_text = data.get("output_text")
        if output_text:
            return output_text.strip()

        _log("generate_outreach_message error: missing output_text in response")
        return None
    except Exception as error:
        body = None
        if "response" in locals():
            body = response.text
        _log(f"generate_outreach_message error: {error}")
        _log(f"generate_outreach_message exact response body: {body}")
        return None

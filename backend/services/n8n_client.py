import os

import requests


N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")


def send_lead_to_n8n(lead: dict, user: dict) -> dict:
    """
    Sends selected lead to n8n workflow for email generation.
    """

    if not N8N_WEBHOOK_URL:
        raise Exception("Missing N8N_WEBHOOK_URL")

    payload = {
        "lead_id": lead.get("id"),
        "user_id": user.get("id"),
        "telegram_chat_id": user.get("telegram_chat_id"),
        "first_name": (lead.get("name", "").split() or [""])[0],
        "last_name": " ".join(lead.get("name", "").split()[1:]),
        "email": lead.get("email") or "noemail@example.com",
        "title": lead.get("title", ""),
        "company": lead.get("company", ""),
        "pain_points": "manual outbound, low reply rates, poor personalization",
    }

    headers = {
        "Content-Type": "application/json",
    }

    print("[n8n] sending lead:", payload)
    response = requests.post(N8N_WEBHOOK_URL, json=payload, headers=headers, timeout=30)

    try:
        data = response.json()
    except Exception:
        raise Exception(f"Invalid response from n8n: {response.text}")

    print("[n8n] response:", data)

    if response.status_code != 200:
        raise Exception(f"n8n error: {data}")

    return data

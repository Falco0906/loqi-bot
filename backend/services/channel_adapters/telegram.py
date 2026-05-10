from services.telegram import send_message


def send_engine_response_to_telegram(chat_id: int, response: dict) -> None:
    for message in response.get("messages", []):
        text = (message.get("text") or "").strip()
        if not text:
            continue
        send_message(chat_id, text)

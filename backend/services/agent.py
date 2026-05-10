from services.channel_adapters.telegram import send_engine_response_to_telegram
from services.conversation_engine import ConversationEngine


engine = ConversationEngine()


def process_message(
    chat_id: int,
    telegram_id: str,
    text: str,
    username: str | None = None,
) -> dict:
    response = engine.handle_message(
        channel="telegram",
        external_user_id=telegram_id,
        text=text,
        username=username,
        transport_metadata={"chat_id": chat_id},
    )
    send_engine_response_to_telegram(chat_id=chat_id, response=response)
    return response

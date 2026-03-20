from services.telegram import send_message
from state.memory import get_session, update_session, clear_session
from services.apollo import search_leads

def process_message(chat_id: int, text: str) -> None:
    session = get_session(chat_id)
    step = session.get("step", 1)
    
    # Handle /start from any state
    if text.strip().lower() == "/start":
        clear_session(chat_id)
        session = get_session(chat_id)
        step = 1

    if step == 1:
        # Step 1: Greeting
        send_message(chat_id, "Hey — I’m Loqi. I’ll help you find leads and run outreach.")
        # Automatically progress to Step 2
        send_message(chat_id, "What do you sell?")
        update_session(chat_id, {"step": 2})

    elif step == 2:
        # Step 2: Store service, ask who to reach
        update_session(chat_id, {"service": text, "step": 3})
        send_message(chat_id, "Who do you want to reach?")

    elif step == 3:
        # Step 3: Store target, fetch and send Apollo leads
        update_session(chat_id, {"target": text, "step": 4})
        
        # Step 4: Generate real leads from Apollo
        leads_response = search_leads(text)
        send_message(chat_id, leads_response)

    elif step == 4:
        # Wait for user confirmation, then drift to Step 5
        service = session.get("service", "with our service")
        target = session.get("target", "this space")

        # Step 5: Draft outreach
        outreach_text = (
            f"Hey — saw you're working on {target}. "
            f"We help {service}. Worth a quick chat?"
        )
        update_session(chat_id, {"outreach": outreach_text, "step": 5})
        send_message(chat_id, f"Here is the draft:\n\n\"{outreach_text}\"")
        # Step 6 setup: Ask to send
        send_message(chat_id, "Send this?")

    elif step == 5:
        # Step 6: User confirms sending
        positive_responses = ["yes", "y", "ok", "sure", "yeah", "yep", "send"]
        if any(word in text.strip().lower() for word in positive_responses):
            send_message(chat_id, "Sent ✅ (mock)")
            clear_session(chat_id)
            send_message(chat_id, "Type /start when you are ready to reach out to more leads.")
        else:
            send_message(chat_id, "Operation cancelled. Type /start to try again.")
            clear_session(chat_id)

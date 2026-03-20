from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from services.agent import process_message

load_dotenv()

app = FastAPI()

@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Receives Telegram updates.
    Extracts chat_id and message text, and passes them to the agent.
    """
    try:
        data = await request.json()
        
        # Check if it's a message update
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"]["text"]
            
            # Route to agent logic
            process_message(chat_id, text)
            
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}

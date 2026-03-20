import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from services.agent import process_message
from services.supabase import test_supabase_connection

load_dotenv()

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    test_supabase_connection()

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
            telegram_id = str(data["message"].get("from", {}).get("id", chat_id))
            username = data["message"].get("from", {}).get("username")
            text = data["message"]["text"]
            
            # Route to agent logic
            process_message(chat_id, telegram_id, text, username=username)
            
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

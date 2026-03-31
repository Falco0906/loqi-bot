import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from services.agent import process_message
from services.google_auth import exchange_code_for_tokens
from services.supabase import save_google_tokens, test_supabase_connection
from services.telegram import send_message

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


@app.get("/google/callback", response_class=PlainTextResponse)
async def google_callback(code: str, state: str):
    try:
        user_id, chat_id = state.split(":", 1)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from error

    try:
        tokens = exchange_code_for_tokens(code)
        saved_user = save_google_tokens(
            user_id,
            email=tokens.get("email", ""),
            telegram_chat_id=int(chat_id),
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=tokens.get("token_expiry"),
        )
        if saved_user is None:
            raise HTTPException(status_code=500, detail="Failed to save Google tokens")

        send_message(
            chat_id=int(chat_id),
            text="Gmail connected successfully. You can send emails now.",
        )
        return "Gmail connected. You can go back to Telegram."
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

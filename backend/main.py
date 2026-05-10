import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from services.agent import process_message
from services.conversation_engine import ConversationEngine
from services.google_auth import exchange_code_for_tokens
from services.supabase import save_google_tokens, test_supabase_connection
from services.telegram import send_message

load_dotenv()

app = FastAPI()
engine = ConversationEngine()

# CORS Configuration - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateWebSessionRequest(BaseModel):
    display_name: str | None = None


class SendWebMessageRequest(BaseModel):
    text: str


@app.on_event("startup")
def startup_event():
    try:
        test_supabase_connection()
    except Exception as e:
        print(f"Warning: Supabase connection test failed: {e}")


@app.get("/", response_class=PlainTextResponse)
def read_root():
    return "Loqi backend running"


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            telegram_id = str(data["message"].get("from", {}).get("id", chat_id))
            username = data["message"].get("from", {}).get("username")
            text = data["message"]["text"]
            process_message(chat_id, telegram_id, text, username=username)

        return {"status": "ok"}
    except Exception as error:
        print(f"Error processing webhook: {error}")
        return {"status": "error", "message": str(error)}


@app.post("/api/web/session")
async def create_web_session(payload: CreateWebSessionRequest):
    try:
        return engine.create_web_session(display_name=payload.display_name)
    except ValueError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/web/session/{session_token}")
async def get_web_session(session_token: str):
    data = engine.get_web_session_summary(session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.get("/api/web/session/{session_token}/messages")
async def get_web_session_messages(session_token: str):
    return {
        "ok": True,
        "messages": engine.list_messages(channel="web", external_user_id=session_token),
    }


@app.post("/api/web/session/{session_token}/messages")
async def post_web_session_message(session_token: str, payload: SendWebMessageRequest):
    summary = engine.get_web_session_summary(session_token)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return engine.handle_message(
        channel="web",
        external_user_id=session_token,
        text=payload.text,
        username=summary.get("display_name"),
    )


@app.get("/api/web/session/{session_token}/gmail")
async def get_web_gmail_status(session_token: str):
    summary = engine.get_web_session_summary(session_token)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    auth_url = engine.get_gmail_connect_url(
        channel="web",
        external_user_id=session_token,
    )
    return {
        "ok": True,
        "gmail_connected": summary.get("gmail_connected", False),
        "connect_url": auth_url,
    }


@app.get("/google/callback")
async def google_callback(code: str, state: str):
    state_parts = state.split(":")

    if len(state_parts) == 2:
        channel = "telegram"
        user_id, transport_id = state_parts
    elif len(state_parts) == 3:
        channel, user_id, transport_id = state_parts
    else:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        tokens = exchange_code_for_tokens(code)
        saved_user = save_google_tokens(
            user_id,
            email=tokens.get("email", ""),
            telegram_chat_id=int(transport_id) if channel == "telegram" else None,
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            token_expiry=tokens.get("token_expiry"),
        )
        if saved_user is None:
            raise HTTPException(status_code=500, detail="Failed to save Google tokens")

        if channel == "telegram":
            send_message(
                chat_id=int(transport_id),
                text="Gmail connected successfully. You can send emails now.",
            )
            return PlainTextResponse("Gmail connected. You can go back to Telegram.")

        return HTMLResponse(
            """
            <html>
              <body style="background:#0b1020;color:#f3f4f6;font-family:system-ui;padding:32px;">
                <h1 style="margin:0 0 12px;">Gmail connected</h1>
                <p style="opacity:.8;">You can close this window and return to Loqi.</p>
                <script>
                  window.opener && window.opener.postMessage({ type: 'loqi:gmail-connected' }, '*');
                </script>
              </body>
            </html>
            """
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

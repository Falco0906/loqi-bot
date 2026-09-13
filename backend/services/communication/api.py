"""HTTP adapters for connected communication-provider reads and diagnostics."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from services.communication import service
from services.identity import dependencies as identity_dependencies
from services.workspace import access as workspace_access


router = APIRouter(tags=["Communication"])
log = logging.getLogger("loqi")


class LegacyProviderConnectRequest(BaseModel):
    """Request body for the development-only raw-token compatibility route."""

    provider_type: str
    auth_token: str
    email: str = ""
    scope: str = ""


class AnalyzeMessageRequest(BaseModel):
    text: str
    conversation_id: str = ""
    sender: str = "lead"
    subject: str = ""


class RecommendRequest(BaseModel):
    text: str
    conversation_id: str = ""


class SummaryRequest(BaseModel):
    text: str
    conversation_id: str = ""


async def _authorized_session_owner(request: Request) -> tuple[str, str]:
    """Resolve the bearer-bound session token and its authenticated owner."""
    token = identity_dependencies.web_session_token(request)
    return token, await identity_dependencies.authenticated_user_id(request, token)


async def _authorized_owner(request: Request, session_token: str) -> str:
    """Resolve the existing bearer-bound user for legacy provider routes."""
    del session_token
    _, owner_id = await _authorized_session_owner(request)
    return owner_id


@router.post("/api/web/session/{session_token}/communication/analyze")
async def communication_analyze(session_token: str, payload: AnalyzeMessageRequest):
    del session_token
    return service.analyze_communication_message(**payload.model_dump())


@router.post("/api/web/session/{session_token}/communication/recommend")
async def communication_recommend(session_token: str, payload: RecommendRequest):
    del session_token
    return service.recommend_communication_follow_up(text=payload.text)


@router.post("/api/web/session/{session_token}/communication/summary")
async def communication_summary(session_token: str, payload: SummaryRequest):
    del session_token
    return service.summarize_communication_message(text=payload.text)


@router.get("/api/web/session/{session_token}/communication/{conversation_id}/timeline")
async def communication_timeline(session_token: str, conversation_id: str, request: Request):
    del session_token
    token, owner_id = await _authorized_session_owner(request)
    del token
    try:
        return service.communication_timeline_for_owner(owner_id=owner_id, conversation_id=conversation_id)
    except service.ConversationNotFoundForOwner as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error


@router.get("/api/auth/gmail/url")
async def gmail_auth_url(request: Request, session_token: str = ""):
    """Issue a Gmail OAuth URL for a bearer- or web-session-bound user."""
    from services.google_auth import get_google_auth_url
    from services.oauth_state import issue_state

    try:
        user_id = ""
        if request.headers.get("authorization", ""):
            from services.identity.api import get_authenticated_user_id

            user_id = await get_authenticated_user_id(request)
        if not user_id and session_token:
            try:
                summary = await identity_dependencies.cached_web_session_identity(session_token)
            except Exception:
                summary = None
            if summary and summary.get("user_id"):
                user_id = str(summary["user_id"])
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required to connect a provider",
            )
        state = await issue_state(user_id)
        return {"ok": True, "url": get_google_auth_url(state=state)}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/api/auth/gmail/callback")
async def gmail_auth_callback(code: str = "", state: str = "", error: str = ""):
    """Complete Gmail OAuth and return the browser popup postMessage page."""
    from services.google_auth import exchange_code_for_tokens

    ok = False
    provider_id = ""
    email_val = ""
    error_msg = error or ""
    try:
        if error:
            raise Exception(f"Google OAuth error: {error}")
        if not code:
            raise Exception("No authorization code provided")
        user_id = await service.resolve_oauth_state_user(state)
        if not user_id:
            raise Exception("Invalid or expired OAuth state")
        log.info("[oauth] state accepted user=%s", user_id[:8])
        tokens = await asyncio.to_thread(exchange_code_for_tokens, code)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        email_val = tokens.get("email", "")
        account_id = tokens.get("account_id", "") or email_val
        log.info("[oauth] token exchange succeeded user=%s", user_id[:8])
        provider_record = await service.connect_gmail_oauth_provider(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            email=email_val,
            account_id=account_id,
        )
        ok = True
        provider_id = provider_record.id
        log.info("[oauth] callback success user=%s provider=%s", user_id[:8], provider_id[:8])
        try:
            from services.events_bus import event_bus

            await event_bus.publish_user_event(
                user_id,
                "provider.connected",
                {"provider": "gmail", "email": email_val},
                status="connected",
            )
        except Exception:
            pass
    except Exception as callback_error:
        error_msg = str(callback_error)
        log.error("[oauth] callback failed error_type=%s", type(callback_error).__name__)

    payload = json.dumps({"ok": ok, "provider_id": provider_id, "email": email_val, "error": error_msg})
    status_text = "✓ Gmail Connected" if ok else "✗ Gmail Connection Failed"
    postmessage_target = service.frontend_postmessage_origin() or "*"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#0f172a;color:#e2e8f0;padding:40px;text-align:center">
<h2>{status_text}</h2>
<p style="color:#94a3b8">{email_val or error_msg}</p>
<p style="color:#6b7280;font-size:13px">You can close this window.</p>
<script>
if (window.opener) {{
    window.opener.postMessage({{ type: 'gmail-oauth', payload: {payload} }}, {json.dumps(postmessage_target)});
    setTimeout(function() {{ window.close(); }}, 500);
}}
</script>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/google/callback")
async def legacy_google_callback(code: str, state: str):
    """Preserve the older web Gmail popup contract as a named compatibility adapter."""
    try:
        await service.complete_legacy_google_callback(code, state)
    except service.LegacyGoogleOAuthStateError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    postmessage_target = service.frontend_postmessage_origin() or "*"
    return HTMLResponse(
        f"""
            <html>
              <body style="background:#0b1020;color:#f3f4f6;font-family:system-ui;padding:32px;">
                <h1 style="margin:0 0 12px;">Gmail connected</h1>
                <p style="opacity:.8;">You can close this window and return to Loqi.</p>
                <script>
                  window.opener && window.opener.postMessage({{ type: 'loqi:gmail-connected' }}, {json.dumps(postmessage_target)});
                </script>
              </body>
            </html>
            """
    )


@router.get("/api/web/session/{session_token}/gmail")
async def web_gmail_status(session_token: str, request: Request = None):
    """Preserve the legacy web-session Gmail status and connect-URL envelope."""
    session_token = identity_dependencies.web_session_token(request)
    summary = await identity_dependencies.cached_web_session_identity(session_token)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "ok": True,
        "gmail_connected": summary.get("gmail_connected", False),
        "connect_url": service.legacy_web_gmail_connect_url(session_token),
    }


@router.get("/api/web/session/{session_token}/providers")
async def provider_list(session_token: str, request: Request):
    owner_id = await _authorized_owner(request, session_token)
    try:
        providers = await service.list_provider_summaries(owner_id)
    except service.DurableProviderLookupError as error:
        raise HTTPException(status_code=503, detail="Unable to load connected accounts") from error
    return {"ok": True, "providers": providers}


@router.get("/api/web/session/{session_token}/providers/{provider_id}/health")
async def provider_health(session_token: str, provider_id: str, request: Request):
    owner_id = await _authorized_owner(request, session_token)
    result = await service.provider_health(owner_id, provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return result


@router.get("/api/web/session/{session_token}/providers/{provider_id}/status")
async def provider_status(session_token: str, provider_id: str, request: Request):
    owner_id = await _authorized_owner(request, session_token)
    result = await service.provider_status(owner_id, provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return result


@router.get("/api/web/session/{session_token}/providers/{provider_id}/threads")
async def provider_threads(session_token: str, provider_id: str, request: Request):
    owner_id = await _authorized_owner(request, session_token)
    result = service.provider_threads(owner_id, provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return result


@router.get("/api/web/session/{session_token}/providers/{provider_id}/messages")
async def provider_messages(session_token: str, provider_id: str, request: Request):
    owner_id = await _authorized_owner(request, session_token)
    result = service.provider_messages(owner_id, provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return result


@router.post("/api/web/session/{session_token}/providers/{provider_id}/disconnect")
async def provider_disconnect(session_token: str, provider_id: str, request: Request):
    del session_token
    token, owner_id = await _authorized_session_owner(request)
    if not await service.disconnect_provider(owner_id, token, provider_id):
        raise HTTPException(status_code=404, detail="Provider not found or already disconnected")
    return {"ok": True}


@router.post("/api/web/session/{session_token}/providers/{provider_id}/sync")
async def provider_sync(
    session_token: str,
    provider_id: str,
    request: Request,
    cursor: str = "",
):
    del session_token
    token, owner_id = await _authorized_session_owner(request)
    result = await service.sync_provider(owner_id, token, provider_id, cursor=cursor)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"ok": True, "result": result.model_dump()}


@router.post("/api/web/session/{session_token}/providers/connect")
async def connect_legacy_raw_token_provider(
    session_token: str,
    payload: LegacyProviderConnectRequest,
    request: Request,
):
    del session_token
    token = identity_dependencies.web_session_token(request)
    try:
        provider = await service.connect_legacy_raw_token_provider(
            user_id=token,
            provider_type=payload.provider_type,
            auth_token=payload.auth_token,
            email=payload.email,
            scope=payload.scope,
        )
    except service.LegacyProviderConnectionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    return {"ok": True, "provider": provider.model_dump()}


@router.get("/api/web/session/{session_token}/providers/events")
async def provider_events_endpoint(
    session_token: str,
    request: Request,
    provider_id: str = "",
    after: int = 0,
):
    # Preserve the legacy route's best-effort identity/workspace lookup: it
    # still returns runtime events when that lookup rejects or fails.
    workspace_id = ""
    try:
        owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
        workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    except HTTPException:
        pass
    except Exception:
        pass
    return await asyncio.to_thread(
        service.provider_events,
        provider_id,
        after,
        workspace_id,
    )


@router.get("/api/web/session/{session_token}/providers/registered")
async def provider_registered_types(session_token: str):
    del session_token
    return service.registered_provider_types()

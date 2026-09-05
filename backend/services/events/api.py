"""Authenticated Server-Sent Events adapter over the event delivery bus."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from services.events_bus import event_bus
from services.identity import dependencies as identity_dependencies


router = APIRouter(tags=["Events"])

_SSE_HEARTBEAT_SECONDS = 15.0
_SSE_REVOCATION_CHECK_SECONDS = 30.0

log = logging.getLogger(__name__)


@router.get("/api/events/stream")
async def events_stream(request: Request):
    """Stream best-effort user events while the authenticated session remains valid.

    Delivery is intentionally non-durable: callers recover authoritative state
    through REST when Redis is unavailable or an event is missed.
    """
    owner_id, token = await identity_dependencies.resolve_web_session(request)
    if not owner_id or not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    pubsub = await event_bus.subscribe_user(owner_id)

    async def generator():
        nonlocal pubsub
        log.info("[sse] stream opened user=%s subscribed=%s", owner_id[:8], pubsub is not None)
        yield "retry: 5000\n\n"
        yield f"data: {json.dumps({'type': 'hello', 'user': owner_id[:8]})}\n\n"

        last_heartbeat = time.monotonic()
        last_revocation_check = time.monotonic()
        still_valid = True
        try:
            while True:
                now = time.monotonic()
                got_event = False
                if pubsub is not None:
                    try:
                        message = await asyncio.wait_for(
                            pubsub.get_message(ignore_subscribe_messages=True), timeout=0.5,
                        )
                        if message is not None and message.get("type") == "message":
                            got_event = True
                            # Payload was scrubbed at the producer; forward verbatim.
                            yield f"data: {message.get('data', '')}\n\n"
                    except asyncio.TimeoutError:
                        pass
                    except Exception as error:
                        log.warning("[sse] pubsub read failed error_type=%s", type(error).__name__)
                        # Pub/sub broke (for example Redis died). Keep the stream
                        # available with heartbeats while REST stays authoritative.
                        try:
                            await pubsub.aclose()
                        except Exception:
                            pass
                        pubsub = None

                now = time.monotonic()
                if not got_event and now - last_heartbeat >= _SSE_HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    yield ": heartbeat\n\n"

                if now - last_revocation_check >= _SSE_REVOCATION_CHECK_SECONDS:
                    last_revocation_check = now
                    identity = await identity_dependencies.cached_web_session_identity(token)
                    if identity is None or identity.get("user_id") != owner_id:
                        log.info("[sse] stream closing: identity no longer valid user=%s", owner_id[:8])
                        still_valid = False
                        break

                await asyncio.sleep(0.5 if pubsub is None else 0.05)
        except asyncio.CancelledError:
            pass
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
            log.info(
                "[sse] stream closed user=%s reason=%s",
                owner_id[:8], "auth" if not still_valid else "client",
            )

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

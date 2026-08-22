"""PR-3A — Real-time event bus (Redis Pub/Sub).

Delivery mechanism ONLY — never a durable source of truth:
    backend producer → Redis channel → subscriber gateway → frontend

Redis Pub/Sub loses messages with no subscriber by design, so:
    - every state change published here is ALREADY durably written to
      Supabase by the producing flow;
    - reconnecting clients recover via normal REST fetches;
    - nothing business-critical may depend on receiving an event.

Channels (namespaced, see redis_client.k_event_channel):
    loqi:v1:events:user:<user_id>       ← per-user delivery
Payloads: identifiers + minimal metadata. NEVER tokens/credentials/email
contents/secrets.

Frontend integration boundary (documented, not built in this phase):
    a small SSE/WebSocket gateway subscribes to the authenticated user's
    channel and forwards JSON events; until that exists the frontend keeps
    polling — the bus adds capability without forcing a frontend rewrite.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    """Publish-side abstraction. Subscribe-side helper for future gateways."""

    def __init__(self) -> None:
        from services import redis_client
        self._rc = redis_client

    async def publish_user_event(
        self,
        user_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        job_id: str = "",
        status: str = "",
        progress: int | None = None,
    ) -> bool:
        """Publish to ``loqi:v1:events:user:<sha256(user_id)>``.

        Returns True when handed to Redis. Never raises: event delivery is
        best-effort and must not break the producing request.
        """
        if not user_id:
            return False
        from services.redis_client import k_event_channel, hash_token

        payload: dict[str, Any] = {"type": event_type}
        if job_id:
            payload["job_id"] = job_id
        if status:
            payload["status"] = status
        if progress is not None:
            payload["progress"] = max(0, min(100, int(progress)))
        if data:
            # Allowlist-style merge: identifiers only, caller's responsibility
            # to keep it minimal — strip obvious sensitive keys defensively.
            banned = ("token", "access_token", "refresh_token", "secret",
                      "password", "credential", "authorization")
            payload["data"] = {
                k: v for k, v in data.items()
                if not any(b in k.lower() for b in banned)
            }

        channel = k_event_channel("user", hash_token(user_id))

        def op(client):
            import json as _json
            return client.publish(channel, _json.dumps(payload, separators=(",", ":")))

        sent = await self._rc.run_with_timeout(op, fallback=0)
        if not sent:
            log.debug("event_publish_degraded type=%s user=%s",
                      event_type, user_id[:8] if user_id else "")
        return bool(sent)

    async def subscribe_user(self, user_id: str):
        """Yield decoded events for one user channel (gateway use).

        Returns the pubsub object; callers iterate ``pubsub.listen()`` and
        must call ``close(pubsub)`` when done. Exposed for the future SSE/WS
        gateway and for tests.
        """
        client = await self._rc.get_client()
        if client is None:
            return None
        from services.redis_client import k_event_channel, hash_token
        channel = k_event_channel("user", hash_token(user_id))
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub


event_bus = EventBus()

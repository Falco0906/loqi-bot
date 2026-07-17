"""Gmail Provider — first implementation of CommunicationProviderBase.

Uses Gmail REST API directly (no google client library dependency).
"""

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from services.communication.provider_base import CommunicationProviderBase
from services.communication.provider_models import (
    CommunicationProvider,
    ProviderMessage,
    ProviderType,
    ProviderStatus,
    MessageDirection,
    SyncResult,
    ProviderEventType,
)
from services.communication.communication_store import store
from services.communication.provider_normalizer import normalize_message
from services.communication.provider_events import emit_event

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailProvider(CommunicationProviderBase):
    """Gmail provider implementation using direct REST API calls."""

    provider_type = ProviderType.GMAIL

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def __init__(self) -> None:
        self._provider_id: str = ""
        self._user_id: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0
        self._client_id: str = ""
        self._client_secret: str = ""
        self._connected: bool = False
        self._watching: bool = False
        self._last_history_id: str = ""
        self._mailbox_email: str = ""

    # ── Connection Lifecycle ──

    def connect(self, auth_token: str, **kwargs) -> CommunicationProvider:
        logger.info(
            "[GMail] connect() called | user_id=%s | email=%s | has_refresh_token=%s | token_prefix=%s...",
            kwargs.get("user_id", "default"),
            kwargs.get("email", ""),
            bool(kwargs.get("refresh_token")),
            auth_token[:20] if auth_token else "none",
        )
        user_id = kwargs.get("user_id", "default")
        self._user_id = user_id
        self._access_token = auth_token
        self._refresh_token = kwargs.get("refresh_token", "")
        self._client_id = kwargs.get("client_id", "")
        self._client_secret = kwargs.get("client_secret", "")
        self._token_expiry = time.time() + 3600
        self._mailbox_email = kwargs.get("email", "")
        self._connected = True

        provider = CommunicationProvider(
            provider_type=ProviderType.GMAIL,
            user_id=user_id,
            status=ProviderStatus.HEALTHY,
            metadata={
                "email": kwargs.get("email", ""),
                "scope": kwargs.get("scope", ""),
            },
        )
        self._provider_id = provider.id
        store.save_provider(provider)
        logger.info(
            "[GMail] Provider saved | provider_id=%s user_id=%s",
            provider.id, user_id,
        )
        emit_event(ProviderEventType.CONNECTED, provider.id, "Gmail connected")
        return provider

    def disconnect(self) -> bool:
        logger.info("[GMail] disconnect() | provider_id=%s", self._provider_id)
        if not self._connected:
            return False
        self._connected = False
        self._access_token = ""
        self._refresh_token = ""
        self._mailbox_email = ""
        self._last_history_id = ""
        store.update_provider_status(self._provider_id, ProviderStatus.DISCONNECTED)
        emit_event(ProviderEventType.DISCONNECTED, self._provider_id, "Gmail disconnected")
        return True

    def health(self) -> ProviderStatus:
        if not self._connected:
            logger.warning("[GMail] health() => OFFLINE (not connected)")
            return ProviderStatus.OFFLINE
        try:
            self._ensure_auth()
            logger.info("[GMail] health() calling /users/me/profile")
            resp = self._gmail_get("/users/me/profile")
            logger.info("[GMail] health() profile response: %s", resp)
            if resp and resp.get("emailAddress"):
                logger.info("[GMail] health() => HEALTHY (%s)", resp["emailAddress"])
                return ProviderStatus.HEALTHY
            logger.warning("[GMail] health() => EXPIRED_TOKEN (no emailAddress in profile)")
            return ProviderStatus.EXPIRED_TOKEN
        except Exception as e:
            if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in str(e):
                logger.warning("[GMail] health() => SCOPE_INSUFFICIENT")
                return ProviderStatus.SCOPE_INSUFFICIENT
            logger.error("[GMail] health() exception: %s", e, exc_info=True)
            raise

    # ── Token Management ──

    def _ensure_auth(self) -> None:
        now = time.time()
        if now >= self._token_expiry - 60:
            logger.info(
                "[GMail] Token expired or expiring | expiry=%.0f now=%.0f | refreshing...",
                self._token_expiry, now,
            )
            self._refresh_auth()
        else:
            logger.debug(
                "[GMail] Token still valid | expiry=%.0f now=%.0f (%.0fs remaining)",
                self._token_expiry, now, self._token_expiry - now,
            )

    def _refresh_auth(self) -> None:
        if not self._refresh_token:
            raise Exception("No refresh token available — cannot refresh Gmail auth")

        logger.info("[GMail] Refreshing access token via %s", TOKEN_URL)
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            logger.info(
                "[GMail] Token refresh response | status=%s body_preview=%s",
                resp.status_code, resp.text[:200] if resp.text else "(empty)",
            )
            if resp.status_code != 200:
                raise Exception(
                    f"Token refresh failed | status={resp.status_code} body={resp.text[:500]}"
                )

            data = resp.json()
            new_token = data.get("access_token", "")
            if new_token:
                self._access_token = new_token
            expires_in = data.get("expires_in", 3600)
            self._token_expiry = time.time() + int(expires_in)
            if data.get("refresh_token"):
                self._refresh_token = data["refresh_token"]

            logger.info(
                "[GMail] Token refreshed | expires_in=%ds new_prefix=%s...",
                expires_in, self._access_token[:20] if self._access_token else "none",
            )
            emit_event(ProviderEventType.TOKEN_REFRESHED, self._provider_id, "Token refreshed")

        except requests.RequestException as e:
            logger.error("[GMail] Token refresh request failed: %s", e, exc_info=True)
            emit_event(
                ProviderEventType.TOKEN_FAILED,
                self._provider_id,
                f"Token refresh failed: {e}",
            )
            raise

    def _gmail_get(self, path: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request to the Gmail API."""
        self._ensure_auth()
        url = f"{GMAIL_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        logger.info(
            "[GMail] GET %s | params=%s | token_prefix=%s...",
            url, params, self._access_token[:20] if self._access_token else "none",
        )

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        logger.info(
            "[GMail] GET %s => status=%d | content_length=%d",
            path, resp.status_code, len(resp.content),
        )

        if resp.status_code == 401:
            logger.warning(
                "[GMail] 401 on %s | body=%s | refreshing token and retrying...",
                path, resp.text[:300],
            )
            self._refresh_auth()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            logger.info(
                "[GMail] RETRY %s => status=%d | content_length=%d",
                path, resp.status_code, len(resp.content),
            )

        if resp.status_code != 200:
            body = resp.text[:1000]
            logger.error(
                "[GMail] Non-200 response | url=%s status=%d body=%s",
                url, resp.status_code, body,
            )
            raise Exception(
                f"Gmail API error | path={path} status={resp.status_code} body={body}"
            )

        json_data = resp.json()
        logger.debug("[GMail] GET %s response JSON (truncated): %s", path, json_data)
        return json_data

    # ── Sync Engine ──

    def sync(self, cursor: str = "") -> SyncResult:
        start_time = time.time()
        provider = store.get_provider(self._provider_id)
        if not provider:
            raise Exception(f"Provider {self._provider_id} not found in store")

        logger.info(
            "[GMail] sync() | provider_id=%s cursor=%s has_cursor=%s",
            self._provider_id, cursor[:30] if cursor else "none", bool(cursor),
        )
        emit_event(ProviderEventType.SYNC_STARTED, self._provider_id, "Sync started")

        try:
            if cursor:
                result = self._incremental_sync(cursor)
            else:
                result = self._initial_sync()

            result.duration_ms = int((time.time() - start_time) * 1000)
            store.update_provider_sync(self._provider_id, result.cursor)

            logger.info(
                "[GMail] Sync FINAL | threads=%d messages=%d conversations=%d cursor=%s errors=%d duration=%dms",
                result.threads_synced, result.messages_synced, result.new_conversations,
                result.cursor[:30] if result.cursor else "none",
                len(result.errors), result.duration_ms,
            )

            emit_event(
                ProviderEventType.SYNC_COMPLETED,
                self._provider_id,
                f"Synced {result.messages_synced} messages from {result.threads_synced} threads — "
                f"{result.new_conversations} new conversations, {len(result.errors)} errors",
                {"threads": result.threads_synced, "messages": result.messages_synced},
            )
            return result

        except Exception as e:
            logger.error("[GMail] sync() exception: %s", e, exc_info=True)
            emit_event(
                ProviderEventType.SYNC_FAILED,
                self._provider_id,
                f"Sync failed: {e}",
                {"error": str(e)},
            )
            raise

    def _initial_sync(self) -> SyncResult:
        logger.info("[GMail] === INITIAL SYNC START ===")
        result = SyncResult(provider_id=self._provider_id)
        threads_seen: set[str] = set()
        new_conversations = 0
        errors: list[str] = []

        # ── Profile (includes the mailbox's latest historyId) ──
        logger.info("[GMail] STEP 1: Fetching /users/me/profile")
        profile = self._gmail_get("/users/me/profile")
        mailbox_email = profile.get("emailAddress", "unknown")
        mailbox_history_id = profile.get("historyId", "")
        logger.info("[GMail] Profile JSON: %s", profile)
        logger.info("[GMail] Authenticated account: %s", mailbox_email)
        logger.info(
            "[GMail] Mailbox historyId from profile: %s",
            mailbox_history_id,
        )
        self._mailbox_email = mailbox_email
        self._last_history_id = mailbox_history_id

        # ── Labels ──
        logger.info("[GMail] STEP 2: Fetching /users/me/labels")
        labels = self._gmail_get("/users/me/labels")
        label_names = [l.get("name", "") for l in labels.get("labels", [])]
        logger.info("[GMail] Mailbox labels (%d): %s", len(label_names), ", ".join(label_names))

        # ── Messages list ──
        logger.info("[GMail] STEP 3: Fetching /users/me/messages?maxResults=100")
        list_resp = self._gmail_get("/users/me/messages", {"maxResults": 100})
        logger.info("[GMail] Messages list response: %s", list_resp)

        messages = list_resp.get("messages", [])
        total_in_mailbox = list_resp.get("resultSizeEstimate", 0)
        logger.info(
            "[GMail] resultSizeEstimate=%d | messages_returned=%d",
            total_in_mailbox, len(messages),
        )

        if not messages:
            logger.info("[GMail] No messages returned — nothing to sync")
            result.cursor = self._last_history_id or "no_messages"
            result.errors = errors
            return result

        # ── Fetch each message ──
        from services.communication.gmail_sync import _process_provider_message

        logger.info("[GMail] STEP 4: Processing %d messages one by one", len(messages))

        for i, msg_meta in enumerate(messages):
            msg_id = msg_meta.get("id", "")
            if not msg_id:
                logger.warning("[GMail] Message at index %d has no id, skipping", i)
                continue

            logger.info("[GMail]   [%d/%d] Fetching message %s", i + 1, len(messages), msg_id)

            try:
                full_msg = self._gmail_get(
                    f"/users/me/messages/{msg_id}", {"format": "full"},
                )
                logger.info(
                    "[GMail]   Message %s | threadId=%s historyId=%s labelIds=%s sizeEstimate=%d",
                    msg_id,
                    full_msg.get("threadId", ""),
                    full_msg.get("historyId", ""),
                    full_msg.get("labelIds", []),
                    full_msg.get("sizeEstimate", 0),
                )
            except Exception as e:
                err = f"Failed to fetch message {msg_id}: {e}"
                logger.error("[GMail]   ERROR fetching message: %s", e)
                errors.append(err)
                continue

            thread_id = full_msg.get("threadId", msg_id)

            # ── Normalize to ProviderMessage ──
            try:
                provider_msg = self._provider_message_from_gmail(full_msg, thread_id)
                logger.info(
                    "[GMail]   ProviderMessage created | ext_id=%s thread=%s from=%s subj=%s dir=%s",
                    provider_msg.external_id,
                    provider_msg.thread_id,
                    provider_msg.raw_headers.get("from", ""),
                    provider_msg.raw_headers.get("subject", "")[:60],
                    provider_msg.direction.value,
                )
            except Exception as e:
                err = f"Failed to create ProviderMessage for {msg_id}: {e}"
                logger.error("[GMail]   ERROR: %s", err)
                errors.append(err)
                continue

            # Check if thread already mapped BEFORE processing (processing creates the mapping)
            thread_was_mapped = bool(store.get_thread_mapping(thread_id))
            logger.info(
                "[GMail]   thread_was_mapped=%s | thread=%s",
                thread_was_mapped, thread_id,
            )

            # ── Process through full intelligence pipeline ──
            try:
                logger.info("[GMail]   Calling _process_provider_message() for %s", msg_id)
                cid = _process_provider_message(self, provider_msg)
                logger.info(
                    "[GMail]   _process_provider_message returned conversation_id=%s",
                    cid,
                )
            except Exception as e:
                err = f"_process_provider_message failed for {msg_id}: {e}"
                logger.error("[GMail]   ERROR: %s", e, exc_info=True)
                errors.append(err)
                continue

            if cid:
                result.messages_synced += 1
                threads_seen.add(thread_id)
                is_new = not thread_was_mapped
                if is_new:
                    new_conversations += 1
                logger.info(
                    "[GMail]   => SYNCED | msg=%s thread=%s conversation=%s is_new=%s total_synced=%d",
                    msg_id, thread_id, cid, is_new, result.messages_synced,
                )

                store.add_recent_message(
                    subject=provider_msg.raw_headers.get("subject", "(no subject)"),
                    sender=provider_msg.raw_headers.get("from", "unknown"),
                    date=provider_msg.received_at,
                    thread_id=thread_id,
                    message_id=msg_id,
                    history_id=full_msg.get("historyId", ""),
                )
                logger.debug("[GMail]   Recent message stored")
            else:
                logger.info(
                    "[GMail]   => SKIPPED (duplicate or no conversation) | msg=%s thread=%s",
                    msg_id, thread_id,
                )

        result.threads_synced = len(threads_seen)
        result.new_conversations = new_conversations
        result.cursor = self._last_history_id or str(int(time.time()))
        result.errors = errors

        logger.info("[GMail] === INITIAL SYNC DONE ===")
        logger.info(
            "[GMail] Result: threads=%d messages=%d conversations=%d cursor=%s errors=%d",
            result.threads_synced, result.messages_synced, result.new_conversations,
            result.cursor[:30] if result.cursor else "none",
            len(result.errors),
        )
        if errors:
            logger.info("[GMail] Errors during sync:")
            for e in errors:
                logger.info("  - %s", e)

        return result

    def _incremental_sync(self, cursor: str) -> SyncResult:
        logger.info("[GMail] === INCREMENTAL SYNC START === cursor=%s", cursor[:40] if cursor else "none")
        result = SyncResult(provider_id=self._provider_id)
        threads_seen: set[str] = set()
        new_conversations = 0
        errors: list[str] = []

        logger.info("[GMail] Calling /users/me/history?startHistoryId=%s&historyTypes=messageAdded", cursor[:30])
        try:
            history_resp = self._gmail_get(
                "/users/me/history",
                {"startHistoryId": cursor, "historyTypes": "messageAdded"},
            )
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or ("startHistoryId" in err_str.lower() and "invalid" in err_str.lower()):
                logger.warning("[GMail] History ID %s expired (404/invalid), falling back to initial sync", cursor[:30])
                return self._initial_sync()
            logger.error("[GMail] History API error: %s", e, exc_info=True)
            raise

        new_history_id = history_resp.get("historyId", cursor)
        history_records = history_resp.get("history", [])
        logger.info(
            "[GMail] History API response | historyId=%s records=%d full_response=%s",
            new_history_id, len(history_records), history_resp,
        )

        if not history_records:
            logger.info("[GMail] No history records — nothing to sync")
            result.cursor = new_history_id
            result.errors = errors
            return result

        from services.communication.gmail_sync import _process_provider_message

        for ri, record in enumerate(history_records):
            messages_added = record.get("messagesAdded", [])
            logger.info("[GMail]   History record %d: %d messagesAdded", ri, len(messages_added))

            for msg_added in messages_added:
                msg_data = msg_added.get("message", {})
                msg_id = msg_data.get("id", "")

                if not msg_id:
                    logger.warning("[GMail]   History record %d has message with no id, skipping", ri)
                    continue

                if store.is_message_seen(msg_id):
                    logger.info("[GMail]   SKIP (already seen) | msg=%s", msg_id)
                    continue

                logger.info("[GMail]   Fetching history message %s", msg_id)

                try:
                    full_msg = self._gmail_get(
                        f"/users/me/messages/{msg_id}", {"format": "full"},
                    )
                except Exception as e:
                    err = f"Failed to fetch history message {msg_id}: {e}"
                    logger.error("[GMail]   ERROR: %s", err)
                    errors.append(err)
                    continue

                thread_id = full_msg.get("threadId", msg_id)
                history_id = full_msg.get("historyId", "")

                thread_was_mapped = bool(store.get_thread_mapping(thread_id))

                try:
                    provider_msg = self._provider_message_from_gmail(full_msg, thread_id)
                except Exception as e:
                    err = f"Failed to create ProviderMessage for history msg {msg_id}: {e}"
                    logger.error("[GMail]   ERROR: %s", err)
                    errors.append(err)
                    continue

                try:
                    cid = _process_provider_message(self, provider_msg)
                except Exception as e:
                    err = f"_process_provider_message failed for history msg {msg_id}: {e}"
                    logger.error("[GMail]   ERROR: %s", e, exc_info=True)
                    errors.append(err)
                    continue

                if cid:
                    result.messages_synced += 1
                    threads_seen.add(thread_id)
                    if not thread_was_mapped:
                        new_conversations += 1

                    store.add_recent_message(
                        subject=provider_msg.raw_headers.get("subject", "(no subject)"),
                        sender=provider_msg.raw_headers.get("from", "unknown"),
                        date=provider_msg.received_at,
                        thread_id=thread_id,
                        message_id=msg_id,
                        history_id=history_id,
                    )
                    logger.info(
                        "[GMail]   SYNCED | msg=%s thread=%s conversation=%s",
                        msg_id, thread_id, cid,
                    )
                else:
                    logger.info("[GMail]   SKIPPED (duplicate) | msg=%s", msg_id)

        result.threads_synced = len(threads_seen)
        result.new_conversations = new_conversations
        result.cursor = new_history_id
        result.errors = errors
        self._last_history_id = new_history_id

        logger.info("[GMail] === INCREMENTAL SYNC DONE ===")
        logger.info(
            "[GMail] Result: threads=%d messages=%d conversations=%d cursor=%s errors=%d",
            result.threads_synced, result.messages_synced, result.new_conversations,
            result.cursor[:30] if result.cursor else "none", len(result.errors),
        )
        return result

    # ── Thread / Message Fetching ──

    def fetch_thread(self, thread_id: str) -> list[ProviderMessage]:
        if not self._connected:
            return []
        logger.info("[GMail] fetch_thread(%s)", thread_id)
        resp = self._gmail_get(f"/users/me/threads/{thread_id}", {"format": "full"})
        messages = resp.get("messages", [])
        logger.info("[GMail] fetch_thread(%s) => %d messages", thread_id, len(messages))
        return [
            self._provider_message_from_gmail(msg, thread_id)
            for msg in messages
        ]

    def fetch_message(self, message_id: str) -> Optional[ProviderMessage]:
        if not self._connected:
            return None
        logger.info("[GMail] fetch_message(%s)", message_id)
        resp = self._gmail_get(f"/users/me/messages/{message_id}", {"format": "full"})
        return self._provider_message_from_gmail(resp, resp.get("threadId", ""))

    # ── Normalization ──

    def normalize(self, message: ProviderMessage) -> dict:
        logger.debug("[GMail] normalize(%s)", message.external_id)
        normalized = normalize_message(message, message.thread_id)
        return normalized.model_dump()

    # ── Watch (Webhook/Push) ──

    def watch(self) -> bool:
        self._watching = True
        return True

    def stop_watch(self) -> bool:
        self._watching = False
        return True

    # ── Internal helpers ──

    def _decode_body(self, payload: dict) -> str:
        if "data" in payload.get("body", {}):
            data = payload["body"]["data"]
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning("[GMail] Body decode error: %s", e)
                return ""
        if payload.get("parts"):
            texts = []
            for part in payload["parts"]:
                texts.append(self._decode_body(part))
            return "\n".join(filter(None, texts))
        return ""

    def _parse_headers(self, payload: dict) -> dict[str, str]:
        headers: dict[str, str] = {}
        for h in payload.get("headers", []):
            headers[h.get("name", "").lower()] = h.get("value", "")
        return headers

    def _provider_message_from_gmail(self, gmail_msg: dict, thread_id: str) -> ProviderMessage:
        payload = gmail_msg.get("payload", {})
        headers = self._parse_headers(payload)
        body = self._decode_body(payload)
        internal_date = gmail_msg.get("internalDate", "0")

        direction = MessageDirection.INCOMING
        if headers.get("from", "").startswith("me"):
            direction = MessageDirection.OUTGOING

        return ProviderMessage(
            provider_id=self._provider_id,
            external_id=gmail_msg.get("id", ""),
            thread_id=thread_id,
            direction=direction,
            raw_headers=headers,
            raw_body=body,
            received_at=datetime.fromtimestamp(
                int(internal_date) / 1000, tz=timezone.utc
            ).isoformat() if internal_date != "0" else "",
            attachments=gmail_msg.get("attachments", []),
            provider_metadata={
                "size_estimate": gmail_msg.get("sizeEstimate", 0),
                "label_ids": gmail_msg.get("labelIds", []),
                "history_id": gmail_msg.get("historyId", ""),
            },
        )

    def process_gmail_message(self, gmail_msg: dict, thread_id: str) -> Optional[dict]:
        """Process a Gmail API message through normalization.

        Returns a NormalizedMessage dict, or None if duplicate.
        """
        external_id = gmail_msg.get("id", "")
        if store.is_message_seen(external_id):
            return None

        provider_msg = self._provider_message_from_gmail(gmail_msg, thread_id)
        store.mark_message_seen(external_id)

        normalized = self.normalize(provider_msg)
        emit_event(
            ProviderEventType.MESSAGE_RECEIVED,
            self._provider_id,
            f"Message received: {normalized.get('subject', '(no subject)')}",
            {"external_id": external_id, "thread_id": thread_id},
        )
        return normalized

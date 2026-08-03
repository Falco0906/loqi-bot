from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult
from services.providers.interface import Provider, ProviderSetupError
from services.providers.models import ProviderConversation
from services.providers.google.gmail.mapper import GmailMapper
from services.providers.google.oauth import GoogleOAuthFlow
from services.providers.oauth import OAuthTokenStore, TokenManager, TokenRefreshError

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailProvider(Provider):
    """Gmail provider — inbox sync, thread sync, labels, drafts, reply detection.

    Uses the Gmail REST API directly (no google client library dependency).
    """

    def __init__(
        self,
        token_store: OAuthTokenStore,
        oauth_flow: GoogleOAuthFlow | None = None,
        provider_id: str = "gmail",
    ) -> None:
        self._provider_id = provider_id
        self._token_store = token_store
        self._flow = oauth_flow or GoogleOAuthFlow(
            scopes="https://www.googleapis.com/auth/gmail.modify "
                   "https://www.googleapis.com/auth/gmail.labels",
            provider_id=provider_id,
        )
        self._token_manager = TokenManager(self._flow, token_store)
        self._user_id: str = ""
        self._mailbox_email: str = ""
        self._last_history_id: str = ""
        self._connected = False
        self._mapper = GmailMapper()

    # ── Identity ─────────────────────────────────────────────────

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return f"Gmail ({self._mailbox_email or self._provider_id})"

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            Capability.EMAIL_RECEIVE,
            Capability.EMAIL_SYNC,
            Capability.THREAD_SYNC,
            Capability.DRAFT_MANAGE,
            Capability.REPLY_DETECTION,
            Capability.OAUTH,
        )

    # ── Lifecycle ────────────────────────────────────────────────

    def connect(self) -> None:
        token = self._get_token()
        if not token.access_token:
            raise ProviderSetupError("Gmail: no access token available")

        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/profile",
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code == 401:
            try:
                token = self._token_manager.get_valid_token(self._provider_id)
                resp = requests.get(
                    f"{GMAIL_API_BASE}/users/me/profile",
                    headers=self._auth_headers(token.access_token),
                    timeout=10,
                )
            except TokenRefreshError as e:
                raise ProviderSetupError(f"Gmail: token refresh failed: {e}") from e

        if resp.status_code != 200:
            raise ProviderSetupError(
                f"Gmail: failed to connect — HTTP {resp.status_code}: {resp.text[:200]}"
            )

        profile = resp.json()
        self._mailbox_email = profile.get("emailAddress", "")
        self._user_id = "me"
        self._connected = True
        logger.info("GmailProvider connected as %s", self._mailbox_email)

    def disconnect(self) -> None:
        self._connected = False
        self._user_id = ""
        self._mailbox_email = ""
        self._last_history_id = ""
        logger.info("GmailProvider disconnected")

    # ── Health ────────────────────────────────────────────────────

    def health(self) -> HealthCheckResult:
        if not self._connected:
            return HealthCheckResult(
                ok=False,
                provider_id=self._provider_id,
                status="offline",
                error="Not connected",
            )
        try:
            token = self._get_token()
            start = time.time()
            resp = requests.get(
                f"{GMAIL_API_BASE}/users/me/profile",
                headers=self._auth_headers(token.access_token),
                timeout=5,
            )
            elapsed = (time.time() - start) * 1000
            if resp.status_code == 200:
                return HealthCheckResult(
                    ok=True,
                    provider_id=self._provider_id,
                    latency_ms=elapsed,
                    details={"email": self._mailbox_email},
                )
            return HealthCheckResult(
                ok=False,
                provider_id=self._provider_id,
                latency_ms=elapsed,
                error=f"HTTP {resp.status_code}",
            )
        except Exception as e:
            return HealthCheckResult(
                ok=False,
                provider_id=self._provider_id,
                error=str(e),
            )

    # ── Sync ─────────────────────────────────────────────────────

    def sync(self) -> list[dict[str, Any]]:
        if not self._connected:
            return []

        events: list[dict[str, Any]] = []
        try:
            history = self._fetch_history()
        except TokenRefreshError:
            logger.warning("Gmail: token refresh failed during sync")
            return []

        for record in history.get("history", []):
            events.extend(self._process_history_record(record))

        if history.get("historyId"):
            self._last_history_id = history["historyId"]

        return events

    def sync_thread(self, thread_id: str) -> dict[str, Any] | None:
        token = self._get_token()
        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/threads/{thread_id}",
            headers=self._auth_headers(token.access_token),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()
        conversation = self._mapper.thread_to_conversation(raw, self._provider_id)
        return self._build_event("THREAD_UPDATED", conversation.to_dict())

    def sync_labels(self) -> list[dict[str, Any]]:
        token = self._get_token()
        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/labels",
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        labels = resp.json().get("labels", [])
        return [
            self._build_event("LABEL_SYNCED", {
                "id": lbl.get("id"),
                "name": lbl.get("name"),
                "type": lbl.get("type"),
            })
            for lbl in labels
        ]

    def list_drafts(self, max_results: int = 50) -> list[dict[str, Any]]:
        token = self._get_token()
        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/drafts",
            params={"maxResults": max_results},
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        result = []
        for draft in resp.json().get("drafts", []):
            detail = self._get_draft_detail(draft.get("id", ""))
            if detail:
                email = self._mapper.draft_to_provider_email(detail, self._provider_id)
                if email:
                    result.append(self._build_event("DRAFT_FOUND", email.to_dict()))
        return result

    def create_draft(self, to: str, subject: str, body: str) -> dict[str, Any] | None:
        token = self._get_token()
        raw_message = self._build_mime_message(to, subject, body)
        payload = {
            "message": {
                "raw": raw_message,
            }
        }
        resp = requests.post(
            f"{GMAIL_API_BASE}/users/me/drafts",
            json=payload,
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return self._build_event("DRAFT_CREATED", resp.json())

    # ── Reply Detection ──────────────────────────────────────────

    def detect_replies(self, conversation: ProviderConversation) -> list[dict[str, Any]]:
        results = []
        if len(conversation.messages) < 2:
            return results

        for i in range(1, len(conversation.messages)):
            prev = conversation.messages[i - 1]
            current = conversation.messages[i]
            if current.is_incoming and not prev.is_incoming:
                reply_gap = self._compute_reply_gap(prev.received_at, current.received_at)
                results.append(self._build_event("REPLY_DETECTED", {
                    "thread_id": conversation.thread_id,
                    "previous_message_id": prev.message_id,
                    "reply_message_id": current.message_id,
                    "reply_from": current.from_email,
                    "reply_subject": current.subject,
                    "reply_gap_hours": reply_gap,
                }))
        return results

    # ── Internal ─────────────────────────────────────────────────

    def _get_token(self):
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self._token_manager.get_valid_token(self._provider_id)
        )

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _fetch_history(self) -> dict[str, Any]:
        token = self._get_token()
        params: dict[str, Any] = {
            "historyTypes": "messageAdded,labelAdded,labelRemoved",
        }
        if self._last_history_id:
            params["startHistoryId"] = self._last_history_id

        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/history",
            params=params,
            headers=self._auth_headers(token.access_token),
            timeout=15,
        )
        if resp.status_code == 401:
            token = self._token_manager.get_valid_token(self._provider_id)
            resp = requests.get(
                f"{GMAIL_API_BASE}/users/me/history",
                params=params,
                headers=self._auth_headers(token.access_token),
                timeout=15,
            )
        resp.raise_for_status()
        return resp.json()

    def _process_history_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        for msg_added in record.get("messagesAdded", []):
            msg = msg_added.get("message", {})
            pm = self._mapper.message_to_provider_message(msg, self._provider_id)
            events.append(self._build_event("EMAIL_RECEIVED", pm.to_dict()))

        for msg_added in record.get("messagesDeleted", []):
            msg = msg_added.get("message", {})
            events.append(self._build_event("EMAIL_DELETED", {
                "message_id": msg.get("id", ""),
                "thread_id": msg.get("threadId", ""),
            }))

        for label_added in record.get("labelsAdded", []):
            msg = label_added.get("message", {})
            events.append(self._build_event("LABEL_ADDED", {
                "message_id": msg.get("id", ""),
                "thread_id": msg.get("threadId", ""),
                "label_ids": label_added.get("labelIds", []),
            }))

        for label_removed in record.get("labelsRemoved", []):
            msg = label_removed.get("message", {})
            events.append(self._build_event("LABEL_REMOVED", {
                "message_id": msg.get("id", ""),
                "thread_id": msg.get("threadId", ""),
                "label_ids": label_removed.get("labelIds", []),
            }))

        return events

    def _get_draft_detail(self, draft_id: str) -> dict[str, Any] | None:
        token = self._get_token()
        resp = requests.get(
            f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
            params={"format": "full"},
            headers=self._auth_headers(token.access_token),
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else None

    def _build_mime_message(self, to: str, subject: str, body: str) -> str:
        import base64
        message = (
            f"To: {to}\r\n"
            f"Subject: {subject}\r\n"
            f"Content-Type: text/plain; charset=UTF-8\r\n"
            f"\r\n"
            f"{body}"
        )
        return base64.urlsafe_b64encode(message.encode("utf-8")).decode("ascii")

    def _compute_reply_gap(self, sent_iso: str, received_iso: str) -> float:
        try:
            sent = datetime.fromisoformat(sent_iso)
            received = datetime.fromisoformat(received_iso)
            return (received - sent).total_seconds() / 3600
        except Exception:
            return 0.0

    @staticmethod
    def _build_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "gmail",
            "data": data,
        }

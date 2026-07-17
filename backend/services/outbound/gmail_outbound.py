"""Gmail Outbound Provider — implements OutboundProviderBase for Gmail.

Pure transport layer.
No intelligence, no AI, no recommendations, no planner.
"""
import base64
import json
import logging
from typing import Optional

import requests

from services.outbound.outbound_base import OutboundProviderBase
from services.outbound.outbound_models import (
    DraftMessage,
    SendRequest,
    SendResult,
    ScheduledMessage,
    DraftListResult,
    DeliveryStatus,
    Recipient,
)
from services.communication.gmail_provider import GMAIL_API_BASE, TOKEN_URL

logger = logging.getLogger(__name__)


class ScopeUpgradeRequired(Exception):
    """Raised when Gmail API returns ACCESS_TOKEN_SCOPE_INSUFFICIENT.
    The provider needs reauthorization with broader OAuth scopes.
    """


class GmailOutboundProvider(OutboundProviderBase):
    provider_type = "gmail"

    def __init__(self) -> None:
        self._provider_id: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0
        self._client_id: str = ""
        self._client_secret: str = ""

    def configure(self, provider_id: str, access_token: str, refresh_token: str,
                  client_id: str, client_secret: str, token_expiry: float) -> None:
        self._provider_id = provider_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_expiry = token_expiry

    def _ensure_auth(self) -> None:
        import time
        now = time.time()
        if now >= self._token_expiry - 60:
            logger.info("[GmailOutbound] Token expired, refreshing...")
            self._refresh_auth()

    def _check_scope_error(self, resp: requests.Response) -> None:
        if resp.status_code == 403:
            try:
                body = resp.json()
                error = body.get("error", {})
                if isinstance(error, dict) and error.get("status") == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
                    logger.error("[GmailOutbound] Scope insufficient for provider %s", self._provider_id[:12])
                    raise ScopeUpgradeRequired(
                        "Gmail API scope insufficient. Reconnect with broader scopes."
                    )
                errors_list = body.get("error", {}).get("errors", [])
                if errors_list and errors_list[0].get("reason") == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
                    logger.error("[GmailOutbound] Scope insufficient for provider %s", self._provider_id[:12])
                    raise ScopeUpgradeRequired(
                        "Gmail API scope insufficient. Reconnect with broader scopes."
                    )
            except (json.JSONDecodeError, AttributeError, KeyError):
                pass

    def _refresh_auth(self) -> None:
        if not self._refresh_token:
            raise Exception("No refresh token available")
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
        if resp.status_code != 200:
            raise Exception(f"Token refresh failed: {resp.text[:500]}")
        data = resp.json()
        if data.get("access_token"):
            self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        import time
        self._token_expiry = time.time() + int(expires_in)

    def _headers(self) -> dict:
        self._ensure_auth()
        return {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}

    def _build_gmail_message(self, subject: str, body: str,
                             recipient: Recipient, sender: Recipient,
                             cc: list[Recipient], bcc: list[Recipient],
                             reply_to_msg_id: str = "",
                             in_reply_to: str = "",
                             references: str = "") -> dict:
        to_addr = f"{recipient.name} <{recipient.email}>" if recipient.name else recipient.email
        sender_addr = f"{sender.name} <{sender.email}>" if sender.name else sender.email

        msg_lines = [
            f"From: {sender_addr}",
            f"To: {to_addr}",
            f"Subject: {subject}",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "",
            body,
        ]
        if cc:
            cc_addrs = ", ".join(
                f"{c.name} <{c.email}>" if c.name else c.email for c in cc
            )
            msg_lines.insert(3, f"Cc: {cc_addrs}")
        if bcc:
            bcc_addrs = ", ".join(
                f"{b.name} <{b.email}>" if b.name else b.email for b in bcc
            )
            msg_lines.insert(4, f"Bcc: {bcc_addrs}")
        if in_reply_to:
            msg_lines.insert(3, f"In-Reply-To: {in_reply_to}")
        if references:
            msg_lines.insert(4, f"References: {references}")

        raw = "\r\n".join(msg_lines)
        encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

        message: dict = {"raw": encoded}
        if reply_to_msg_id or in_reply_to or references:
            thread_id = None
            if in_reply_to:
                thread_id = in_reply_to
            elif references:
                thread_id = references.split()[-1] if references.split() else None
            if reply_to_msg_id:
                message["threadId"] = reply_to_msg_id
            elif thread_id:
                message["threadId"] = thread_id

        return message

    def create_draft(self, draft: DraftMessage) -> DraftMessage:
        logger.info("[GmailOutbound] create_draft | draft=%s subj=%s", draft.id, draft.subject[:60])
        gmail_msg = self._build_gmail_message(
            subject=draft.subject, body=draft.body,
            recipient=draft.recipient, sender=draft.sender,
            cc=draft.cc, bcc=draft.bcc,
            reply_to_msg_id=draft.reply_to_message_id,
            in_reply_to=draft.in_reply_to,
            references=draft.references,
        )
        payload = {"message": gmail_msg}
        if draft.thread_id:
            payload["message"]["threadId"] = draft.thread_id

        resp = requests.post(
            f"{GMAIL_API_BASE}/users/me/drafts",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        self._check_scope_error(resp)
        if resp.status_code != 200:
            raise Exception(f"Failed to create draft: {resp.text[:500]}")
        data = resp.json()
        draft.external_draft_id = data.get("id", "")
        logger.info("[GmailOutbound] create_draft OK | external_id=%s", draft.external_draft_id)
        return draft

    def update_draft(self, draft: DraftMessage) -> DraftMessage:
        logger.info("[GmailOutbound] update_draft | draft=%s external=%s",
                    draft.id, draft.external_draft_id)
        if not draft.external_draft_id:
            raise Exception("Cannot update draft without external_draft_id")

        gmail_msg = self._build_gmail_message(
            subject=draft.subject, body=draft.body,
            recipient=draft.recipient, sender=draft.sender,
            cc=draft.cc, bcc=draft.bcc,
            reply_to_msg_id=draft.reply_to_message_id,
            in_reply_to=draft.in_reply_to,
            references=draft.references,
        )
        payload = {
            "id": draft.external_draft_id,
            "message": gmail_msg,
        }
        if draft.thread_id:
            payload["message"]["threadId"] = draft.thread_id

        resp = requests.put(
            f"{GMAIL_API_BASE}/users/me/drafts/{draft.external_draft_id}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        self._check_scope_error(resp)
        if resp.status_code != 200:
            raise Exception(f"Failed to update draft: {resp.text[:500]}")
        logger.info("[GmailOutbound] update_draft OK")
        return draft

    def delete_draft(self, draft_id: str) -> bool:
        logger.info("[GmailOutbound] delete_draft | draft=%s", draft_id)
        resp = requests.delete(
            f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
            headers=self._headers(),
            timeout=30,
        )
        self._check_scope_error(resp)
        if resp.status_code not in (200, 204):
            logger.warning("[GmailOutbound] delete_draft failed | status=%d", resp.status_code)
            return False
        return True

    def send(self, request: SendRequest) -> SendResult:
        logger.info("[GmailOutbound] send | subj=%s to=%s", request.subject[:60], request.recipient.email)
        result = SendResult(provider_id=request.provider_id, draft_id=request.draft_id)

        if request.draft_id:
            resp = requests.post(
                f"{GMAIL_API_BASE}/users/me/drafts/{request.draft_id}/send",
                headers=self._headers(),
                timeout=30,
            )
        else:
            gmail_msg = self._build_gmail_message(
                subject=request.subject, body=request.body,
                recipient=request.recipient, sender=request.sender,
                cc=request.cc, bcc=request.bcc,
                reply_to_msg_id=request.reply_to_message_id,
                in_reply_to=request.in_reply_to,
                references=request.references,
            )
            payload: dict = {"raw": gmail_msg["raw"]}
            if request.thread_id:
                payload["threadId"] = request.thread_id

            resp = requests.post(
                f"{GMAIL_API_BASE}/users/me/messages/send",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )

        try:
            self._check_scope_error(resp)
        except ScopeUpgradeRequired:
            result.status = DeliveryStatus.FAILED
            result.error = "Scope upgrade required. Reconnect Gmail with broader permissions."
            return result

        if resp.status_code != 200:
            error_text = resp.text[:500]
            logger.error("[GmailOutbound] send failed | status=%d body=%s", resp.status_code, error_text)
            result.status = DeliveryStatus.FAILED
            result.error = error_text
            return result

        data = resp.json()
        result.status = DeliveryStatus.SENT
        result.external_message_id = data.get("id", "")
        result.thread_id = data.get("threadId", "")
        logger.info("[GmailOutbound] send OK | ext_id=%s thread=%s",
                    result.external_message_id, result.thread_id)
        return result

    def schedule(self, draft: DraftMessage, send_at: str) -> ScheduledMessage:
        logger.info("[GmailOutbound] schedule | draft=%s send_at=%s", draft.id, send_at)
        return ScheduledMessage(
            provider_id=self._provider_id,
            conversation_id=draft.conversation_id,
            subject=draft.subject,
            body=draft.body,
            recipient=draft.recipient,
            sender=draft.sender,
            send_at=send_at,
            draft_id=draft.id,
        )

    def cancel_schedule(self, schedule_id: str) -> bool:
        logger.info("[GmailOutbound] cancel_schedule | id=%s", schedule_id)
        return True

    def get_status(self, message_id: str) -> str:
        logger.info("[GmailOutbound] get_status | msg=%s", message_id)
        try:
            resp = requests.get(
                f"{GMAIL_API_BASE}/users/me/messages/{message_id}",
                headers=self._headers(),
                timeout=15,
            )
            self._check_scope_error(resp)
            if resp.status_code == 200:
                return "sent"
            return "unknown"
        except Exception:
            return "unknown"

    def fetch_draft(self, draft_id: str) -> Optional[DraftMessage]:
        logger.info("[GmailOutbound] fetch_draft | id=%s", draft_id)
        try:
            resp = requests.get(
                f"{GMAIL_API_BASE}/users/me/drafts/{draft_id}",
                headers=self._headers(),
                timeout=15,
            )
            self._check_scope_error(resp)
            if resp.status_code != 200:
                return None
            data = resp.json()
            msg = data.get("message", {})
            payload = msg.get("payload", {})
            headers = {}
            for h in payload.get("headers", []):
                headers[h.get("name", "").lower()] = h.get("value", "")
            body = ""
            if "data" in payload.get("body", {}):
                try:
                    body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
                except Exception:
                    body = ""
            return DraftMessage(
                id=draft_id,
                provider_id=self._provider_id,
                external_draft_id=draft_id,
                subject=headers.get("subject", ""),
                body=body,
                recipient=Recipient(email=headers.get("to", ""), name=""),
                sender=Recipient(email=headers.get("from", ""), name=""),
                thread_id=msg.get("threadId", ""),
            )
        except Exception as e:
            logger.error("[GmailOutbound] fetch_draft error: %s", e)
            return None

    def list_drafts(self) -> DraftListResult:
        logger.info("[GmailOutbound] list_drafts")
        try:
            resp = requests.get(
                f"{GMAIL_API_BASE}/users/me/drafts",
                headers=self._headers(),
                params={"maxResults": 50},
                timeout=15,
            )
            self._check_scope_error(resp)
            if resp.status_code != 200:
                return DraftListResult()
            data = resp.json()
            draft_metas = data.get("drafts", [])
            drafts = []
            for dm in draft_metas:
                d = self.fetch_draft(dm.get("id", ""))
                if d:
                    drafts.append(d)
            return DraftListResult(drafts=drafts, total=len(drafts))
        except Exception as e:
            logger.error("[GmailOutbound] list_drafts error: %s", e)
            return DraftListResult()

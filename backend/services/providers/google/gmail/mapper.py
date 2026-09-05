from __future__ import annotations

import base64
from typing import Any

from services.providers.models import ProviderConversation, ProviderMessage, ProviderEmail


class GmailMapper:
    """Maps raw Gmail API responses to normalized domain models.

    No raw Gmail payloads leak past this class.
    """

    @staticmethod
    def message_to_provider_message(
        raw: dict[str, Any],
        provider_id: str = "gmail",
    ) -> ProviderMessage:
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        body = GmailMapper._extract_body(raw.get("payload", {}))
        snippet = raw.get("snippet", "")
        internal_date = raw.get("internalDate", "")

        if internal_date and internal_date.isdigit():
            import datetime
            ts = int(internal_date) / 1000
            received_at = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
        else:
            received_at = ""

        return ProviderMessage(
            message_id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            from_email=headers.get("from", ""),
            from_name=headers.get("from", ""),
            to_email=headers.get("to", ""),
            to_name=headers.get("to", ""),
            subject=headers.get("subject", ""),
            body=body,
            snippet=snippet,
            received_at=received_at,
            is_incoming=True,
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )

    @staticmethod
    def thread_to_conversation(
        raw: dict[str, Any],
        provider_id: str = "gmail",
    ) -> ProviderConversation:
        messages_raw = raw.get("messages", [])
        subject = ""
        msgs = []
        for m in messages_raw:
            pm = GmailMapper.message_to_provider_message(m, provider_id)
            if not subject:
                import email.utils
                parsed = email.utils.parseaddr(pm.from_email)
                pm.is_incoming = True
            msgs.append(pm)
            if not subject and pm.subject:
                subject = pm.subject

        return ProviderConversation(
            thread_id=raw.get("id", ""),
            subject=subject,
            messages=msgs,
            provider_id=provider_id,
            external_id=raw.get("id", ""),
        )

    @staticmethod
    def draft_to_provider_email(
        raw: dict[str, Any],
        provider_id: str = "gmail",
    ) -> ProviderEmail | None:
        message = raw.get("message")
        if not message:
            return None
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        body = GmailMapper._extract_body(message.get("payload", {}))
        return ProviderEmail(
            to_email=headers.get("to", ""),
            to_name=headers.get("to", ""),
            subject=headers.get("subject", ""),
            body=body,
            from_email=headers.get("from", ""),
            from_name=headers.get("from", ""),
            external_message_id=message.get("id", ""),
            thread_id=message.get("threadId", ""),
            provider_id=provider_id,
        )

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        mime = payload.get("mimeType", "")
        if mime == "text/plain" and payload.get("body", {}).get("data"):
            return GmailMapper._decode(payload["body"]["data"])
        if mime == "text/html" and payload.get("body", {}).get("data"):
            return GmailMapper._decode(payload["body"]["data"])
        parts = payload.get("parts", [])
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/plain" and part.get("body", {}).get("data"):
                return GmailMapper._decode(part["body"]["data"])
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/html" and part.get("body", {}).get("data"):
                return GmailMapper._decode(part["body"]["data"])
            nested = part.get("parts", [])
            for sub in nested:
                if sub.get("body", {}).get("data"):
                    return GmailMapper._decode(sub["body"]["data"])
        return ""

    @staticmethod
    def _decode(data: str) -> str:
        try:
            decoded = base64.urlsafe_b64decode(data)
            return decoded.decode("utf-8", errors="replace")
        except Exception:
            return ""

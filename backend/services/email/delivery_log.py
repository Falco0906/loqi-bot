from __future__ import annotations

import logging
import time

log = logging.getLogger("loqi.email")


def log_email_sent(
    request_id: str,
    recipient: str,
    template: str,
    provider: str,
    status: str,
    duration_ms: float,
) -> None:
    log.info(
        "email_sent request_id=%s recipient=%s template=%s provider=%s status=%s duration_ms=%.1f",
        request_id,
        recipient,
        template,
        provider,
        status,
        duration_ms,
    )


def log_email_failed(
    request_id: str,
    recipient: str,
    template: str,
    provider: str,
    error: str,
    duration_ms: float,
) -> None:
    log.warning(
        "email_failed request_id=%s recipient=%s template=%s provider=%s error=%s duration_ms=%.1f",
        request_id,
        recipient,
        template,
        provider,
        error,
        duration_ms,
    )

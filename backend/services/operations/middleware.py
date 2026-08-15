from __future__ import annotations

import logging
import re
import time
import traceback
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

log = logging.getLogger("loqi")

# The web session token is a bearer credential carried in the URL path for
# legacy routes (`/api/web/session/{token}/...`). It must never reach logs,
# exception traces, or responses. PR10.8.3: redact it from any logged path.
_SESSION_PATH_RE = re.compile(r"(/api/web/session/)[^/?]+")


def redact_session_path(path: str) -> str:
    """Replace the session token in a request path with [REDACTED]."""
    try:
        return _SESSION_PATH_RE.sub(r"\1[REDACTED]", path or "")
    except Exception:
        return path or ""


class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            log.error(
                "request_id=%s method=%s path=%s status=500 duration_ms=%d exception=%s message=%s trace=%s",
                request_id,
                request.method,
                redact_session_path(request.url.path),
                duration_ms,
                type(exc).__name__,
                str(exc),
                "".join(traceback.format_tb(exc.__traceback__)),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred",
                        "request_id": request_id,
                    }
                },
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "request_id=%s method=%s path=%s status=%d duration_ms=%d",
            request_id,
            request.method,
            redact_session_path(request.url.path),
            response.status_code,
            duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response

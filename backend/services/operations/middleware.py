from __future__ import annotations

import logging
import time
import traceback
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

log = logging.getLogger("loqi")


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
                request.url.path,
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
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response

"""core/timeout_middleware.py — Hard request-timeout middleware.

Extracted from app.py. Aborts requests that exceed REQUEST_HARD_TIMEOUT
seconds with a 504 response. Streaming and long-running routes are exempted
so SSE connections (chat, shell, research) are never interrupted.
"""
from __future__ import annotations

import asyncio
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

REQUEST_HARD_TIMEOUT: float = float(os.getenv("REQUEST_HARD_TIMEOUT", "45"))

# Routes that are intentionally long-running or streaming — never timeout.
_TIMEOUT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/chat",            # streaming SSE
    "/api/shell/stream",    # SSE
    "/api/research",        # multi-minute jobs
    "/api/model/download",  # may run pip installs
    "/api/model/probe",     # SSE; iterates models with up to 8s timeout each
    "/api/model-endpoints", # /probe sub-route also iterates models
    "/api/cookbook/setup",  # remote pacman/apt installs
    "/api/upload",          # large files
    "/api/image",           # diffusion proxies — own 120s httpx timeout
)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort requests that exceed REQUEST_HARD_TIMEOUT seconds with HTTP 504."""

    def __init__(self, app: ASGIApp, timeout: float = REQUEST_HARD_TIMEOUT) -> None:
        super().__init__(app)
        self._timeout = timeout

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if any(path.startswith(p) for p in _TIMEOUT_EXEMPT_PREFIXES):
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=self._timeout)
        except asyncio.TimeoutError:
            return JSONResponse(
                {"detail": f"Request exceeded {self._timeout:.0f}s timeout"},
                status_code=504,
            )

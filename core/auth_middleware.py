"""core/auth_middleware.py — Authentication middleware for Odysseus.

Extracted from app.py. Handles three auth paths:
  1. Cookie-based session auth (normal browser login)
  2. Bearer token auth (API tokens, external integrations)
  3. Internal tool token (agent loopback calls to admin-gated routes)

The middleware is only added to the app when AUTH_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from datetime import datetime, timezone

import bcrypt as _bcrypt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

# Auth-exempt exact paths — no token/cookie required.
AUTH_EXEMPT_EXACT: frozenset[str] = frozenset({
    "/api/auth/setup",
    "/api/auth/signup",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/status",
    "/api/auth/features",
    "/api/auth/settings",
    "/api/auth/integrations/presets",
    "/api/health",
    "/api/version",
    "/login",
})

# Auth-exempt prefixes.
AUTH_EXEMPT_PREFIXES: tuple[str, ...] = ("/static",)

# Dynamic paths whose own handler proves identity via a path-embedded
# secret. The route handler validates the per-task webhook_token itself.
AUTH_EXEMPT_PATTERNS: list[re.Pattern] = [
    re.compile(r"^/api/tasks/[^/]+/webhook/[^/]+/?$"),
]

# Headers that prove a request was forwarded by a proxy/tunnel.
_PROXY_FWD_HEADERS: tuple[str, ...] = (
    "cf-connecting-ip", "cf-ray", "cf-visitor",
    "x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded",
)


def is_auth_exempt(path: str) -> bool:
    """Return True when the path doesn't require authentication."""
    if path in AUTH_EXEMPT_EXACT:
        return True
    if any(path.startswith(p) for p in AUTH_EXEMPT_PREFIXES):
        return True
    return any(p.match(path) for p in AUTH_EXEMPT_PATTERNS)


def is_trusted_loopback(request: Request) -> bool:
    """True ONLY for a DIRECT loopback connection with no proxy/tunnel headers.

    A bare ``client.host in ('127.0.0.1','::1')`` check is unsafe behind a
    Cloudflare tunnel: those connect from loopback, so a remote visitor would
    otherwise inherit local trust. Odysseus's own in-process agent calls carry
    none of these proxy headers, so they still qualify.
    """
    host = request.client.host if request.client else None
    if host not in ("127.0.0.1", "::1"):
        return False
    for header in _PROXY_FWD_HEADERS:
        if request.headers.get(header):
            return False
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware — only added when AUTH_ENABLED=true."""

    def __init__(self, app, auth_manager, localhost_bypass: bool = False, session_cookie: str = "session") -> None:
        super().__init__(app)
        self._auth_manager = auth_manager
        self._localhost_bypass = localhost_bypass
        self._session_cookie = session_cookie

    async def dispatch(self, request: Request, call_next):
        from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
        from core import token_cache as tc
        from core.database import SessionLocal, ApiToken
        from core.auth import normalize_known_username

        path = request.url.path

        # Let genuine CORS preflights through — they carry no credentials by
        # design and must reach CORSMiddleware to be answered.
        from core.middleware import is_cors_preflight
        if is_cors_preflight(request.method, request.headers):
            return await call_next(request)

        if is_auth_exempt(path):
            return await call_next(request)

        # In-process internal-tool token — agent layer HTTP loopback.
        try:
            hdr = request.headers.get(INTERNAL_TOOL_HEADER)
            if hdr and secrets.compare_digest(hdr, INTERNAL_TOOL_TOKEN) and is_trusted_loopback(request):
                _impersonate = (request.headers.get("X-Odysseus-Owner") or "").strip()
                if _impersonate and _impersonate in getattr(self._auth_manager, "users", {}):
                    request.state.current_user = _impersonate
                else:
                    request.state.current_user = "internal-tool"
                request.state.api_token = False
                return await call_next(request)
        except Exception:
            pass

        # LOCALHOST_BYPASS — dev-only, direct loopback only.
        if self._localhost_bypass and is_trusted_loopback(request):
            return await call_next(request)

        if not self._auth_manager.is_configured:
            if not path.startswith("/api/"):
                return RedirectResponse(url="/login", status_code=302)
            return JSONResponse(status_code=401, content={"error": "Setup required"})

        # --- Bearer token auth ---
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ody_"):
            raw_token = auth_header[7:]
            if len(raw_token) < 12 or len(raw_token) > 100:
                return JSONResponse(status_code=401, content={"error": "Invalid API token"})
            prefix = raw_token[:8]
            try:
                if tc.is_dirty():
                    async with tc.get_lock():
                        if tc.is_dirty():
                            await asyncio.to_thread(
                                tc.rebuild, self._auth_manager, SessionLocal, ApiToken, normalize_known_username
                            )
                candidates = list(tc.get_cache().get(prefix, ()))
                matched_id = matched_owner = None
                matched_scopes: list = []
                for tid, thash, owner, scopes in candidates:
                    if _bcrypt.checkpw(raw_token.encode(), thash.encode()):
                        matched_id = tid
                        matched_owner = owner
                        matched_scopes = scopes or []
                        break
                if matched_id:
                    # Fire-and-forget last_used_at update.
                    asyncio.create_task(self._touch_last_used(matched_id))
                    request.state.current_user = "api"
                    request.state.api_token = True
                    request.state.api_token_id = matched_id
                    request.state.api_token_owner = matched_owner
                    request.state.api_token_scopes = matched_scopes
                    return await call_next(request)
            except Exception:
                logger.warning("API token auth error", exc_info=False)
            return JSONResponse(status_code=401, content={"error": "Invalid API token"})

        # --- Cookie-based session auth ---
        token = request.cookies.get(self._session_cookie)
        if not self._auth_manager.validate_token(token):
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"error": "Not authenticated"})
            return RedirectResponse(url="/login", status_code=302)

        request.state.current_user = self._auth_manager.get_username_for_token(token)
        request.state.api_token = False
        return await call_next(request)

    @staticmethod
    async def _touch_last_used(tid: str) -> None:
        """Update last_used_at for an API token off the hot path."""
        from core.database import SessionLocal, ApiToken as _ApiToken

        def _do() -> None:
            _db = SessionLocal()
            try:
                _db.query(_ApiToken).filter(_ApiToken.id == tid).update(
                    {"last_used_at": datetime.now(timezone.utc).replace(tzinfo=None)}
                )
                _db.commit()
            finally:
                _db.close()

        try:
            await asyncio.to_thread(_do)
        except Exception:
            pass

"""core/static_serving.py — Template caching for HTML pages.

Caches the raw HTML bytes of index.html and login.html at startup so that
every page request only does a cheap string.replace for the CSP nonce
instead of an fs.open+read.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# HTML template cache: filename → raw template string
_html_cache: dict[str, str] = {}


def preload_templates(static_dir: str | Path, base_dir: str | Path) -> None:
    """Read HTML templates into memory at startup.

    Call once during application startup (e.g. from core/lifespan.py).
    A missing file is logged as a warning and skipped — the per-request
    handler falls back to reading from disk.
    """
    templates = [
        ("index.html", os.path.join(str(static_dir), "index.html")),
        ("login.html", os.path.join(str(static_dir), "login.html")),
    ]
    for name, path in templates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _html_cache[name] = fh.read()
            logger.debug("[static] cached %s (%d bytes)", name, len(_html_cache[name]))
        except FileNotFoundError:
            logger.warning("[static] template not found: %s", path)


def serve_html_with_nonce(request: Request, file_path: str) -> HTMLResponse:
    """Return an HTMLResponse with {{CSP_NONCE}} replaced by the request nonce.

    Uses the in-memory cache when the file was pre-loaded; falls back to
    reading from disk so cold-start and dev-mode (no preload) still work.
    """
    filename = os.path.basename(file_path)
    nonce = getattr(request.state, "csp_nonce", "")

    if filename in _html_cache:
        return HTMLResponse(_html_cache[filename].replace("{{CSP_NONCE}}", nonce))

    # Fallback: disk read (dev mode / file not yet preloaded)
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            html = fh.read()
        return HTMLResponse(html.replace("{{CSP_NONCE}}", nonce))
    except FileNotFoundError as exc:
        raise HTTPException(404, f"{filename} not found") from exc


class RevalidatingStatic(StaticFiles):
    """StaticFiles that forces REVALIDATION for JS/CSS/HTML on every load.

    Prevents stale browser-cached modules across deploys — the app ships raw
    ES modules with no build step or versioned URLs. `no-cache` keeps cached
    bytes but requires a conditional request; unchanged files still return a
    cheap 304 (ETag/Last-Modified are preserved).
    """

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        if path.endswith((".js", ".css", ".html")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

"""core/lifespan.py — Application startup and shutdown lifecycle.

Extracted from app.py. Contains the startup and shutdown event handlers
that were previously inline in app.py.

The lifespan context manager is still wired in app.py (which calls
build_lifespan()), so the orchestration file knows which components
exist at startup time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _check_dangerous_config() -> None:
    """Refuse to start if LOCALHOST_BYPASS + network bind are both set.

    This combination lets any process on the same machine bypass authentication,
    AND exposes the unauthenticated surface over the network — a complete auth bypass.
    Fail fast at startup rather than silently accepting the misconfiguration.
    """
    localhost_bypass = os.getenv("LOCALHOST_BYPASS", "false").lower() == "true"
    app_bind = os.getenv("APP_BIND", "127.0.0.1")
    if localhost_bypass and app_bind not in ("127.0.0.1", "::1", "localhost"):
        logger.critical(
            "REFUSING TO START: LOCALHOST_BYPASS=true combined with APP_BIND=%s "
            "would expose an unauthenticated surface over the network. "
            "Set LOCALHOST_BYPASS=false or bind to 127.0.0.1.",
            app_bind,
        )
        sys.exit(1)

    auth_enabled = os.getenv("AUTH_ENABLED", "true").lower() != "false"
    if not auth_enabled:
        logger.warning(
            "\u26a0\ufe0f  AUTH IS DISABLED (AUTH_ENABLED=false) — all routes are publicly "
            "accessible without any credentials. Set AUTH_ENABLED=true for any "
            "network-accessible deployment."
        )


@asynccontextmanager
async def build_lifespan(app: "FastAPI", components: dict, startup_fn, shutdown_fn):
    """Build the FastAPI lifespan context manager.

    startup_fn and shutdown_fn are async callables defined in app.py that
    perform the actual startup/shutdown work (they reference module-level
    globals that live in app.py). This wrapper adds the dangerous-config
    check before startup.
    """
    _check_dangerous_config()
    await startup_fn()
    yield
    await shutdown_fn()

from fastapi import APIRouter, HTTPException, Request, Response, Form, Query, Body
from typing import List, Dict, Any, Optional
import json
import uuid
import logging
from datetime import datetime
from pydantic import BaseModel
from core.database import SessionLocal, ModelEndpoint
from core.middleware import require_admin
from src.auth_helpers import _auth_disabled, owner_filter

from .shared import *
from .state import *

def setup_models_routes(router: APIRouter):
    @router.get("/models")
    def api_models(request: Request, refresh: bool = False):
        """Get available models — per-user (caller sees only their endpoints +
        legacy/shared null-owner rows). Cached per-user for 30s."""
        # Require auth; "" is the unconfigured single-user mode, treated as
        # "see everything" by _fetch_models.
        try:
            from src.auth_helpers import get_current_user as _gcu
            owner = _gcu(request) or ""
        except Exception:
            owner = ""
        # Reject anonymous in configured deployments — no leaking the model
        # list to unauthenticated callers.
        try:
            auth_mgr = getattr(request.app.state, "auth_manager", None)
            if not owner and not _auth_disabled() and auth_mgr is not None and getattr(auth_mgr, "is_configured", False):
                raise HTTPException(401, "Not authenticated")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Auth gate error in GET /api/models, failing closed: %s", e)
            raise HTTPException(status_code=500, detail="Internal error")
        # Admins see every endpoint (they manage the global pool); regular
        # users get the owner-scoped view.
        _is_admin = False
        try:
            auth_mgr = getattr(request.app.state, "auth_manager", None)
            if owner and auth_mgr is not None and getattr(auth_mgr, "is_admin", None):
                _is_admin = bool(auth_mgr.is_admin(owner))
        except Exception:
            _is_admin = False
        now = _time.time()
        # Cache key includes the admin flag so a demotion / promotion doesn't
        # serve the wrong scoped view from cache.
        _cache_key = (owner, _is_admin)
        cache_entry = _models_cache.get(_cache_key)
        if not refresh and cache_entry is not None and (now - cache_entry["time"]) < _MODELS_CACHE_TTL:
            return cache_entry["data"]
        result = _fetch_models(owner=owner, is_admin=_is_admin)
        _models_cache[_cache_key] = {"data": result, "time": now}
        # Kick off background refresh to update caches from live endpoints
        _refresh_caches_bg(force=refresh)
        return result

    # Brief cache for local-probe results so picker-open doesn't hammer
    # endpoint health checks every time. 8s TTL — long enough to amortize cost,
    # short enough that a freshly-killed local server shows as offline
    # within ~8s of the user noticing.
    _LOCAL_PROBE_TTL = 8.0
    _local_probe_cache: Dict[str, Any] = {"data": None, "time": 0.0}



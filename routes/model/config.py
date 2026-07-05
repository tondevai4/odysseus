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

def setup_config_routes(router: APIRouter):
    @router.get("/default-chat")
    def get_default_chat(request: Request):
        # SECURITY: resolve the default endpoint + model from the CALLER's
        # per-user prefs ONLY. We deliberately do NOT fall back to the
        # global `default_model` / `default_endpoint_id` in settings.json
        # for authenticated users — that's what was leaking the previous
        # admin's pick into every new account's composer. If the user has
        # no per-user default yet, we resolve via the owner-scoped endpoint
        # lookup below (last-resort: first enabled endpoint THIS user owns).
        # Unauthenticated single-user mode keeps the old behavior.
        from src.auth_helpers import get_current_user as _gcu
        try:
            _user = _gcu(request) or ""
        except Exception:
            _user = ""
        # Admins resolve via the global defaults (they own them, and the
        # scoped resolution was making the picker disappear for them).
        # Regular users get per-user prefs with NO global fallback for the
        # model/endpoint values — that's what was leaking the previous
        # admin's pick into every new account's composer.
        settings = _load_settings()
        _is_admin = False
        try:
            auth_mgr = getattr(request.app.state, "auth_manager", None)
            if _user and auth_mgr is not None and getattr(auth_mgr, "is_admin", None):
                _is_admin = bool(auth_mgr.is_admin(_user))
        except Exception:
            _is_admin = False
        if _user and not _is_admin:
            from routes.prefs_routes import _load_for_user
            _user_prefs = _load_for_user(_user) or {}
            ep_id = (_user_prefs.get("default_endpoint_id") or "").strip()
            model = (_user_prefs.get("default_model") or "").strip()
            _fallbacks = _user_prefs.get("default_model_fallbacks") or []
        else:
            ep_id = settings.get("default_endpoint_id", "")
            model = settings.get("default_model", "")
            _fallbacks = settings.get("default_model_fallbacks") or []
        db = SessionLocal()
        try:
            ep = None
            if ep_id:
                ep_q = db.query(ModelEndpoint).filter(
                    ModelEndpoint.id == ep_id, ModelEndpoint.is_enabled == True
                )
                # Honor the same owner-scope rule as /api/models — a per-user
                # default that points at an endpoint owned by a different user
                # mustn't silently resolve. Admins are exempt (they manage the
                # global pool).
                if _user and not _is_admin:
                    ep_q = owner_filter(ep_q, ModelEndpoint, _user)
                ep = ep_q.first()
            # Configured fallback chain — when the chosen default endpoint is
            # gone/disabled, honor the user's configured `default_model_fallbacks`
            # in order BEFORE arbitrarily grabbing the first enabled endpoint.
            # (Previously this jumped straight to "first enabled", which is why
            # deleting/changing the main endpoint silently reassigned the default
            # chat to some unrelated endpoint instead of the fallback.)
            if not ep:
                for entry in _fallbacks:
                    if not isinstance(entry, dict):
                        continue
                    fid = (entry.get("endpoint_id") or "").strip()
                    if not fid:
                        continue
                    cand_q = db.query(ModelEndpoint).filter(
                        ModelEndpoint.id == fid, ModelEndpoint.is_enabled == True
                    )
                    if _user and not _is_admin:
                        cand_q = owner_filter(cand_q, ModelEndpoint, _user)
                    cand = cand_q.first()
                    if cand:
                        ep = cand
                        # Use the fallback entry's model. Reset even when empty
                        # so we don't carry the prior endpoint's stale model onto
                        # this fallback — the cached-models lookup below then
                        # fills it from the fallback endpoint.
                        model = (entry.get("model") or "").strip()
                        break
            # Last resort: first enabled endpoint owned by THIS user. Do not
            # include null-owner/shared endpoints here: a brand-new user with
            # no explicit default should not auto-open a pending chat using an
            # existing shared/admin endpoint. Shared endpoints remain visible
            # in the picker and still work when explicitly selected/saved.
            if not ep:
                _last_q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
                if _user and not _is_admin:
                    _last_q = owner_filter(_last_q, ModelEndpoint, _user, include_shared=False)
                ep = _last_q.first()
            if not ep:
                return {"endpoint_id": "", "endpoint_url": "", "model": ""}
            base = _normalize_base(ep.base_url)
            chat_url = build_chat_url(base)
            if not model and (getattr(ep, "cached_models", None) or getattr(ep, "pinned_models", None)):
                try:
                    visible = _visible_models(ep.cached_models, getattr(ep, "hidden_models", None), getattr(ep, "pinned_models", None))
                    if visible:
                        model = visible[0]
                except Exception:
                    pass
            return {"endpoint_id": ep.id, "endpoint_url": chat_url, "model": model}
        finally:
            db.close()



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

def setup_management_routes(router: APIRouter):
    @router.get("/model-endpoints")
    def list_model_endpoints(request: Request) -> List[Dict[str, Any]]:
        require_admin(request)
        db = SessionLocal()
        try:
            rows = db.query(ModelEndpoint).order_by(ModelEndpoint.created_at).all()
            results = []
            for r in rows:
                all_models = _cached_model_ids(r)
                hidden = _hidden_model_ids(r)
                pinned = _normalize_model_ids(getattr(r, "pinned_models", None))
                visible = _visible_models(all_models, r.hidden_models, pinned)
                # Endpoint counts as reachable if it has any model — including
                # admin-pinned IDs that a probe would never surface.
                status = "online" if (all_models or pinned) else "offline"
                ping = None
                # When cached_models is empty, do a quick reachability probe.
                # Bumped 1.0s → 3.5s because the user reported endpoints they
                # were ACTIVELY chatting with showed "offline" — the previous
                # 1s timeout was clipping live cloud endpoints (DeepSeek can
                # take 1.5–2.5s on /v1/models when their region is under load,
                # vLLM on a remote GPU box behind SSH can also push past 1s).
                # 3.5s still keeps the picker render snappy in the common
                # "everything's already cached" path because this branch only
                # runs for endpoints with an empty cached_models.
                if not all_models and not pinned and r.is_enabled:
                    ping = _ping_endpoint(r.base_url, r.api_key, timeout=3.5)
                    if ping.get("reachable"):
                        status = "empty"
                        # Best-effort: if the probe came back reachable, try
                        # to populate cached_models in the background so the
                        # NEXT picker load shows "online" instead of "empty".
                        # Failure here is silent — we already returned the
                        # "empty" status, and the existing background refresh
                        # path will eventually fill it in too.
                        try:
                            probed = _probe_endpoint(r.base_url, r.api_key, timeout=5)
                            if probed:
                                r.cached_models = json.dumps(probed)
                                db.commit()
                                all_models = probed
                                visible = _visible_models(all_models, r.hidden_models, pinned)
                                status = "online"
                        except Exception as _refill_err:
                            logger.debug(f"opportunistic cached_models refill failed for {r.id}: {_refill_err!r}")
                base = _normalize_base(r.base_url)
                kind = _effective_endpoint_kind(r, base)
                results.append({
                    "id": r.id,
                    "name": r.name,
                    "base_url": r.base_url,
                    "has_key": bool(r.api_key),
                    "api_key_fingerprint": _api_key_fingerprint(r.api_key),
                    "is_enabled": r.is_enabled,
                    "models": visible,
                    "pinned_models": pinned,
                    "hidden_count": len(hidden),
                    "online": status != "offline",
                    "status": status,
                    "ping_error": (ping or {}).get("error") if ping else None,
                    "model_type": getattr(r, "model_type", None) or "llm",
                    "supports_tools": getattr(r, "supports_tools", None),
                    "endpoint_kind": kind,
                    "category": _classify_endpoint(base, kind),
                    "model_refresh_mode": _endpoint_refresh_mode(r, kind),
                    "model_refresh_interval": getattr(r, "model_refresh_interval", None),
                    "model_refresh_timeout": getattr(r, "model_refresh_timeout", None),
                })
            return results
        finally:
            db.close()


    @router.post("/model-endpoints")
    def create_model_endpoint(
        request: Request,
        name: str = Form(""),
        base_url: str = Form(...),
        api_key: str = Form(""),
        skip_probe: str = Form("false"),
        require_models: str = Form("false"),
        model_type: str = Form("llm"),
        endpoint_kind: str = Form("auto"),
        model_refresh_mode: str = Form(""),
        model_refresh_interval: str = Form(""),
        model_refresh_timeout: str = Form(""),
        supports_tools: str = Form(""),  # "true"/"false"/"" (unknown)
        pinned_models: str = Form(""),  # admin-pinned IDs: list/JSON/comma/newline
        container_local: str = Form("false"),
        # Default `shared=true` → endpoints are visible to all users (the
        # app's historical behaviour). Admins can pass `shared=false` to
        # scope a new endpoint to their own account only.
        shared: str = Form("true"),
    ):
        require_admin(request)
        base_url = _normalize_base(base_url)
        if not base_url:
            raise HTTPException(400, "Base URL is required")
        # Resolve hostname via Tailscale if DNS fails
        from src.endpoint_resolver import resolve_url
        base_url = resolve_url(base_url)
        # In Docker, manually added loopback URLs usually point at a host-local
        # server. Cookbook local serves are launched inside Odysseus itself, so
        # keep those container-local when the frontend marks them as such.
        base_url = _rewrite_loopback_for_docker(base_url, container_local=_truthy(container_local))

        # Auto-generate name from URL if not provided
        if not name.strip():
            name = base_url.replace("http://", "").replace("https://", "").split("/")[0]

        requested_kind = _normalize_endpoint_kind(endpoint_kind)
        refresh_mode = _normalize_refresh_mode(model_refresh_mode, requested_kind)
        refresh_interval = _parse_positive_int(model_refresh_interval, minimum=30, maximum=86400)
        refresh_timeout = _parse_positive_int(model_refresh_timeout, minimum=1, maximum=60)
        require_model_list = _truthy(require_models)
        should_probe = (
            require_model_list or requested_kind in ("api", "proxy") or not _truthy(skip_probe)
        )
        explicit_timeout = _explicit_model_list_timeout(base_url, requested_kind, refresh_timeout)

        # Dedupe: if an endpoint with the same base_url already exists and
        # is reachable by the caller (shared or owned by them), return it
        # instead of creating a duplicate row. Fixes "Scan for Servers"
        # re-adding manually-added endpoints under their host:port name.
        from src.auth_helpers import get_current_user as _gcu_dedup
        _caller = _gcu_dedup(request) or None
        _incoming_api_key = api_key.strip()
        _db_dedup = SessionLocal()
        try:
            _same_url_rows = (
                _db_dedup.query(ModelEndpoint)
                .filter(ModelEndpoint.base_url == base_url)
                .filter((ModelEndpoint.owner.is_(None)) | (ModelEndpoint.owner == _caller))
                .order_by(ModelEndpoint.owner.desc())  # prefer owned over shared
                .all()
            )
            existing = None
            _empty_key_existing = None
            for _candidate in _same_url_rows:
                _candidate_key = (getattr(_candidate, "api_key", None) or "").strip()
                if _candidate_key == _incoming_api_key:
                    existing = _candidate
                    break
                if _incoming_api_key and not _candidate_key and _empty_key_existing is None:
                    _empty_key_existing = _candidate
            if existing is None and _incoming_api_key and _empty_key_existing is not None:
                existing = _empty_key_existing
            if existing:
                changed = False
                # Persist any incoming pinned IDs onto the existing row. An
                # empty/omitted form field must not wipe previously pinned IDs.
                _incoming_pinned = _normalize_model_ids(pinned_models)
                if _incoming_pinned:
                    _merged_pinned = _merge_model_ids(
                        _normalize_model_ids(getattr(existing, "pinned_models", None)),
                        _incoming_pinned,
                    )
                    existing.pinned_models = json.dumps(_merged_pinned) if _merged_pinned else None
                    changed = True
                existing_kind_for_probe = requested_kind if requested_kind != "auto" else _effective_endpoint_kind(existing, base_url)
                if requested_kind != "auto" and _endpoint_kind(existing) == "auto":
                    existing.endpoint_kind = requested_kind
                    changed = True
                if model_refresh_mode or (requested_kind == "proxy" and _endpoint_refresh_mode(existing, requested_kind) != refresh_mode):
                    existing.model_refresh_mode = refresh_mode
                    changed = True
                if refresh_interval is not None:
                    existing.model_refresh_interval = refresh_interval
                    changed = True
                if refresh_timeout is not None:
                    existing.model_refresh_timeout = refresh_timeout
                    changed = True
                if api_key.strip() and not existing.api_key:
                    existing.api_key = api_key.strip()
                    changed = True
                if should_probe:
                    probed_models = _probe_endpoint(
                        base_url,
                        (api_key.strip() or existing.api_key or None),
                        timeout=_explicit_model_list_timeout(base_url, existing_kind_for_probe, refresh_timeout),
                    )
                    if probed_models:
                        existing.cached_models = json.dumps(probed_models)
                        changed = True
                if changed:
                    _db_dedup.commit()
                    _invalidate_models_cache()
                    _local_probe_cache["data"] = None
                existing_models = _cached_model_ids(existing)
                _existing_pinned = _normalize_model_ids(getattr(existing, "pinned_models", None))
                existing_kind = _effective_endpoint_kind(existing, existing.base_url)
                return {
                    "id": existing.id,
                    "name": existing.name,
                    "base_url": existing.base_url,
                    "has_key": bool(existing.api_key),
                    "api_key_fingerprint": _api_key_fingerprint(existing.api_key),
                    "models": _visible_models(
                        existing_models,
                        getattr(existing, "hidden_models", None),
                        existing.pinned_models,
                    ),
                    "pinned_models": _existing_pinned,
                    "online": True,
                    "status": "online",
                    "existing": True,
                    "endpoint_kind": existing_kind,
                    "category": _classify_endpoint(existing.base_url, existing_kind),
                }
        finally:
            _db_dedup.close()

        model_ids = _probe_endpoint(base_url, api_key.strip() or None, timeout=explicit_timeout) if should_probe else []
        ping = {"reachable": False, "error": None}
        if (should_probe or requested_kind in ("api", "proxy")) and not model_ids:
            ping = _ping_endpoint(base_url, api_key.strip() or None, timeout=min(explicit_timeout, 2.0))
        if require_model_list and not model_ids:
            raise HTTPException(400, _model_endpoint_error_message(base_url, ping))

        ep_id = str(uuid.uuid4())[:8]
        db = SessionLocal()
        try:
            _st_raw = (supports_tools or "").strip().lower()
            _st = True if _st_raw in ("true", "1", "yes") else (False if _st_raw in ("false", "0", "no") else None)
            _pinned = _normalize_model_ids(pinned_models)
            # Stamp owner so the picker only shows this endpoint to the admin
            # who added it. Pass `shared=true` to mark it null-owner (visible
            # to all users), preserving the pre-fix "everyone sees everything"
            # behaviour for endpoints the admin explicitly intends to share.
            from src.auth_helpers import get_current_user as _gcu
            _shared_flag = (shared or "").strip().lower() in ("true", "1", "yes")
            _owner_val = None if _shared_flag else (_gcu(request) or None)
            ep = ModelEndpoint(
                id=ep_id,
                name=name.strip(),
                base_url=base_url,
                api_key=api_key.strip() or None,
                is_enabled=True,
                model_type=model_type.strip() if model_type else "llm",
                endpoint_kind=requested_kind,
                model_refresh_mode=refresh_mode,
                model_refresh_interval=refresh_interval,
                model_refresh_timeout=refresh_timeout,
                cached_models=json.dumps(model_ids) if model_ids else None,
                pinned_models=json.dumps(_pinned) if _pinned else None,
                supports_tools=_st,
                owner=_owner_val,
            )
            db.add(ep)
            db.commit()
            # Auto-set as default chat endpoint when none is usable yet — either
            # nothing is configured, or the configured default points at an
            # endpoint that is now missing/disabled (#3586). Seed the first CHAT
            # model (not raw model_ids[0]) so we don't pin the global default to
            # an embedding/tts/etc. entry a provider happens to list first.
            settings = _load_settings()
            enabled_ids = {
                e.id
                for e in db.query(ModelEndpoint).filter(
                    ModelEndpoint.is_enabled == True  # noqa: E712
                ).all()
            }
            if _default_endpoint_needs_assignment(settings.get("default_endpoint_id") or "", enabled_ids):
                from src.endpoint_resolver import _first_chat_model
                settings["default_endpoint_id"] = ep.id
                settings["default_model"] = _first_chat_model(model_ids) or ""
                _save_settings(settings)
            _invalidate_models_cache()
            _local_probe_cache["data"] = None
        finally:
            db.close()

        # Return immediately — probing happens via the separate /probe SSE endpoint
        return {
            "id": ep_id,
            "name": name.strip(),
            "base_url": base_url,
            "has_key": bool(api_key.strip()),
            "api_key_fingerprint": _api_key_fingerprint(api_key),
            "models": _merge_model_ids(model_ids, _pinned),
            "pinned_models": _pinned,
            "online": bool(model_ids) or bool(_pinned) or bool(ping.get("reachable")),
            "status": "online" if (model_ids or _pinned) else ("empty" if ping.get("reachable") else "offline"),
            "ping_error": ping.get("error") if ping else None,
            "endpoint_kind": requested_kind,
            "category": _classify_endpoint(base_url, requested_kind),
        }


    @router.post("/model-endpoints/test")
    def test_model_endpoint(
        request: Request,
        base_url: str = Form(...),
        api_key: str = Form(""),
        endpoint_kind: str = Form("auto"),
        model_refresh_timeout: str = Form(""),
    ):
        require_admin(request)
        base_url = _normalize_base(base_url)
        if not base_url:
            raise HTTPException(400, "Base URL is required")
        from src.endpoint_resolver import resolve_url
        base_url = resolve_url(base_url)
        base_url = _rewrite_loopback_for_docker(base_url)
        requested_kind = _normalize_endpoint_kind(endpoint_kind)
        configured_timeout = _parse_positive_int(model_refresh_timeout, minimum=1, maximum=60)
        probe_timeout = _explicit_model_list_timeout(base_url, requested_kind, configured_timeout)
        models = _probe_endpoint(base_url, api_key.strip() or None, timeout=probe_timeout)
        ping = {"reachable": True, "error": None} if models else _ping_endpoint(base_url, api_key.strip() or None, timeout=min(probe_timeout, 2.0))
        return {
            "base_url": base_url,
            "online": bool(models) or bool(ping.get("reachable")),
            "status": "online" if models else ("empty" if ping.get("reachable") else "offline"),
            "ping_error": ping.get("error") if ping else None,
            "models": models,
            "count": len(models),
            "endpoint_kind": requested_kind,
            "category": _classify_endpoint(base_url, requested_kind),
        }


    @router.get("/model-endpoints/{ep_id}/probe")
    def probe_endpoint_models(ep_id: str, request: Request):
        """Re-probe all models on an endpoint. Updates hidden_models and streams SSE results."""
        require_admin(request)
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            if not ep:
                raise HTTPException(404, "Endpoint not found")
            ep_data = {"id": ep.id, "name": ep.name, "base_url": ep.base_url, "api_key": ep.api_key}
        finally:
            db.close()

        base = _normalize_base(ep_data["base_url"])
        all_models = _probe_endpoint(base, ep_data["api_key"])
        chat_models = [m for m in all_models if _is_chat_model(m)]
        skipped = len(all_models) - len(chat_models)

        def _stream():
            yield f"data: {json.dumps({'type': 'probe_start', 'endpoint': ep_data['name'], 'model_count': len(chat_models), 'skipped': skipped})}\n\n"
            failed = []
            ok_count = 0
            for mid in chat_models:
                result = _probe_single_model(base, ep_data["api_key"], mid, timeout=8)
                result["model"] = mid
                result["type"] = "probe_result"
                result["endpoint"] = ep_data["name"]
                if result["status"] == "ok":
                    ok_count += 1
                else:
                    failed.append(mid)
                yield f"data: {json.dumps(result)}\n\n"

            # Update hidden_models and cached_models in DB
            db2 = SessionLocal()
            try:
                ep_obj = db2.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
                if ep_obj:
                    ep_obj.hidden_models = json.dumps(failed) if failed else None
                    if all_models:
                        ep_obj.cached_models = json.dumps(all_models)
                    db2.commit()
            finally:
                db2.close()
            _invalidate_models_cache()

            yield f"data: {json.dumps({'type': 'probe_done', 'total': len(all_models), 'ok': ok_count, 'hidden': len(failed)})}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")


    @router.get("/model-endpoints/{ep_id}/models")
    def list_endpoint_models(
        ep_id: str,
        request: Request,
        response: Response,
        refresh: bool = False,
        refresh_timeout: Optional[int] = Query(None, ge=1, le=60),
    ):
        """List all discovered models for an endpoint with hidden/visible state."""
        require_admin(request)
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            if not ep:
                raise HTTPException(404, "Endpoint not found")
            hidden = _hidden_model_ids(ep)
            all_models = _cached_model_ids(ep)
            if refresh:
                base = _normalize_base(ep.base_url)
                kind = _effective_endpoint_kind(ep, base)
                category = _classify_endpoint(base, kind)
                timeout = _manual_refresh_timeout(ep, category, refresh_timeout)
                try:
                    probed = _probe_endpoint(base, ep.api_key, timeout=timeout)
                except Exception as exc:
                    logger.warning("Manual model refresh failed for endpoint %s at %s: %s", ep_id, base, exc)
                    probed = []
                if probed:
                    all_models = probed
                    ep.cached_models = json.dumps(all_models)
                    db.commit()
                    _invalidate_models_cache()
                    response.headers["X-Model-Refresh-Status"] = "refreshed"
                    response.headers["X-Model-Refresh-Count"] = str(len(probed))
                else:
                    response.headers["X-Model-Refresh-Status"] = "failed"
                    response.headers["X-Model-Refresh-Warning"] = "Model refresh failed or returned no models; kept cached models."
            pinned = _normalize_model_ids(getattr(ep, "pinned_models", None))
            pinned_set = set(pinned)
            return [
                {
                    "id": m,
                    "display": m.split("/")[-1],
                    "is_hidden": m in hidden,
                    "is_pinned": m in pinned_set,
                }
                for m in _merge_model_ids(all_models, pinned)
            ]
        finally:
            db.close()


    @router.patch("/model-endpoints/{ep_id}/models")
    async def update_hidden_models(ep_id: str, request: Request):
        """Bulk update hidden and/or pinned model lists for an endpoint.

        Expects JSON body with optional keys:
          {"hidden": ["model-id-1", ...], "pinned_models": ["deploy-id", ...]}
        Each key is updated only when present, so callers can patch one list
        without clobbering the other.
        """
        require_admin(request)
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            if not ep:
                raise HTTPException(404, "Endpoint not found")
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(400, "Body must be a JSON object")
            if "hidden" in body:
                hidden = body.get("hidden")
                if not isinstance(hidden, list):
                    raise HTTPException(400, "hidden must be a list of model IDs")
                ep.hidden_models = json.dumps(hidden) if hidden else None
            # Accept either "pinned" or "pinned_models" for the manual IDs list.
            if "pinned_models" in body or "pinned" in body:
                pinned = _normalize_model_ids(body.get("pinned_models", body.get("pinned")))
                ep.pinned_models = json.dumps(pinned) if pinned else None
            db.commit()
            _invalidate_models_cache()
            hidden_count = len(json.loads(ep.hidden_models)) if ep.hidden_models else 0
            pinned_count = len(json.loads(ep.pinned_models)) if ep.pinned_models else 0
            return {"id": ep_id, "hidden_count": hidden_count, "pinned_count": pinned_count}
        finally:
            db.close()


    @router.patch("/model-endpoints/{ep_id}")
    async def toggle_model_endpoint(ep_id: str, request: Request):
        require_admin(request)
        # Optional JSON body for field-targeted updates. No body → toggle is_enabled (legacy behaviour).
        body: Dict[str, Any] = {}
        try:
            if int(request.headers.get("content-length") or 0) > 0:
                body = await request.json()
                if not isinstance(body, dict):
                    body = {}
        except Exception:
            body = {}
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            if not ep:
                raise HTTPException(404, "Endpoint not found")
            if body:
                if "supports_tools" in body:
                    v = body["supports_tools"]
                    ep.supports_tools = {True: True, False: False, 'true': True, 'false': False, 1: True, 0: False}.get(v)
                if "is_enabled" in body:
                    v_ie = body['is_enabled']
                    ep.is_enabled = v_ie.lower() in ('true', '1', 'yes') if isinstance(v_ie, str) else bool(v_ie)
                if "name" in body and isinstance(body["name"], str):
                    ep.name = body["name"].strip() or ep.name
                if "model_type" in body and isinstance(body["model_type"], str):
                    ep.model_type = body["model_type"].strip() or ep.model_type
                if "pinned_models" in body:
                    _pinned = _normalize_model_ids(body["pinned_models"])
                    ep.pinned_models = json.dumps(_pinned) if _pinned else None
                if "endpoint_kind" in body:
                    ep.endpoint_kind = _normalize_endpoint_kind(body.get("endpoint_kind"))
                if "model_refresh_mode" in body:
                    ep.model_refresh_mode = _normalize_refresh_mode(body.get("model_refresh_mode"), _endpoint_kind(ep))
                if "model_refresh_interval" in body:
                    interval = _parse_positive_int(body.get("model_refresh_interval"), minimum=30, maximum=86400)
                    ep.model_refresh_interval = interval
                if "model_refresh_timeout" in body:
                    timeout = _parse_positive_int(body.get("model_refresh_timeout"), minimum=1, maximum=60)
                    ep.model_refresh_timeout = timeout
                # Rotating an API key used to require DELETE+POST, which wiped
                # endpoint_url/model from every session referencing the old base
                # URL. Allow in-place updates so the admin can change the key
                # (or correct a typo'd base URL) without nuking session state.
                if "api_key" in body and isinstance(body["api_key"], str):
                    _new_key = body["api_key"].strip()
                    # Empty string means "clear it" (e.g. local Ollama no longer needs a key).
                    ep.api_key = _new_key or None
                if "base_url" in body and isinstance(body["base_url"], str):
                    _new_base = body["base_url"].strip().rstrip("/")
                    for _suffix in ("/models", "/chat/completions", "/completions", "/v1/messages"):
                        if _new_base.endswith(_suffix):
                            _new_base = _new_base[: -len(_suffix)].rstrip("/")
                    _new_base = _normalize_base(_new_base)
                    if _new_base:
                        ep.base_url = _new_base
            else:
                ep.is_enabled = not ep.is_enabled
            db.commit()
            _invalidate_models_cache()
            _local_probe_cache["data"] = None
            return {
                "id": ep.id,
                "is_enabled": ep.is_enabled,
                "supports_tools": ep.supports_tools,
                "name": ep.name,
                "model_type": ep.model_type,
                "base_url": ep.base_url,
                "pinned_models": _normalize_model_ids(getattr(ep, "pinned_models", None)),
                "endpoint_kind": getattr(ep, "endpoint_kind", None) or "auto",
                "model_refresh_mode": getattr(ep, "model_refresh_mode", None) or "auto",
                "model_refresh_interval": getattr(ep, "model_refresh_interval", None),
                "model_refresh_timeout": getattr(ep, "model_refresh_timeout", None),
            }
        finally:
            db.close()

    def _settings_using_endpoint(ep_id: str) -> list:
        """Return human-readable labels for settings that reference this endpoint."""
        return _endpoint_settings_using_endpoint(_load_settings(), ep_id, include_speech=True)

    def _clear_settings_for_endpoint(ep_id: str) -> list:
        """Clear all settings that reference this endpoint. Returns list of cleared labels."""
        settings = _load_settings()
        cleared = _clear_endpoint_settings_for_endpoint(settings, ep_id, include_speech=True)
        if cleared:
            _save_settings(settings)
        return cleared

    def _clear_user_prefs_for_endpoint(ep_id: str) -> int:
        """Clear per-user endpoint selections and fallback chains."""
        try:
            from routes.prefs_routes import _load as _load_prefs, _save as _save_prefs
            all_prefs = _load_prefs()
            cleared_users = _clear_user_pref_endpoint_refs(all_prefs, ep_id)
            if cleared_users:
                _save_prefs(all_prefs)
            return cleared_users
        except Exception as e:
            logger.warning("Failed to clear user prefs for endpoint %s: %s", ep_id, e)
            return 0

    def _session_uses_endpoint_url(session_url: str, base_url: str) -> bool:
        if not session_url or not base_url:
            return False
        sess = session_url.rstrip("/")
        base = _normalize_base(base_url).rstrip("/")
        variants = {
            base,
            base + "/chat/completions",
            build_chat_url(base).rstrip("/"),
        }
        return sess in variants or sess.startswith(base + "/")

    def _clear_sessions_for_endpoint(db, base_url: str) -> int:
        """Drop stored auth for sessions using an endpoint being deleted.

        Keep the session's endpoint URL and model intact. If the admin is
        replacing an endpoint with the same URL, clearing those fields leaves
        the UI looking selected while chat requests arrive with an empty model.
        The chat-time orphan guard still clears truly dead endpoints when no
        matching enabled endpoint exists.
        """
        cleared = 0
        rows = db.query(DbSession).filter(DbSession.endpoint_url.isnot(None)).all()
        for row in rows:
            if _session_uses_endpoint_url(row.endpoint_url or "", base_url):
                row.headers = {}
                row.updated_at = datetime.utcnow()
                cleared += 1
        return cleared

    def _clear_loaded_sessions_for_endpoint(base_url: str) -> int:
        try:
            from src.ai_interaction import get_session_manager
            manager = get_session_manager()
        except Exception:
            manager = None
        if not manager:
            return 0
        cleared = 0
        try:
            for sess in list(getattr(manager, "sessions", {}).values()):
                if _session_uses_endpoint_url(getattr(sess, "endpoint_url", "") or "", base_url):
                    sess.headers = {}
                    cleared += 1
        except Exception:
            return cleared
        return cleared


    @router.get("/model-endpoints/{ep_id}/dependents")
    def get_endpoint_dependents(ep_id: str, request: Request):
        """Check which settings depend on this endpoint."""
        require_admin(request)
        return {"dependents": _settings_using_endpoint(ep_id)}


    @router.delete("/model-endpoints/{ep_id}")
    def delete_model_endpoint(ep_id: str, request: Request):
        require_admin(request)
        db = SessionLocal()
        try:
            ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
            if not ep:
                raise HTTPException(404, "Endpoint not found")
            # Clean up any settings that reference this endpoint
            cleared = _clear_settings_for_endpoint(ep_id)
            cleared_user_preferences = _clear_user_prefs_for_endpoint(ep_id)
            cleared_sessions = _clear_sessions_for_endpoint(db, ep.base_url)
            cleared_loaded_sessions = _clear_loaded_sessions_for_endpoint(ep.base_url)
            auth_id = getattr(ep, "provider_auth_id", None)
            db.delete(ep)
            cleared_provider_auth = _delete_orphaned_provider_auth(db, auth_id, exclude_ep_id=ep_id)
            db.commit()
            _invalidate_models_cache()
            _local_probe_cache["data"] = None
            return {
                "deleted": True,
                "cleared_settings": cleared,
                "cleared_user_preferences": cleared_user_preferences,
                "cleared_sessions": cleared_sessions,
                "cleared_loaded_sessions": cleared_loaded_sessions,
                "cleared_provider_auth": cleared_provider_auth,
            }
        finally:
            db.close()

    # ── Tool management ──



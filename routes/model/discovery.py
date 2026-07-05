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

def setup_discovery_routes(router: APIRouter, model_discovery):
    @router.get("/model-endpoints/probe-local")
    async def probe_local_endpoints(request: Request):
        """Fast parallel reachability check for LOCAL endpoints only.
        Cloud endpoints (api.openai.com, api.anthropic.com, etc.) are
        assumed up. Local endpoints get a 1.5s cheap reachability probe so the UI
        can dim stale entries pointing at dead vLLM servers. Returns
        {ep_id: {alive, latency_ms, error}}."""
        require_admin(request)
        now = _time.time()
        if (_local_probe_cache["data"] is not None and
                (now - _local_probe_cache["time"]) < _LOCAL_PROBE_TTL):
            return _local_probe_cache["data"]

        db = SessionLocal()
        try:
            endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
            local_eps = []
            for ep in endpoints:
                base = _normalize_base(ep.base_url)
                kind = _effective_endpoint_kind(ep, base)
                if _classify_endpoint(base, kind) == "local":
                    local_eps.append((ep.id, base, ep.api_key))
        finally:
            db.close()

        grouped: Dict[str, Dict[str, Any]] = {}
        for ep_id, base, api_key in local_eps:
            key = _refresh_key(base, api_key)
            grouped.setdefault(key, {"base": base, "api_key": api_key, "endpoint_ids": []})["endpoint_ids"].append(ep_id)

        async def _probe_one(data: Dict[str, Any]) -> Dict[str, Any]:
            t0 = _time.time()
            try:
                import asyncio as _asyncio
                # Bumped 1.5s → 3.5s. The previous 1.5s budget was clipping
                # local vLLM endpoints on Tailscale links where the model
                # server is still loading (Qwen3.5-122B takes 2–3 min to
                # warm); /v1/models can take 500–2500 ms on a busy box,
                # which pushed _ping_endpoint's full path-discovery sweep
                # past the cap and marked the row offline despite the
                # user actively chatting with it.
                ping = await _asyncio.to_thread(_ping_endpoint, data["base"], data.get("api_key"), 3.5)
                lat = round((_time.time() - t0) * 1000)
                return {
                    "alive": bool(ping.get("reachable")),
                    "latency_ms": lat,
                    "status_code": ping.get("status_code"),
                    "error": ping.get("error"),
                }
            except Exception as e:
                return {"alive": False, "latency_ms": None, "status_code": None, "error": str(e)[:120]}

        import asyncio as _asyncio
        results_list = await _asyncio.gather(
            *[_probe_one(data) for data in grouped.values()],
            return_exceptions=False,
        )
        results: Dict[str, Any] = {}
        for data, r in zip(grouped.values(), results_list):
            for eid in data["endpoint_ids"]:
                results[eid] = r

        _local_probe_cache["data"] = results
        _local_probe_cache["time"] = now
        return results


    @router.get("/ping")
    def ping_endpoints(request: Request):
        """Probe all enabled endpoints and return status + latency."""
        require_admin(request)
        db = SessionLocal()
        try:
            endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
        finally:
            db.close()

        results = []
        for ep in endpoints:
            base = _normalize_base(ep.base_url)
            provider = _safe_detect_provider(base)
            kind = _effective_endpoint_kind(ep, base)
            cached_count = len(_cached_model_ids(ep))
            entry = {
                "id": ep.id,
                "name": ep.name,
                "base_url": base,
                "provider": provider,
                "category": _classify_endpoint(base, kind),
                "endpoint_kind": kind,
            }
            try:
                t0 = _time.time()
                ping = _ping_endpoint(base, ep.api_key, timeout=1.5)
                entry["latency_ms"] = round((_time.time() - t0) * 1000)
                entry["status"] = "online" if ping.get("reachable") or cached_count else "offline"
                entry["error"] = ping.get("error")
                entry["model_count"] = cached_count or (len(ANTHROPIC_MODELS) if provider == "anthropic" else 0)
            except Exception as e:
                entry["latency_ms"] = None
                entry["status"] = "online" if cached_count else "offline"
                entry["error"] = str(e)
                entry["model_count"] = cached_count
            results.append(entry)

        return {"endpoints": results}


    @router.post("/probe-selected")
    def probe_selected(request: Request, request_body: dict = Body(...)):
        """Probe specific models for compare pre-check. Body: {models: [{endpoint_id, model}]}."""
        require_admin(request)
        models_to_probe = request_body.get("models", [])
        if not models_to_probe:
            return {"results": []}

        db = SessionLocal()
        try:
            endpoints_cache = {}
            results = []
            for item in models_to_probe:
                ep_id = item.get("endpoint_id", "")
                model_id = item.get("model", "")
                if not model_id:
                    results.append({"model": model_id, "status": "fail", "error": "No model specified"})
                    continue

                # Cache endpoint lookups
                if ep_id and ep_id not in endpoints_cache:
                    ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
                    if ep:
                        endpoints_cache[ep_id] = {"base_url": ep.base_url, "api_key": ep.api_key}
                ep_data = endpoints_cache.get(ep_id)
                if not ep_data:
                    # Try to find by base_url from the model's endpoint field
                    endpoint_url = item.get("endpoint", "")
                    if endpoint_url:
                        ep_data = {"base_url": endpoint_url, "api_key": item.get("api_key", "")}
                    else:
                        results.append({"model": model_id, "status": "fail", "error": "Endpoint not found"})
                        continue

                base = _normalize_base(ep_data["base_url"])
                _with_tools = item.get("with_tools", False)
                result = _probe_single_model(base, ep_data.get("api_key"), model_id, timeout=8, with_tools=_with_tools)
                result["model"] = model_id
                result["endpoint_id"] = ep_id
                results.append(result)

            return {"results": results}
        finally:
            db.close()


    @router.get("/probe")
    def probe_models(request: Request, endpoint_id: Optional[str] = Query(None)):
        """Probe individual models with a tiny completion request. Streams SSE results."""
        require_admin(request)
        db = SessionLocal()
        try:
            q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
            if endpoint_id:
                q = q.filter(ModelEndpoint.id == endpoint_id)
            endpoints = q.all()
            # Detach from session
            ep_data = []
            for ep in endpoints:
                ep_data.append({
                    "id": ep.id,
                    "name": ep.name,
                    "base_url": ep.base_url,
                    "api_key": ep.api_key,
                })
        finally:
            db.close()

        if not ep_data:
            def _empty():
                yield f"data: {json.dumps({'type': 'probe_done', 'total': 0, 'ok': 0})}\n\n"
            return StreamingResponse(_empty(), media_type="text/event-stream")

        def _stream():
            total = 0
            ok_count = 0
            for ep in ep_data:
                base = _normalize_base(ep["base_url"])
                all_models = _probe_endpoint(base, ep.get("api_key"))
                # Update cached_models in DB
                if all_models:
                    db2 = SessionLocal()
                    try:
                        ep_obj = db2.query(ModelEndpoint).filter(ModelEndpoint.id == ep["id"]).first()
                        if ep_obj:
                            ep_obj.cached_models = json.dumps(all_models)
                            db2.commit()
                    finally:
                        db2.close()
                if not all_models:
                    yield f"data: {json.dumps({'type': 'probe_start', 'endpoint': ep['name'], 'model_count': 0, 'error': 'No models found or endpoint offline'})}\n\n"
                    continue

                models = [m for m in all_models if _is_chat_model(m)]
                skipped = len(all_models) - len(models)
                yield f"data: {json.dumps({'type': 'probe_start', 'endpoint': ep['name'], 'model_count': len(models), 'skipped': skipped})}\n\n"

                for model_id in models:
                    total += 1
                    result = _probe_single_model(base, ep.get("api_key"), model_id, timeout=8)
                    result["type"] = "probe_result"
                    result["endpoint"] = ep["name"]
                    result["model"] = model_id
                    if result["status"] == "ok":
                        ok_count += 1
                    yield f"data: {json.dumps(result)}\n\n"

            yield f"data: {json.dumps({'type': 'probe_done', 'total': total, 'ok': ok_count})}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # /api/providers runs a full host port-scan (discover_models) which can take
    # seconds when a configured LLM host is unreachable. It's fetched on every
    # page load, so cache it briefly like _models_cache to keep page load snappy.
    _providers_cache = {"data": None, "time": 0}
    _PROVIDERS_CACHE_TTL = 30  # seconds


    @router.get("/providers")
    def providers(request: Request, refresh: bool = False):
        """Get all available providers (cached for 30s)."""
        require_admin(request)
        now = _time.time()
        if not refresh and _providers_cache["data"] is not None and (now - _providers_cache["time"]) < _PROVIDERS_CACHE_TTL:
            return _providers_cache["data"]
        result = model_discovery.get_providers()
        _providers_cache["data"] = result
        _providers_cache["time"] = now
        return result


    @router.get("/discover")
    def discover_local(request: Request):
        """Scan local network for model servers on common ports."""
        require_admin(request)
        return model_discovery.discover_models()

    # ---- Admin: model endpoints CRUD ----



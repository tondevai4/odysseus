from typing import Dict, Any, List, Optional
import time as _time
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.database import SessionLocal, ModelEndpoint
from .shared import *

logger = logging.getLogger(__name__)


# ---- Model list cache ----
import time as _time
# Per-user cache: { owner_key: {"data": ..., "time": ...} }. owner_key is
# the username (or "" for the unconfigured / single-user case). Without
# this every user shared the same cached result and the picker showed
# whichever admin's endpoint list happened to populate it first.
_models_cache: dict = {}
_MODELS_CACHE_TTL = 30  # seconds

def _invalidate_models_cache() -> None:
    """Clear the per-user /api/models cache. Call after any change that
    affects the visible endpoint list (CRUD on ModelEndpoint, prefs
    flip)."""
    _models_cache.clear()

# Track model-list refreshes by URL+key. This prevents repeated picker/API
# opens from starting duplicate /models probes, and gives slow/offline
# providers a cooldown after failures.
_refresh_state: Dict[str, Dict[str, Any]] = {}
_refresh_inflight = {"v": False}  # coarse single-flight guard
_REFRESH_FAILURE_BASE = 300.0
_REFRESH_FAILURE_MAX = 3600.0

def _refresh_key(base: str, api_key: Optional[str]) -> str:
    return f"{base.rstrip('/')}\x00{api_key or ''}"

def _ts(value: Any) -> float:
    try:
        return float(value.timestamp()) if value else 0.0
    except Exception:
        return 0.0

def _failure_delay(fails: int) -> float:
    if fails <= 0:
        return 0.0
    return min(_REFRESH_FAILURE_BASE * (2 ** max(0, fails - 1)), _REFRESH_FAILURE_MAX)

def _should_refresh_endpoint(ep: Any, now: float, force: bool = False) -> tuple[bool, Dict[str, Any]]:
    base = _normalize_base(getattr(ep, "base_url", "") or "")
    kind = _effective_endpoint_kind(ep, base)
    category = _classify_endpoint(base, kind)
    mode = _endpoint_refresh_mode(ep, kind)
    cached = _cached_model_ids(ep)
    key = _refresh_key(base, getattr(ep, "api_key", None))
    state = _refresh_state.get(key, {})

    info = {
        "id": getattr(ep, "id", ""),
        "base": base,
        "api_key": getattr(ep, "api_key", None),
        "kind": kind,
        "category": category,
        "mode": mode,
        "key": key,
        "timeout": _endpoint_refresh_timeout(ep, category),
    }
    if not base:
        return False, info
    if state.get("inflight"):
        return False, info
    if mode in ("manual", "disabled") and not force:
        return False, info
    fails = int(state.get("fail_count") or 0)
    if fails and not force:
        last_failure = float(state.get("last_failure") or 0.0)
        if now - last_failure < _failure_delay(fails):
            return False, info
    if cached and not force:
        interval = _endpoint_refresh_interval(ep, category)
        last_good = float(state.get("last_success") or 0.0) or _ts(getattr(ep, "updated_at", None)) or _ts(getattr(ep, "created_at", None))
        if last_good and now - last_good < interval:
            return False, info
    return True, info

def _refresh_caches_bg(force: bool = False):
    """Background thread: safely refresh model caches with per-base single-flight.

    The public /api/models path stays cached-first. This refresh never clears
    a non-empty cached model list on timeout/failure, and proxy/manual
    endpoints are skipped unless explicitly forced."""
    import threading
    if _refresh_inflight["v"]:
        return  # already running
    _refresh_inflight["v"] = True

    def _do():
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            db = SessionLocal()
            changed = False
            try:
                endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
                now = _time.time()
                groups: Dict[str, Dict[str, Any]] = {}
                for ep in endpoints:
                    ok, info = _should_refresh_endpoint(ep, now, force=force)
                    if not ok:
                        continue
                    groups.setdefault(info["key"], {
                        "base": info["base"],
                        "api_key": info["api_key"],
                        "timeout": info["timeout"],
                        "endpoint_ids": [],
                    })["endpoint_ids"].append(info["id"])

                for key in groups:
                    st = _refresh_state.setdefault(key, {})
                    st["inflight"] = True
                    st["last_attempt"] = now

                def _probe_one(key: str, data: Dict[str, Any]):
                    try:
                        ids = _probe_endpoint(data["base"], data.get("api_key"), timeout=data.get("timeout") or 2)
                        return key, data["endpoint_ids"], ids, None
                    except Exception as e:
                        return key, data["endpoint_ids"], None, e

                if groups:
                    with ThreadPoolExecutor(max_workers=min(4, len(groups))) as pool:
                        futures = [pool.submit(_probe_one, key, data) for key, data in groups.items()]
                        for fut in as_completed(futures):
                            key, endpoint_ids, ids, err = fut.result()
                            st = _refresh_state.setdefault(key, {})
                            if ids:
                                for ep_id in endpoint_ids:
                                    ep_obj = db.query(ModelEndpoint).filter(ModelEndpoint.id == ep_id).first()
                                    if ep_obj:
                                        ep_obj.cached_models = json.dumps(ids)
                                        changed = True
                                st["last_success"] = _time.time()
                                st["fail_count"] = 0
                                st.pop("last_failure", None)
                            else:
                                st["last_failure"] = _time.time()
                                st["fail_count"] = int(st.get("fail_count") or 0) + 1
                            st["inflight"] = False
                    db.commit()
            finally:
                db.close()
            if changed:
                _invalidate_models_cache()
        except Exception as e:
            logger.warning('Background endpoint refresh failed: %s', e)
        finally:
            for st in _refresh_state.values():
                st["inflight"] = False
            _refresh_inflight["v"] = False
    threading.Thread(target=_do, daemon=True).start()

def _fetch_models(owner: str = "", is_admin: bool = False):
    """Return model list from cached data (instant). Background refresh keeps caches fresh.

    SECURITY: filters endpoints by `owner` — without this the picker
    leaked every admin-added endpoint (and the model list behind each
    one) to every authenticated user. NULL-owner rows are treated as
    legacy/shared so existing configs still appear after migration.

    Admins see EVERY endpoint (they manage the global pool, and the
    scoped filter was making the picker disappear for them).
    """
    items = []

    db = SessionLocal()
    try:
        q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)
        if owner and not is_admin:
            # Regular users see: their own endpoints + null-owner
            # (legacy / shared). Admins see everything.
            q = owner_filter(q, ModelEndpoint, owner)
        endpoints = q.all()
    finally:
        db.close()

    for ep in endpoints:
        base = _normalize_base(ep.base_url)
        provider = _safe_detect_provider(base)
        # Merge cached + pinned models, then filter out hidden ones
        ep_model_type = getattr(ep, "model_type", None) or "llm"
        model_ids = _visible_models(
            _cached_model_ids(ep),
            ep.hidden_models,
            getattr(ep, "pinned_models", None),
        )
        # Build correct URL based on provider
        chat_url = build_chat_url(base)
        kind = _effective_endpoint_kind(ep, base)
        category = _classify_endpoint(base, kind)

        if model_ids:
            curated_key = _match_provider_curated(base, None)
            curated, extra = _curate_models(model_ids, curated_key)
            # Pinned models are admin-selected — they always belong in the
            # primary curated list, not buried in extras.
            pinned = _normalize_model_ids(getattr(ep, "pinned_models", None))
            for m in pinned:
                if m not in curated:
                    curated.append(m)
            extra = [m for m in extra if m not in pinned]
            items.append({
                "host": "custom",
                "port": 0,
                "url": chat_url,
                "models": curated,
                "models_display": [mid.split("/")[-1] for mid in curated],
                "models_extra": extra,
                "models_extra_display": [mid.split("/")[-1] for mid in extra],
                "endpoint_id": ep.id,
                "endpoint_name": ep.name,
                "category": category,
                "endpoint_kind": kind,
                "model_type": ep_model_type,
            })
        else:
            # Endpoint unreachable but still show it greyed out
            items.append({
                "host": "custom",
                "port": 0,
                "url": chat_url,
                "models": [],
                "models_display": [],
                "models_extra": [],
                "models_extra_display": [],
                "endpoint_id": ep.id,
                "endpoint_name": ep.name,
                "category": category,
                "endpoint_kind": kind,
                "model_type": ep_model_type,
                "offline": True,
            })

    return {"hosts": [], "items": items}


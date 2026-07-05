"""core/token_cache.py — In-memory API token cache.

Extracted from app.py. Provides a prefix-keyed cache for API bearer token
validation to avoid a bcrypt DB scan on every request.

The cache is dirty-flagged (via an asyncio.Event) whenever tokens are
created or revoked. auth_middleware rebuilds from the DB on the next
request that hits a dirty cache.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# prefix → list[(token_id, token_hash, owner, scopes)]
_token_cache: dict[str, list[tuple]] = {}
_token_cache_lock = asyncio.Lock()
# asyncio.Event replaces the old nonlocal_dict trick (app.state.__dict__
# mutation was fragile under concurrent access). Set = cache is dirty.
_dirty_event = asyncio.Event()
_dirty_event.set()  # dirty on startup → first request rebuilds


def get_cache() -> dict:
    """Return the live token cache dict."""
    return _token_cache


def get_lock() -> asyncio.Lock:
    """Return the cache rebuild lock."""
    return _token_cache_lock


def is_dirty() -> bool:
    """True when the cache needs rebuilding."""
    return _dirty_event.is_set()


def invalidate() -> None:
    """Mark the cache as dirty; the next auth check will rebuild from the DB."""
    _dirty_event.set()


def mark_clean() -> None:
    """Clear the dirty flag after a successful rebuild."""
    _dirty_event.clear()


def rebuild(auth_manager, SessionLocal, ApiToken, normalize_known_username) -> None:
    """Rebuild the prefix→[(id,hash,owner,scopes)] map from the DB.

    Called via asyncio.to_thread so the bcrypt/DB work stays off the event loop.
    """
    new_map: dict = defaultdict(list)
    db = SessionLocal()
    try:
        rows = db.query(ApiToken).filter(ApiToken.is_active == True).all()  # noqa: E712
        for r in rows:
            owner_key = normalize_known_username(
                auth_manager.users, getattr(r, "owner", None)
            )
            if not owner_key:
                logger.warning(
                    "Ignoring active API token '%s' for unknown auth user '%s'",
                    getattr(r, "id", ""),
                    getattr(r, "owner", None),
                )
                continue
            scopes = [
                s.strip()
                for s in (getattr(r, "scopes", "") or "chat").split(",")
                if s.strip()
            ]
            new_map[r.token_prefix].append((r.id, r.token_hash, owner_key, scopes))
    finally:
        db.close()
    _token_cache.clear()
    _token_cache.update(new_map)
    mark_clean()


def register_on_app(app: "FastAPI") -> None:
    """Attach the invalidate callback to app.state for use by api_token_routes."""
    app.state.invalidate_token_cache = invalidate
    app.state._token_cache = _token_cache
    # Backward-compat flag read by old code. Keep as a property-like alias.
    app.state._token_cache_dirty = True  # will be overwritten by is_dirty() checks

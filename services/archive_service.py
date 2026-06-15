"""Owner-scoped Archive dossiers stored separately from Vanta Brain."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from routes.prefs_routes import _load_for_user, _save_for_user

PREF_KEY = "archive-dossiers-v1"
CONFIDENCE = {"unknown", "weak", "plausible", "likely", "confirmed", "false"}


class ArchiveError(ValueError):
    pass


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string_list(value: Any, limit: int = 50, item_limit: int = 1000) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, item_limit) for item in value[:limit] if _text(item, item_limit)]


def _source_list(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    sources = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"), 2000)
        title = _text(item.get("title"), 300)
        quality = _text(item.get("quality"), 80)
        if url or title:
            sources.append({"url": url, "title": title, "quality": quality})
    return sources


def normalize_dossier(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    title = _text(value.get("title"), 200)
    if not title:
        return None
    confidence = _text(value.get("confidence"), 30).lower()
    if confidence not in CONFIDENCE:
        confidence = "unknown"
    created_at = _text(value.get("created_at"), 50) or _now()
    return {
        "id": _text(value.get("id"), 100) or str(uuid.uuid4()),
        "title": title,
        "topic": _text(value.get("topic"), 300),
        "summary": _text(value.get("summary"), 12000),
        "claims": _string_list(value.get("claims")),
        "timeline": _string_list(value.get("timeline")),
        "sources": _source_list(value.get("sources")),
        "evidence_for": _string_list(value.get("evidence_for")),
        "evidence_against": _string_list(value.get("evidence_against")),
        "confidence": confidence,
        "notes": _text(value.get("notes"), 6000),
        "created_at": created_at,
        "updated_at": _text(value.get("updated_at"), 50) or created_at,
    }


def load_dossiers(owner: Optional[str]) -> Dict[str, Any]:
    value = (_load_for_user(owner) or {}).get(PREF_KEY)
    if not isinstance(value, dict) or value.get("version") != 1:
        return {"version": 1, "dossiers": []}
    rows = value.get("dossiers")
    dossiers = []
    if isinstance(rows, list):
        dossiers = [item for item in (normalize_dossier(row) for row in rows) if item]
    dossiers.sort(key=lambda row: row["updated_at"], reverse=True)
    return {"version": 1, "dossiers": dossiers}


def _save(owner: Optional[str], state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    prefs[PREF_KEY] = state
    _save_for_user(owner, prefs)
    return state


def add_dossier(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    dossier = normalize_dossier({
        **payload,
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
    })
    if not dossier:
        raise ArchiveError("A dossier title is required.")
    state = load_dossiers(owner)
    if any(row["title"].casefold() == dossier["title"].casefold() for row in state["dossiers"]):
        raise ArchiveError("An Archive dossier with that title already exists.")
    state["dossiers"].insert(0, dossier)
    _save(owner, state)
    return dossier


def find_dossier(owner: Optional[str], identifier: str) -> Dict[str, Any]:
    needle = _text(identifier, 200).casefold()
    for dossier in load_dossiers(owner)["dossiers"]:
        if dossier["id"].casefold() == needle or dossier["title"].casefold() == needle:
            return dossier
    matches = [
        row for row in load_dossiers(owner)["dossiers"]
        if needle and needle in row["title"].casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    raise ArchiveError("Archive dossier not found.")


def update_dossier(
    owner: Optional[str],
    identifier: str,
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    state = load_dossiers(owner)
    current = find_dossier(owner, identifier)
    allowed = {
        "title", "topic", "summary", "claims", "timeline", "sources",
        "evidence_for", "evidence_against", "confidence", "notes",
    }
    updated = normalize_dossier({
        **current,
        **{key: value for key, value in changes.items() if key in allowed},
        "updated_at": _now(),
    })
    if not updated:
        raise ArchiveError("A dossier title is required.")
    state["dossiers"] = [
        updated if row["id"] == current["id"] else row for row in state["dossiers"]
    ]
    _save(owner, state)
    return updated


def append_claim(owner: Optional[str], identifier: str, claim: str) -> Dict[str, Any]:
    dossier = find_dossier(owner, identifier)
    claim_text = _text(claim, 1000)
    if not claim_text:
        raise ArchiveError("Claim text is required.")
    return update_dossier(owner, dossier["id"], {
        "claims": [*dossier["claims"], claim_text],
    })

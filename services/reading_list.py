"""Owner-scoped reading list stored in versioned user preferences."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import Document, SessionLocal
from routes.document_helpers import _verify_doc_owner
from routes.prefs_routes import _load_for_user, _save_for_user

PREF_KEY = "reading-list-v1"
STATUSES = {"want_to_read", "reading", "finished", "paused"}
PRIORITIES = {"low", "normal", "high"}
CATEGORIES = {
    "body", "money", "discipline", "work", "fatherhood", "spiritual",
    "reference", "other",
}


class ReadingListError(ValueError):
    """A safe validation error suitable for API/tool responses."""


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_item(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    title = _text(value.get("title"), 200)
    if not title:
        return None
    status = _text(value.get("status"), 30)
    priority = _text(value.get("priority"), 20)
    category = _text(value.get("category"), 30)
    created_at = _text(value.get("created_at"), 50) or _now()
    return {
        "id": _text(value.get("id"), 100) or str(uuid.uuid4()),
        "title": title,
        "author": _text(value.get("author"), 160),
        "category": category if category in CATEGORIES else "other",
        "status": status if status in STATUSES else "want_to_read",
        "priority": priority if priority in PRIORITIES else "normal",
        "progress": _text(value.get("progress"), 160),
        "notes": _text(value.get("notes"), 3000),
        "document_id": _text(value.get("document_id"), 100),
        "created_at": created_at,
        "updated_at": _text(value.get("updated_at"), 50) or created_at,
    }


def load_reading_list(owner: Optional[str]) -> Dict[str, Any]:
    value = (_load_for_user(owner) or {}).get(PREF_KEY)
    if not isinstance(value, dict) or value.get("version") != 1:
        return {"version": 1, "items": []}
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return {"version": 1, "items": []}
    return {
        "version": 1,
        "items": [
            item for item in (_normalize_item(row) for row in raw_items)
            if item is not None
        ],
    }


def save_reading_list(owner: Optional[str], state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    prefs[PREF_KEY] = state
    _save_for_user(owner, prefs)
    return state


def _document_for_owner(document_id: str, owner: Optional[str]) -> Optional[Document]:
    if not document_id:
        return None
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise ReadingListError("Library document not found.")
        try:
            _verify_doc_owner(db, document, owner)
        except Exception as exc:
            raise ReadingListError("Library document not found.") from exc
        if not document.is_active or bool(getattr(document, "archived", False)):
            raise ReadingListError("Library document is not active.")
        db.expunge(document)
        return document
    finally:
        db.close()


def _with_document(item: Dict[str, str], owner: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(item)
    document_id = item.get("document_id", "")
    if not document_id:
        result["document"] = None
        return result
    try:
        document = _document_for_owner(document_id, owner)
    except ReadingListError:
        result["document"] = {"id": document_id, "available": False}
        return result
    from src.pdf_form_doc import find_source_upload_id

    result["document"] = {
        "id": document.id,
        "title": document.title,
        "language": document.language,
        "available": True,
        "is_pdf": bool(find_source_upload_id(document.current_content or "")),
    }
    return result


def list_reading_items(owner: Optional[str]) -> List[Dict[str, Any]]:
    items = load_reading_list(owner)["items"]
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return [_with_document(item, owner) for item in items]


def add_reading_item(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    title = _text(payload.get("title"), 200)
    if not title:
        raise ReadingListError("Title is required.")
    state = load_reading_list(owner)
    if any(item["title"].casefold() == title.casefold() for item in state["items"]):
        raise ReadingListError("That title is already on your reading list.")
    document_id = _text(payload.get("document_id"), 100)
    document = _document_for_owner(document_id, owner) if document_id else None
    now = _now()
    item = _normalize_item({
        **payload,
        "id": str(uuid.uuid4()),
        "title": title,
        "author": _text(payload.get("author"), 160),
        "document_id": document.id if document else "",
        "created_at": now,
        "updated_at": now,
    })
    if item is None:
        raise ReadingListError("Title is required.")
    state["items"].append(item)
    save_reading_list(owner, state)
    return _with_document(item, owner)


def update_reading_item(
    owner: Optional[str],
    identifier: str,
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    state = load_reading_list(owner)
    needle = _text(identifier, 200).casefold()
    item = next(
        (
            row for row in state["items"]
            if row["id"].casefold() == needle or row["title"].casefold() == needle
        ),
        None,
    )
    if item is None:
        raise ReadingListError("Reading item not found.")

    allowed = {
        "title", "author", "category", "status", "priority", "progress",
        "notes", "document_id",
    }
    merged = {**item, **{key: value for key, value in changes.items() if key in allowed}}
    if "document_id" in changes:
        document_id = _text(changes.get("document_id"), 100)
        merged["document_id"] = (
            _document_for_owner(document_id, owner).id if document_id else ""
        )
    normalized = _normalize_item({**merged, "updated_at": _now()})
    if normalized is None:
        raise ReadingListError("Title is required.")
    if any(
        row["id"] != item["id"]
        and row["title"].casefold() == normalized["title"].casefold()
        for row in state["items"]
    ):
        raise ReadingListError("That title is already on your reading list.")
    state["items"] = [
        normalized if row["id"] == item["id"] else row for row in state["items"]
    ]
    save_reading_list(owner, state)
    return _with_document(normalized, owner)


async def manage_reading_list_tool(content: str, owner: Optional[str]) -> Dict[str, Any]:
    try:
        args = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {"error": "Invalid reading-list request.", "exit_code": 1}
    if not isinstance(args, dict):
        return {"error": "Invalid reading-list request.", "exit_code": 1}
    action = _text(args.get("action"), 30)
    try:
        if action == "list":
            items = list_reading_items(owner)
            return {"items": items, "count": len(items), "exit_code": 0}
        if action == "add":
            item = add_reading_item(owner, args)
            return {
                "item": item,
                "output": f'Added "{item["title"]}" to your reading list.',
                "exit_code": 0,
            }
        if action == "update":
            identifier = _text(args.get("id") or args.get("title"), 200)
            if not identifier:
                raise ReadingListError("A title or id is required.")
            item = update_reading_item(owner, identifier, args)
            return {
                "item": item,
                "output": f'Updated "{item["title"]}" on your reading list.',
                "exit_code": 0,
            }
        if action in {"delete", "remove"}:
            return {
                "error": (
                    "Reading-list deletion is not available from chat. "
                    "Open Reading List to manage it manually."
                ),
                "exit_code": 1,
            }
        return {"error": "Use list, add, or update.", "exit_code": 1}
    except ReadingListError as exc:
        return {"error": str(exc), "exit_code": 1}

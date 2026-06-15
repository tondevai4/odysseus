"""Authenticated reading-list routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.reading_list import (
    ReadingListError,
    add_reading_item,
    list_reading_items,
    update_reading_item,
)
from src.auth_helpers import get_current_user


class ReadingItemBody(BaseModel):
    title: str
    author: str = ""
    category: str = "other"
    status: str = "want_to_read"
    priority: str = "normal"
    progress: str = ""
    notes: str = ""
    document_id: str = ""


class ReadingItemPatch(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    progress: Optional[str] = None
    notes: Optional[str] = None
    document_id: Optional[str] = None


def setup_reading_list_routes() -> APIRouter:
    router = APIRouter(prefix="/api/reading-list", tags=["reading-list"])

    @router.get("")
    async def get_reading_list(request: Request):
        owner = get_current_user(request)
        items = list_reading_items(owner)
        return {"version": 1, "items": items}

    @router.post("")
    async def create_reading_item(request: Request, body: ReadingItemBody):
        owner = get_current_user(request)
        try:
            return add_reading_item(owner, body.model_dump())
        except ReadingListError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/{item_id}")
    async def edit_reading_item(
        request: Request,
        item_id: str,
        body: ReadingItemPatch,
    ):
        owner = get_current_user(request)
        changes: Dict[str, Any] = body.model_dump(exclude_none=True)
        try:
            return update_reading_item(owner, item_id, changes)
        except ReadingListError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router

"""Authenticated, read-only Vanta Brain diagnostics."""

from typing import Any, Dict

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.auth_helpers import require_user


class BrainPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


def setup_brain_routes(brain_service) -> APIRouter:
    router = APIRouter(prefix="/api/brain", tags=["brain"])

    @router.get("/health")
    async def brain_health(request: Request) -> Dict[str, Any]:
        owner = require_user(request) or None
        return brain_service.health(owner)

    @router.post("/preview")
    async def brain_preview(request: Request, body: BrainPreviewRequest) -> Dict[str, Any]:
        owner = require_user(request) or None
        result = brain_service.retrieve(body.query.strip(), owner)
        return {
            "query": body.query.strip(),
            "sources": result.public_sources(),
            "errors": result.errors,
            "limits": {"max_snippets": 8, "max_characters": 6000},
        }

    return router

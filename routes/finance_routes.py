"""Authenticated, read-only routes for manual statement analysis."""

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.finance_statement_analyzer import CATEGORIES, EXTRACTION_FAILURE_MESSAGE
from src.auth_helpers import require_user


class StatementPreviewRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)


class StatementAnalysisRequest(StatementPreviewRequest):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    category: Optional[str] = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=250)


def _load(analyzer, request: Request, document_id: str):
    owner = require_user(request)
    auth_manager = getattr(getattr(request.app, "state", None), "auth_manager", None)
    try:
        result = analyzer.analyze_document(
            document_id,
            owner,
            auth_manager=auth_manager,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "The statement could not be read.") from exc
    if not result.detected:
        raise HTTPException(400, "This document is not a supported Revolut GBP statement.")
    return result


def setup_finance_routes(analyzer) -> APIRouter:
    router = APIRouter(prefix="/api/finance", tags=["finance"])

    @router.post("/preview-statement")
    async def preview_statement(
        request: Request,
        body: StatementPreviewRequest,
    ) -> Dict[str, Any]:
        result = _load(analyzer, request, body.document_id)
        return {
            "document": {
                "id": result.document_id,
                "title": result.document_title,
                "type": "revolut_gbp_statement",
            },
            "summary": result.summary_dict(),
            "warnings": result.warnings,
            "extractable": bool(result.transactions),
            "message": EXTRACTION_FAILURE_MESSAGE if not result.transactions else None,
        }

    @router.post("/analyze-document")
    async def analyze_document(
        request: Request,
        body: StatementAnalysisRequest,
    ) -> Dict[str, Any]:
        result = _load(analyzer, request, body.document_id)
        if not result.transactions:
            return {
                "document": {"id": result.document_id, "title": result.document_title},
                "message": EXTRACTION_FAILURE_MESSAGE,
                "transactions": [],
                "warnings": result.warnings,
            }
        if body.category and body.category not in CATEGORIES:
            raise HTTPException(400, "Unknown transaction category")

        rows = result.completed
        if body.start_date:
            rows = [row for row in rows if row.date >= body.start_date.isoformat()]
        if body.end_date:
            rows = [row for row in rows if row.date <= body.end_date.isoformat()]
        if body.category:
            rows = [row for row in rows if row.category == body.category]

        category_totals = result.category_totals(rows)
        page = rows[body.offset:body.offset + body.limit]
        return {
            "document": {
                "id": result.document_id,
                "title": result.document_title,
                "type": "revolut_gbp_statement",
            },
            "statement_summary": result.summary_dict(),
            "analysis": {
                "matched_completed_transactions": len(rows),
                "external_spend_excluding_internal_savings": f"{result.external_spend(rows):.2f}",
                "category_totals": {
                    category: f"{amount:.2f}"
                    for category, amount in category_totals.items()
                },
                "filters": {
                    "start_date": body.start_date.isoformat() if body.start_date else None,
                    "end_date": body.end_date.isoformat() if body.end_date else None,
                    "category": body.category,
                },
            },
            "transactions": [
                row.public_dict(result.document_id)
                for row in page
            ],
            "pagination": {
                "offset": body.offset,
                "limit": body.limit,
                "returned": len(page),
                "total": len(rows),
            },
            "warnings": result.warnings,
        }

    return router

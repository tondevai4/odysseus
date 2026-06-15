"""Isolated Archive research chat and dossier routes."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from routes.chat_helpers import _enforce_chat_privileges
from routes.session_routes import _verify_session_owner
from services.archive_service import (
    ArchiveError,
    add_dossier,
    append_claim,
    find_dossier,
    load_dossiers,
    update_dossier,
)
from src.archive_prompt import ARCHIVE_SYSTEM_PROMPT
from src.auth_helpers import get_current_user
from src.llm_core import llm_call_async
from src.prompt_security import untrusted_context_message
from src.search import comprehensive_web_search


class ArchiveChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=30000)
    session: str
    history: List[Dict[str, str]] = Field(default_factory=list)
    use_web: bool = True
    incognito: bool = False


class DossierBody(BaseModel):
    title: str
    topic: str = ""
    summary: str = ""
    claims: list = Field(default_factory=list)
    timeline: list = Field(default_factory=list)
    sources: list = Field(default_factory=list)
    evidence_for: list = Field(default_factory=list)
    evidence_against: list = Field(default_factory=list)
    confidence: str = "unknown"
    notes: str = ""


class DossierPatch(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None
    summary: Optional[str] = None
    claims: Optional[list] = None
    timeline: Optional[list] = None
    sources: Optional[list] = None
    evidence_for: Optional[list] = None
    evidence_against: Optional[list] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None
    claim: Optional[str] = None


def _history_messages(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    messages = []
    for item in history[-12:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()[:12000]
        if content:
            messages.append({"role": item["role"], "content": content})
    return messages


def _save_command(message: str) -> bool:
    return bool(re.search(r"\bsave\s+(?:this|it)\s+as\s+(?:an?\s+)?archive\s+dossier\b", message, re.I))


def _dossier_action(message: str) -> tuple[str, str, str]:
    if re.search(r"\b(?:show|list)\s+(?:my\s+)?archive\s+dossiers\b", message, re.I):
        return "list", "", ""
    match = re.search(r"\bopen\s+(?:archive\s+)?dossier\s+(.+?)\s*$", message, re.I)
    if match:
        return "open", match.group(1).strip(" .\"'"), ""
    match = re.search(
        r"\badd\s+(?:this\s+)?claim\s+to\s+(?:the\s+)?dossier\s+(.+?)\s*:\s*(.+)$",
        message,
        re.I | re.S,
    )
    if match:
        return "claim", match.group(1).strip(" .\"'"), match.group(2).strip()
    if re.search(r"\b(?:delete|remove)\b.{0,80}\b(?:archive\s+)?dossier\b", message, re.I):
        return "delete", "", ""
    return "", "", ""


def setup_archive_routes(session_manager) -> APIRouter:
    router = APIRouter(prefix="/api/archive", tags=["archive"])

    @router.post("/chat")
    async def archive_chat(request: Request, body: ArchiveChatBody):
        _verify_session_owner(request, body.session, session_manager)
        try:
            sess = session_manager.get_session(body.session)
        except KeyError as exc:
            raise HTTPException(404, "Selected chat session was not found.") from exc
        if not getattr(sess, "model", "").strip():
            raise HTTPException(400, "Select a model in normal chat before opening The Archive.")
        _enforce_chat_privileges(request, sess)
        owner = get_current_user(request)

        dossier_action, dossier_title, dossier_claim = _dossier_action(body.message)
        if dossier_action:
            if body.incognito:
                return {
                    "answer": "Archive dossier actions are disabled in incognito/private mode.",
                    "sources": [],
                    "action": "blocked",
                }
            if dossier_action == "delete":
                return {
                    "answer": "Archive dossiers cannot be deleted from chat.",
                    "sources": [],
                    "action": "blocked",
                }
            try:
                if dossier_action == "list":
                    dossiers = load_dossiers(owner)["dossiers"]
                    answer = (
                        "\n".join(
                            f'- {row["title"]} [{row["confidence"]}]'
                            for row in dossiers
                        )
                        if dossiers else "No Archive dossiers are saved yet."
                    )
                    return {"answer": answer, "sources": [], "action": "dossier_list"}
                if dossier_action == "open":
                    dossier = find_dossier(owner, dossier_title)
                    return {
                        "answer": (
                            f'## {dossier["title"]}\n\n'
                            f'{dossier["summary"]}\n\n'
                            f'Confidence: {dossier["confidence"]}'
                        ),
                        "sources": dossier["sources"],
                        "action": "dossier_opened",
                        "dossier": dossier,
                    }
                dossier = append_claim(owner, dossier_title, dossier_claim)
                return {
                    "answer": f'Added the claim to "{dossier["title"]}".',
                    "sources": [],
                    "action": "dossier_updated",
                    "dossier": dossier,
                }
            except ArchiveError as exc:
                return {"answer": str(exc), "sources": [], "action": "none"}

        if _save_command(body.message):
            if body.incognito:
                return {
                    "answer": "Archive dossier actions are disabled in incognito/private mode.",
                    "sources": [],
                    "action": "blocked",
                }
            prior = _history_messages(body.history)
            latest_answer = next(
                (item["content"] for item in reversed(prior) if item["role"] == "assistant"),
                "",
            )
            latest_topic = next(
                (item["content"] for item in reversed(prior) if item["role"] == "user"),
                "Archive investigation",
            )
            if not latest_answer:
                return {
                    "answer": "There is no completed Archive investigation to save yet.",
                    "sources": [],
                    "action": "none",
                }
            title = re.sub(r"\s+", " ", latest_topic).strip(" .:")[:120] or "Archive investigation"
            try:
                dossier = add_dossier(owner, {
                    "title": title,
                    "topic": latest_topic[:300],
                    "summary": latest_answer,
                    "confidence": "unknown",
                })
            except ArchiveError as exc:
                return {"answer": str(exc), "sources": [], "action": "none"}
            return {
                "answer": f'Saved Archive dossier: "{dossier["title"]}".',
                "sources": [],
                "action": "dossier_saved",
                "dossier": dossier,
            }

        web_sources = []
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": ARCHIVE_SYSTEM_PROMPT},
            *_history_messages(body.history),
        ]
        search_status = "not_requested"
        if body.use_web:
            try:
                web_context, web_sources = await asyncio.to_thread(
                    comprehensive_web_search,
                    body.message,
                    return_sources=True,
                )
                search_status = "available" if web_sources else "unavailable"
                messages.append(untrusted_context_message(
                    "Archive web evidence",
                    web_context[:24000],
                ))
                if not web_sources:
                    messages.append({
                        "role": "system",
                        "content": "Live search returned no usable sources. Say search is unavailable for this request.",
                    })
            except Exception:
                search_status = "unavailable"
                messages.append({
                    "role": "system",
                    "content": "Live web search is unavailable for this request. Say so plainly.",
                })
        messages.append({"role": "user", "content": body.message})
        answer = await llm_call_async(
            sess.endpoint_url,
            sess.model,
            messages,
            headers=sess.headers,
            temperature=0.35,
            max_tokens=3000,
            prompt_type="archive",
            session_id=None,
        )
        return {
            "answer": answer,
            "sources": web_sources[:12],
            "search_status": search_status,
            "isolation": "clean-room",
        }

    @router.get("/dossiers")
    async def list_archive_dossiers(request: Request):
        return load_dossiers(get_current_user(request))

    @router.get("/dossiers/{identifier}")
    async def get_archive_dossier(request: Request, identifier: str):
        try:
            return find_dossier(get_current_user(request), identifier)
        except ArchiveError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/dossiers")
    async def create_archive_dossier(request: Request, body: DossierBody):
        try:
            return add_dossier(get_current_user(request), body.model_dump())
        except ArchiveError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/dossiers/{identifier}")
    async def edit_archive_dossier(request: Request, identifier: str, body: DossierPatch):
        values = body.model_dump(exclude_none=True)
        try:
            if "claim" in values:
                return append_claim(get_current_user(request), identifier, values["claim"])
            return update_dossier(get_current_user(request), identifier, values)
        except ArchiveError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router

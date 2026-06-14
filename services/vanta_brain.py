"""User-scoped, read-only retrieval for Vanta chat context."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.database import Document, Note, SessionLocal
from routes.prefs_routes import _load_for_user
from src.rag_singleton import get_rag_manager

logger = logging.getLogger(__name__)

MAX_SNIPPETS = 8
MAX_CONTEXT_CHARS = 6000
MAX_SNIPPET_CHARS = 900

_STOPWORDS = frozenset(
    "a an the is am are was were be been being have has had do does did "
    "i me my we us our you your he him his she her they them their it its "
    "and but or not so if then than in on at to for of by with from about "
    "what when where which who how why this that these those please tell "
    "show find know want need can could would should".split()
)


@dataclass
class BrainSnippet:
    source: str
    source_id: str
    label: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> Dict[str, Any]:
        value = {
            "source": self.source,
            "source_id": self.source_id,
            "label": self.label,
            "text": self.text,
            "score": round(float(self.score), 4),
        }
        if self.metadata:
            value["metadata"] = self.metadata
        return value


@dataclass
class BrainRetrieval:
    snippets: List[BrainSnippet] = field(default_factory=list)
    rag_sources: List[Dict[str, Any]] = field(default_factory=list)
    used_memories: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)

    def public_sources(self) -> List[Dict[str, Any]]:
        return [snippet.public_dict() for snippet in self.snippets]

    def context_text(self) -> str:
        blocks = []
        used = 0
        for snippet in self.snippets:
            separator = "\n\n---\n\n" if blocks else ""
            prefix = f"[{snippet.source.upper()}: {snippet.label}]\n"
            available = MAX_CONTEXT_CHARS - used - len(separator) - len(prefix)
            if available <= 0:
                break
            text = snippet.text[:available]
            blocks.append(separator + prefix + text)
            used += len(separator) + len(prefix) + len(text)
        return "".join(blocks)


def _tokens(value: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", (value or "").lower())
    return [word for word in words if len(word) >= 3 and word not in _STOPWORDS]


def _clean_text(value: Any, limit: int = MAX_SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _keyword_score(query: str, text: str) -> float:
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(_tokens(text))
    overlap = len(query_tokens & text_tokens)
    if not overlap:
        return 0.0
    score = overlap / len(query_tokens)
    query_phrase = " ".join(_tokens(query))
    if query_phrase and query_phrase in " ".join(_tokens(text)):
        score += 0.25
    return min(score, 1.0)


class VantaBrainService:
    """Collect small, labelled snippets without mutating source stores."""

    def __init__(self, memory_manager, personal_docs_manager, memory_vector=None):
        self.memory_manager = memory_manager
        self.personal_docs_manager = personal_docs_manager
        self.memory_vector = memory_vector

    def _resolve_rag(self):
        rag = get_rag_manager()
        if rag is not None and getattr(rag, "healthy", False):
            if getattr(self.personal_docs_manager, "rag_manager", None) is not rag:
                self.personal_docs_manager.rag_manager = rag
            return rag
        return None

    def _memory_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> tuple[List[BrainSnippet], List[Dict[str, Any]]]:
        try:
            entries = self.memory_manager.load(owner=owner)
        except Exception:
            logger.warning("Vanta Brain memory retrieval failed", exc_info=True)
            errors.append({"source": "memory", "detail": "Memory retrieval unavailable."})
            return [], []

        vector_scores: Dict[str, float] = {}
        if self.memory_vector and getattr(self.memory_vector, "healthy", False):
            try:
                for row in self.memory_vector.search(query, k=20):
                    memory_id = str(row.get("memory_id") or "")
                    if memory_id:
                        vector_scores[memory_id] = max(float(row.get("score") or 0), 0.0)
            except Exception:
                errors.append({"source": "memory_vector", "detail": "Semantic memory search degraded."})

        snippets: List[BrainSnippet] = []
        used: List[Dict[str, Any]] = []
        for entry in entries:
            text = _clean_text(entry.get("text"))
            if not text:
                continue
            pinned = bool(entry.get("pinned"))
            keyword = _keyword_score(query, text)
            vector = vector_scores.get(str(entry.get("id") or ""), 0.0)
            if not pinned and keyword <= 0 and vector < 0.2:
                continue
            score = 2.0 if pinned else (0.6 * vector) + (0.4 * keyword)
            category = str(entry.get("category") or "fact")
            snippets.append(BrainSnippet(
                source="memory",
                source_id=str(entry.get("id") or ""),
                label=f"{'Pinned ' if pinned else ''}Memory: {category}",
                text=text,
                score=score,
                metadata={"type": "pinned" if pinned else "recalled"},
            ))
            used.append({
                "text": text,
                "category": category,
                "type": "pinned" if pinned else "recalled",
            })
        return snippets, used

    def _note_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> List[BrainSnippet]:
        db = SessionLocal()
        try:
            rows = db.query(Note).filter(Note.archived == False)  # noqa: E712
            if owner is not None:
                rows = rows.filter(Note.owner == owner)
            candidates = []
            for note in rows.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(250).all():
                checklist = []
                if note.items:
                    try:
                        items = json.loads(note.items)
                        if isinstance(items, list):
                            checklist = [
                                str(item.get("text") or "").strip()
                                for item in items if isinstance(item, dict) and item.get("text")
                            ]
                    except (TypeError, json.JSONDecodeError):
                        pass
                combined = "\n".join(filter(None, [
                    note.title or "",
                    note.content or "",
                    "\n".join(checklist),
                ]))
                score = _keyword_score(query, combined)
                if score <= 0:
                    continue
                label = _clean_text(note.title or "Untitled note", 120)
                candidates.append(BrainSnippet(
                    source="note",
                    source_id=str(note.id),
                    label=label,
                    text=_clean_text(combined),
                    score=score + (0.08 if note.pinned else 0.0),
                ))
            return candidates
        except Exception:
            logger.warning("Vanta Brain note retrieval failed", exc_info=True)
            errors.append({"source": "notes", "detail": "Notes retrieval unavailable."})
            return []
        finally:
            db.close()

    def _document_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> List[BrainSnippet]:
        db = SessionLocal()
        try:
            rows = db.query(Document).filter(
                Document.is_active == True,  # noqa: E712
                (Document.archived == False) | (Document.archived.is_(None)),  # noqa: E712
            )
            if owner is None:
                rows = rows.filter(False)
            else:
                rows = rows.filter(Document.owner == owner)
            candidates = []
            for doc in rows.order_by(Document.updated_at.desc()).limit(250).all():
                combined = "\n".join(filter(None, [doc.title or "", doc.current_content or ""]))
                score = _keyword_score(query, combined)
                if score <= 0:
                    continue
                candidates.append(BrainSnippet(
                    source="document",
                    source_id=str(doc.id),
                    label=_clean_text(doc.title or "Untitled document", 120),
                    text=_clean_text(combined),
                    score=score,
                    metadata={"language": doc.language or "text"},
                ))
            return candidates
        except Exception:
            logger.warning("Vanta Brain document retrieval failed", exc_info=True)
            errors.append({"source": "documents", "detail": "Library retrieval unavailable."})
            return []
        finally:
            db.close()

    def _housing_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> List[BrainSnippet]:
        try:
            value = (_load_for_user(owner) or {}).get("housing-bids-v1")
            if not isinstance(value, dict) or value.get("version") != 1:
                return []
            entries = value.get("entries")
            if not isinstance(entries, list):
                return []
            candidates = []
            for entry in entries[:250]:
                if not isinstance(entry, dict):
                    continue
                property_area = _clean_text(entry.get("propertyArea"), 160)
                date_bidded = _clean_text(entry.get("dateBidded"), 20)
                if not property_area or not date_bidded:
                    continue
                combined = "\n".join(filter(None, [
                    property_area,
                    date_bidded,
                    entry.get("description"),
                    entry.get("status"),
                    entry.get("priorityBand"),
                    entry.get("notes"),
                    entry.get("outcome"),
                ]))
                score = _keyword_score(query, combined)
                if score <= 0:
                    continue
                candidates.append(BrainSnippet(
                    source="housing",
                    source_id=_clean_text(entry.get("id"), 100),
                    label=f"Housing Bid: {property_area}",
                    text=_clean_text(combined),
                    score=score,
                    metadata={"status": _clean_text(entry.get("status"), 40)},
                ))
            return candidates
        except Exception:
            logger.warning("Vanta Brain housing retrieval failed", exc_info=True)
            errors.append({"source": "housing", "detail": "Housing preferences unavailable."})
            return []

    def _rag_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> tuple[List[BrainSnippet], List[Dict[str, Any]]]:
        rag = self._resolve_rag()
        if rag is None:
            errors.append({"source": "rag", "detail": "Personal RAG is unavailable."})
            return [], []
        try:
            rows = rag.search(query, k=8, owner=owner)
            snippets = []
            legacy_sources = []
            for row in rows:
                similarity = float(row.get("similarity") or 0.0)
                if similarity < 0.2:
                    continue
                metadata = row.get("metadata") or {}
                filename = _clean_text(
                    metadata.get("filename") or os.path.basename(metadata.get("source") or "") or "Personal document",
                    160,
                )
                text = _clean_text(row.get("document"))
                if not text:
                    continue
                snippets.append(BrainSnippet(
                    source="rag",
                    source_id=str(row.get("id") or ""),
                    label=filename,
                    text=text,
                    score=similarity,
                    metadata={"embedding_lane": row.get("embedding_lane")},
                ))
                legacy_sources.append({
                    "filename": filename,
                    "snippet": text[:200],
                    "similarity": round(similarity, 3),
                })
            return snippets, legacy_sources
        except Exception:
            logger.warning("Vanta Brain RAG retrieval failed", exc_info=True)
            errors.append({"source": "rag", "detail": "Personal RAG search degraded."})
            return [], []

    def retrieve(
        self,
        query: str,
        owner: Optional[str],
        *,
        include_memory: bool = True,
        include_rag: bool = True,
    ) -> BrainRetrieval:
        result = BrainRetrieval()
        candidates: List[BrainSnippet] = []

        if include_memory:
            memory, result.used_memories = self._memory_candidates(query, owner, result.errors)
            candidates.extend(memory)
        candidates.extend(self._note_candidates(query, owner, result.errors))
        candidates.extend(self._document_candidates(query, owner, result.errors))
        candidates.extend(self._housing_candidates(query, owner, result.errors))
        if include_rag:
            rag, result.rag_sources = self._rag_candidates(query, owner, result.errors)
            candidates.extend(rag)

        candidates.sort(key=lambda item: (-item.score, item.source, item.label.lower()))
        selected = []
        used_chars = 0
        seen = set()
        for candidate in candidates:
            dedupe_key = (candidate.source, candidate.source_id, candidate.text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            separator_len = len("\n\n---\n\n") if selected else 0
            prefix_len = len(f"[{candidate.source.upper()}: {candidate.label}]\n")
            remaining = MAX_CONTEXT_CHARS - used_chars - separator_len - prefix_len
            if remaining <= 0 or len(selected) >= MAX_SNIPPETS:
                break
            candidate.text = candidate.text[:min(MAX_SNIPPET_CHARS, remaining)]
            if not candidate.text:
                continue
            selected.append(candidate)
            used_chars += separator_len + prefix_len + len(candidate.text)

        result.snippets = selected
        result.used_memories = [
            item for item in result.used_memories
            if any(
                snippet.source == "memory" and snippet.text == item.get("text")
                for snippet in selected
            )
        ]
        result.rag_sources = [
            item for item in result.rag_sources
            if any(
                snippet.source == "rag"
                and snippet.label == item.get("filename")
                and snippet.text.startswith(item.get("snippet", ""))
                for snippet in selected
            )
        ]
        return result

    def _owner_rag_inventory(self, owner: Optional[str]) -> Dict[str, Any]:
        rag = self._resolve_rag()
        if rag is None:
            return {
                "ready": False,
                "healthy": False,
                "chunk_count": 0,
                "embedding_lanes": [],
                "indexed_sources": set(),
                "detail": "Chroma/RAG is unavailable.",
            }
        try:
            stats = rag.get_stats()
            ids = set()
            sources = set()
            lane_counts: Dict[str, int] = {}
            for lane_name, collection in rag._active_collections():
                kwargs = {"include": ["metadatas"]}
                if owner:
                    kwargs["where"] = {"owner": owner}
                rows = collection.get(**kwargs)
                row_ids = rows.get("ids") or []
                lane_counts[lane_name] = len(row_ids)
                for doc_id, metadata in zip(row_ids, rows.get("metadatas") or []):
                    ids.add(doc_id)
                    if isinstance(metadata, dict) and metadata.get("source"):
                        sources.add(os.path.realpath(str(metadata["source"])))
            lanes = []
            for lane in stats.get("embedding_lanes") or []:
                if not isinstance(lane, dict):
                    continue
                lanes.append({
                    "name": _clean_text(lane.get("name"), 80),
                    "model": _clean_text(lane.get("model"), 120),
                    "dimension": lane.get("dimension"),
                    "count": lane_counts.get(str(lane.get("name") or ""), 0),
                    "healthy": bool(lane.get("healthy")),
                })
            return {
                "ready": True,
                "healthy": bool(getattr(rag, "healthy", False)),
                "chunk_count": len(ids),
                "embedding_lanes": lanes,
                "indexed_sources": sources,
                "detail": "Personal RAG ready.",
            }
        except Exception:
            logger.warning("Vanta Brain RAG health failed", exc_info=True)
            return {
                "ready": False,
                "healthy": False,
                "chunk_count": 0,
                "embedding_lanes": [],
                "indexed_sources": set(),
                "detail": "Chroma/RAG health check degraded.",
            }

    def health(self, owner: Optional[str]) -> Dict[str, Any]:
        errors = []
        db = SessionLocal()
        try:
            memory_count = len(self.memory_manager.load(owner=owner))
        except Exception:
            memory_count = 0
            errors.append({"source": "memory", "detail": "Memory count unavailable."})

        try:
            notes_q = db.query(Note)
            if owner is not None:
                notes_q = notes_q.filter(Note.owner == owner)
            notes_count = notes_q.filter(Note.archived == False).count()  # noqa: E712

            docs_q = db.query(Document).filter(
                Document.is_active == True,  # noqa: E712
                (Document.archived == False) | (Document.archived.is_(None)),  # noqa: E712
            )
            docs_q = docs_q.filter(Document.owner == owner) if owner is not None else docs_q.filter(False)
            document_count = docs_q.count()
        except Exception:
            notes_count = 0
            document_count = 0
            errors.append({"source": "database", "detail": "Notes or Library counts unavailable."})
        finally:
            db.close()

        try:
            housing = (_load_for_user(owner) or {}).get("housing-bids-v1")
            housing_entries = housing.get("entries") if isinstance(housing, dict) and housing.get("version") == 1 else []
            housing_count = len([row for row in housing_entries if isinstance(row, dict)])
        except Exception:
            housing_count = 0
            errors.append({"source": "housing", "detail": "Housing count unavailable."})

        rag = self._owner_rag_inventory(owner)
        indexed_sources = rag.pop("indexed_sources")
        listed_files = []
        for row in getattr(self.personal_docs_manager, "index", []) or []:
            path = row.get("path") if isinstance(row, dict) else None
            if not path:
                continue
            resolved = os.path.realpath(path)
            if owner:
                owner_segment = re.sub(r"[^A-Za-z0-9_.-]", "_", owner)[:80] or "local"
                if owner_segment not in resolved.split(os.sep):
                    continue
            listed_files.append((resolved, _clean_text(row.get("name") or os.path.basename(resolved), 160)))

        unindexed = sorted({name for path, name in listed_files if path not in indexed_sources})
        sources = {
            "memory": {"ready": not any(e["source"] == "memory" for e in errors), "count": memory_count},
            "notes": {"ready": not any(e["source"] == "database" for e in errors), "count": notes_count},
            "documents": {"ready": not any(e["source"] == "database" for e in errors), "count": document_count},
            "housing": {"ready": not any(e["source"] == "housing" for e in errors), "count": housing_count},
            "rag": {
                **rag,
                "listed_document_count": len(listed_files),
                "likely_unindexed_count": len(unindexed),
                "likely_unindexed": unindexed[:20],
            },
        }
        degraded = bool(errors) or not rag["ready"] or bool(unindexed)
        return {
            "overall": "degraded" if degraded else "ok",
            "sources": sources,
            "errors": errors,
        }

"""User-scoped, read-only retrieval for Vanta chat context."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
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


def _clean_multiline_text(value: Any, limit: int = MAX_SNIPPET_CHARS) -> str:
    lines = [
        re.sub(r"[ \t]+", " ", line).strip()
        for line in str(value or "").splitlines()
    ]
    text = "\n".join(line for line in lines if line)
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


def _first_value(entry: Dict[str, Any], *keys: str, limit: int) -> str:
    for key in keys:
        value = _clean_text(entry.get(key), limit)
        if value:
            return value
    return ""


def _housing_intent(query: str) -> bool:
    normalized = " ".join(re.findall(r"[a-z0-9]+", (query or "").lower()))
    tokens = set(normalized.split())
    domain_terms = {
        "housing", "bid", "bids", "bidding", "property", "properties",
        "flat", "flats", "council", "homechoice", "applied",
        "application", "applications",
    }
    if tokens & domain_terms:
        return True
    return any(phrase in normalized for phrase in (
        "home choice",
        "housing applications",
        "properties i applied",
        "property i applied",
        "what have i bid",
        "what have i made",
    ))


def _finance_intent(query: str) -> bool:
    preview, spend, money_in, savings, payment = _finance_intents(query)
    return preview or spend or money_in or savings or payment


def _finance_intents(query: str) -> tuple[bool, bool, bool, bool, bool]:
    normalized = " ".join(re.findall(r"[a-z0-9]+", (query or "").lower()))
    tokens = set(normalized.split())
    finance_context = bool(tokens & {"revolut", "statement", "bank", "finance"})
    preview_signal = bool(tokens & {
        "preview", "summary", "summarise", "summarize", "reconcile",
        "reconciles", "reconciled",
    }) or any(phrase in normalized for phrase in (
        "date range",
        "opening balance",
        "closing balance",
        "money out",
        "money in",
        "check my bank statement",
        "check my revolut",
    ))
    explicit_preview_field = any(phrase in normalized for phrase in (
        "date range",
        "opening balance",
        "closing balance",
        "money out",
        "money in",
    ))
    preview = preview_signal and (finance_context or explicit_preview_field)
    spend = bool(tokens & {
        "spend", "spending", "spent", "leaking", "leak", "category",
        "categories", "takeaway", "transport", "subscription", "subscriptions",
    }) or any(phrase in normalized for phrase in (
        "money leaking",
        "money leak",
        "takeaway transport subscriptions",
        "takeaway spending",
        "transport spending",
        "subscription spending",
    ))
    generic_statement = finance_context and any(phrase in normalized for phrase in (
        "bank statement",
        "revolut statement",
    ))
    money_in = bool(tokens & {"income", "incoming", "refund", "refunds"}) or any(
        phrase in normalized for phrase in (
            "money came in",
            "money come in",
            "money received",
            "payments received",
            "what came in",
        )
    )
    savings = (
        "savings" in tokens
        and bool(tokens & {"internal", "movement", "movements", "transfer", "transfers"})
    ) or any(phrase in normalized for phrase in (
        "internal savings",
        "savings movement",
        "savings transfer",
    ))
    payment = bool(tokens & {"pay", "payee", "payment"}) or any(
        phrase in normalized for phrase in (
            "move money",
            "send money",
            "transfer money",
            "pay someone",
            "make a payment",
        )
    )
    preview = preview or (
        generic_statement and not any((spend, money_in, savings, payment))
    )
    return preview, spend, money_in, savings, payment


def finance_payment_intent(query: str) -> bool:
    return _finance_intents(query)[4]


def _finance_categories(query: str) -> List[str]:
    normalized = (query or "").lower()
    requested = []
    aliases = {
        "takeaway_fast_food": ("takeaway", "fast food", "deliveroo", "uber eats"),
        "transport": ("transport", "taxi", "uber", "bolt", "bus", "train"),
        "subscriptions_apps": ("subscription", "subscriptions", "apps", "app spending"),
        "groceries": ("groceries", "grocery", "supermarket"),
        "alcohol_vapes": ("alcohol", "vape", "vapes"),
        "shopping_random": ("shopping",),
        "cash_withdrawal": ("cash", "withdrawal", "atm"),
        "transfer_to_person": ("person transfer", "transfers to people"),
    }
    for category, terms in aliases.items():
        if any(term in normalized for term in terms):
            requested.append(category)
    return requested


def _looks_like_revolut_document(document: Any) -> bool:
    text = " ".join(filter(None, [
        str(getattr(document, "title", "") or ""),
        str(getattr(document, "current_content", "") or "")[:4000],
    ])).lower()
    return "revolut" in text and ("gbp statement" in text or "statement" in text)


def _normalize_housing_entry(entry: Any) -> Optional[Dict[str, str]]:
    if not isinstance(entry, dict):
        return None
    property_area = _first_value(
        entry, "propertyArea", "property", "area", "address", "title", limit=160,
    )
    date_bidded = _first_value(
        entry, "dateBidded", "bidDate", "date", limit=40,
    )
    if not property_area or not date_bidded:
        return None
    return {
        "id": _clean_text(entry.get("id"), 100),
        "property_area": property_area,
        "date_bidded": date_bidded,
        "description": _clean_text(entry.get("description"), 300),
        "status": _clean_text(entry.get("status"), 80),
        "priority_band": _first_value(entry, "priorityBand", "band", limit=120),
        "notes": _clean_text(entry.get("notes"), 2000),
        "outcome": _clean_text(entry.get("outcome"), 500),
        "updated_at": _clean_text(entry.get("updatedAt"), 40),
    }


def _housing_store(owner: Optional[str]) -> tuple[bool, List[Dict[str, str]]]:
    value = (_load_for_user(owner) or {}).get("housing-bids-v1")
    recognized = (
        isinstance(value, dict)
        and value.get("version") == 1
        and isinstance(value.get("entries"), list)
    )
    if not recognized:
        return False, []
    entries = [
        normalized
        for normalized in (_normalize_housing_entry(entry) for entry in value["entries"])
        if normalized is not None
    ]
    return True, entries


class VantaBrainService:
    """Collect small, labelled snippets without mutating source stores."""

    def __init__(
        self,
        memory_manager,
        personal_docs_manager,
        memory_vector=None,
        finance_analyzer=None,
    ):
        self.memory_manager = memory_manager
        self.personal_docs_manager = personal_docs_manager
        self.memory_vector = memory_vector
        self.finance_analyzer = finance_analyzer

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
            recognized, entries = _housing_store(owner)
            if not recognized:
                return []
            housing_intent = _housing_intent(query)
            if housing_intent and not entries:
                return [BrainSnippet(
                    source="housing",
                    source_id="housing-bids-v1-empty",
                    label="Housing Bids",
                    text="No housing bids are saved in the Housing Bids tracker yet.",
                    score=3.0,
                    metadata={"empty": True, "schema_recognized": True},
                )]

            entries.sort(
                key=lambda entry: (entry["date_bidded"], entry["updated_at"]),
                reverse=True,
            )
            candidates = []
            for index, entry in enumerate(entries[:250]):
                combined = "\n".join(filter(None, [
                    f"Property / area: {entry['property_area']}",
                    f"Bid date: {entry['date_bidded']}",
                    f"Status: {entry['status']}" if entry["status"] else "",
                    f"Priority / band: {entry['priority_band']}" if entry["priority_band"] else "",
                    f"Outcome: {entry['outcome']}" if entry["outcome"] else "",
                    f"Description: {entry['description']}" if entry["description"] else "",
                    f"Notes: {entry['notes']}" if entry["notes"] else "",
                ]))
                score = _keyword_score(query, combined)
                if not housing_intent and score <= 0:
                    continue
                candidates.append(BrainSnippet(
                    source="housing",
                    source_id=entry["id"],
                    label=f"Housing Bid: {entry['property_area']}",
                    text=_clean_text(combined),
                    score=(3.0 + score + max(MAX_SNIPPETS - index, 0) * 0.001)
                    if housing_intent else score,
                    metadata={
                        "status": entry["status"],
                        "date_bidded": entry["date_bidded"],
                        "schema_recognized": True,
                    },
                ))
                if housing_intent and len(candidates) >= MAX_SNIPPETS:
                    break
            return candidates
        except Exception:
            logger.warning("Vanta Brain housing retrieval failed", exc_info=True)
            errors.append({"source": "housing", "detail": "Housing preferences unavailable."})
            return []

    def _finance_candidates(
        self,
        query: str,
        owner: Optional[str],
        errors: List[Dict[str, str]],
    ) -> List[BrainSnippet]:
        if not self.finance_analyzer or not _finance_intent(query):
            return []
        try:
            documents = self.finance_analyzer.find_owner_statements(owner, limit=10)
            (
                preview_intent,
                spend_intent,
                money_in_intent,
                savings_intent,
                payment_intent,
            ) = _finance_intents(query)
            requested_categories = _finance_categories(query)
            this_month = "this month" in (query or "").lower()
            month_prefix = datetime.now().strftime("%Y-%m") if this_month else ""
            candidates = []

            if not documents:
                return [BrainSnippet(
                    source="finance",
                    source_id="revolut-statement-not-found",
                    label="Revolut Statement",
                    text="I could not find an owner-owned Revolut statement in Library.",
                    score=4.0,
                    metadata={"status": "not_found"},
                )]

            for document in documents:
                try:
                    analysis = self.finance_analyzer.analyze_document(
                        str(document.id),
                        owner,
                    )
                except FileNotFoundError:
                    if _looks_like_revolut_document(document):
                        return [BrainSnippet(
                            source="finance",
                            source_id=str(document.id),
                            label=f"Revolut Statement: {_clean_text(document.title, 100)}",
                            text=(
                                "I found the Library document, but the original PDF "
                                "upload is unavailable."
                            ),
                            score=4.0,
                            metadata={
                                "document_id": str(document.id),
                                "status": "source_unavailable",
                            },
                        )]
                    continue
                except (LookupError, ValueError):
                    continue
                if not analysis.detected:
                    continue
                label = f"Revolut Statement: {_clean_text(document.title, 100)}"
                if not analysis.transactions:
                    candidates.append(BrainSnippet(
                        source="finance",
                        source_id=str(document.id),
                        label=label,
                        text=(
                            "I found the statement but could not extract transaction rows. "
                            "Upload CSV or text-based PDF."
                        ),
                        score=4.0,
                        metadata={
                            "document_id": str(document.id),
                            "extractable": False,
                            "status": "extraction_failed",
                        },
                    ))
                    continue

                text_blocks = [
                    "Library access: succeeded. The owner-owned original PDF was opened and analyzed.",
                ]
                if preview_intent:
                    summary = analysis.summary_dict()
                    counts = summary["counts"]
                    date_range = summary["date_range"]
                    warnings = "; ".join(analysis.warnings) if analysis.warnings else "None."
                    text_blocks.append("\n".join([
                        "Statement preview:",
                        f"Generated: {summary['generated_date'] or 'unknown'}",
                        (
                            f"Range: {date_range['start'] or 'unknown'} "
                            f"to {date_range['end'] or 'unknown'}"
                        ),
                        f"Opening balance: GBP {summary['opening_balance'] or 'unknown'}",
                        f"Total money out: GBP {summary['total_money_out'] or 'unknown'}",
                        f"Total money in: GBP {summary['total_money_in'] or 'unknown'}",
                        f"Closing balance: GBP {summary['closing_balance'] or 'unknown'}",
                        f"Completed rows: {counts['completed']}",
                        f"Pending: {counts['pending']}",
                        f"Reverted: {counts['reverted']}",
                        (
                            "Reconciled: yes"
                            if summary["completed_totals_reconciled"]
                            else "Reconciled: no"
                        ),
                        f"Warnings: {warnings}",
                    ]))

                rows = analysis.completed
                if month_prefix:
                    rows = [row for row in rows if row.date.startswith(month_prefix)]
                if money_in_intent:
                    incoming = [row for row in rows if row.money_in and row.money_in > 0]
                    income_rows = [row for row in incoming if row.category == "income"]
                    savings_rows = [
                        row for row in incoming
                        if row.category == "internal_savings_transfer"
                    ]
                    other_rows = [
                        row for row in incoming
                        if row.category not in {"income", "internal_savings_transfer"}
                    ]
                    income_total = sum(
                        (row.money_in for row in income_rows),
                        Decimal("0.00"),
                    )
                    savings_in = sum(
                        (row.money_in for row in savings_rows),
                        Decimal("0.00"),
                    )
                    other_in = sum(
                        (row.money_in for row in other_rows),
                        Decimal("0.00"),
                    )
                    incoming.sort(
                        key=lambda row: (row.money_in or Decimal("0"), row.date),
                        reverse=True,
                    )
                    incoming_lines = [
                        f"{row.date}: {row.description} GBP {row.money_in:.2f} "
                        f"({row.category.replace('_', ' ')}, page {row.page})"
                        for row in incoming[:6]
                    ]
                    text_blocks.append("\n".join([
                        "Money-in breakdown:",
                        f"Total money in: GBP {analysis.total_money_in or Decimal('0.00'):.2f}",
                        f"Income: GBP {income_total:.2f}",
                        f"Internal savings withdrawals: GBP {savings_in:.2f}",
                        f"Other/refund-like or unknown money in: GBP {other_in:.2f}",
                        (
                            "Top incoming transactions:\n" + "\n".join(incoming_lines)
                            if incoming_lines
                            else "Top incoming transactions: none."
                        ),
                        (
                            "Income is separated from internal savings movement and "
                            "refund-like/unknown incoming money where the statement "
                            "description supports that distinction."
                        ),
                    ]))
                if savings_intent:
                    internal_rows = [
                        row for row in rows
                        if row.category == "internal_savings_transfer"
                    ]
                    savings_out = sum(
                        (row.money_out or Decimal("0.00") for row in internal_rows),
                        Decimal("0.00"),
                    )
                    savings_in = sum(
                        (row.money_in or Decimal("0.00") for row in internal_rows),
                        Decimal("0.00"),
                    )
                    internal_total = savings_out + savings_in
                    completed_out = sum(
                        (row.money_out or Decimal("0.00") for row in rows),
                        Decimal("0.00"),
                    )
                    text_blocks.append("\n".join([
                        "Internal savings movement:",
                        f"Deposited into savings: GBP {savings_out:.2f}",
                        f"Withdrawn from savings: GBP {savings_in:.2f}",
                        f"Total internal savings movement: GBP {internal_total:.2f}",
                        f"Completed money out: GBP {completed_out:.2f}",
                        (
                            "External spend excluding internal savings: "
                            f"GBP {analysis.external_spend(rows):.2f}"
                        ),
                        (
                            "Internal savings movement is movement between your own "
                            "balances, not lifestyle spending."
                        ),
                    ]))
                if spend_intent:
                    category_totals = analysis.category_totals(rows)
                    if requested_categories:
                        selected_totals = [
                            f"{category.replace('_', ' ')}: GBP {category_totals[category]:.2f}"
                            for category in requested_categories
                        ]
                    else:
                        selected_totals = [
                            f"{category.replace('_', ' ')}: GBP {amount:.2f}"
                            for category, amount in sorted(
                                category_totals.items(),
                                key=lambda item: item[1],
                                reverse=True,
                            )
                            if amount > 0 and category != "internal_savings_transfer"
                        ][:6]

                    examples = [
                        row for row in rows
                        if row.money_out
                        and row.category != "internal_savings_transfer"
                        and (not requested_categories or row.category in requested_categories)
                    ]
                    examples.sort(key=lambda row: (row.date, row.money_out), reverse=True)
                    example_lines = [
                        f"{row.date}: {row.description} GBP {row.money_out:.2f} "
                        f"({row.category.replace('_', ' ')}, page {row.page})"
                        for row in examples[:8]
                    ]
                    period = (
                        datetime.now().strftime("%B %Y")
                        if this_month else
                        f"{analysis.statement_start or 'unknown'} to {analysis.statement_end or 'unknown'}"
                    )
                    text_blocks.append("\n".join(filter(None, [
                        f"Spending period: {period}",
                        f"External money out excluding internal savings: GBP {analysis.external_spend(rows):.2f}",
                        "Category totals: " + "; ".join(selected_totals)
                        if selected_totals else "Category totals: no matching completed spending.",
                        "Recent matching transactions:\n" + "\n".join(example_lines)
                        if example_lines else "Recent matching transactions: none.",
                        (
                            "Pending and reverted transactions are excluded from spending totals. "
                            f"Pending: {len(analysis.pending)}; reverted: {len(analysis.reverted)}."
                        ),
                    ])))
                candidates.append(BrainSnippet(
                    source="finance",
                    source_id=str(document.id),
                    label=label,
                    text=_clean_multiline_text("\n\n".join(text_blocks)),
                    score=4.0,
                    metadata={
                        "document_id": str(document.id),
                        "statement_start": analysis.statement_start,
                        "statement_end": analysis.statement_end,
                        "extractable": True,
                        "status": "analyzed",
                        "preview": preview_intent,
                        "spend": spend_intent,
                        "money_in": money_in_intent,
                        "savings": savings_intent,
                        "payment_request": payment_intent,
                    },
                ))
                break
            return candidates or [BrainSnippet(
                source="finance",
                source_id="revolut-statement-not-found",
                label="Revolut Statement",
                text="I could not find an owner-owned Revolut statement in Library.",
                score=4.0,
                metadata={"status": "not_found"},
            )]
        except Exception:
            logger.warning("Vanta Brain finance retrieval failed", exc_info=True)
            errors.append({"source": "finance", "detail": "Statement analysis unavailable."})
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
        housing_query: Optional[str] = None,
    ) -> BrainRetrieval:
        result = BrainRetrieval()
        candidates: List[BrainSnippet] = []

        if include_memory:
            memory, result.used_memories = self._memory_candidates(query, owner, result.errors)
            candidates.extend(memory)
        candidates.extend(self._note_candidates(query, owner, result.errors))
        candidates.extend(self._document_candidates(query, owner, result.errors))
        candidates.extend(self._housing_candidates(
            housing_query if housing_query is not None else query,
            owner,
            result.errors,
        ))
        candidates.extend(self._finance_candidates(query, owner, result.errors))
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
            housing_schema_recognized, housing_entries = _housing_store(owner)
            housing_count = len(housing_entries)
        except Exception:
            housing_count = 0
            housing_schema_recognized = False
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
            "housing": {
                "ready": not any(e["source"] == "housing" for e in errors),
                "count": housing_count,
                "schema_recognized": housing_schema_recognized,
            },
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

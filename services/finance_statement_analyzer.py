"""Read-only analysis for owner-scoped Revolut GBP statement PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.database import Document, SessionLocal
from routes.document_helpers import _resolve_user_upload_path
from src.pdf_form_doc import find_source_upload_id

EXTRACTION_FAILURE_MESSAGE = (
    "I found the statement but could not extract transaction rows. "
    "Upload CSV or text-based PDF."
)

_DATE_RE = re.compile(r"^\s*(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})\s+")
_MONEY_RE = re.compile(r"(?P<negative>-)?[£Ł]\s*(?P<amount>\d[\d,]*\.\d{2})")
_CARD_RE = re.compile(r"(?:\*{2,}|\s)(\d{4})\s*$")
_SECTION_RE = re.compile(
    r"^(Pending|Account transactions|Reverted)\s+from\s+"
    r"(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)

CATEGORIES = (
    "income",
    "internal_savings_transfer",
    "transfer_to_person",
    "groceries",
    "takeaway_fast_food",
    "transport",
    "subscriptions_apps",
    "shopping_random",
    "alcohol_vapes",
    "cash_withdrawal",
    "unknown",
)


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    match = _MONEY_RE.search(value)
    if not match:
        return None
    try:
        amount = Decimal(match.group("amount").replace(",", ""))
    except InvalidOperation:
        return None
    return -amount if match.group("negative") else amount


def _money(value: Optional[Decimal]) -> Optional[str]:
    return f"{value:.2f}" if value is not None else None


def _iso_date(value: str) -> str:
    for date_format in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    return value.strip()


def _clean(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _redact_sensitive_text(value: str) -> str:
    redacted = re.sub(r"\b\d{6,10}\b", "[redacted]", value or "")
    return re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[redacted]", redacted)


def _public_details(lines: Iterable[str]) -> List[str]:
    details = []
    for line in lines:
        if line.startswith("Card:"):
            continue
        redacted = _redact_sensitive_text(line)
        details.append(_clean(redacted, 300))
    return details


def _category(description: str, details: Iterable[str], money_in: Optional[Decimal]) -> str:
    text = " ".join([description, *details]).lower()
    if "withdrawing savings" in text or "depositing savings" in text:
        return "internal_savings_transfer"
    if money_in is not None and money_in > 0:
        if any(term in text for term in (
            "payment from", "transfer from", "salary", "wages", "payroll",
        )):
            return "income"
        return "unknown"
    if description.lower().startswith("to ") or re.search(r"\bto:\s+[a-z].*,\s*\d{6,8}\b", text):
        return "transfer_to_person"
    if any(term in text for term in (
        "atm", "cash withdrawal", "cashpoint", "withdrawal",
    )):
        return "cash_withdrawal"
    if any(term in text for term in (
        "uber eats", "deliveroo", "just eat", "mcdonald", "kfc", "burger king",
        "pizza", "chicken", "restaurant", "cafe", "coffee", "takeaway",
    )):
        return "takeaway_fast_food"
    if any(term in text for term in (
        "tesco", "lidl", "aldi", "waitrose", "sainsbury", "asda", "morrisons",
        "supermar", "mini mart", "grocery", "food store", "co-op",
    )):
        return "groceries"
    if any(term in text for term in (
        "uber *trip", "bolt", "stagecoach", "go south coast", "trainline",
        "national express", "transport", "taxi", "rail", "bus",
    )):
        return "transport"
    if any(term in text for term in (
        "apple.com/bill", "google play", "netflix", "spotify", "adobe",
        "capcut", "subscription", "membership", "prime video", "disney",
    )):
        return "subscriptions_apps"
    if any(term in text for term in (
        "greene king", "wetherspoon", "beer", "wine", "vodka", "whisky",
        "whiskey", "vape", "tobacco", "off licence",
    )):
        return "alcohol_vapes"
    if any(term in text for term in (
        "amazon", "ebay", "temu", "shein", "argos", "primark", "shop",
        "store", "retail",
    )):
        return "shopping_random"
    return "unknown"


@dataclass
class StatementTransaction:
    date: str
    description: str
    money_out: Optional[Decimal]
    money_in: Optional[Decimal]
    balance: Optional[Decimal]
    status: str
    page: int
    detail_lines: List[str] = field(default_factory=list)
    reference: str = ""
    card_last_four: str = ""
    category: str = "unknown"

    def public_dict(self, source_document: str) -> Dict[str, Any]:
        return {
            "date": self.date,
            "description": self.description,
            "money_out": _money(self.money_out),
            "money_in": _money(self.money_in),
            "balance": _money(self.balance),
            "merchant_details": _public_details(self.detail_lines),
            "reference": _redact_sensitive_text(self.reference) or None,
            "card_last_four": self.card_last_four or None,
            "category": self.category,
            "status": self.status,
            "source": {"document_id": source_document, "page": self.page},
        }


@dataclass
class StatementAnalysis:
    detected: bool
    document_id: str = ""
    document_title: str = ""
    generated_date: str = ""
    statement_start: str = ""
    statement_end: str = ""
    opening_balance: Optional[Decimal] = None
    total_money_out: Optional[Decimal] = None
    total_money_in: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    transactions: List[StatementTransaction] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def completed(self) -> List[StatementTransaction]:
        return [row for row in self.transactions if row.status == "completed"]

    @property
    def pending(self) -> List[StatementTransaction]:
        return [row for row in self.transactions if row.status == "pending"]

    @property
    def reverted(self) -> List[StatementTransaction]:
        return [row for row in self.transactions if row.status == "reverted"]

    def category_totals(self, rows: Optional[Iterable[StatementTransaction]] = None) -> Dict[str, Decimal]:
        totals = {category: Decimal("0.00") for category in CATEGORIES}
        for row in rows if rows is not None else self.completed:
            if row.money_out:
                totals[row.category] += row.money_out
        return totals

    def external_spend(self, rows: Optional[Iterable[StatementTransaction]] = None) -> Decimal:
        return sum(
            (
                row.money_out or Decimal("0.00")
                for row in (rows if rows is not None else self.completed)
                if row.category != "internal_savings_transfer"
            ),
            Decimal("0.00"),
        )

    def summary_dict(self) -> Dict[str, Any]:
        completed_out = sum((row.money_out or Decimal("0") for row in self.completed), Decimal("0"))
        completed_in = sum((row.money_in or Decimal("0") for row in self.completed), Decimal("0"))
        reconciled = (
            self.total_money_out is not None
            and self.total_money_in is not None
            and completed_out == self.total_money_out
            and completed_in == self.total_money_in
        )
        return {
            "generated_date": self.generated_date or None,
            "date_range": {
                "start": self.statement_start or None,
                "end": self.statement_end or None,
            },
            "opening_balance": _money(self.opening_balance),
            "total_money_out": _money(self.total_money_out),
            "total_money_in": _money(self.total_money_in),
            "closing_balance": _money(self.closing_balance),
            "external_spend_excluding_internal_savings": _money(self.external_spend()),
            "counts": {
                "completed": len(self.completed),
                "pending": len(self.pending),
                "reverted": len(self.reverted),
            },
            "completed_totals_reconciled": reconciled,
            "category_totals": {
                category: _money(amount)
                for category, amount in self.category_totals().items()
            },
        }


class FinanceStatementAnalyzer:
    """Parse supported statements in memory without persisting transactions."""

    def __init__(self, upload_handler=None):
        self.upload_handler = upload_handler

    @staticmethod
    def extract_pages(pdf_path: str) -> List[str]:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        return [
            page.extract_text(extraction_mode="layout") or ""
            for page in reader.pages
        ]

    @classmethod
    def parse_pages(
        cls,
        pages: List[str],
        *,
        document_id: str = "",
        document_title: str = "",
    ) -> StatementAnalysis:
        first_page = pages[0] if pages else ""
        detected = bool(
            re.search(r"\bGBP Statement\b", first_page, re.IGNORECASE)
            and re.search(r"\bRevolut Ltd\b", first_page, re.IGNORECASE)
            and "Balance summary" in first_page
        )
        result = StatementAnalysis(
            detected=detected,
            document_id=document_id,
            document_title=_clean(document_title, 160),
        )
        if not detected:
            return result

        generated = re.search(
            r"Generated on the\s+(\d{1,2}\s+\w+\s+\d{4})",
            first_page,
            re.IGNORECASE,
        )
        if generated:
            result.generated_date = _iso_date(generated.group(1))

        summary_match = re.search(
            r"^\s*Total\s+(.+)$",
            first_page,
            re.MULTILINE | re.IGNORECASE,
        )
        if summary_match:
            values = [_decimal(match.group(0)) for match in _MONEY_RE.finditer(summary_match.group(1))]
            if len(values) >= 4:
                (
                    result.opening_balance,
                    result.total_money_out,
                    result.total_money_in,
                    result.closing_balance,
                ) = values[:4]

        current: Optional[StatementTransaction] = None
        section = ""
        columns: Dict[str, int] = {}

        def finish_current() -> None:
            nonlocal current
            if current is None:
                return
            current.category = _category(
                current.description,
                current.detail_lines,
                current.money_in,
            )
            result.transactions.append(current)
            current = None

        for page_number, page_text in enumerate(pages, start=1):
            for raw_line in page_text.splitlines():
                line = raw_line.rstrip()
                stripped = line.strip()
                section_match = _SECTION_RE.match(stripped)
                if section_match:
                    finish_current()
                    section_name = section_match.group(1).lower()
                    section = {
                        "pending": "pending",
                        "account transactions": "completed",
                        "reverted": "reverted",
                    }[section_name]
                    if section == "completed":
                        result.statement_start = _iso_date(section_match.group(2))
                        result.statement_end = _iso_date(section_match.group(3))
                    columns = {}
                    continue

                if (
                    ("Description" in line and "Money out" in line and "Money in" in line)
                    and ("Date" in line or "Start date" in line)
                ):
                    columns = {
                        "description": line.index("Description"),
                        "money_out": line.index("Money out"),
                        "money_in": line.index("Money in"),
                    }
                    if "Balance" in line:
                        columns["balance"] = line.index("Balance")
                    continue

                if not section or not columns:
                    continue
                date_match = _DATE_RE.match(line)
                if date_match:
                    finish_current()
                    description = line[
                        columns["description"]:columns["money_out"]
                    ].strip()
                    out_end = columns["money_in"]
                    in_end = columns.get("balance", len(line))
                    current = StatementTransaction(
                        date=_iso_date(date_match.group(1)),
                        description=_clean(description, 240),
                        money_out=_decimal(line[columns["money_out"]:out_end]),
                        money_in=_decimal(line[columns["money_in"]:in_end]),
                        balance=_decimal(line[columns["balance"]:])
                        if "balance" in columns else None,
                        status=section,
                        page=page_number,
                    )
                    continue

                if current is None or not stripped:
                    continue
                if stripped.startswith(("Report lost or stolen card", "© ")):
                    finish_current()
                    continue
                detail = _clean(stripped, 300)
                if detail.startswith(("To:", "From:", "Reference:", "Card:", "Fee:", "Revolut Rate")):
                    current.detail_lines.append(detail)
                    if detail.startswith("Reference:"):
                        current.reference = _clean(detail.partition(":")[2], 160)
                    elif detail.startswith("Card:"):
                        card_match = _CARD_RE.search(detail)
                        if card_match:
                            current.card_last_four = card_match.group(1)

        finish_current()

        if not result.transactions:
            result.warnings.append(EXTRACTION_FAILURE_MESSAGE)
            return result

        completed_out = sum((row.money_out or Decimal("0") for row in result.completed), Decimal("0"))
        completed_in = sum((row.money_in or Decimal("0") for row in result.completed), Decimal("0"))
        if result.total_money_out is not None and completed_out != result.total_money_out:
            result.warnings.append("Completed money-out rows do not match the statement summary.")
        if result.total_money_in is not None and completed_in != result.total_money_in:
            result.warnings.append("Completed money-in rows do not match the statement summary.")
        if any(row.balance is None for row in result.completed):
            result.warnings.append("Some completed transaction balances could not be extracted.")
        return result

    def analyze_pdf(
        self,
        pdf_path: str,
        *,
        document_id: str = "",
        document_title: str = "",
    ) -> StatementAnalysis:
        return self.parse_pages(
            self.extract_pages(pdf_path),
            document_id=document_id,
            document_title=document_title,
        )

    def analyze_document(
        self,
        document_id: str,
        owner: Optional[str],
        *,
        auth_manager=None,
    ) -> StatementAnalysis:
        db = SessionLocal()
        try:
            query = db.query(Document).filter(Document.id == document_id)
            query = query.filter(Document.owner == owner) if owner is not None else query.filter(False)
            document = query.first()
            if document is None:
                raise LookupError("Document not found")
            upload_id = find_source_upload_id(document.current_content or "")
            if not upload_id:
                raise ValueError("Document is not linked to an uploaded PDF")
            path = _resolve_user_upload_path(
                self.upload_handler,
                upload_id,
                owner,
                auth_manager,
            )
            if not path or Path(path).suffix.lower() != ".pdf":
                raise FileNotFoundError("Source PDF is unavailable")
            return self.analyze_pdf(
                path,
                document_id=str(document.id),
                document_title=document.title or "Revolut statement",
            )
        finally:
            db.close()

    def find_owner_statements(self, owner: Optional[str], limit: int = 10) -> List[Document]:
        db = SessionLocal()
        try:
            query = db.query(Document).filter(
                Document.is_active == True,  # noqa: E712
                (Document.archived == False) | (Document.archived.is_(None)),  # noqa: E712
                Document.current_content.like('%pdf_source upload_id="%'),
            )
            query = query.filter(Document.owner == owner) if owner is not None else query.filter(False)
            rows = query.order_by(Document.updated_at.desc()).limit(limit).all()
            return [
                Document(
                    id=row.id,
                    owner=row.owner,
                    title=row.title,
                    current_content=row.current_content,
                    is_active=row.is_active,
                    archived=row.archived,
                )
                for row in rows
            ]
        finally:
            db.close()

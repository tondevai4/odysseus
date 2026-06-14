import asyncio
from types import SimpleNamespace

import pytest

from routes import finance_routes
from core.database import Document, SessionLocal
from services.finance_statement_analyzer import (
    EXTRACTION_FAILURE_MESSAGE,
    FinanceStatementAnalyzer,
)


def _placed_line(values):
    chars = [" "] * 230
    for position, value in values:
        chars[position:position + len(value)] = value
    return "".join(chars).rstrip()


def _header(balance=False):
    values = [
        (1, "Date" if balance else "Start date"),
        (33, "Description"),
        (115, "Money out"),
        (147, "Money in"),
    ]
    if balance:
        values.append((189, "Balance"))
    return _placed_line(values)


def _line(date, description, money_out="", money_in="", balance=""):
    return _placed_line([
        (1, date),
        (33, description),
        (115, money_out),
        (147, money_in),
        (189, balance),
    ])


def _synthetic_pages():
    page_one = "\n".join([
        "GBP Statement                                      Generated on the 14 Jun 2026",
        "Revolut Ltd",
        "Balance summary",
        " Product Opening balance Money out Money in Closing balance",
        " Total £100.00 £22.50 £70.00 £147.50",
        "Pending from 1 June 2026 to 14 June 2026",
        _header(),
        _line("12 Jun 2026", "Stagecoach", "£5.00"),
        "                                 To: Stagecoach, Perth",
        "                                 Card: 416549******2172",
        "Account transactions from 1 June 2026 to 14 June 2026",
        _header(balance=True),
        _line("10 Jun 2026", "Withdrawing savings", "", "£20.00", "£120.00"),
        _line("11 Jun 2026", "Deliveroo", "£12.50", "", "£107.50"),
        "                                 To: Deliveroo, London",
        "                                 Reference: DINNER",
        "                                 Card: 416549******7616",
        _line("12 Jun 2026", "Payment from FLEXEARN LTD", "", "£50.00", "£157.50"),
        "                                 From: FLEXEARN LTD, 00002547",
        _line("13 Jun 2026", "To Jane Example", "£10.00", "", "£147.50"),
        "                                 To: Jane Example, 12345678",
    ])
    page_two = "\n".join([
        "GBP Statement",
        "Revolut Ltd",
        "Reverted from 1 June 2026 to 14 June 2026",
        _header(),
        _line("14 Jun 2026", "Uber", "£7.00"),
        "                                 To: Uber *trip, London",
    ])
    return [page_one, page_two]


def test_revolut_parser_separates_statuses_reconciles_and_categorises():
    result = FinanceStatementAnalyzer.parse_pages(
        _synthetic_pages(),
        document_id="doc-1",
        document_title="June statement",
    )

    assert result.detected is True
    assert (len(result.completed), len(result.pending), len(result.reverted)) == (4, 1, 1)
    assert result.summary_dict()["completed_totals_reconciled"] is True
    assert result.summary_dict()["external_spend_excluding_internal_savings"] == "22.50"
    assert result.completed[0].category == "internal_savings_transfer"
    assert result.completed[1].category == "takeaway_fast_food"
    assert result.completed[1].reference == "DINNER"
    assert result.completed[1].card_last_four == "7616"
    assert result.completed[2].category == "income"
    assert result.completed[3].category == "transfer_to_person"
    assert result.reverted[0].category == "transport"


def test_parser_returns_required_message_when_statement_has_no_rows():
    result = FinanceStatementAnalyzer.parse_pages([
        "GBP Statement\nGenerated on the 14 Jun 2026\nRevolut Ltd\nBalance summary",
    ])

    assert result.detected is True
    assert result.transactions == []
    assert result.warnings == [EXTRACTION_FAILURE_MESSAGE]


def test_non_statement_is_not_detected():
    result = FinanceStatementAnalyzer.parse_pages(["Ordinary PDF"])
    assert result.detected is False


def test_finance_routes_pass_authenticated_owner_and_bound_results(monkeypatch):
    parsed = FinanceStatementAnalyzer.parse_pages(
        _synthetic_pages(),
        document_id="doc-1",
        document_title="June statement",
    )

    class _Analyzer:
        def __init__(self):
            self.calls = []

        def analyze_document(self, document_id, owner, auth_manager=None):
            self.calls.append((document_id, owner, auth_manager))
            return parsed

    analyzer = _Analyzer()
    monkeypatch.setattr(finance_routes, "require_user", lambda request: "alice")
    router = finance_routes.setup_finance_routes(analyzer)
    endpoints = {route.path: route.endpoint for route in router.routes}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager="auth")))

    response = asyncio.run(endpoints["/api/finance/analyze-document"](
        request,
        finance_routes.StatementAnalysisRequest(
            document_id="doc-1",
            category="takeaway_fast_food",
            limit=10,
        ),
    ))

    assert analyzer.calls == [("doc-1", "alice", "auth")]
    assert response["analysis"]["matched_completed_transactions"] == 1
    assert response["transactions"][0]["description"] == "Deliveroo"
    assert response["transactions"][0]["source"] == {"document_id": "doc-1", "page": 1}
    serialized = str(response)
    assert "416549" not in serialized
    assert "IBAN" not in serialized


def test_finance_route_rejects_unknown_category(monkeypatch):
    parsed = FinanceStatementAnalyzer.parse_pages(_synthetic_pages(), document_id="doc-1")
    analyzer = SimpleNamespace(analyze_document=lambda *args, **kwargs: parsed)
    monkeypatch.setattr(finance_routes, "require_user", lambda request: "alice")
    router = finance_routes.setup_finance_routes(analyzer)
    endpoint = {route.path: route.endpoint for route in router.routes}[
        "/api/finance/analyze-document"
    ]
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_manager=None)))

    with pytest.raises(Exception) as exc:
        asyncio.run(endpoint(
            request,
            finance_routes.StatementAnalysisRequest(
                document_id="doc-1",
                category="invented",
            ),
        ))
    assert getattr(exc.value, "status_code", None) == 400


def test_analyzer_cannot_open_another_owners_document():
    upload_id = "a" * 32 + ".pdf"
    db = SessionLocal()
    try:
        db.add(Document(
            id="bob-private-statement",
            owner="bob",
            title="Bob statement",
            current_content=f'<!-- pdf_source upload_id="{upload_id}" -->',
            is_active=True,
            archived=False,
        ))
        db.commit()
    finally:
        db.close()

    analyzer = FinanceStatementAnalyzer(upload_handler=SimpleNamespace())
    with pytest.raises(LookupError):
        analyzer.analyze_document("bob-private-statement", "alice")

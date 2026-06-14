import asyncio
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace

import services.vanta_brain as brain_module
from core.database import Document, Note, SessionLocal
from routes import brain_routes
from routes.chat_helpers import save_assistant_response
from services.vanta_brain import (
    MAX_CONTEXT_CHARS,
    MAX_SNIPPETS,
    BrainRetrieval,
    BrainSnippet,
    VantaBrainService,
)
from src.chat_processor import ChatProcessor
from src.vanta_core import VANTA_CORE_PROMPT
from services.finance_statement_analyzer import (
    FinanceStatementAnalyzer,
    StatementAnalysis,
    StatementTransaction,
)


class _MemoryManager:
    def __init__(self, entries=None):
        self.entries = entries or []
        self.incremented = []

    def load(self, owner=None):
        if owner is None:
            return list(self.entries)
        return [entry for entry in self.entries if entry.get("owner") == owner]

    def increment_uses(self, ids):
        self.incremented.extend(ids)


class _PersonalDocs:
    def __init__(self, rag_manager=None, index=None):
        self.rag_manager = rag_manager
        self.index = index or []


class _Rag:
    healthy = True

    def __init__(self, rows=None):
        self.rows = rows or []
        self.owners = []

    def search(self, query, k=5, owner=None):
        self.owners.append(owner)
        return list(self.rows)[:k]


def _service(memory=None, docs=None):
    return VantaBrainService(memory or _MemoryManager(), docs or _PersonalDocs())


def test_vanta_core_is_first_with_no_preset_and_before_preset():
    processor = ChatProcessor(_MemoryManager(), _PersonalDocs())

    preface, _, _ = processor.build_context_preface(
        "hello",
        None,
        use_memory=False,
        use_rag=False,
    )
    assert preface[0] == {"role": "system", "content": VANTA_CORE_PROMPT}

    overlaid, _, _ = processor.build_context_preface(
        "hello",
        None,
        use_memory=False,
        use_rag=False,
        preset_system_prompt="Speak like a pirate.",
    )
    assert overlaid[0]["content"] == VANTA_CORE_PROMPT
    assert "subordinate to Vanta Core" in overlaid[1]["content"]
    assert overlaid[1]["content"].endswith("Speak like a pirate.")


def test_chat_injects_one_brain_message_and_incognito_suppresses_retrieval():
    class _Brain:
        def __init__(self):
            self.calls = 0

        def retrieve(self, *args, **kwargs):
            self.calls += 1
            return BrainRetrieval(snippets=[
                BrainSnippet("note", "n1", "Work", "CSCS interview prep", 1.0),
            ])

    brain = _Brain()
    processor = ChatProcessor(
        _MemoryManager([{"id": "secret", "text": "Private memory", "pinned": True}]),
        _PersonalDocs(),
        brain_service=brain,
    )

    preface, _, _ = processor.build_context_preface("CSCS", None, use_memory=True, use_rag=True)
    brain_messages = [
        row for row in preface
        if row.get("role") == "user" and "Vanta Brain retrieval" in row.get("content", "")
    ]
    assert len(brain_messages) == 1
    assert brain.calls == 1
    assert processor._last_brain_sources[0]["source"] == "note"

    private_preface, _, _ = processor.build_context_preface(
        "CSCS",
        None,
        use_memory=True,
        use_rag=True,
        incognito=True,
    )
    assert private_preface[0]["content"] == VANTA_CORE_PROMPT
    assert all("Vanta Brain retrieval" not in row.get("content", "") for row in private_preface)
    assert all("Private memory" not in row.get("content", "") for row in private_preface)
    assert brain.calls == 1


def test_brain_sources_are_saved_in_assistant_metadata():
    class _Session:
        def __init__(self):
            self.model = "test-model"
            self.history = []

        def add_message(self, message):
            self.history.append(message)

    session = _Session()
    save_assistant_response(
        session,
        object(),
        "session-1",
        "Answer",
        None,
        brain_sources=[{"source": "note", "label": "Mission", "text": "CSCS"}],
        incognito=True,
    )

    assert session.history[-1].metadata["brain_sources"][0]["label"] == "Mission"


def test_memory_retrieval_keeps_pinned_and_owner_isolated(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {})
    monkeypatch.setattr(brain_module, "get_rag_manager", lambda: None)
    memory = _MemoryManager([
        {"id": "a1", "owner": "alice", "text": "Tony is preparing for CSCS", "pinned": True},
        {"id": "a2", "owner": "alice", "text": "Carpentry interview on Tuesday", "category": "career"},
        {"id": "b1", "owner": "bob", "text": "Bob private housing note", "pinned": True},
    ])
    service = _service(memory)
    monkeypatch.setattr(service, "_note_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_document_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_housing_candidates", lambda *args: [])

    result = service.retrieve("carpentry interview", "alice", include_rag=False)

    assert any(source.metadata.get("type") == "pinned" for source in result.snippets)
    assert any("Carpentry" in source.text for source in result.snippets)
    assert all("Bob" not in source.text for source in result.snippets)


def test_notes_documents_and_housing_are_bounded_and_filter_inactive_rows(monkeypatch):
    owner = f"brain-test-{uuid.uuid4()}"
    other = f"brain-test-{uuid.uuid4()}"
    db = SessionLocal()
    try:
        db.add_all([
            Note(id=str(uuid.uuid4()), owner=owner, title="CSCS plan", content="Book the labouring test", items='[{"text":"Practice interview answers","done":false}]', archived=False),
            Note(id=str(uuid.uuid4()), owner=owner, title="Archived CSCS", content="Do not retrieve", archived=True),
            Note(id=str(uuid.uuid4()), owner=other, title="Private CSCS", content="Other owner", archived=False),
            Document(id=str(uuid.uuid4()), owner=owner, title="Carpentry opportunities", current_content="Local labouring and carpentry leads", is_active=True, archived=False),
            Document(id=str(uuid.uuid4()), owner=owner, title="Inactive carpentry", current_content="Do not retrieve", is_active=False, archived=False),
            Document(id=str(uuid.uuid4()), owner=owner, title="Archived carpentry", current_content="Do not retrieve", is_active=True, archived=True),
            Document(id=str(uuid.uuid4()), owner=other, title="Private carpentry", current_content="Other owner", is_active=True, archived=False),
        ])
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(brain_module, "get_rag_manager", lambda: None)
    monkeypatch.setattr(brain_module, "_load_for_user", lambda user: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [
                {"id": "h1", "propertyArea": "Camden", "dateBidded": "2026-06-10", "status": "Pending"},
                {"id": "bad", "propertyArea": "", "dateBidded": "2026-06-11"},
            ],
        },
    })
    service = _service()

    result = service.retrieve("CSCS carpentry Camden", owner, include_memory=False, include_rag=False)
    text = "\n".join(source.text for source in result.snippets)

    assert "Practice interview answers" in text
    assert "Local labouring and carpentry leads" in text
    assert "Camden" in text
    assert "Do not retrieve" not in text
    assert "Other owner" not in text


def test_malformed_housing_preferences_are_ignored(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {"housing-bids-v1": {"version": 9, "entries": "bad"}})
    service = _service()
    assert service._housing_candidates("housing", "alice", []) == []


def test_generic_housing_intent_returns_latest_alias_entries(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [
                {
                    "id": "older",
                    "property": "Old Kent Road",
                    "bidDate": "2026-05-01",
                    "status": "Unsuccessful",
                },
                {
                    "id": "latest",
                    "address": "12 Camden High Street",
                    "date": "2026-06-12",
                    "status": "Pending",
                    "band": "Band B",
                    "outcome": "Awaiting shortlist",
                    "notes": "Near the station",
                },
            ],
        },
    })
    service = _service()

    results = service._housing_candidates("What housing bids have I made?", "alice", [])

    assert [result.source_id for result in results] == ["latest", "older"]
    assert results[0].label == "Housing Bid: 12 Camden High Street"
    assert "Bid date: 2026-06-12" in results[0].text
    assert "Priority / band: Band B" in results[0].text
    assert "Outcome: Awaiting shortlist" in results[0].text
    assert "Notes: Near the station" in results[0].text
    assert results[0].score >= 3.0


def test_generic_housing_intent_survives_unified_selection(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [
                {"id": f"h{index}", "propertyArea": f"Property {index}", "dateBidded": f"2026-06-{index + 1:02d}"}
                for index in range(10)
            ],
        },
    })
    service = _service()
    monkeypatch.setattr(service, "_memory_candidates", lambda *args: ([], []))
    monkeypatch.setattr(service, "_note_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_document_candidates", lambda *args: [])

    result = service.retrieve(
        "What housing bids have I made?",
        "alice",
        include_memory=False,
        include_rag=False,
    )

    housing = [source for source in result.snippets if source.source == "housing"]
    assert len(housing) == 8
    assert housing[0].source_id == "h9"
    assert housing[-1].source_id == "h2"


def test_expanded_general_query_does_not_force_housing_details(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [
                {"id": "h1", "propertyArea": "Camden", "dateBidded": "2026-06-10"},
            ],
        },
    })
    service = _service()
    monkeypatch.setattr(service, "_memory_candidates", lambda *args: ([], []))
    monkeypatch.setattr(service, "_note_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_document_candidates", lambda *args: [])

    result = service.retrieve(
        "Plan today housing bids admin",
        "alice",
        include_memory=False,
        include_rag=False,
        housing_query="Who are you, and what do you call me?",
    )

    assert all(source.source != "housing" for source in result.snippets)


def test_known_property_query_still_returns_housing_entry(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [
                {"id": "h1", "area": "Camden", "dateBidded": "2026-06-10"},
                {"id": "h2", "area": "Hackney", "dateBidded": "2026-06-11"},
            ],
        },
    })
    service = _service()

    results = service._housing_candidates("Camden", "alice", [])

    assert len(results) == 1
    assert results[0].label == "Housing Bid: Camden"


def test_empty_housing_tracker_returns_honest_intent_result(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {"version": 1, "entries": []},
    })
    service = _service()

    results = service._housing_candidates("Show my housing bids", "alice", [])

    assert len(results) == 1
    assert results[0].metadata["empty"] is True
    assert "No housing bids are saved" in results[0].text


def test_housing_preferences_remain_owner_scoped(monkeypatch):
    stores = {
        "alice": {
            "housing-bids-v1": {
                "version": 1,
                "entries": [{"id": "alice-bid", "propertyArea": "Camden", "dateBidded": "2026-06-10"}],
            },
        },
        "bob": {
            "housing-bids-v1": {
                "version": 1,
                "entries": [{"id": "bob-bid", "propertyArea": "Hackney", "dateBidded": "2026-06-11"}],
            },
        },
    }
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: stores[owner])
    service = _service()

    results = service._housing_candidates("Show my housing bids", "alice", [])

    assert [result.source_id for result in results] == ["alice-bid"]
    assert all("Hackney" not in result.text for result in results)


def test_housing_health_reports_count_and_schema_recognition(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "housing-bids-v1": {
            "version": 1,
            "entries": [{"id": "h1", "title": "Council flat", "bidDate": "2026-06-10"}],
        },
    })
    service = _service()
    monkeypatch.setattr(service, "_owner_rag_inventory", lambda owner: {
        "ready": True,
        "healthy": True,
        "chunk_count": 0,
        "embedding_lanes": [],
        "indexed_sources": set(),
        "detail": "Personal RAG ready.",
    })

    health = service.health("alice")

    assert health["sources"]["housing"]["count"] == 1
    assert health["sources"]["housing"]["schema_recognized"] is True


def test_dynamic_rag_recovers_and_updates_legacy_manager(monkeypatch):
    docs = _PersonalDocs(rag_manager=None)
    rag = _Rag([{
        "id": "chunk-1",
        "document": "Personal upload about CSCS renewal",
        "metadata": {"filename": "cscs.txt", "owner": "alice"},
        "similarity": 0.91,
        "embedding_lane": "fastembed",
    }])
    available = iter([None, rag])
    monkeypatch.setattr(brain_module, "get_rag_manager", lambda: next(available))
    service = _service(docs=docs)

    first, _ = service._rag_candidates("CSCS", "alice", [])
    second, _ = service._rag_candidates("CSCS", "alice", [])

    assert first == []
    assert second and second[0].label == "cscs.txt"
    assert docs.rag_manager is rag
    assert rag.owners == ["alice"]


def test_snippet_and_character_limits_include_labels_and_separators(monkeypatch):
    service = _service()
    candidates = [
        BrainSnippet("note", str(index), f"Label {index}", "x" * 1200, 1.0 - index / 100)
        for index in range(20)
    ]
    monkeypatch.setattr(service, "_memory_candidates", lambda *args: (candidates, []))
    monkeypatch.setattr(service, "_note_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_document_candidates", lambda *args: [])
    monkeypatch.setattr(service, "_housing_candidates", lambda *args: [])

    result = service.retrieve("anything", "alice", include_rag=False)

    assert len(result.snippets) <= MAX_SNIPPETS
    assert len(result.context_text()) <= MAX_CONTEXT_CHARS


def test_brain_routes_return_health_and_preview(monkeypatch):
    class _Service:
        def health(self, owner):
            return {"overall": "ok", "owner": owner}

        def retrieve(self, query, owner):
            return BrainRetrieval(snippets=[
                BrainSnippet("note", "n1", "Mission", query, 0.8),
            ])

    monkeypatch.setattr(brain_routes, "require_user", lambda request: "alice")
    router = brain_routes.setup_brain_routes(_Service())
    endpoints = {route.path: route.endpoint for route in router.routes}

    health = asyncio.run(endpoints["/api/brain/health"](object()))
    preview = asyncio.run(endpoints["/api/brain/preview"](
        object(),
        brain_routes.BrainPreviewRequest(query="labouring"),
    ))

    assert health == {"overall": "ok", "owner": "alice"}
    assert preview["sources"][0]["label"] == "Mission"
    assert preview["limits"] == {"max_snippets": 8, "max_characters": 6000}


def test_finance_intent_adds_bounded_statement_context():
    analysis = FinanceStatementAnalyzer.parse_pages([
        "\n".join([
            "GBP Statement Generated on the 14 Jun 2026",
            "Revolut Ltd",
            "Balance summary",
            " Total £10.00 £12.00 £20.00 £18.00",
            "Account transactions from 1 June 2026 to 14 June 2026",
            " Date                            Description"
            "                                                                       Money out"
            "                        Money in"
            "                                  Balance",
            " 10 Jun 2026                     Deliveroo"
            "                                                                          £12.00"
            "                                                                          £18.00",
            "                                 To: Deliveroo, London",
            " 11 Jun 2026                     Payment from WORK LTD"
            "                                                                                                          £20.00"
            "                                  £38.00",
        ]),
    ], document_id="finance-doc", document_title="June Revolut")

    class _Finance:
        def find_owner_statements(self, owner, limit=10):
            assert owner == "alice"
            return [SimpleNamespace(id="finance-doc", title="June Revolut")]

        def analyze_document(self, document_id, owner):
            assert (document_id, owner) == ("finance-doc", "alice")
            return analysis

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_Finance(),
    )
    sources = service._finance_candidates(
        "What did I spend on takeaway this month?",
        "alice",
        [],
    )

    assert len(sources) == 1
    assert sources[0].source == "finance"
    assert "takeaway fast food: GBP 12.00" in sources[0].text
    assert "Deliveroo" in sources[0].text
    assert len(sources[0].text) <= 900


def test_finance_preview_intent_includes_full_statement_summary():
    analysis = FinanceStatementAnalyzer.parse_pages([
        "\n".join([
            "GBP Statement Generated on the 14 Jun 2026",
            "Revolut Ltd",
            "Balance summary",
            " Total £10.00 £12.00 £20.00 £18.00",
            "Account transactions from 1 June 2026 to 14 June 2026",
            " Date                            Description"
            "                                                                       Money out"
            "                        Money in"
            "                                  Balance",
            " 10 Jun 2026                     Deliveroo"
            "                                                                          £12.00"
            "                                                                          £18.00",
            " 11 Jun 2026                     Payment from WORK LTD"
            "                                                                                                          £20.00"
            "                                  £38.00",
        ]),
    ], document_id="finance-doc", document_title="June Revolut")

    class _Finance:
        def find_owner_statements(self, owner, limit=10):
            return [SimpleNamespace(
                id="finance-doc",
                title="June Revolut",
                current_content="Revolut GBP Statement",
            )]

        def analyze_document(self, document_id, owner):
            return analysis

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_Finance(),
    )
    sources = service._finance_candidates(
        (
            "Check my Revolut bank statement in Library. Preview it only. "
            "Tell me the date range, opening balance, money out, money in, "
            "closing balance, and whether it reconciles."
        ),
        "alice",
        [],
    )

    assert len(sources) == 1
    text = sources[0].text
    assert "Library access: succeeded" in text
    assert "Generated: 2026-06-14" in text
    assert "Range: 2026-06-01 to 2026-06-14" in text
    assert "Opening balance: GBP 10.00" in text
    assert "Total money out: GBP 12.00" in text
    assert "Total money in: GBP 20.00" in text
    assert "Closing balance: GBP 18.00" in text
    assert "Completed rows: 2" in text
    assert "Pending: 0" in text
    assert "Reverted: 0" in text
    assert "Reconciled: yes" in text
    assert "Warnings: None." in text
    assert "Category totals:" not in text
    assert sources[0].metadata["status"] == "analyzed"
    assert "IBAN" not in text
    assert "Account Number" not in text
    assert re.search(r"\b\d{6}\*{6}\d{4}\b", text) is None


def test_finance_success_adds_trusted_chat_access_status():
    class _Brain:
        def retrieve(self, *args, **kwargs):
            return BrainRetrieval(snippets=[BrainSnippet(
                "finance",
                "finance-doc",
                "Revolut Statement: June",
                "Statement preview:\nRange: 2026-06-01 to 2026-06-14",
                4.0,
                metadata={"status": "analyzed"},
            )])

    processor = ChatProcessor(
        _MemoryManager(),
        _PersonalDocs(),
        brain_service=_Brain(),
    )
    preface, _, _ = processor.build_context_preface(
        "Preview my Revolut statement in Library.",
        None,
        owner="alice",
        use_memory=False,
        use_rag=False,
    )
    trusted = [
        row["content"] for row in preface
        if row.get("role") == "system" and "finance analyzer successfully" in row.get("content", "")
    ]

    assert len(trusted) == 1
    assert "Do not claim Library is inaccessible" in trusted[0]
    assert "ask him to upload the statement" in trusted[0]


def test_finance_not_found_and_missing_pdf_are_explicit():
    class _NoDocuments:
        def find_owner_statements(self, owner, limit=10):
            return []

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_NoDocuments(),
    )
    missing = service._finance_candidates("Preview my Revolut statement", "alice", [])
    assert missing[0].metadata["status"] == "not_found"
    assert missing[0].text == (
        "I could not find an owner-owned Revolut statement in Library."
    )

    class _MissingPdf:
        def find_owner_statements(self, owner, limit=10):
            return [SimpleNamespace(
                id="finance-doc",
                title="Revolut June",
                current_content="Revolut GBP Statement",
            )]

        def analyze_document(self, document_id, owner):
            raise FileNotFoundError("Source PDF is unavailable")

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_MissingPdf(),
    )
    unavailable = service._finance_candidates("Preview my Revolut statement", "alice", [])
    assert unavailable[0].metadata["status"] == "source_unavailable"
    assert unavailable[0].text == (
        "I found the Library document, but the original PDF upload is unavailable."
    )

    failed_analysis = FinanceStatementAnalyzer.parse_pages([
        "GBP Statement\nGenerated on the 14 Jun 2026\nRevolut Ltd\nBalance summary",
    ], document_id="finance-doc", document_title="Revolut June")

    class _ExtractionFailed(_MissingPdf):
        def analyze_document(self, document_id, owner):
            return failed_analysis

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_ExtractionFailed(),
    )
    failed = service._finance_candidates("Preview my Revolut statement", "alice", [])
    assert failed[0].metadata["status"] == "extraction_failed"
    assert failed[0].text == (
        "I found the statement but could not extract transaction rows. "
        "Upload CSV or text-based PDF."
    )


def test_unrelated_query_does_not_open_finance_documents():
    class _Finance:
        def find_owner_statements(self, owner, limit=10):
            raise AssertionError("finance should not run for unrelated queries")

    service = VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_Finance(),
    )
    assert service._finance_candidates("Who are you?", "alice", []) == []
    assert service._finance_candidates("Summarise this paragraph.", "alice", []) == []


def _income_savings_analysis():
    return StatementAnalysis(
        detected=True,
        document_id="finance-doc",
        document_title="June Revolut",
        statement_start="2026-06-01",
        statement_end="2026-06-14",
        total_money_out=Decimal("42.00"),
        total_money_in=Decimal("125.00"),
        transactions=[
            StatementTransaction(
                date="2026-06-10",
                description="Payment from WORK LTD",
                money_out=None,
                money_in=Decimal("100.00"),
                balance=Decimal("100.00"),
                status="completed",
                page=2,
                category="income",
            ),
            StatementTransaction(
                date="2026-06-11",
                description="Withdrawing savings",
                money_out=None,
                money_in=Decimal("20.00"),
                balance=Decimal("120.00"),
                status="completed",
                page=3,
                category="internal_savings_transfer",
            ),
            StatementTransaction(
                date="2026-06-12",
                description="Uber Eats refund",
                money_out=None,
                money_in=Decimal("5.00"),
                balance=Decimal("125.00"),
                status="completed",
                page=4,
                category="unknown",
            ),
            StatementTransaction(
                date="2026-06-12",
                description="Depositing savings",
                money_out=Decimal("30.00"),
                money_in=None,
                balance=Decimal("95.00"),
                status="completed",
                page=4,
                category="internal_savings_transfer",
            ),
            StatementTransaction(
                date="2026-06-13",
                description="Deliveroo",
                money_out=Decimal("12.00"),
                money_in=None,
                balance=Decimal("83.00"),
                status="completed",
                page=5,
                category="takeaway_fast_food",
            ),
        ],
    )


def _finance_service_for(analysis):
    class _Finance:
        def find_owner_statements(self, owner, limit=10):
            return [SimpleNamespace(
                id="finance-doc",
                title="June Revolut",
                current_content="Revolut GBP Statement",
            )]

        def analyze_document(self, document_id, owner):
            return analysis

    return VantaBrainService(
        _MemoryManager(),
        _PersonalDocs(),
        finance_analyzer=_Finance(),
    )


def test_finance_money_in_intent_returns_breakdown_and_examples():
    sources = _finance_service_for(_income_savings_analysis())._finance_candidates(
        "What money came in on this statement?",
        "alice",
        [],
    )

    text = sources[0].text
    assert "Total money in: GBP 125.00" in text
    assert "Income: GBP 100.00" in text
    assert "Internal savings withdrawals: GBP 20.00" in text
    assert "Other/refund-like or unknown money in: GBP 5.00" in text
    assert "2026-06-10: Payment from WORK LTD GBP 100.00 (income, page 2)" in text
    assert "2026-06-11: Withdrawing savings GBP 20.00" in text
    assert "2026-06-12: Uber Eats refund GBP 5.00" in text
    assert "cannot see transaction list" not in text.lower()
    assert sources[0].metadata["money_in"] is True


def test_finance_internal_savings_intent_returns_numeric_movement():
    sources = _finance_service_for(_income_savings_analysis())._finance_candidates(
        "How much of this statement is internal savings movement?",
        "alice",
        [],
    )

    text = sources[0].text
    assert "Deposited into savings: GBP 30.00" in text
    assert "Withdrawn from savings: GBP 20.00" in text
    assert "Total internal savings movement: GBP 50.00" in text
    assert "Completed money out: GBP 42.00" in text
    assert "External spend excluding internal savings: GBP 12.00" in text
    assert "not lifestyle spending" in text
    assert sources[0].metadata["savings"] is True


def test_payment_request_adds_no_payment_workflow_guard():
    class _Brain:
        def retrieve(self, *args, **kwargs):
            return BrainRetrieval()

    processor = ChatProcessor(
        _MemoryManager(),
        _PersonalDocs(),
        brain_service=_Brain(),
    )
    preface, _, _ = processor.build_context_preface(
        "Can you move money or pay someone from this statement?",
        None,
        owner="alice",
        use_memory=False,
        use_rag=False,
    )
    guard = [
        row["content"] for row in preface
        if row.get("role") == "system"
        and row.get("content", "").startswith("Payment safety boundary:")
    ]

    assert len(guard) == 1
    assert "cannot move money, pay anyone, or prepare payment instructions" in guard[0]
    assert "Do not ask Tony for a sort code, IBAN, Revolut handle" in guard[0]
    assert "must handle any payment himself inside Revolut" in guard[0]
    assert "analyse spending, identify bills, or help build a budget" in guard[0]

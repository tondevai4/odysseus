import asyncio
import uuid

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

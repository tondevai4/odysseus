import asyncio
import json
from pathlib import Path

import routes.prefs_routes as prefs_routes
import services.vanta_brain as brain_module
from services.reading_list import (
    add_reading_item,
    list_reading_items,
    manage_reading_list_tool,
    update_reading_item,
)
from services.vanta_brain import VantaBrainService
from src.action_intents import classify_tool_intent
from src.chat_processor import ChatProcessor


class _Memory:
    def load(self, owner=None):
        return []


class _Docs:
    rag_manager = None
    index = []


def _prefs_file(monkeypatch, tmp_path):
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(path))
    return path


def test_reading_list_is_versioned_owner_scoped_and_updateable(monkeypatch, tmp_path):
    path = _prefs_file(monkeypatch, tmp_path)
    alice = add_reading_item("alice", {
        "title": "Can't Hurt Me",
        "status": "want_to_read",
        "priority": "high",
    })
    add_reading_item("bob", {"title": "Bob's Book"})

    updated = update_reading_item(
        "alice",
        "Can't Hurt Me",
        {"status": "reading", "progress": "chapter 3"},
    )
    assert updated["status"] == "reading"
    assert updated["progress"] == "chapter 3"
    assert [item["title"] for item in list_reading_items("alice")] == ["Can't Hurt Me"]
    assert [item["title"] for item in list_reading_items("bob")] == ["Bob's Book"]

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["_users"]["alice"]["reading-list-v1"]["version"] == 1
    assert stored["_users"]["alice"]["reading-list-v1"]["items"][0]["id"] == alice["id"]


def test_chat_tool_add_update_and_delete_refusal(monkeypatch, tmp_path):
    _prefs_file(monkeypatch, tmp_path)
    added = asyncio.run(manage_reading_list_tool(json.dumps({
        "action": "add",
        "title": "Deep Work",
    }), "alice"))
    assert added["exit_code"] == 0

    updated = asyncio.run(manage_reading_list_tool(json.dumps({
        "action": "update",
        "title": "Deep Work",
        "status": "finished",
    }), "alice"))
    assert updated["item"]["status"] == "finished"

    refused = asyncio.run(manage_reading_list_tool(json.dumps({
        "action": "delete",
        "title": "Deep Work",
    }), "alice"))
    assert refused["exit_code"] == 1
    assert "not available from chat" in refused["error"]


def test_reading_intent_is_relevant_only(monkeypatch):
    monkeypatch.setattr(brain_module, "_load_for_user", lambda owner: {
        "reading-list-v1": {
            "version": 1,
            "items": [{
                "id": "r1",
                "title": "Atomic Habits",
                "status": "reading",
                "priority": "high",
                "progress": "chapter 2",
            }],
        },
    })
    service = VantaBrainService(_Memory(), _Docs())
    assert service._reading_candidates("What should I read tonight?", "alice", [])
    assert service._reading_candidates("What housing bids have I made?", "alice", []) == []


def test_reading_actions_promote_to_tools_and_incognito_blocks_them():
    assert classify_tool_intent("Add Can't Hurt Me to my reading list.").category == "reading"
    processor = ChatProcessor(_Memory(), _Docs())
    preface, _, _ = processor.build_context_preface(
        "Mark Can't Hurt Me as finished.",
        None,
        use_memory=False,
        use_rag=False,
        incognito=True,
    )
    assert any(
        "reading list actions are disabled in incognito/private mode" in row["content"]
        for row in preface
    )


def test_reading_list_static_wiring():
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "static" / "app.js").read_text(encoding="utf-8")
    module = (root / "static" / "js" / "readingList.js").read_text(encoding="utf-8")

    assert 'id="tool-reading-list-btn"' in index
    assert "readingListModule.open()" in app
    assert "/api/reading-list" in module
    assert "/api/documents/library?limit=50" in module
    assert "/render-pdf" in module
    assert "/export-pdf" in module
    assert "localStorage" not in module
    assert "textContent" in module

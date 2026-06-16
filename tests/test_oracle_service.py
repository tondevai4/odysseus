import asyncio
import json
from pathlib import Path

import routes.prefs_routes as prefs_routes
import services.vanta_brain as brain_module
from services.oracle_service import (
    PREF_KEY,
    add_gratitude,
    add_important_date,
    add_manifestation,
    add_sign,
    calculate_numerology,
    cosmic_calendar,
    daily_reading,
    load_oracle,
    manage_oracle_tool,
    update_manifestation,
    update_profile,
)
from services.vanta_brain import VantaBrainService
from src.action_intents import classify_tool_intent, oracle_context_intent
from src.tool_policy import build_effective_tool_policy


ROOT = Path(__file__).resolve().parents[1]


class _Memory:
    def load(self, owner=None):
        return []


class _Docs:
    rag_manager = None
    index = []


def _prefs_file(monkeypatch, tmp_path):
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(path))
    monkeypatch.setattr(brain_module, "_load_for_user", prefs_routes._load_for_user)
    return path


def test_oracle_store_is_empty_versioned_and_owner_scoped(monkeypatch, tmp_path):
    path = _prefs_file(monkeypatch, tmp_path)
    alice = load_oracle("alice")
    assert alice["version"] == 1
    assert alice["birth_profile"]["date_of_birth"] == ""

    update_profile("alice", {"date_of_birth": "2001-07-21", "birth_city": "London"})
    update_profile("bob", {"date_of_birth": "1990-01-01"})

    assert load_oracle("alice")["birth_profile"]["date_of_birth"] == "2001-07-21"
    assert load_oracle("bob")["birth_profile"]["date_of_birth"] == "1990-01-01"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["_users"]["alice"][PREF_KEY]["version"] == 1
    assert stored["_users"]["alice"][PREF_KEY]["birth_profile"]["birth_city"] == "London"


def test_numerology_preserves_master_numbers_and_can_save(monkeypatch, tmp_path):
    _prefs_file(monkeypatch, tmp_path)
    update_profile("alice", {"date_of_birth": "2001-07-21"})
    result = calculate_numerology("alice", {"date": "2026-06-22", "label": "Test Day", "save": True})

    assert result["universal_day"] == 2
    assert result["life_path"] == 4
    assert result["personal_year"] == 11
    assert result["personal_month"] == 8
    assert result["personal_day"] == 3
    assert load_oracle("alice")["numerology_calculations"][0]["label"] == "Test Day"


def test_oracle_entries_and_delete_refusal(monkeypatch, tmp_path):
    _prefs_file(monkeypatch, tmp_path)
    add_gratitude("alice", {"grateful_for": ["health"], "action_receipt": "walked"})
    item = add_manifestation("alice", {
        "title": "Council Home",
        "statement": "I receive the right home with action.",
        "category": "housing",
    })
    updated = update_manifestation("alice", item["id"], {"status": "materialised"})
    add_sign("alice", {"date": "2026-06-16", "type": "angel_number", "value": "333"})
    add_important_date("alice", {"date": "2026-06-22", "label": "Reset day"})

    state = load_oracle("alice")
    assert state["gratitude_entries"][0]["grateful_for"] == ["health"]
    assert updated["status"] == "materialised"
    assert state["synchronicities"][0]["value"] == "333"
    assert state["important_dates"][0]["label"] == "Reset day"

    refused = asyncio.run(manage_oracle_tool(json.dumps({
        "action": "delete",
        "id": item["id"],
    }), "alice"))
    assert refused["exit_code"] == 1
    assert "delete" in refused["error"].lower()


def test_daily_reading_and_cosmic_calendar_are_honest(monkeypatch, tmp_path):
    _prefs_file(monkeypatch, tmp_path)
    reading = daily_reading("alice")
    calendar = cosmic_calendar("alice", target_date="2026-06-16")

    assert reading["action_receipt_prompt"]
    assert "pending" in reading["vedic_status"].lower()
    assert calendar["reference"] == "local_reference_data"
    assert calendar["next_mercury_retrograde"]["start"] == "2026-06-29"


def test_oracle_chat_routing_and_tool_policy():
    assert classify_tool_intent("Add gratitude that I got through today").category == "oracle"
    assert classify_tool_intent("Calculate numerology for 2026-06-22").category == "oracle"
    assert oracle_context_intent("What signs have I seen?")

    policy = build_effective_tool_policy(last_user_message="Add a manifestation for housing")
    assert policy.blocks("manage_memory")
    assert policy.blocks("manage_notes")
    assert not policy.blocks("manage_oracle")


def test_brain_retrieves_oracle_only_when_relevant(monkeypatch, tmp_path):
    _prefs_file(monkeypatch, tmp_path)
    add_sign("alice", {"date": "2026-06-16", "type": "angel_number", "value": "333", "context": "after housing paperwork"})
    service = VantaBrainService(_Memory(), _Docs())

    plain = service.retrieve("What should I do about work?", "alice")
    assert not any(snippet.source == "oracle" for snippet in plain.snippets)

    oracle = service.retrieve("What signs have I seen?", "alice", include_rag=False)
    assert any(snippet.source == "oracle" and "333" in snippet.text for snippet in oracle.snippets)


def test_oracle_static_wiring():
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    oracle = (ROOT / "static" / "js" / "oracle.js").read_text(encoding="utf-8")
    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="tool-oracle-btn"' in index
    assert 'data-command-center-action="oracle"' in index
    assert "import oracleModule from './js/oracle.js'" in app
    assert "/api/oracle" in oracle
    assert "localStorage" not in oracle
    assert ".oracle-modal" in style

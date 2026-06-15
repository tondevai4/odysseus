import asyncio
import json

from services import gym_log
from services.vanta_brain import VantaBrainService
from src.action_intents import (
    classify_tool_intent,
    destructive_gym_action,
    gym_context_intent,
)
from src.tool_policy import build_effective_tool_policy
from src.chat_processor import ChatProcessor


class _Memory:
    def get_memories(self, *args, **kwargs):
        return []


class _Docs:
    index = []
    rag_manager = None


def _prefs_file(tmp_path, monkeypatch):
    from routes import prefs_routes

    target = tmp_path / "prefs.json"
    monkeypatch.setattr(prefs_routes, "PREFS_FILE", str(target))
    return target


def test_parse_pasted_exercises():
    rows = gym_log.parse_exercises(
        "Leg Press — 100kg: 15 / 20 / 20; 107kg: 15\n"
        "Incline DB Press — 12kg: 12 / 10 / 8\n"
        "Unparsed note"
    )
    assert rows[0]["name"] == "Leg Press"
    assert rows[0]["sets"][-1] == {"weight": "107kg", "reps": 15}
    assert len(rows[1]["sets"]) == 3
    normalized = gym_log.normalize_entry({
        "date": "2026-06-15",
        "title": "Parsed workout",
        "raw_log": "Leg Press — 100kg: 15 / 20; 107kg: 15",
    })
    assert normalized["total_sets"] == 3
    assert normalized["total_reps"] == 50


def test_owner_scoped_add_update_and_append(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    alice = gym_log.add_workout("alice", {
        "date": "2026-06-15",
        "title": "Full-body strength",
        "duration": "59:52",
        "raw_log": "Leg Press — 100kg: 15 / 20; 107kg: 15",
    })
    gym_log.add_workout("bob", {
        "date": "2026-06-15",
        "title": "Bob private workout",
    })
    updated = gym_log.update_workout("alice", alice["id"], {"total_sets": 16})
    appended = gym_log.append_workout_note("alice", "2026-06-15", "Good form.")

    assert updated["total_sets"] == 16
    assert appended["notes"] == "Good form."
    assert gym_log.load_gym_log("alice")["entries"][0]["title"] == "Full-body strength"
    assert gym_log.load_gym_log("bob")["entries"][0]["title"] == "Bob private workout"


def test_chat_tool_add_list_filter_append_and_delete_refusal(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    added = asyncio.run(gym_log.manage_gym_log_tool(json.dumps({
        "action": "add",
        "date": "2026-06-15",
        "title": "Leg day",
        "details": "Leg Press — 100kg: 15 / 20 / 20; 107kg: 15",
    }), owner="alice"))
    listed = asyncio.run(gym_log.manage_gym_log_tool(json.dumps({
        "action": "list",
        "exercise": "leg press",
    }), owner="alice"))
    appended = asyncio.run(gym_log.manage_gym_log_tool(json.dumps({
        "action": "append_note",
        "date": "2026-06-15",
        "note": "No knee pain.",
    }), owner="alice"))
    refused = asyncio.run(gym_log.manage_gym_log_tool(
        '{"action":"delete","date":"2026-06-15"}',
        owner="alice",
    ))

    assert added["exit_code"] == 0
    assert listed["count"] == 1
    assert listed["entries"][0]["exercises"][0]["name"] == "Leg Press"
    assert appended["entry"]["notes"] == "No knee pain."
    assert refused["exit_code"] == 1
    assert "can't delete gym logs from chat" in refused["error"]


def test_gym_intents_and_tool_policy():
    for text in (
        "Log today's workout: Leg Press — 100kg: 15",
        "Create gym log for 15 Jun 2026: full body",
        "What was my last workout?",
        "What should I train next?",
        "Show my leg press progress.",
        "Add this to today's gym log: good form",
    ):
        assert gym_context_intent(text)
        assert classify_tool_intent(text).category == "gym"
    assert destructive_gym_action("Delete gym log for today") == "delete"
    policy = build_effective_tool_policy(last_user_message="What was my last workout?")
    assert policy.blocks("manage_memory")
    assert policy.blocks("manage_notes")
    assert not policy.blocks("manage_gym_log")


def test_brain_gym_scope_is_relevant_and_owner_scoped(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    gym_log.add_workout("alice", {
        "date": "2026-06-15",
        "title": "Full-body strength",
        "total_sets": 16,
        "total_reps": 157,
        "raw_log": "Leg Press — 100kg: 15 / 20; 107kg: 15",
    })
    gym_log.add_workout("bob", {
        "date": "2026-06-15",
        "title": "Bob private workout",
    })
    brain = VantaBrainService(_Memory(), _Docs())
    result = brain.retrieve(
        "Show my leg press progress",
        "alice",
        source_scope="gym",
    )
    assert result.snippets
    assert all(row.source == "gym" for row in result.snippets)
    text = result.context_text()
    assert "Leg Press" in text
    assert "Bob private workout" not in text


def test_empty_gym_brain_state(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    result = VantaBrainService(_Memory(), _Docs()).retrieve(
        "What was my last workout?",
        "alice",
        source_scope="gym",
    )
    assert result.snippets[0].metadata["status"] == "empty"
    assert "No gym workouts are saved yet" in result.snippets[0].text


def test_chat_uses_gym_only_scope_and_incognito_blocks_retrieval():
    class _Brain:
        def __init__(self):
            self.calls = []

        def retrieve(self, *args, **kwargs):
            from services.vanta_brain import BrainRetrieval

            self.calls.append(kwargs)
            return BrainRetrieval()

    brain = _Brain()
    processor = ChatProcessor(_Memory(), _Docs(), brain_service=brain)
    processor.build_context_preface(
        "What was my last workout?",
        None,
        owner="alice",
    )
    assert brain.calls[0]["source_scope"] == "gym"

    private_preface, _, _ = processor.build_context_preface(
        "Log today's workout: leg press",
        None,
        owner="alice",
        incognito=True,
    )
    assert len(brain.calls) == 1
    text = "\n".join(row["content"] for row in private_preface)
    assert "gym log actions are disabled in incognito/private mode" in text

    delete_preface, _, _ = processor.build_context_preface(
        "Delete gym log for today",
        None,
        owner="alice",
    )
    delete_text = "\n".join(row["content"] for row in delete_preface)
    assert "I can't delete gym logs from chat" in delete_text
    route_source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "routes" / "chat_routes.py"
    ).read_text(encoding="utf-8")
    assert 'disabled_tools.add("manage_gym_log")' in route_source

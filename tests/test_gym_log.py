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


def test_parse_garmin_summary_and_preserve_raw_text():
    raw = """Total Time 59:52
Work Time 31:46
Rest Time 28:06
Avg Heart Rate 127 bpm
Max Heart Rate 164 bpm
Primary Benefit Anaerobic Capacity
Resting Calories 107
Active Calories 515
Total Calories Burned 622
Est. Sweat Loss 417 ml
Total Reps 157
Total Sets 16
Avg Time/Set 1:59
Total Volume 0 lbs
Moderate 30 min
Vigorous 25 min
Total 80 min
Net Impact -7"""
    parsed = gym_log.parse_garmin_summary(raw)
    assert parsed["total_time"] == "59:52"
    assert parsed["avg_hr"] == 127
    assert parsed["primary_benefit"] == "Anaerobic Capacity"
    assert parsed["active_calories"] == 515
    assert parsed["estimated_sweat_loss_ml"] == 417
    assert parsed["intensity_minutes_total"] == 80
    assert parsed["body_battery_net_impact"] == -7
    entry = gym_log.normalize_entry({
        "date": "2026-06-15",
        "title": "Garmin strength",
        "raw_garmin_text": raw,
    })
    assert entry["duration"] == "59:52"
    assert entry["total_sets"] == 16
    assert entry["raw_garmin_text"] == raw


def test_live_session_add_edit_remove_and_finish(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    started = gym_log.start_session("alice", "Full-body strength")
    assert started["title"] == "Full-body strength"
    gym_log.add_session_set("alice", "Leg Press", "100kg", 15)
    gym_log.add_session_set("alice", "Leg Press", "100kg", 20)
    edited = gym_log.edit_session_set("alice", "Leg Press", 1, "107kg", 15)
    assert edited["exercises"][0]["sets"][1] == {"weight": "107kg", "reps": 15}
    trimmed = gym_log.delete_last_session_set("alice")
    assert len(trimmed["exercises"][0]["sets"]) == 1
    saved = gym_log.finish_session("alice", {
        "raw_garmin_text": "Active Calories 515\nPrimary Benefit Anaerobic Capacity",
    })
    state = gym_log.load_gym_log("alice")
    assert saved["total_sets"] == 1
    assert saved["active_calories"] == 515
    assert state["active_session"] is None
    assert state["entries"][0]["exercises"][0]["name"] == "Leg Press"


def test_existing_phase_nine_entry_remains_compatible(tmp_path, monkeypatch):
    target = _prefs_file(tmp_path, monkeypatch)
    from routes import prefs_routes

    prefs_routes._save_for_user("alice", {
        "gym-log-v1": {
            "version": 1,
            "entries": [{
                "id": "old",
                "date": "2026-06-14",
                "title": "Old workout",
                "duration": "45:00",
                "total_sets": 8,
                "total_reps": 80,
            }],
        },
    })
    state = gym_log.load_gym_log("alice")
    assert target.exists()
    assert state["entries"][0]["duration"] == "45:00"
    assert state["entries"][0]["total_time"] == "45:00"
    assert state["active_session"] is None


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


def test_chat_tool_live_session_and_garmin_update(tmp_path, monkeypatch):
    _prefs_file(tmp_path, monkeypatch)
    started = asyncio.run(gym_log.manage_gym_log_tool(
        '{"action":"start_session","title":"Full-body strength"}',
        owner="alice",
    ))
    added = asyncio.run(gym_log.manage_gym_log_tool(json.dumps({
        "action": "add_set",
        "exercise": "Leg Press",
        "weight": "100kg",
        "reps": 15,
    }), owner="alice"))
    finished = asyncio.run(gym_log.manage_gym_log_tool(
        '{"action":"finish_session"}',
        owner="alice",
    ))
    updated = asyncio.run(gym_log.manage_gym_log_tool(json.dumps({
        "action": "update_garmin",
        "date": finished["entry"]["date"],
        "raw_garmin_text": "Avg HR 127\nMax HR 164\nActive Calories 515",
    }), owner="alice"))

    assert started["exit_code"] == 0
    assert added["active_session"]["exercises"][0]["sets"][0]["reps"] == 15
    assert finished["entry"]["total_sets"] == 1
    assert updated["entry"]["avg_hr"] == 127
    assert updated["entry"]["active_calories"] == 515


def test_gym_intents_and_tool_policy():
    for text in (
        "Log today's workout: Leg Press — 100kg: 15",
        "Create gym log for 15 Jun 2026: full body",
        "What was my last workout?",
        "What should I train next?",
        "Show my leg press progress.",
        "Add this to today's gym log: good form",
        "Start a full-body workout.",
        "Add Leg Press 100kg x 15.",
        "Finish workout.",
        "Add Garmin stats to today's workout: avg HR 127.",
        "What did Garmin say about my last workout?",
        "How hard was that session?",
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

from core.models import ChatMessage
from src.action_intents import (
    classify_tool_intent,
    classify_tool_intent_with_context,
    note_followup_turn,
)
from src.chat_processor import ChatProcessor


class _Memory:
    def get_memories(self, *args, **kwargs):
        return []


class _Docs:
    pass


class _FailingBrain:
    def retrieve(self, *args, **kwargs):
        raise AssertionError("Notes turns must not retrieve general Brain context")


def _pending_history():
    return [
        ChatMessage("user", "Add to notes: bench press 80kg for five reps"),
        ChatMessage("assistant", "What title should I use for the note?"),
        ChatMessage("user", "New note gym log with date please."),
        ChatMessage("assistant", "Do you want it exact as-is or formatted nicely?"),
        ChatMessage("user", "Format nicely."),
        ChatMessage(
            "assistant",
            "Gym Log — 15 Jun 2026\n\nBench press: 80 kg x 5 reps",
        ),
    ]


def test_direct_new_note_routes_to_notes():
    intent = classify_tool_intent("New note gym log with date please")
    assert intent.needs_tools is True
    assert intent.category == "notes"


def test_confirmation_phrases_continue_pending_note_workflow():
    history = _pending_history()
    for phrase in (
        "Create then",
        "go ahead",
        "yes",
        "do it",
        "save it",
        "add it",
        "make the note",
        "create it",
    ):
        intent = classify_tool_intent_with_context(phrase, history)
        assert intent.needs_tools is True
        assert intent.category == "notes"


def test_missing_title_reply_continues_notes_but_unrelated_yes_does_not():
    title_history = [
        ChatMessage("user", "Add to notes: bought protein powder"),
        ChatMessage("assistant", "What title should I use for the note?"),
    ]
    assert note_followup_turn("Gym Log", title_history) is True
    assert classify_tool_intent_with_context("Gym Log", title_history).category == "notes"
    assert classify_tool_intent_with_context("yes", []).needs_tools is False


def test_note_followup_suppresses_brain_and_adds_execution_policy():
    processor = ChatProcessor(_Memory(), _Docs(), brain_service=_FailingBrain())
    preface, rag_sources, _ = processor.build_context_preface(
        "Create then",
        None,
        owner="alice",
        note_action_turn=True,
    )
    text = "\n".join(message["content"] for message in preface)
    assert "Recover the pending" in text
    assert "`manage_notes`, never `manage_memory`" in text
    assert "Do not claim Notes are unavailable" in text
    assert rag_sources == []
    assert processor._last_brain_sources == []


def test_incognito_blocks_pending_note_execution():
    processor = ChatProcessor(_Memory(), _Docs(), brain_service=_FailingBrain())
    preface, _, _ = processor.build_context_preface(
        "Create then",
        None,
        owner="alice",
        incognito=True,
        note_action_turn=True,
    )
    text = "\n".join(message["content"] for message in preface)
    assert "note actions are disabled in incognito/private mode" in text

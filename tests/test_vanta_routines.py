from services.vanta_brain import BrainRetrieval, BrainSnippet
from src.chat_processor import ChatProcessor
from src.vanta_core import VANTA_CORE_PROMPT
from src.vanta_routines import (
    ROUTINES,
    resolve_active_vanta_routine,
    resolve_vanta_routine,
)


class _Memory:
    def load(self, owner=None):
        return []


class _Docs:
    rag_manager = None


class _Brain:
    def __init__(self):
        self.queries = []

    def retrieve(self, query, owner, **kwargs):
        self.queries.append((query, owner, kwargs))
        return BrainRetrieval(snippets=[
            BrainSnippet("note", "n1", "Today", "CSCS application deadline", 0.8),
        ])


class _Message:
    def __init__(self, role, content):
        self.role = role
        self.content = content

    def get(self, key, default=None):
        return getattr(self, key, default)


class _Session:
    def __init__(self, history):
        self.history = history


def test_all_four_explicit_routine_intents_are_recognized():
    cases = {
        "Start my Morning Command Brief.": "morning-command-brief",
        "Run my night shutdown review": "night-shutdown-review",
        "I'm overwhelmed. Start Panic / Brain Shutdown Mode.": "panic-brain-shutdown",
        "Start Urge Reset Mode.": "urge-reset",
    }
    for message, expected in cases.items():
        assert resolve_vanta_routine(message).id == expected


def test_ordinary_time_words_do_not_trigger_routines():
    for message in (
        "Good morning, what is the weather?",
        "I worked the night shift.",
        "I have an urge to learn carpentry.",
    ):
        assert resolve_vanta_routine(message) is None


def test_morning_and_night_continue_for_one_immediate_answer_turn():
    session = _Session([
        _Message("user", "Start my Morning Command Brief."),
        _Message("assistant", "What are your check-in numbers?"),
        _Message("user", "Energy 7, mood 6, slept well."),
    ])
    assert resolve_active_vanta_routine("Energy 7, mood 6, slept well.", session).id == (
        "morning-command-brief"
    )

    expired = _Session([
        _Message("user", "Start my Night Shutdown Review."),
        _Message("assistant", "What was completed?"),
        _Message("user", "Gym and housing admin done."),
        _Message("assistant", "Here is the shutdown summary."),
        _Message("user", "Explain a Python dictionary."),
    ])
    assert resolve_active_vanta_routine("Explain a Python dictionary.", expired) is None


def test_routine_prompts_preserve_core_approval_and_direct_action_boundaries():
    assert len(ROUTINES) == 4
    for routine in ROUTINES:
        assert "direct" in routine.prompt.lower()
        assert "explicit approval" in routine.prompt.lower()
        assert "Never invent" in routine.prompt


def test_chat_adds_trusted_routine_and_expands_brain_query():
    brain = _Brain()
    processor = ChatProcessor(_Memory(), _Docs(), brain_service=brain)

    preface, _, _ = processor.build_context_preface(
        "Start my Morning Command Brief.",
        None,
        owner="tony",
    )

    assert preface[0]["content"] == VANTA_CORE_PROMPT
    routine_messages = [
        row for row in preface
        if row["role"] == "system" and "Active Vanta routine" in row["content"]
    ]
    assert len(routine_messages) == 1
    assert "energy 1-10" in routine_messages[0]["content"]
    assert "housing bids" in brain.queries[0][0]
    assert brain.queries[0][1] == "tony"
    assert any(
        row["role"] == "user" and "Vanta Brain retrieval" in row["content"]
        for row in preface
    )


def test_incognito_keeps_routine_and_core_but_disables_brain():
    brain = _Brain()
    processor = ChatProcessor(_Memory(), _Docs(), brain_service=brain)

    preface, _, _ = processor.build_context_preface(
        "Start Urge Reset Mode.",
        None,
        owner="tony",
        incognito=True,
    )

    assert preface[0]["content"] == VANTA_CORE_PROMPT
    assert any("Active Vanta routine: Urge Reset Mode" in row["content"] for row in preface)
    assert not brain.queries
    assert all("Vanta Brain retrieval" not in row["content"] for row in preface)

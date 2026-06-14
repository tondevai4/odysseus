"""Trusted, read-only command routine definitions for Vanta chat."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class VantaRoutine:
    id: str
    label: str
    prompt: str
    retrieval_terms: str
    patterns: tuple[str, ...]

    def retrieval_query(self, user_message: str) -> str:
        return f"{user_message}\nRelevant routine topics: {self.retrieval_terms}"


_SHARED_BOUNDARY = (
    "Use Vanta Core tone. Use retrieved Vanta Brain context only when relevant, "
    "and name its source labels naturally. Give a direct, practical action plan, "
    "not generic advice. Never invent personal facts or completion status. Never "
    "message anyone, spend money, delete data, or change an external service "
    "without Tony's explicit approval."
)


ROUTINES = (
    VantaRoutine(
        id="morning-command-brief",
        label="Morning Command Brief",
        prompt=(
            "Run the Morning Command Brief. Ask for any missing answers in one "
            "compact batch: energy 1-10, mood 1-10, sleep quality, main deadline, "
            "one avoided task, gym/body action, job/money action, housing/admin "
            "action, room/life-admin action, learning/spiritual action, and a "
            "fatherhood action only if relevant. Once answered, produce a short "
            "prioritized Now / Next / Later plan. "
            + _SHARED_BOUNDARY
        ),
        retrieval_terms=(
            "today deadlines priorities avoiding sleep mood energy gym body job "
            "work money housing bids admin room learning spiritual fatherhood"
        ),
        patterns=(
            r"\bmorning\s+(?:command\s+)?brief\b",
            r"\bstart\s+(?:my\s+)?morning\s+(?:command\s+)?brief\b",
        ),
    ),
    VantaRoutine(
        id="night-shutdown-review",
        label="Night Shutdown Review",
        prompt=(
            "Run the Night Shutdown Review. Check, without judgment: gym/body, "
            "job/money, housing/admin, room improvement, learning/spiritual, "
            "porn/alcohol/doomscrolling honestly avoided or logged, and a "
            "fatherhood action only if relevant. Ask what carries to tomorrow. "
            "Then give a concise shutdown summary and tomorrow carry-over list. "
            + _SHARED_BOUNDARY
        ),
        retrieval_terms=(
            "today completed gym body job work money housing admin room learning "
            "spiritual fatherhood porn alcohol doomscrolling tomorrow carry over"
        ),
        patterns=(
            r"\bnight\s+shutdown(?:\s+review)?\b",
            r"\bshutdown\s+review\b",
            r"\bend\s+of\s+day\s+review\b",
        ),
    ),
    VantaRoutine(
        id="panic-brain-shutdown",
        label="Panic / Brain Shutdown Mode",
        prompt=(
            "Run Panic / Brain Shutdown Mode immediately. Do not create a huge "
            "plan and do not begin with a questionnaire. Give a tiny ordered reset: "
            "water; wash face or shower; clean one visible area; ten press-ups or "
            "a short walk; one small admin/job action; phone away; no porn; no "
            "alcohol; bed on time. Reduce it further if Tony sounds overloaded. "
            "Be steady, concrete, and non-diagnostic. If he describes immediate "
            "danger or self-harm, prioritize urgent human or emergency support. "
            + _SHARED_BOUNDARY
        ),
        retrieval_terms=(
            "overwhelmed panic shutdown reset smallest next action job admin room "
            "sleep phone alcohol porn wellbeing"
        ),
        patterns=(
            r"\bpanic\s+mode\b",
            r"\bbrain\s+shutdown(?:\s+mode)?\b",
            r"\bpanic\s*/\s*brain\s+shutdown\b",
            r"\bi(?:'m| am)\s+overwhelmed\b.*\b(?:reset|shutdown|panic)\b",
        ),
    ),
    VantaRoutine(
        id="urge-reset",
        label="Urge Reset Mode",
        prompt=(
            "Run Urge Reset Mode immediately for porn, alcohol, doomscrolling, or "
            "late-night phone urges. Lead with a physical interruption, change of "
            "room or environment, water, and one short replacement action. Put the "
            "phone across the room, outside the bedroom, in a drawer away from bed, "
            "or plugged in somewhere Tony must stand up to reach. Never suggest "
            "putting it under a pillow, beside the bed, or within reach from bed. "
            "Keep it brief. Use correction over self-hate, "
            "with no shame spiral or moralizing. If alcohol withdrawal or immediate "
            "physical danger is described, advise appropriate urgent medical help. "
            + _SHARED_BOUNDARY
        ),
        retrieval_terms=(
            "urge reset porn alcohol doomscrolling late night phone triggers "
            "replacement action sleep habits wellbeing"
        ),
        patterns=(
            r"\burge\s+reset(?:\s+mode)?\b",
            r"\breset\s+(?:this|the|my)\s+urge\b",
            r"\b(?:porn|alcohol|doomscrolling|phone)\s+urge\b",
        ),
    ),
)


def resolve_vanta_routine(message: str) -> Optional[VantaRoutine]:
    """Return a routine only for a clear, explicit routine intent."""
    normalized = " ".join(str(message or "").lower().split())
    if not normalized:
        return None
    for routine in ROUTINES:
        if any(re.search(pattern, normalized) for pattern in routine.patterns):
            return routine
    return None


def resolve_active_vanta_routine(
    message: str,
    session: Any = None,
) -> Optional[VantaRoutine]:
    """Resolve an explicit routine or one immediate check-in follow-up."""
    routine = resolve_vanta_routine(message)
    if routine:
        return routine

    history = list(getattr(session, "history", None) or [])
    # The current user message is already appended before context is built.
    # Inspect only the three entries immediately before it so a check-in can
    # consume one answer turn without making the routine sticky.
    for row in reversed(history[-4:-1]):
        role = row.get("role") if hasattr(row, "get") else getattr(row, "role", "")
        if role != "user":
            continue
        content = row.get("content", "") if hasattr(row, "get") else getattr(row, "content", "")
        previous = resolve_vanta_routine(str(content or ""))
        if previous and previous.id in {
            "morning-command-brief",
            "night-shutdown-review",
        } and _looks_like_checkin_answer(message, previous.id):
            return previous
        break
    return None


def _looks_like_checkin_answer(message: str, routine_id: str) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    if not normalized:
        return False
    if routine_id == "morning-command-brief":
        signals = (
            "energy", "mood", "sleep", "slept", "deadline", "avoiding",
            "gym", "body", "job", "work", "money", "housing", "bid",
            "admin", "room", "learning", "spiritual", "fatherhood",
        )
        return any(signal in normalized for signal in signals) or bool(
            re.search(r"\b(?:energy|mood)\s*(?:is|:)?\s*\d{1,2}\b", normalized)
        )
    if routine_id == "night-shutdown-review":
        signals = (
            "done", "completed", "missed", "carried", "carry", "tomorrow",
            "gym", "body", "job", "work", "money", "housing", "bid",
            "admin", "room", "learning", "spiritual", "fatherhood",
            "porn", "alcohol", "doomscroll",
        )
        return any(signal in normalized for signal in signals)
    return False

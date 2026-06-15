"""Lightweight routing hints for chat requests that need tools.

These patterns are intentionally conservative. They only promote plain chat
to agent mode when the user asks the assistant to take an action, not when the
user asks how a feature works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Pattern, Sequence


@dataclass(frozen=True)
class ToolIntent:
    """A cheap, deterministic chat-to-agent routing decision."""

    needs_tools: bool
    category: str = ""
    reason: str = ""


_NOTE_DESTRUCTIVE_RE = re.compile(
    r"\b(delete|remove|archive|overwrite|replace|clear|reset|rename)\b"
    r".{0,180}\bnotes?\b",
    re.I,
)
_NOTE_CONFIRMATION_RE = re.compile(
    r"^\s*(?:yes|yep|yeah|ok(?:ay)?|sure|create then|create it|go ahead|"
    r"do it|save it|add it|make the note)\s*[.!]?\s*$",
    re.I,
)
_NOTE_FORMAT_FOLLOWUP_RE = re.compile(
    r"^\s*(?:format (?:it )?nicely|make (?:it )?(?:neat|clean|tidy)|"
    r"(?:keep|use) (?:it )?exact(?:ly)? as[- ]is)\s*[.!]?\s*$",
    re.I,
)
_NOTE_WORKFLOW_RE = re.compile(
    r"\badd\s+to\s+notes?\b|"
    r"\b(?:create|make|new)\b.{0,100}\bnotes?\b|"
    r"\bnotes?\s+(?:called|named)\b",
    re.I,
)
_NOTE_TITLE_PROMPT_RE = re.compile(
    r"\b(?:what|which|provide|give me|need)\b.{0,80}\btitle\b|"
    r"\btitle\b.{0,80}\b(?:note|use|want|call)\b",
    re.I,
)


_ACTION_QUESTION = r"\b(?:can|could|would|will)\s+you\s+"
_ACTION_FOLLOWUP = (
    r"\b(?:you\s+should\s+be\s+able\s+to|"
    r"(?:can|could|would|will|should)\s+you|"
    r"you\s+(?:can|could|would|will|should|need\s+to|have\s+to))\s+"
)
_PLEASE = r"^\s*(?:(?:please|ok(?:ay)?|alright|right|sure|cool|great|thanks)[\s,.!-]+)*"

_CALENDAR_ACTION = (
    r"(?:add|adding|create|creating|recreate|recreating|schedule|scheduling|"
    r"reschedule|rescheduling|book|booking|put|set\s+up|make|making|"
    r"delete|deleting|remove|removing|cancel|cancelling|canceling)"
)
_CALENDAR_THING = r"(?:calendar|calendar\s+(?:entry|item)|event|meeting|appointment|entry|call)"
_CALENDAR_READ_THING = r"(?:calendar|schedule|events?|meetings?|appointments?|classes?)"
_EXPLANATORY_PREFIX = re.compile(
    r"^\s*(?:how\s+(?:do|can)\s+i|can\s+you\s+explain|what\s+about|tell\s+me\s+how|show\s+me\s+how)\b",
    re.I,
)

_PANEL = (
    r"(?:calendar|notes?|inbox|email|mail|documents?|docs|library|gallery|"
    r"settings|cookbook|sessions?|chats?|skills|memories|memory|brain)"
)

_ROUTING_PATTERNS: tuple[tuple[str, str, Pattern[str]], ...] = tuple(
    (category, reason, re.compile(pattern, re.I))
    for category, reason, pattern in (
        # Calendar/event creation. Covers "Can you add an entry to my
        # calendar?", imperatives like "add lunch to my calendar", and
        # follow-ups such as "you should be able to create that event now".
        ("calendar", "assistant calendar action request", rf"{_ACTION_QUESTION}{_CALENDAR_ACTION}\b.{{0,120}}\b{_CALENDAR_THING}\b"),
        ("calendar", "calendar follow-up action request", rf"{_ACTION_FOLLOWUP}{_CALENDAR_ACTION}\b.{{0,120}}\b{_CALENDAR_THING}\b"),
        ("calendar", "calendar imperative action request", rf"{_PLEASE}{_CALENDAR_ACTION}\b.{{0,120}}\b{_CALENDAR_THING}\b"),
        ("calendar", "calendar target action request", rf"{_PLEASE}{_CALENDAR_ACTION}\b.{{0,120}}\b(?:to|on|in|into|for)\s+(?:my\s+|the\s+|this\s+)?calendar\b"),
        ("calendar", "calendar item action request", rf"{_PLEASE}{_CALENDAR_ACTION}\s+(?:it\s+)?(?:a\s+|an\s+)?(?:calendar\s+)?(?:event|meeting|appointment|entry|item|call)\b"),
        ("calendar", "calendar target action request", rf"\b{_CALENDAR_ACTION}\b.{{0,120}}\b(?:to|on|in|into|for)\s+(?:my\s+|the\s+|this\s+)?calendar\b"),
        ("calendar", "put item on calendar request", r"\bput\s+.+\bon\s+(?:my\s+)?calendar\b"),

        # Calendar/event lookup. A question such as "Do I have Taekwondo
        # classes this week?" needs the calendar tool; plain chat cannot know.
        ("calendar", "calendar lookup request", rf"\b(?:list|show|check|find)\b.{{0,120}}\b(?:my\s+|the\s+)?(?:upcoming|next|today'?s?|tomorrow'?s?|this\s+week'?s?)\b.{{0,120}}\b{_CALENDAR_READ_THING}\b"),
        ("calendar", "calendar lookup question", rf"\b(?:what|which)\b.{{0,120}}\b(?:upcoming|next|today'?s?|tomorrow'?s?|this\s+week'?s?)\b.{{0,120}}\b{_CALENDAR_READ_THING}\b"),
        ("calendar", "calendar availability question", rf"\bdo\s+i\s+have\b.{{0,120}}\b(?:upcoming|next|today|tomorrow|this\s+week)\b.{{0,120}}\b{_CALENDAR_READ_THING}\b"),
        ("calendar", "calendar agenda question", r"\bwhat(?:'s| is)\s+on\s+(?:my\s+)?calendar\b"),
        ("calendar", "next calendar item question", r"\bwhen\s+(?:is|are)\s+(?:my\s+)?next\s+(?:event|meeting|appointment|class)\b"),

        # Notes, todos, checklists, and reminders.
        ("notes", "reminder request", r"\bremind\s+me\b"),
        ("notes", "assistant note/todo action request", rf"{_ACTION_QUESTION}(?:add|create|make|take|jot|write\s+down|set)\b.{{0,120}}\b(?:note|todo|task|checklist|reminder)\b"),
        ("notes", "note/todo imperative request", rf"{_PLEASE}(?:add|create|make)\s+(?:a\s+|an\s+)?(?:todo|task|reminder|note|checklist)\b"),
        ("notes", "named note creation request", rf"{_PLEASE}(?:make|create)\s+(?:me\s+)?(?:a\s+)?(?:checklist\s+)?note\s+(?:called|named)\b"),
        ("notes", "new note request", rf"{_PLEASE}new\s+(?:checklist\s+)?note\b"),
        ("notes", "append to named note request", rf"{_PLEASE}(?:add|append|put)\b.{{0,160}}\bto\s+(?:a\s+|my\s+|the\s+)?note\s+(?:called|named)\b"),
        ("notes", "protected note mutation request", rf"{_PLEASE}(?:delete|remove|archive|overwrite|replace|clear|reset|rename)\b.{{0,180}}\bnotes?\b"),
        ("notes", "take note request", rf"{_PLEASE}(?:take|jot|write\s+down)\s+(?:a\s+|an\s+)?note\b"),
        ("notes", "add item to notes/todo request", rf"{_PLEASE}(?:add|jot|write\s+down)\b.{{0,120}}\b(?:to|in|into)\s+(?:my\s+|the\s+)?(?:todo(?:\s+list)?|task\s+list|notes?|checklist)\b"),
        ("notes", "set reminder request", rf"{_PLEASE}set\s+(?:a\s+)?reminder\b"),
        ("notes", "assistant reminder request", rf"{_ACTION_QUESTION}set\s+(?:a\s+)?reminder\b"),

        # Reading List mutations and state lookups. These must reach the
        # dedicated owner-scoped tool rather than ambient memory.
        ("reading", "add reading-list item", rf"{_PLEASE}(?:add|put)\b.{{0,140}}\b(?:reading\s+list|reading\s+shelf)\b"),
        ("reading", "update reading-list status", rf"{_PLEASE}mark\b.{{0,140}}\b(?:as\s+)?(?:reading|finished|paused|want(?:ing)?\s+to\s+read)\b"),
        ("reading", "update reading progress", rf"{_PLEASE}(?:set|update)\s+(?:my\s+)?progress\s+on\b.{{1,180}}\bto\b.{{1,160}}"),
        ("reading", "append reading note", rf"{_PLEASE}add\s+(?:this\s+|a\s+reading\s+)?note\s+to\b.{{0,220}}"),
        ("reading", "current reading-list lookup", r"\bwhat\s+am\s+i\s+reading\b"),
        ("reading", "reading-list recommendation lookup", r"\bwhat\s+should\s+i\s+read(?:\s+tonight)?\b"),

        # Email actions.
        ("email", "assistant email action request", rf"{_ACTION_QUESTION}(?:send|write|reply|email|message|archive|delete|mark)\b.{{0,120}}\b(?:emails?|mail|messages?|inbox|unread|read)\b"),
        ("email", "send/write/reply email request", rf"{_PLEASE}(?:send|write|reply)\b.{{0,120}}\b(?:emails?|mail|messages?)\b"),
        ("email", "archive/delete/mark email request", rf"{_PLEASE}(?:archive|delete|mark)\b.{{0,120}}\b(?:emails?|mail|messages?|inbox)\b"),
        ("email", "email composition request", r"\b(?:send|write|reply)\s+(?:an?\s+)?(?:email|message|mail)\b"),
        ("email", "email contact request", r"\bemail\s+\w+\b"),
        ("email", "check inbox request", r"\bcheck\s+(?:my\s+)?(?:email|inbox|mail)\b"),
        ("email", "unread email request", r"\bunread\s+(?:email|mail)s?\b"),

        # UI/control-plane actions that should open panels or flip toggles.
        ("ui", "open/show panel request", rf"{_PLEASE}(?:open|show|bring\s+up)\s+(?:me\s+)?(?:my\s+|the\s+)?{_PANEL}\b"),
        ("ui", "tool or feature toggle request", r"\b(?:disable|enable|turn\s+(?:on|off))\s+(?:the\s+)?(?:shell|search|web|browser|documents?|memory|skills|images?|calendar|email|mail|research|incognito)\b"),

        # Deep research jobs, not quick conceptual mentions of research.
        ("research", "deep research imperative request", rf"{_PLEASE}(?:research|deep\s+dive|look\s+into|investigate)\s+.+"),
        ("research", "assistant deep research request", rf"{_ACTION_QUESTION}(?:research|do\s+research|deep\s+dive|look\s+into|investigate)\s+.+"),

        # Shell / remote-host intent.
        ("shell", "ssh request", r"\bssh\s+(?:in)?to\b"),
        ("shell", "ssh target request", r"\bssh\s+\w+"),
        ("shell", "remote command request", r"\b(run|execute)\s+.{1,40}\bon\s+\w+"),
        ("shell", "assistant command execution request", r"\b(can|could|please|would)\s+you\s+(run|execute|exec)\b"),
        # Shell verbs only count in imperative position (start of message,
        # optionally after "please") or as a "can you ..." request. A bare
        # word match promoted informational questions ("What does the grep
        # command do?") and incidental uses ("My cat ate my homework").
        ("shell", "imperative shell command request", rf"{_PLEASE}(deploy|build|install|restart|reboot|kill|tail|grep|cat|ls|cd|cp|mv|rm)\b\s+\S+"),
        ("shell", "assistant shell command request", rf"{_ACTION_QUESTION}(deploy|build|install|restart|reboot|kill|tail|grep|cat|ls|cd|cp|mv|rm)\b\s+\S+"),
        ("shell", "system/file check request", r"\b(check|see)\s+(if|whether|what)\s+.{1,40}\b(running|process|service|port|file|exists?)\b"),
    )
)

_TOOL_INTENT_PATTERNS: tuple[Pattern[str], ...] = tuple(
    pattern for _, _, pattern in _ROUTING_PATTERNS
)


def classify_tool_intent(text: str) -> ToolIntent:
    """Classify whether a chat message should be promoted to agent mode."""
    if not text:
        return ToolIntent(False, reason="empty message")
    if _EXPLANATORY_PREFIX.search(text):
        return ToolIntent(False, reason="explanatory feature question")
    for category, reason, pattern in _ROUTING_PATTERNS:
        if pattern.search(text):
            return ToolIntent(True, category=category, reason=reason)
    return ToolIntent(False, reason="no tool-action pattern matched")


def _message_text(message: Any) -> str:
    if hasattr(message, "get"):
        return str(message.get("content", "") or "")
    return str(getattr(message, "content", "") or "")


def pending_note_workflow(messages: Sequence[Any], limit: int = 10) -> bool:
    """Return whether recent history contains an unfinished Notes workflow."""
    recent = list(messages or [])[-limit:]
    saw_note_request = any(
        str(message.get("role", "") if hasattr(message, "get") else getattr(message, "role", "")).lower() == "user"
        and _NOTE_WORKFLOW_RE.search(_message_text(message))
        for message in recent
    )
    if not saw_note_request:
        return False
    return any(
        str(message.get("role", "") if hasattr(message, "get") else getattr(message, "role", "")).lower() == "assistant"
        and re.search(r"\b(?:format|formatted|draft|note|title|save|create|as-is)\b", _message_text(message), re.I)
        for message in recent
    )


def note_followup_turn(text: str, messages: Sequence[Any]) -> bool:
    """Recognize a short follow-up that continues a pending Notes action."""
    if not pending_note_workflow(messages):
        return False
    if _NOTE_CONFIRMATION_RE.match(text or "") or _NOTE_FORMAT_FOLLOWUP_RE.match(text or ""):
        return True
    recent = list(messages or [])
    if recent:
        latest = recent[-1]
        role = latest.get("role", "") if hasattr(latest, "get") else getattr(latest, "role", "")
        if str(role).lower() == "assistant" and _NOTE_TITLE_PROMPT_RE.search(_message_text(latest)):
            return bool((text or "").strip())
    return False


def classify_tool_intent_with_context(text: str, messages: Sequence[Any]) -> ToolIntent:
    """Classify a turn, recovering short Notes follow-ups from chat history."""
    direct = classify_tool_intent(text)
    if direct.needs_tools:
        return direct
    if note_followup_turn(text, messages):
        return ToolIntent(True, category="notes", reason="pending Notes workflow follow-up")
    return direct


def message_needs_tools(text: str, patterns: Iterable[Pattern[str]] = _TOOL_INTENT_PATTERNS) -> bool:
    """Return True when a plain chat message should be promoted to agent mode."""
    if not text:
        return False
    if _EXPLANATORY_PREFIX.search(text):
        return False
    if patterns is _TOOL_INTENT_PATTERNS:
        return classify_tool_intent(text).needs_tools
    return any(pattern.search(text) for pattern in patterns)


def note_management_intent(text: str) -> bool:
    """Return whether the turn is an actionable Notes request."""
    return classify_tool_intent(text).category == "notes"


def reading_context_intent(text: str) -> bool:
    """Return whether a turn is specifically about the Reading List/books."""
    normalized = " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))
    tokens = set(normalized.split())
    if tokens & {"reading", "book", "books", "bookshelf"}:
        return True
    return any(phrase in normalized for phrase in (
        "what am i reading",
        "what should i read",
        "current book",
        "reading list",
        "reading shelf",
        "my progress on",
        "add this note to",
    ))


def reading_management_intent(text: str) -> bool:
    """Return whether the turn asks to mutate the Reading List."""
    return classify_tool_intent(text).category == "reading"


def destructive_note_action(text: str) -> str:
    """Return the destructive Notes verb, or an empty string."""
    match = _NOTE_DESTRUCTIVE_RE.search(text or "")
    return match.group(1).lower() if match else ""

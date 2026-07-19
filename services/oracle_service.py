"""Owner-scoped STRNOS Oracle preferences and local calculations."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from routes.prefs_routes import _load_for_user, _save_for_user
from src.astrology.engine import get_birth_chart, get_transits, is_mercury_retrograde

PREF_KEY = "strnos-oracle-v1"

MANIFESTATION_CATEGORIES = {"housing", "money", "apprenticeship", "daughter", "peace", "creativity", "love", "custom"}
MANIFESTATION_STATUSES = {"active", "materialised", "released", "paused"}
SIGN_TYPES = {"angel_number", "date", "dream", "tarot", "coincidence", "other"}
IMPORTANT_DATE_TYPES = {"personal", "housing", "money", "relationship", "work", "spiritual", "custom"}

MERCURY_RETROGRADE_PERIODS = [
    {"start": "2026-02-26", "end": "2026-03-20", "label": "Mercury retrograde"},
    {"start": "2026-06-29", "end": "2026-07-23", "label": "Mercury retrograde"},
    {"start": "2026-10-24", "end": "2026-11-13", "label": "Mercury retrograde"},
    {"start": "2027-02-09", "end": "2027-03-03", "label": "Mercury retrograde"},
    {"start": "2027-06-10", "end": "2027-07-04", "label": "Mercury retrograde"},
    {"start": "2027-10-07", "end": "2027-10-28", "label": "Mercury retrograde"},
    {"start": "2028-01-24", "end": "2028-02-24", "label": "Mercury retrograde"},
    {"start": "2028-05-21", "end": "2028-06-24", "label": "Mercury retrograde"},
    {"start": "2028-09-19", "end": "2028-10-11", "label": "Mercury retrograde"},
    {"start": "2029-01-07", "end": "2029-01-27", "label": "Mercury retrograde"},
    {"start": "2029-05-01", "end": "2029-05-25", "label": "Mercury retrograde"},
    {"start": "2029-09-02", "end": "2029-09-24", "label": "Mercury retrograde"},
    {"start": "2029-12-22", "end": "2030-01-11", "label": "Mercury retrograde"},
    {"start": "2030-04-12", "end": "2030-05-06", "label": "Mercury retrograde"},
    {"start": "2030-08-15", "end": "2030-09-08", "label": "Mercury retrograde"},
    {"start": "2030-12-05", "end": "2030-12-25", "label": "Mercury retrograde"},
]


class OracleError(ValueError):
    """Safe Oracle validation error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _date_text(value: Any) -> str:
    text = _text(value, 20)
    if not text:
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise OracleError("Use dates as YYYY-MM-DD.")


def _list_text(value: Any, *, limit: int = 10, item_limit: int = 300) -> List[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r",|\n", value) if part.strip()]
    elif isinstance(value, list):
        parts = value
    else:
        parts = []
    return [_text(part, item_limit) for part in parts[:limit] if _text(part, item_limit)]


def _id(value: Any, prefix: str) -> str:
    return _text(value, 100) or f"{prefix}-{uuid.uuid4()}"


def _empty_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "display_name": "",
        "preferred_names": [],
        "birth_profile": {
            "full_name": "",
            "date_of_birth": "",
            "time_of_birth": "",
            "birth_city": "",
            "birth_country": "",
            "timezone": "",
            "preferred_system": "vedic",
            "ayanamsa": "lahiri",
            "house_system": "whole_sign",
            "manual_placements": "",
            "notes": "",
        },
        "spiritual_preferences": {
            "belief_style": [],
            "tone": "grounded_mystic",
            "strictness": "direct",
            "manifestation_style": ["action_receipts"],
            "avoid_tone": ["fluffy", "fake-positive", "generic CoStar-style"],
            "vedic_first": True,
            "avoid_guaranteed_predictions": True,
            "always_include_action_receipt": True,
            "include_numerology": True,
        },
        "manifestation_categories": [],
        "saved_readings": [],
        "daily_entries": [],
        "manifestations": [],
        "gratitude_entries": [],
        "synchronicities": [],
        "important_dates": [],
        "numerology_calculations": [],
        "manual_vedic_notes": {},
        "meta": {},
    }


def _owner_seed_state() -> Dict[str, Any]:
    state = _empty_state()
    state["display_name"] = "Tony"
    state["preferred_names"] = ["Boss", "Tony"]
    state["manifestation_categories"] = ["housing", "money", "apprenticeship", "daughter", "peace", "creativity"]
    state["meta"] = {"seeded_by": "owner_default_seed", "seeded_scope": "current_authenticated_user", "ephemeris_status": "pending_manual_vedic_notes_only"}
    state["birth_profile"].update({
        "full_name": "Tony",
        "date_of_birth": "2001-07-21",
        "time_of_birth": "20:00",
        "birth_city": "Harare",
        "birth_country": "Zimbabwe",
        "timezone": "Africa/Harare",
        "preferred_system": "vedic",
        "ayanamsa": "lahiri",
        "house_system": "whole_sign",
    })
    state["spiritual_preferences"].update({
        "belief_style": ["universe", "energy", "astrology", "science", "divine_figure"],
        "tone": "grounded_mystic",
        "strictness": "direct",
        "manifestation_style": ["prayer", "scripting", "visualisation", "law_of_attraction", "angel_numbers", "action_receipts"],
        "avoid_tone": ["fluffy", "fake-positive", "generic CoStar-style"],
        "vedic_first": True,
        "avoid_guaranteed_predictions": True,
        "always_include_action_receipt": True,
        "include_numerology": True,
    })
    state["important_dates"] = [{
        "id": "owner-date-2026-07-11",
        "date": "2026-07-11",
        "label": "Important intuitive date",
        "type": "spiritual",
        "notes": "Owner said 11 July feels important.",
        "created_at": _now(),
    }]
    state["synchronicities"] = [{
        "id": "owner-sign-333",
        "date": "2026-06-16",
        "type": "angel_number",
        "value": "333",
        "context": "Owner reported seeing 333.",
        "meaning": "Symbolically: support, growth, guidance, creative expression.",
        "action_prompt": "Turn the sign into a receipt: create, bid, apply, train, or document evidence.",
        "created_at": _now(),
    }]
    return state


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (list, dict)) and not value)


def reduce_number(value: int, *, preserve_master: bool = True) -> int:
    value = abs(int(value))
    while value > 9:
        if preserve_master and value in {11, 22, 33}:
            return value
        value = sum(int(ch) for ch in str(value))
    return value


def _digits_from_date(date_text: str) -> List[int]:
    return [int(ch) for ch in date_text if ch.isdigit()]


def numerology_for(target_date: str, birth_date: str = "", label: str = "", kind: str = "custom") -> Dict[str, Any]:
    target = _date_text(target_date)
    year, month, day = (int(part) for part in target.split("-"))
    universal_day = reduce_number(sum(_digits_from_date(target)))
    date_reduction = universal_day
    life_path = reduce_number(sum(_digits_from_date(birth_date))) if birth_date else None
    day_number = None
    personal_year = personal_month = personal_day = None
    if birth_date:
        _, birth_month, birth_day = (int(part) for part in birth_date.split("-"))
        day_number = f"{birth_day} / {reduce_number(birth_day)}"
        personal_year = reduce_number(birth_month + birth_day + sum(int(ch) for ch in str(year)))
        personal_month = reduce_number(personal_year + month)
        personal_day = reduce_number(personal_month + day)
    focus_number = personal_day or universal_day
    interpretations = {
        1: "begin cleanly and act without waiting for permission",
        2: "cooperate, listen, and move with patience",
        3: "speak clearly, create, and let the signal out",
        4: "build structure, receipts, and practical proof",
        5: "adapt, move, and break stale loops",
        6: "handle home, care, duty, and responsibility",
        7: "study, reflect, and separate signal from noise",
        8: "focus money, power, discipline, and long-term authority",
        9: "release what is done and act from maturity",
        11: "treat intuition as a prompt, then verify with action",
        22: "turn vision into a real system with receipts",
        33: "serve, guide, and lead without martyrdom",
    }
    return {
        "date": target,
        "label": _text(label, 160),
        "type": kind if kind in IMPORTANT_DATE_TYPES else "custom",
        "date_reduction": date_reduction,
        "universal_day": universal_day,
        "personal_year": personal_year,
        "personal_month": personal_month,
        "personal_day": personal_day,
        "life_path": life_path,
        "day_number": day_number,
        "interpretation": f"Symbolically, {focus_number} points toward {interpretations.get(focus_number, 'reflection and clean action')}.",
        "best_use": interpretations.get(focus_number, "reflection and clean action"),
        "caution": "Do not worship the date. Use the date.",
        "action_suggestion": "Use it as a prompt for one practical action receipt, not a guarantee.",
    }


def _normalize_birth_profile(value: Any) -> Dict[str, str]:
    base = _empty_state()["birth_profile"]
    if not isinstance(value, dict):
        return base
    aliases = {"display_name": "full_name", "city": "birth_city", "country": "birth_country"}
    value = {**value}
    for old, new in aliases.items():
        if old in value and new not in value:
            value[new] = value[old]
    merged = {key: _text(value.get(key), 500) for key in base}
    merged["preferred_system"] = merged["preferred_system"] or "vedic"
    merged["ayanamsa"] = merged["ayanamsa"] or "lahiri"
    merged["house_system"] = merged["house_system"] or "whole_sign"
    return merged


def _normalize_manifestation(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    title = _text(value.get("title"), 200)
    statement = _text(value.get("statement"), 1000)
    if not title and not statement:
        return None
    created = _text(value.get("created_at"), 60) or _now()
    category = _text(value.get("category"), 40)
    status = _text(value.get("status"), 40)
    return {
        "id": _id(value.get("id"), "manifestation"),
        "category": category if category in MANIFESTATION_CATEGORIES else "custom",
        "title": title or statement[:80],
        "statement": statement,
        "status": status if status in MANIFESTATION_STATUSES else "active",
        "created_at": created,
        "updated_at": _text(value.get("updated_at"), 60) or created,
        "target_date": _text(value.get("target_date"), 20),
        "evidence": _list_text(value.get("evidence"), limit=20),
        "action_receipts": _list_text(value.get("action_receipts"), limit=20),
        "notes": _text(value.get("notes"), 2000),
    }


def _normalize_gratitude(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    entry_date = _text(value.get("date"), 10) or date.today().isoformat()
    try:
        entry_date = date.fromisoformat(entry_date).isoformat()
    except ValueError:
        return None
    created = _text(value.get("created_at"), 60) or _now()
    return {
        "id": _id(value.get("id"), "gratitude"),
        "date": entry_date,
        "grateful_for": _list_text(value.get("grateful_for") or value.get("already_mine"), limit=3),
        "thankful_before_materialised": _list_text(value.get("thankful_before_materialised") or value.get("on_its_way"), limit=3),
        "scripting": _text(value.get("scripting") or value.get("script"), 2000),
        "signs_seen": _list_text(value.get("signs_seen") or value.get("sign_seen"), limit=10),
        "mood": _text(value.get("mood"), 80),
        "stress": _text(value.get("stress"), 80),
        "action_receipt": _text(value.get("action_receipt"), 1000),
        "created_at": created,
        "updated_at": _text(value.get("updated_at"), 60) or created,
    }


def _normalize_sign(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    sign_value = _text(value.get("value"), 160)
    if not sign_value:
        return None
    sign_type = _text(value.get("type"), 40)
    created = _text(value.get("created_at"), 60) or _now()
    return {
        "id": _id(value.get("id"), "sign"),
        "date": _text(value.get("date"), 10) or date.today().isoformat(),
        "type": sign_type if sign_type in SIGN_TYPES else "other",
        "value": sign_value,
        "context": _text(value.get("context"), 1000),
        "meaning": _text(value.get("meaning"), 1000),
        "action_prompt": _text(value.get("action_prompt"), 1000),
        "created_at": created,
    }


def _normalize_important_date(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    try:
        target = _date_text(value.get("date"))
    except OracleError:
        return None
    label = _text(value.get("label"), 160) or target
    kind = _text(value.get("type") or value.get("category"), 40)
    created = _text(value.get("created_at"), 60) or _now()
    return {"id": _id(value.get("id"), "date"), "date": target, "label": label, "type": kind if kind in IMPORTANT_DATE_TYPES else "custom", "notes": _text(value.get("notes"), 1000), "created_at": created}


def _normalize_daily(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    entry_date = _text(value.get("date"), 10)
    if not entry_date:
        return None
    fields = ["title", "vedic_focus", "vedic_status", "numerology_focus", "energy", "emotional_weather", "warning", "shadow_warning", "best_action", "do_not_do", "reflection_question", "manifestation_prompt", "gratitude_prompt", "action_receipt_prompt", "closing_line"]
    row = {"date": entry_date, "created_at": _text(value.get("created_at"), 60) or _now()}
    for field in fields:
        row[field] = _text(value.get(field), 800)
    return row


def normalize_state(value: Any) -> Dict[str, Any]:
    state = _empty_state()
    if not isinstance(value, dict):
        return state
    raw = dict(value)
    if raw.get("version") != 1:
        if any(key in raw for key in ("birth_profile", "spiritual_preferences", "initial_signs", "signs")):
            raw["version"] = 1
            if "synchronicities" not in raw and "signs" in raw:
                raw["synchronicities"] = raw.get("signs")
        else:
            return state

    state["display_name"] = _text(raw.get("display_name"), 160)
    state["preferred_names"] = _list_text(raw.get("preferred_names"), limit=8)
    state["birth_profile"] = _normalize_birth_profile(raw.get("birth_profile"))
    prefs = raw.get("spiritual_preferences") if isinstance(raw.get("spiritual_preferences"), dict) else {}
    state["spiritual_preferences"] = {
        "belief_style": _list_text(prefs.get("belief_style"), limit=12),
        "tone": _text(prefs.get("tone"), 80) or "grounded_mystic",
        "strictness": _text(prefs.get("strictness"), 80) or "direct",
        "manifestation_style": _list_text(prefs.get("manifestation_style"), limit=12),
        "avoid_tone": _list_text(prefs.get("avoid_tone"), limit=12),
        "vedic_first": bool(prefs.get("vedic_first", True)),
        "avoid_guaranteed_predictions": bool(prefs.get("avoid_guaranteed_predictions", True)),
        "always_include_action_receipt": bool(prefs.get("always_include_action_receipt", True)),
        "include_numerology": bool(prefs.get("include_numerology", True)),
    }
    state["manifestation_categories"] = _list_text(raw.get("manifestation_categories"), limit=20)
    state["manual_vedic_notes"] = raw.get("manual_vedic_notes") if isinstance(raw.get("manual_vedic_notes"), dict) else {}
    state["meta"] = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for key, normalizer in (("manifestations", _normalize_manifestation), ("gratitude_entries", _normalize_gratitude), ("synchronicities", _normalize_sign), ("important_dates", _normalize_important_date), ("daily_entries", _normalize_daily)):
        rows = raw.get(key) if isinstance(raw.get(key), list) else []
        state[key] = [item for item in (normalizer(row) for row in rows) if item]
    state["saved_readings"] = [item for item in (_normalize_daily(row) for row in raw.get("saved_readings", [])) if item] if isinstance(raw.get("saved_readings"), list) else []
    state["numerology_calculations"] = (raw.get("numerology_calculations") if isinstance(raw.get("numerology_calculations"), list) else [])[:50]
    return state


def _has_any_content(state: Dict[str, Any]) -> bool:
    birth = state.get("birth_profile") or {}
    return bool(birth.get("date_of_birth") or birth.get("birth_city") or birth.get("full_name") or state.get("manifestations") or state.get("gratitude_entries") or state.get("synchronicities") or state.get("important_dates"))


def _merge_missing_seed(state: Dict[str, Any]) -> Dict[str, Any]:
    seed = _owner_seed_state()
    if not state.get("display_name"):
        state["display_name"] = seed["display_name"]
    if not state.get("preferred_names"):
        state["preferred_names"] = seed["preferred_names"]
    if not state.get("manifestation_categories"):
        state["manifestation_categories"] = seed["manifestation_categories"]
    if not state.get("meta"):
        state["meta"] = seed["meta"]
    for key, value in seed["birth_profile"].items():
        if not state["birth_profile"].get(key):
            state["birth_profile"][key] = value
    for key, value in seed["spiritual_preferences"].items():
        if not state["spiritual_preferences"].get(key):
            state["spiritual_preferences"][key] = value
    if not state.get("important_dates"):
        state["important_dates"] = seed["important_dates"]
    if not state.get("synchronicities"):
        state["synchronicities"] = seed["synchronicities"]
    return normalize_state(state)


def load_oracle(owner: Optional[str]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    raw = (prefs or {}).get(PREF_KEY)
    if _is_empty_value(raw):
        state = _owner_seed_state()
        prefs[PREF_KEY] = state
        _save_for_user(owner, prefs)
        return state
    state = normalize_state(raw)
    if not _has_any_content(state):
        state = _owner_seed_state()
    else:
        state = _merge_missing_seed(state)
    prefs[PREF_KEY] = state
    _save_for_user(owner, prefs)
    return state


def save_oracle(owner: Optional[str], state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    prefs[PREF_KEY] = normalize_state(state)
    _save_for_user(owner, prefs)
    return prefs[PREF_KEY]


def update_profile(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    state = load_oracle(owner)
    state["birth_profile"] = _normalize_birth_profile({**state["birth_profile"], **payload})
    if state["birth_profile"].get("full_name"):
        state["display_name"] = state["birth_profile"]["full_name"]
    return save_oracle(owner, state)["birth_profile"]


def update_preferences(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    state = load_oracle(owner)
    current = state["spiritual_preferences"]
    current.update(payload or {})
    state["spiritual_preferences"] = normalize_state({"version": 1, "spiritual_preferences": current})["spiritual_preferences"]
    return save_oracle(owner, state)["spiritual_preferences"]


def add_gratitude(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    entry = _normalize_gratitude(payload)
    if not entry or not (entry["grateful_for"] or entry["thankful_before_materialised"] or entry["scripting"]):
        raise OracleError("Add at least one gratitude, future-thanks, or scripting entry.")
    state = load_oracle(owner)
    existing = [row for row in state["gratitude_entries"] if row["date"] != entry["date"]]
    state["gratitude_entries"] = [entry] + existing
    save_oracle(owner, state)
    return entry


def add_manifestation(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    item = _normalize_manifestation(payload)
    if not item:
        raise OracleError("Manifestation title or statement is required.")
    state = load_oracle(owner)
    state["manifestations"].append(item)
    save_oracle(owner, state)
    return item


def _find_by_id_or_title(rows: List[Dict[str, Any]], identifier: str) -> Dict[str, Any]:
    needle = _text(identifier, 200).casefold()
    exact = [row for row in rows if row.get("id", "").casefold() == needle or row.get("title", "").casefold() == needle]
    if exact:
        return exact[0]
    partial = [row for row in rows if needle and needle in row.get("title", "").casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise OracleError("That manifestation title is ambiguous.")
    raise OracleError("Manifestation not found.")


def update_manifestation(owner: Optional[str], identifier: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    state = load_oracle(owner)
    item = _find_by_id_or_title(state["manifestations"], identifier)
    allowed = {"category", "title", "statement", "status", "target_date", "notes"}
    merged = {**item, **{key: value for key, value in (changes or {}).items() if key in allowed}}
    if changes.get("evidence"):
        merged["evidence"] = item["evidence"] + _list_text(changes.get("evidence"), limit=5)
    if changes.get("action_receipt") or changes.get("action_receipts"):
        merged["action_receipts"] = item["action_receipts"] + _list_text(changes.get("action_receipts") or changes.get("action_receipt"), limit=5)
    merged["updated_at"] = _now()
    normalized = _normalize_manifestation(merged)
    if not normalized:
        raise OracleError("Manifestation title or statement is required.")
    state["manifestations"] = [normalized if row["id"] == item["id"] else row for row in state["manifestations"]]
    save_oracle(owner, state)
    return normalized


def add_sign(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    item = _normalize_sign(payload)
    if not item:
        raise OracleError("Sign value is required.")
    if not item["meaning"]:
        item["meaning"] = "Symbolically, treat this as a reflection prompt, not objective proof."
    if not item["action_prompt"]:
        item["action_prompt"] = "Name one grounded action this sign is asking you to take."
    state = load_oracle(owner)
    state["synchronicities"].insert(0, item)
    save_oracle(owner, state)
    return item


def add_important_date(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    item = _normalize_important_date(payload)
    if not item:
        raise OracleError("Important date is required.")
    state = load_oracle(owner)
    state["important_dates"].append(item)
    save_oracle(owner, state)
    return item


def calculate_numerology(owner: Optional[str], payload: Dict[str, Any], *, persist: bool = False) -> Dict[str, Any]:
    state = load_oracle(owner)
    result = numerology_for(payload.get("date") or date.today().isoformat(), birth_date=state["birth_profile"].get("date_of_birth") or "", label=payload.get("label") or "", kind=payload.get("type") or "custom")
    if persist:
        state["numerology_calculations"].insert(0, {**result, "created_at": _now()})
        state["numerology_calculations"] = state["numerology_calculations"][:50]
        save_oracle(owner, state)
    return result


def daily_reading(owner: Optional[str], target_date: Optional[str] = None, *, save: bool = False) -> Dict[str, Any]:
    state = load_oracle(owner)
    today = _date_text(target_date or date.today().isoformat())
    numerology = numerology_for(today, state["birth_profile"].get("date_of_birth") or "")
    active = [row for row in state["manifestations"] if row["status"] == "active"]
    latest_gratitude = state["gratitude_entries"][0] if state["gratitude_entries"] else None
    latest_sign = state["synchronicities"][0] if state["synchronicities"] else None
    
    # Inject real astrology transits!
    try:
        transits = get_transits(today)
        vedic_status = f"Live Ephemeris: Sun in {transits['Sun']['sign']}, Moon in {transits['Moon']['sign']}."
        vedic_focus = f"Moon is in {transits['Moon']['sign']} at {transits['Moon']['degree']}°. Check where this falls in your natal chart for today's physical energy."
        mercury_rx = transits.get('Mercury', {}).get('retrograde', False)
        if mercury_rx:
            vedic_focus += " Mercury is retrograde."
    except Exception as e:
        vedic_status = "Placements engine failed to load ephemeris."
        vedic_focus = "Vedic-first mode is on. Error loading real-time transits."
        
    reading = {
        "date": today,
        "title": "Receipt Day, Not Waiting Day",
        "vedic_focus": vedic_focus,
        "vedic_status": vedic_status,
        "numerology_focus": numerology["interpretation"],
        "energy": "Steady command energy: faith with action, signs without delusion.",
        "emotional_weather": "Grounded, watchful, slightly electric. Regulate the body before asking the universe for proof.",
        "warning": "Do not wait for a sign to do the obvious next right thing.",
        "shadow_warning": "Do not worship the date. Use the date.",
        "best_action": "Create one action receipt today: body, money/work, home/admin, learning, or family peace.",
        "do_not_do": "Do not trade action for over-reading signs.",
        "reflection_question": "What would the man who can hold this blessing do before tonight?",
        "manifestation_prompt": active[0]["statement"] if active else "I am becoming the man who can hold what I am calling in.",
        "gratitude_prompt": "Name three things already yours, then three things you are becoming available for.",
        "action_receipt_prompt": latest_gratitude.get("action_receipt") if latest_gratitude else "Write one receipt proving you moved correctly.",
        "latest_sign_prompt": latest_sign.get("action_prompt") if latest_sign else "Log any sign only after you decide the grounded action.",
        "closing_line": "Boss — faith with action. Today’s receipt matters more than today’s mood.",
        "numerology": numerology,
        "created_at": _now(),
    }
    if save:
        state["daily_entries"] = [row for row in state["daily_entries"] if row.get("date") != today]
        state["daily_entries"].insert(0, reading)
        save_oracle(owner, state)
    return reading


def cosmic_calendar(owner: Optional[str], target_date: Optional[str] = None) -> Dict[str, Any]:
    state = load_oracle(owner)
    today = date.fromisoformat(_date_text(target_date or date.today().isoformat()))
    active, upcoming, all_periods = [], [], []
    for row in MERCURY_RETROGRADE_PERIODS:
        start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
        item = {**row, "source": "Local reference data"}
        all_periods.append(item)
        if start <= today <= end:
            active.append(item)
        elif start >= today:
            upcoming.append(item)
    upcoming.sort(key=lambda row: row["start"])
    important = sorted(state["important_dates"], key=lambda row: row["date"])[:20]
    highlights = [numerology_for(row["date"], state["birth_profile"].get("date_of_birth") or "", row["label"], row["type"]) for row in important[:8]]
    
    # Calculate live mercury retrograde status if needed
    is_live_retrograde = False
    try:
        is_live_retrograde = is_mercury_retrograde(today.isoformat())
    except:
        pass
        
    return {
        "date": today.isoformat(),
        "mercury_retrograde_active": is_live_retrograde or bool(active),
        "active_periods": active,
        "next_mercury_retrograde": upcoming[0] if upcoming else None,
        "upcoming_mercury_retrogrades": upcoming[:6],
        "mercury_retrograde_periods": all_periods,
        "important_dates": important,
        "numerology_highlights": highlights,
        "reference": "live_ephemeris",
        "vedic_engine": "online",
        "disclaimer": "Cosmic calendar uses live Swiss Ephemeris data.",
    }


def oracle_summary(owner: Optional[str]) -> Dict[str, Any]:
    state = load_oracle(owner)
    today = date.today().isoformat()
    gratitude_done = any(row["date"] == today for row in state["gratitude_entries"])
    latest_sign = state["synchronicities"][0] if state["synchronicities"] else None
    birth = state["birth_profile"].get("date_of_birth") or ""
    numerology = numerology_for(today, birth) if birth else numerology_for(today)
    return {
        "display_name": state.get("display_name") or state["birth_profile"].get("full_name"),
        "personal_day": numerology.get("personal_day") or numerology.get("universal_day"),
        "life_path": numerology.get("life_path"),
        "day_number": numerology.get("day_number"),
        "latest_sign": latest_sign,
        "active_manifestation_count": len([row for row in state["manifestations"] if row["status"] == "active"]),
        "manifestation_count": len(state["manifestations"]),
        "gratitude_count": len(state["gratitude_entries"]),
        "sign_count": len(state["synchronicities"]),
        "important_date_count": len(state["important_dates"]),
        "birth_profile_saved": bool(state["birth_profile"].get("date_of_birth")),
        "gratitude_done": gratitude_done,
    }


async def manage_oracle_tool(content: str, owner: Optional[str]) -> Dict[str, Any]:
    try:
        args = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {"error": "Invalid Oracle request.", "exit_code": 1}
    if not isinstance(args, dict):
        return {"error": "Invalid Oracle request.", "exit_code": 1}
    action = _text(args.get("action"), 40)
    try:
        if action == "profile":
            profile = load_oracle(owner)["birth_profile"]
            try:
                # Add real calculated birth chart if available
                chart = get_birth_chart(profile.get("date_of_birth", ""), profile.get("time_of_birth", ""))
                profile["calculated_chart"] = chart
            except:
                profile["calculated_chart"] = None
            return {"profile": profile, "exit_code": 0}
        if action == "update_profile":
            return {"profile": update_profile(owner, args), "output": "Done, Boss. Birth profile updated.", "exit_code": 0}
        if action == "daily":
            return {"reading": daily_reading(owner, args.get("date")), "exit_code": 0}
        if action == "add_gratitude":
            entry = add_gratitude(owner, args)
            return {"entry": entry, "output": "Done, Boss. Gratitude logged.", "exit_code": 0}
        if action == "add_manifestation":
            item = add_manifestation(owner, args)
            return {"manifestation": item, "output": "Done, Boss. Manifestation bank updated.", "exit_code": 0}
        if action == "update_manifestation":
            item = update_manifestation(owner, args.get("id") or args.get("title") or args.get("category"), args)
            return {"manifestation": item, "output": "Done, Boss. Manifestation updated.", "exit_code": 0}
        if action == "list_manifestations":
            items = load_oracle(owner)["manifestations"]
            return {"manifestations": items, "count": len(items), "exit_code": 0}
        if action == "add_sign":
            item = add_sign(owner, args)
            return {"sign": item, "output": "Done, Boss. Sign logged with grounded action.", "exit_code": 0}
        if action == "list_signs":
            signs = load_oracle(owner)["synchronicities"]
            return {"signs": signs[:20], "count": len(signs), "exit_code": 0}
        if action == "add_important_date":
            item = add_important_date(owner, args)
            return {"important_date": item, "output": "Done, Boss. Important date saved.", "exit_code": 0}
        if action == "numerology":
            return {"numerology": calculate_numerology(owner, args, persist=bool(args.get("save"))), "exit_code": 0}
        if action == "cosmic_calendar":
            return {"calendar": cosmic_calendar(owner, args.get("date")), "exit_code": 0}
        if action in {"delete", "remove"}:
            return {"error": "Boss, I can't delete Oracle records from chat. Open Oracle and manage them manually.", "exit_code": 1}
        return {"error": "Use profile, update_profile, daily, add_gratitude, add_manifestation, update_manifestation, list_manifestations, add_sign, list_signs, add_important_date, numerology, or cosmic_calendar.", "exit_code": 1}
    except OracleError as exc:
        return {"error": str(exc), "exit_code": 1}

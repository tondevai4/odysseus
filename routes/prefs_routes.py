"""User preferences API — per-user key/value store backed by a JSON file."""
import copy
import json
import os
import copy
from typing import Optional
from fastapi import APIRouter, Request
from src.auth_helpers import get_current_user
from src.constants import USER_PREFS_FILE

PREFS_FILE = USER_PREFS_FILE
ORACLE_PREF_KEY = "strnos-oracle-v1"

OWNER_ORACLE_SEED = {
    "display_name": "Tony",
    "preferred_names": ["Boss", "Tony"],
    "birth_profile": {
        "date_of_birth": "2001-07-21",
        "time_of_birth": "20:00",
        "birth_city": "Harare",
        "birth_country": "Zimbabwe",
        "timezone": "Africa/Harare",
        "preferred_system": "vedic",
        "ayanamsa": "lahiri",
        "house_system": "whole_sign",
    },
    "spiritual_preferences": {
        "belief_style": ["universe", "energy", "astrology", "science", "divine_figure"],
        "tone": "grounded_mystic",
        "strictness": "direct",
        "manifestation_style": [
            "prayer",
            "scripting",
            "visualisation",
            "law_of_attraction",
            "angel_numbers",
            "action_receipts",
        ],
        "avoid_tone": ["fluffy", "fake-positive", "generic CoStar-style"],
        "vedic_first": True,
        "avoid_guaranteed_predictions": True,
        "always_include_action_receipt": True,
        "include_numerology": True,
    },
    "manifestation_categories": [
        "housing",
        "money",
        "apprenticeship",
        "daughter",
        "peace",
        "creativity",
    ],
    "important_dates": [
        {
            "date": "2026-07-11",
            "label": "Important intuitive date",
            "category": "spiritual",
            "notes": "Owner said 11 July feels important.",
        }
    ],
    "initial_signs": [
        {
            "date": "2026-06-16",
            "type": "angel_number",
            "value": "333",
            "context": "Owner reported seeing 333.",
            "meaning": "Symbolically: support, growth, guidance, creative expression.",
            "action_prompt": "Turn the sign into a receipt: create, bid, apply, train, or document evidence.",
        }
    ],
    "manifestations": [],
    "gratitude_entries": [],
    "signs": [],
    "manual_vedic_notes": {},
    "meta": {
        "seeded_by": "owner_default_seed",
        "seeded_scope": "current_authenticated_user",
        "ephemeris_status": "pending_manual_vedic_notes_only",
    },
}

# --- STRNOS Oracle v2 owner seed ---
# When the STRNOS Oracle v1 preference slot is empty (None, empty string, empty
# list/dict), we seed a default owner profile for Tony/Boss. This ensures the
# Oracle dashboard shows meaningful initial data without forcing the owner to
# manually enter birth details or preferences. Seeding only happens once per
# user; existing data is preserved.
ORACLE_PREF_KEY = "strnos-oracle-v1"

OWNER_ORACLE_SEED = {
    "display_name": "Tony",
    "preferred_names": ["Boss", "Tony"],
    "birth_profile": {
        "date_of_birth": "2001-07-21",
        "time_of_birth": "20:00",
        "birth_city": "Harare",
        "birth_country": "Zimbabwe",
        "timezone": "Africa/Harare",
        "preferred_system": "vedic",
        "ayanamsa": "lahiri",
        "house_system": "whole_sign",
    },
    "spiritual_preferences": {
        "belief_style": ["universe", "energy", "astrology", "science", "divine_figure"],
        "tone": "grounded_mystic",
        "strictness": "direct",
        "manifestation_style": [
            "prayer",
            "scripting",
            "visualisation",
            "law_of_attraction",
            "angel_numbers",
            "action_receipts",
        ],
        "avoid_tone": ["fluffy", "fake-positive", "generic CoStar-style"],
        "vedic_first": True,
        "avoid_guaranteed_predictions": True,
        "always_include_action_receipt": True,
        "include_numerology": True,
    },
    "manifestation_categories": [
        "housing",
        "money",
        "apprenticeship",
        "daughter",
        "peace",
        "creativity",
    ],
    "important_dates": [
        {
            "date": "2026-07-11",
            "label": "Important intuitive date",
            "category": "spiritual",
            "notes": "Owner said 11 July feels important.",
        }
    ],
    "initial_signs": [
        {
            "date": "2026-06-16",
            "type": "angel_number",
            "value": "333",
            "context": "Owner reported seeing 333.",
            "meaning": "Symbolically: support, growth, guidance, creative expression.",
            "action_prompt": "Turn the sign into a receipt: create, bid, apply, train, or document evidence.",
        }
    ],
    "manifestations": [],
    "gratitude_entries": [],
    "signs": [],
    "manual_vedic_notes": {},
    "meta": {
        "seeded_by": "owner_default_seed",
        "seeded_scope": "current_authenticated_user",
        "ephemeris_status": "pending_manual_vedic_notes_only",
    },
}

def _is_empty_oracle_value(value) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False

def _seed_oracle_if_empty(user: Optional[str]) -> dict:
    prefs = _load_for_user(user)
    current = prefs.get(ORACLE_PREF_KEY)
    if not _is_empty_oracle_value(current):
        return current
    seeded = copy.deepcopy(OWNER_ORACLE_SEED)
    # Materialise initial_signs into signs so 333 appears on first open.
    seeded["signs"] = copy.deepcopy(seeded.get("initial_signs") or [])
    prefs[ORACLE_PREF_KEY] = seeded
    _save_for_user(user, prefs)
    return seeded

def _load():
    """Load the raw prefs file (internal use only)."""
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save(prefs):
    os.makedirs(os.path.dirname(PREFS_FILE) or ".", exist_ok=True)
    tmp = f"{PREFS_FILE}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PREFS_FILE)

def _load_for_user(user: Optional[str] = None) -> dict:
    """Load preferences for a specific user."""
    all_prefs = _load()
    if "_users" in all_prefs:
        if user is None:
            # Auth disabled — return first user's prefs for backward compat
            users = all_prefs["_users"]
            return dict(next(iter(users.values()), {}))
        return dict(all_prefs["_users"].get(user, {}))
    # Legacy flat format — return as-is
    return dict(all_prefs)

def _save_for_user(user: Optional[str], prefs: dict):
    """Save preferences for a specific user."""
    all_prefs = _load()
    if user is None:
        # Auth disabled. If the store is already multi-user (e.g. auth was
        # turned off on a deployment that previously ran multi-user), writing
        # `prefs` flat would overwrite the whole `_users` map and destroy every
        # other user's preferences. Instead write back into the same (first)
        # slot _load_for_user(None) reads from, preserving the others.
        if "_users" in all_prefs:
            users = all_prefs["_users"]
            first_key = next(iter(users), None)
            if first_key is not None:
                users[first_key] = prefs
                _save(all_prefs)
                return
        _save(prefs)
        return
    if "_users" not in all_prefs:
        all_prefs = {"_users": {}}
    all_prefs["_users"][user] = prefs
    _save(all_prefs)

<<<<<<< HEAD
=======

def _is_empty_oracle_value(value) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _seed_oracle_if_empty(user: Optional[str]) -> dict:
    """Seed Tony/Boss Oracle defaults only for the current owner/user when empty.

    This preserves existing owner edits, keeps the data in the same per-user
    preferences store as the rest of the app, and avoids any schema migration.
    The caller must only invoke this from Oracle-specific preference access.
    """
    prefs = _load_for_user(user)
    current = prefs.get(ORACLE_PREF_KEY)
    if not _is_empty_oracle_value(current):
        return current
    seeded = copy.deepcopy(OWNER_ORACLE_SEED)
    # Keep initial_signs as source data and materialise them into signs so the
    # dashboard immediately shows 333 on first Oracle open without forcing the
    # owner to re-enter it.
    seeded["signs"] = copy.deepcopy(seeded.get("initial_signs") or [])
    prefs[ORACLE_PREF_KEY] = seeded
    _save_for_user(user, prefs)
    return seeded


>>>>>>> dev
def setup_prefs_routes():
    router = APIRouter(prefix="/api/prefs", tags=["preferences"])

    @router.get("")
    async def get_all_prefs(request: Request):
        user = get_current_user(request)
        return _load_for_user(user)

    @router.get("/{key}")
    async def get_pref(request: Request, key: str):
        user = get_current_user(request)
<<<<<<< HEAD
        # Seed Oracle defaults on first access
=======
>>>>>>> dev
        if key == ORACLE_PREF_KEY:
            value = _seed_oracle_if_empty(user)
            return {"key": key, "value": value}
        prefs = _load_for_user(user)
        return {"key": key, "value": prefs.get(key)}

    @router.put("/{key}")
    async def set_pref(request: Request, key: str, body: dict):
        user = get_current_user(request)
        prefs = _load_for_user(user)
        prefs[key] = body.get("value")
        _save_for_user(user, prefs)
        return {"key": key, "value": prefs[key]}

    return router

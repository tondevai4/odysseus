"""Owner-scoped gym log stored in versioned user preferences."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from routes.prefs_routes import _load_for_user, _save_for_user

PREF_KEY = "gym-log-v1"


class GymLogError(ValueError):
    """Safe validation error for API and tool responses."""


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _number(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_exercises(raw_log: str) -> List[Dict[str, Any]]:
    """Parse simple `Exercise — 100kg: 10 / 8; 110kg: 5` lines."""
    exercises: List[Dict[str, Any]] = []
    for raw_line in (raw_log or "").splitlines():
        line = raw_line.strip(" -*\t")
        match = re.match(r"^(.+?)\s*(?:—|–|-)\s*(.+)$", line)
        if not match:
            continue
        name, set_text = match.groups()
        sets = []
        for group in set_text.split(";"):
            weight_match = re.match(r"\s*([^:]{1,40})\s*:\s*(.+)$", group)
            if not weight_match:
                continue
            weight, reps_text = weight_match.groups()
            for reps in re.findall(r"\d+", reps_text):
                sets.append({"weight": _text(weight, 40), "reps": int(reps)})
        if sets:
            exercises.append({"name": _text(name, 120), "sets": sets})
    return exercises[:40]


def _normalize_exercises(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    exercises = []
    for row in value[:40]:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"), 120)
        if not name:
            continue
        sets = []
        for item in row.get("sets") or []:
            if not isinstance(item, dict):
                continue
            reps = _number(item.get("reps"))
            if reps is None:
                continue
            sets.append({"weight": _text(item.get("weight"), 40), "reps": reps})
        exercises.append({"name": name, "sets": sets[:30]})
    return exercises


def normalize_entry(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    workout_date = _text(value.get("date"), 10)
    title = _text(value.get("title"), 160)
    if not workout_date or not title:
        return None
    try:
        date.fromisoformat(workout_date)
    except ValueError:
        return None
    raw_log = _text(value.get("raw_log"), 12000)
    exercises = _normalize_exercises(value.get("exercises"))
    if not exercises and raw_log:
        exercises = parse_exercises(raw_log)
    total_sets = _number(value.get("total_sets"))
    total_reps = _number(value.get("total_reps"))
    if exercises:
        if total_sets is None:
            total_sets = sum(len(item["sets"]) for item in exercises)
        if total_reps is None:
            total_reps = sum(
                workout_set["reps"]
                for item in exercises
                for workout_set in item["sets"]
            )
    created_at = _text(value.get("created_at"), 50) or _now()
    return {
        "id": _text(value.get("id"), 100) or str(uuid.uuid4()),
        "date": workout_date,
        "title": title,
        "duration": _text(value.get("duration"), 30),
        "work_time": _text(value.get("work_time"), 30),
        "rest_time": _text(value.get("rest_time"), 30),
        "avg_hr": _number(value.get("avg_hr")),
        "max_hr": _number(value.get("max_hr")),
        "active_calories": _number(value.get("active_calories")),
        "total_calories": _number(value.get("total_calories")),
        "total_reps": total_reps,
        "total_sets": total_sets,
        "primary_benefit": _text(value.get("primary_benefit"), 160),
        "exercises": exercises,
        "notes": _text(value.get("notes"), 4000),
        "win": _text(value.get("win"), 1000),
        "raw_log": raw_log,
        "created_at": created_at,
        "updated_at": _text(value.get("updated_at"), 50) or created_at,
    }


def load_gym_log(owner: Optional[str]) -> Dict[str, Any]:
    value = (_load_for_user(owner) or {}).get(PREF_KEY)
    if not isinstance(value, dict) or value.get("version") != 1:
        return {"version": 1, "entries": []}
    rows = value.get("entries")
    if not isinstance(rows, list):
        return {"version": 1, "entries": []}
    entries = [entry for entry in (normalize_entry(row) for row in rows) if entry]
    entries.sort(key=lambda row: (row["date"], row["updated_at"]), reverse=True)
    return {"version": 1, "entries": entries}


def save_gym_log(owner: Optional[str], state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    prefs[PREF_KEY] = state
    _save_for_user(owner, prefs)
    return state


def add_workout(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    raw_log = _text(payload.get("raw_log") or payload.get("details"), 12000)
    entry = normalize_entry({
        **payload,
        "id": str(uuid.uuid4()),
        "date": _text(payload.get("date"), 10) or date.today().isoformat(),
        "title": _text(payload.get("title"), 160) or "Workout",
        "raw_log": raw_log,
        "exercises": payload.get("exercises") or parse_exercises(raw_log),
        "created_at": now,
        "updated_at": now,
    })
    if not entry:
        raise GymLogError("A valid workout date and title are required.")
    state = load_gym_log(owner)
    state["entries"].append(entry)
    state["entries"].sort(key=lambda row: (row["date"], row["updated_at"]), reverse=True)
    save_gym_log(owner, state)
    return entry


def _resolve(entries: List[Dict[str, Any]], identifier: str) -> Dict[str, Any]:
    needle = _text(identifier, 160).casefold()
    exact = [
        row for row in entries
        if row["id"].casefold() == needle or row["date"] == identifier
    ]
    if exact:
        return exact[0]
    raise GymLogError("Gym log entry not found.")


def update_workout(
    owner: Optional[str],
    identifier: str,
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    state = load_gym_log(owner)
    entry = _resolve(state["entries"], identifier)
    allowed = {
        "date", "title", "duration", "work_time", "rest_time", "avg_hr",
        "max_hr", "active_calories", "total_calories", "total_reps",
        "total_sets", "primary_benefit", "exercises", "notes", "win", "raw_log",
    }
    merged = {**entry, **{key: value for key, value in changes.items() if key in allowed}}
    if "raw_log" in changes and "exercises" not in changes:
        merged["exercises"] = parse_exercises(_text(changes.get("raw_log"), 12000))
        if "total_sets" not in changes:
            merged["total_sets"] = None
        if "total_reps" not in changes:
            merged["total_reps"] = None
    normalized = normalize_entry({**merged, "updated_at": _now()})
    if not normalized:
        raise GymLogError("A valid workout date and title are required.")
    state["entries"] = [
        normalized if row["id"] == entry["id"] else row for row in state["entries"]
    ]
    save_gym_log(owner, state)
    return normalized


def append_workout_note(
    owner: Optional[str],
    identifier: str,
    note: str,
) -> Dict[str, Any]:
    state = load_gym_log(owner)
    entry = _resolve(state["entries"], identifier)
    note_text = _text(note, 2000)
    if not note_text:
        raise GymLogError("Workout note text is required.")
    existing = _text(entry.get("notes"), 4000)
    combined = f"{existing}\n{note_text}".strip() if existing else note_text
    return update_workout(owner, entry["id"], {"notes": combined[:4000]})


async def manage_gym_log_tool(content: str, owner: Optional[str]) -> Dict[str, Any]:
    try:
        args = json.loads(content or "{}")
    except (TypeError, ValueError):
        return {"error": "Invalid gym-log request.", "exit_code": 1}
    if not isinstance(args, dict):
        return {"error": "Invalid gym-log request.", "exit_code": 1}
    action = _text(args.get("action"), 30)
    try:
        if action == "list":
            entries = load_gym_log(owner)["entries"]
            exercise = _text(args.get("exercise"), 120).casefold()
            if exercise:
                entries = [
                    row for row in entries
                    if any(exercise in item["name"].casefold() for item in row["exercises"])
                ]
            return {
                "entries": entries[:20],
                "latest": entries[0] if entries else None,
                "count": len(entries),
                "exit_code": 0,
            }
        if action == "add":
            entry = add_workout(owner, args)
            return {"entry": entry, "output": "Done, Boss. Gym log saved.", "exit_code": 0}
        if action == "update":
            identifier = _text(args.get("id") or args.get("date"), 160)
            if not identifier:
                raise GymLogError("A workout id or date is required.")
            entry = update_workout(owner, identifier, args)
            return {"entry": entry, "output": "Done, Boss. Gym log updated.", "exit_code": 0}
        if action == "append_note":
            identifier = _text(args.get("id") or args.get("date"), 160)
            if not identifier:
                identifier = date.today().isoformat()
            entry = append_workout_note(owner, identifier, args.get("note"))
            return {"entry": entry, "output": "Done, Boss. Added to the gym log.", "exit_code": 0}
        if action in {"delete", "remove"}:
            return {
                "error": "Boss, I can't delete gym logs from chat. Open Gym / Body to manage it manually.",
                "exit_code": 1,
            }
        return {"error": "Use list, add, update, or append_note.", "exit_code": 1}
    except GymLogError as exc:
        return {"error": str(exc), "exit_code": 1}

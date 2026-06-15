"""Owner-scoped gym log and live workout state in versioned preferences."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from routes.prefs_routes import _load_for_user, _save_for_user

PREF_KEY = "gym-log-v1"

GARMIN_TEXT_FIELDS = {
    "total_time": (r"total\s*time",),
    "work_time": (r"work\s*time",),
    "rest_time": (r"rest\s*time",),
    "avg_time_per_set": (r"avg(?:erage)?\s*time\s*/?\s*set",),
}
GARMIN_NUMBER_FIELDS = {
    "avg_hr": (r"avg(?:erage)?\s*(?:heart\s*rate|hr)",),
    "max_hr": (r"max(?:imum)?\s*(?:heart\s*rate|hr)",),
    "resting_calories": (r"resting\s*calories",),
    "active_calories": (r"active\s*calories",),
    "total_calories": (r"total\s*calories(?:\s*burned)?",),
    "estimated_sweat_loss_ml": (r"(?:est(?:imated)?\.?\s*)?sweat\s*loss",),
    "total_reps": (r"total\s*reps",),
    "total_sets": (r"total\s*sets",),
    "total_volume": (r"total\s*volume",),
    "intensity_minutes_moderate": (r"moderate",),
    "intensity_minutes_vigorous": (r"vigorous",),
    "intensity_minutes_total": (r"intensity\s*minutes\s*total",),
    "body_battery_net_impact": (r"(?:body\s*battery\s*)?net\s*impact",),
}
GARMIN_LABEL_FIELDS = {
    "primary_benefit": (r"primary\s*benefit",),
    "muscle_primary": (r"(?:primary\s*muscles?|muscle\s*primary)",),
    "muscle_secondary": (r"(?:secondary\s*muscles?|muscle\s*secondary)",),
    "muscle_untargeted": (r"(?:untargeted\s*muscles?|muscle\s*untargeted)",),
}


class GymLogError(ValueError):
    """Safe validation error for API and tool responses."""


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _number(value: Any, *, signed: bool = False) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        result = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return result if signed or result >= 0 else None


def _decimal_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return round(result, 2) if result >= 0 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _match_line(lines: List[str], patterns: tuple[str, ...]) -> Optional[str]:
    for line in lines:
        for pattern in patterns:
            match = re.match(
                rf"^\s*{pattern}(?:\s*:\s*|\s+-\s+|\s+)(.+?)\s*$",
                line,
                re.I,
            )
            if match:
                return match.group(1).strip()
    return None


def parse_garmin_summary(raw_text: str) -> Dict[str, Any]:
    """Parse common Garmin strength-summary labels without guessing."""
    text = _text(raw_text, 16000)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parsed: Dict[str, Any] = {}
    for field, patterns in GARMIN_TEXT_FIELDS.items():
        value = _match_line(lines, patterns)
        if value:
            parsed[field] = _text(value, 30)
    for field, patterns in GARMIN_NUMBER_FIELDS.items():
        value = _match_line(lines, patterns)
        if not value:
            continue
        match = re.search(r"-?[\d,]+(?:\.\d+)?", value)
        if not match:
            continue
        if field == "total_volume":
            parsed[field] = _decimal_number(match.group())
        else:
            parsed[field] = _number(
                match.group(),
                signed=field == "body_battery_net_impact",
            )
    for field, patterns in GARMIN_LABEL_FIELDS.items():
        value = _match_line(lines, patterns)
        if value:
            parsed[field] = _text(value, 300)

    # Garmin often labels the third intensity row simply "Total".
    if "intensity_minutes_total" not in parsed:
        intensity_index = next(
            (i for i, line in enumerate(lines) if re.match(r"^vigorous\b", line, re.I)),
            -1,
        )
        if intensity_index >= 0:
            for line in lines[intensity_index + 1:intensity_index + 4]:
                match = re.match(r"^total\s*[:\-]?\s*(\d+)", line, re.I)
                if match:
                    parsed["intensity_minutes_total"] = int(match.group(1))
                    break
    if text:
        parsed["raw_garmin_text"] = text
    return parsed


def parse_exercises(raw_log: str) -> List[Dict[str, Any]]:
    """Parse simple `Exercise - 100kg: 10 / 8; 110kg: 5` lines."""
    exercises: List[Dict[str, Any]] = []
    for raw_line in (raw_log or "").splitlines():
        line = raw_line.strip(" -*\t")
        match = re.match(r"^(.+?)\s*(?:\u2014|\u2013|-)\s*(.+)$", line)
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
    raw_garmin_text = _text(value.get("raw_garmin_text"), 16000)
    garmin = parse_garmin_summary(raw_garmin_text) if raw_garmin_text else {}
    exercises = _normalize_exercises(value.get("exercises"))
    if not exercises and raw_log:
        exercises = parse_exercises(raw_log)
    total_sets = _number(value.get("total_sets", garmin.get("total_sets")))
    total_reps = _number(value.get("total_reps", garmin.get("total_reps")))
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

    def source(field: str, default: Any = "") -> Any:
        current = value.get(field)
        return garmin.get(field, default) if current in (None, "") else current

    return {
        "id": _text(value.get("id"), 100) or str(uuid.uuid4()),
        "date": workout_date,
        "title": title,
        "duration": _text(source("duration", source("total_time")), 30),
        "total_time": _text(source("total_time", value.get("duration")), 30),
        "work_time": _text(source("work_time"), 30),
        "rest_time": _text(source("rest_time"), 30),
        "avg_hr": _number(source("avg_hr")),
        "max_hr": _number(source("max_hr")),
        "resting_calories": _number(source("resting_calories")),
        "active_calories": _number(source("active_calories")),
        "total_calories": _number(source("total_calories")),
        "estimated_sweat_loss_ml": _number(source("estimated_sweat_loss_ml")),
        "total_reps": total_reps,
        "total_sets": total_sets,
        "avg_time_per_set": _text(source("avg_time_per_set"), 30),
        "total_volume": _decimal_number(source("total_volume")),
        "intensity_minutes_moderate": _number(source("intensity_minutes_moderate")),
        "intensity_minutes_vigorous": _number(source("intensity_minutes_vigorous")),
        "intensity_minutes_total": _number(source("intensity_minutes_total")),
        "body_battery_net_impact": _number(
            source("body_battery_net_impact"),
            signed=True,
        ),
        "primary_benefit": _text(source("primary_benefit"), 160),
        "muscle_primary": _text(source("muscle_primary"), 300),
        "muscle_secondary": _text(source("muscle_secondary"), 300),
        "muscle_untargeted": _text(source("muscle_untargeted"), 300),
        "exercises": exercises,
        "notes": _text(value.get("notes"), 4000),
        "win": _text(value.get("win"), 1000),
        "raw_log": raw_log,
        "raw_garmin_text": raw_garmin_text,
        "created_at": created_at,
        "updated_at": _text(value.get("updated_at"), 50) or created_at,
    }


def _normalize_session(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    exercises = _normalize_exercises(value.get("exercises"))
    return {
        "id": _text(value.get("id"), 100) or str(uuid.uuid4()),
        "date": _text(value.get("date"), 10) or date.today().isoformat(),
        "title": _text(value.get("title"), 160) or "Workout",
        "started_at": _text(value.get("started_at"), 50) or _now(),
        "exercises": exercises,
        "notes": _text(value.get("notes"), 4000),
        "win": _text(value.get("win"), 1000),
    }


def load_gym_log(owner: Optional[str]) -> Dict[str, Any]:
    value = (_load_for_user(owner) or {}).get(PREF_KEY)
    if not isinstance(value, dict) or value.get("version") != 1:
        return {"version": 1, "entries": [], "active_session": None}
    rows = value.get("entries")
    entries = []
    if isinstance(rows, list):
        entries = [entry for entry in (normalize_entry(row) for row in rows) if entry]
    entries.sort(key=lambda row: (row["date"], row["updated_at"]), reverse=True)
    return {
        "version": 1,
        "entries": entries,
        "active_session": _normalize_session(value.get("active_session")),
    }


def save_gym_log(owner: Optional[str], state: Dict[str, Any]) -> Dict[str, Any]:
    prefs = _load_for_user(owner)
    prefs[PREF_KEY] = state
    _save_for_user(owner, prefs)
    return state


def add_workout(owner: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    raw_log = _text(payload.get("raw_log") or payload.get("details"), 12000)
    garmin_text = _text(payload.get("raw_garmin_text") or payload.get("garmin_text"), 16000)
    entry = normalize_entry({
        **parse_garmin_summary(garmin_text),
        **payload,
        "id": str(uuid.uuid4()),
        "date": _text(payload.get("date"), 10) or date.today().isoformat(),
        "title": _text(payload.get("title"), 160) or "Workout",
        "raw_log": raw_log,
        "raw_garmin_text": garmin_text,
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
    allowed = set(entry) - {"id", "created_at", "updated_at"}
    garmin_text = changes.get("raw_garmin_text") or changes.get("garmin_text")
    parsed = parse_garmin_summary(garmin_text) if garmin_text else {}
    accepted = {key: value for key, value in {**parsed, **changes}.items() if key in allowed}
    merged = {**entry, **accepted}
    if garmin_text:
        merged["raw_garmin_text"] = _text(garmin_text, 16000)
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


def start_session(owner: Optional[str], title: str = "") -> Dict[str, Any]:
    state = load_gym_log(owner)
    if state["active_session"]:
        return state["active_session"]
    session = _normalize_session({
        "title": title or "Workout",
        "date": date.today().isoformat(),
        "started_at": _now(),
        "exercises": [],
    })
    state["active_session"] = session
    save_gym_log(owner, state)
    return session


def add_session_set(
    owner: Optional[str],
    exercise: str,
    weight: str,
    reps: Any,
) -> Dict[str, Any]:
    state = load_gym_log(owner)
    session = state.get("active_session")
    if not session:
        raise GymLogError("Start a workout before adding a set.")
    exercise_name = _text(exercise, 120)
    rep_count = _number(reps)
    if not exercise_name or rep_count is None:
        raise GymLogError("Exercise name and reps are required.")
    target = next(
        (item for item in session["exercises"] if item["name"].casefold() == exercise_name.casefold()),
        None,
    )
    if target is None:
        target = {"name": exercise_name, "sets": []}
        session["exercises"].append(target)
    target["sets"].append({"weight": _text(weight, 40), "reps": rep_count})
    state["active_session"] = session
    save_gym_log(owner, state)
    return session


def edit_session_set(
    owner: Optional[str],
    exercise: str,
    set_index: Any,
    weight: str,
    reps: Any,
) -> Dict[str, Any]:
    state = load_gym_log(owner)
    session = state.get("active_session")
    if not session:
        raise GymLogError("No active workout is ready to edit.")
    target = next(
        (
            item for item in session["exercises"]
            if item["name"].casefold() == _text(exercise, 120).casefold()
        ),
        None,
    )
    index = _number(set_index)
    rep_count = _number(reps)
    if target is None or index is None or index >= len(target["sets"]) or rep_count is None:
        raise GymLogError("Workout set not found.")
    target["sets"][index] = {"weight": _text(weight, 40), "reps": rep_count}
    state["active_session"] = session
    save_gym_log(owner, state)
    return session


def delete_last_session_set(owner: Optional[str]) -> Dict[str, Any]:
    state = load_gym_log(owner)
    session = state.get("active_session")
    if not session:
        raise GymLogError("No active workout is ready to edit.")
    for exercise in reversed(session["exercises"]):
        if exercise["sets"]:
            exercise["sets"].pop()
            if not exercise["sets"]:
                session["exercises"].remove(exercise)
            state["active_session"] = session
            save_gym_log(owner, state)
            return session
    raise GymLogError("No workout set is available to remove.")


def finish_session(owner: Optional[str], changes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = load_gym_log(owner)
    session = state.get("active_session")
    if not session:
        raise GymLogError("No active workout is ready to finish.")
    payload = {
        **session,
        **(changes or {}),
        "exercises": session["exercises"],
    }
    entry = add_workout(owner, payload)
    state = load_gym_log(owner)
    state["active_session"] = None
    save_gym_log(owner, state)
    return entry


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
            state = load_gym_log(owner)
            entries = state["entries"]
            exercise = _text(args.get("exercise"), 120).casefold()
            if exercise:
                entries = [
                    row for row in entries
                    if any(exercise in item["name"].casefold() for item in row["exercises"])
                ]
            return {
                "entries": entries[:20],
                "latest": entries[0] if entries else None,
                "active_session": state["active_session"],
                "count": len(entries),
                "exit_code": 0,
            }
        if action == "start_session":
            session = start_session(owner, args.get("title"))
            return {"active_session": session, "output": "Workout started, Boss.", "exit_code": 0}
        if action == "add_set":
            session = add_session_set(
                owner,
                args.get("exercise"),
                args.get("weight"),
                args.get("reps"),
            )
            return {"active_session": session, "output": "Set logged, Boss.", "exit_code": 0}
        if action == "edit_set":
            session = edit_session_set(
                owner,
                args.get("exercise"),
                args.get("set_index"),
                args.get("weight"),
                args.get("reps"),
            )
            return {"active_session": session, "output": "Set updated, Boss.", "exit_code": 0}
        if action == "delete_last_set":
            session = delete_last_session_set(owner)
            return {"active_session": session, "output": "Last set removed, Boss.", "exit_code": 0}
        if action == "finish_session":
            entry = finish_session(owner, args)
            return {"entry": entry, "output": "Done, Boss. Workout saved.", "exit_code": 0}
        if action == "add":
            entry = add_workout(owner, args)
            return {"entry": entry, "output": "Done, Boss. Gym log saved.", "exit_code": 0}
        if action in {"update", "update_garmin"}:
            identifier = _text(args.get("id") or args.get("date"), 160)
            if not identifier:
                identifier = date.today().isoformat()
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
        return {
            "error": (
                "Use list, start_session, add_set, edit_set, delete_last_set, "
                "finish_session, add, update, update_garmin, or append_note."
            ),
            "exit_code": 1,
        }
    except GymLogError as exc:
        return {"error": str(exc), "exit_code": 1}

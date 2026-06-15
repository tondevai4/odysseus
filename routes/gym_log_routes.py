"""Authenticated Gym / Body tracker routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.gym_log import (
    GymLogError,
    add_session_set,
    add_workout,
    delete_last_session_set,
    edit_session_set,
    finish_session,
    load_gym_log,
    start_session,
    update_workout,
)
from src.auth_helpers import get_current_user


class GymEntryBody(BaseModel):
    date: str
    title: str
    duration: str = ""
    total_time: str = ""
    work_time: str = ""
    rest_time: str = ""
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    resting_calories: Optional[int] = None
    active_calories: Optional[int] = None
    total_calories: Optional[int] = None
    estimated_sweat_loss_ml: Optional[int] = None
    total_reps: Optional[int] = None
    total_sets: Optional[int] = None
    avg_time_per_set: str = ""
    total_volume: Optional[float] = None
    intensity_minutes_moderate: Optional[int] = None
    intensity_minutes_vigorous: Optional[int] = None
    intensity_minutes_total: Optional[int] = None
    body_battery_net_impact: Optional[int] = None
    primary_benefit: str = ""
    muscle_primary: str = ""
    muscle_secondary: str = ""
    muscle_untargeted: str = ""
    exercises: list = Field(default_factory=list)
    notes: str = ""
    win: str = ""
    raw_log: str = ""
    raw_garmin_text: str = ""


class GymEntryPatch(BaseModel):
    date: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    total_time: Optional[str] = None
    work_time: Optional[str] = None
    rest_time: Optional[str] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    resting_calories: Optional[int] = None
    active_calories: Optional[int] = None
    total_calories: Optional[int] = None
    estimated_sweat_loss_ml: Optional[int] = None
    total_reps: Optional[int] = None
    total_sets: Optional[int] = None
    avg_time_per_set: Optional[str] = None
    total_volume: Optional[float] = None
    intensity_minutes_moderate: Optional[int] = None
    intensity_minutes_vigorous: Optional[int] = None
    intensity_minutes_total: Optional[int] = None
    body_battery_net_impact: Optional[int] = None
    primary_benefit: Optional[str] = None
    muscle_primary: Optional[str] = None
    muscle_secondary: Optional[str] = None
    muscle_untargeted: Optional[str] = None
    exercises: Optional[list] = None
    notes: Optional[str] = None
    win: Optional[str] = None
    raw_log: Optional[str] = None
    raw_garmin_text: Optional[str] = None


class StartSessionBody(BaseModel):
    title: str = "Workout"


class AddSetBody(BaseModel):
    exercise: str
    weight: str = ""
    reps: int


class EditSetBody(AddSetBody):
    set_index: int


class FinishSessionBody(BaseModel):
    duration: str = ""
    notes: str = ""
    win: str = ""
    raw_garmin_text: str = ""


def setup_gym_log_routes() -> APIRouter:
    router = APIRouter(prefix="/api/gym-log", tags=["gym-log"])

    @router.get("")
    async def get_gym_log(request: Request):
        return load_gym_log(get_current_user(request))

    @router.get("/latest")
    async def get_latest_workout(request: Request):
        entries = load_gym_log(get_current_user(request))["entries"]
        return {"entry": entries[0] if entries else None}

    @router.post("/session/start")
    async def begin_workout(request: Request, body: StartSessionBody):
        return start_session(get_current_user(request), body.title)

    @router.post("/session/set")
    async def log_workout_set(request: Request, body: AddSetBody):
        try:
            return add_session_set(
                get_current_user(request),
                body.exercise,
                body.weight,
                body.reps,
            )
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/session/set")
    async def revise_workout_set(request: Request, body: EditSetBody):
        try:
            return edit_session_set(
                get_current_user(request),
                body.exercise,
                body.set_index,
                body.weight,
                body.reps,
            )
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/session/set/last")
    async def remove_last_workout_set(request: Request):
        try:
            return delete_last_session_set(get_current_user(request))
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/session/finish")
    async def complete_workout(request: Request, body: FinishSessionBody):
        try:
            return finish_session(
                get_current_user(request),
                body.model_dump(exclude_none=True),
            )
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("")
    async def create_workout(request: Request, body: GymEntryBody):
        try:
            return add_workout(get_current_user(request), body.model_dump())
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/{entry_id}")
    async def edit_workout(request: Request, entry_id: str, body: GymEntryPatch):
        changes: Dict[str, Any] = body.model_dump(exclude_none=True)
        try:
            return update_workout(get_current_user(request), entry_id, changes)
        except GymLogError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router

"""Authenticated Gym / Body tracker routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.gym_log import GymLogError, add_workout, load_gym_log, update_workout
from src.auth_helpers import get_current_user


class GymEntryBody(BaseModel):
    date: str
    title: str
    duration: str = ""
    work_time: str = ""
    rest_time: str = ""
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    active_calories: Optional[int] = None
    total_calories: Optional[int] = None
    total_reps: Optional[int] = None
    total_sets: Optional[int] = None
    primary_benefit: str = ""
    exercises: list = Field(default_factory=list)
    notes: str = ""
    win: str = ""
    raw_log: str = ""


class GymEntryPatch(BaseModel):
    date: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    work_time: Optional[str] = None
    rest_time: Optional[str] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    active_calories: Optional[int] = None
    total_calories: Optional[int] = None
    total_reps: Optional[int] = None
    total_sets: Optional[int] = None
    primary_benefit: Optional[str] = None
    exercises: Optional[list] = None
    notes: Optional[str] = None
    win: Optional[str] = None
    raw_log: Optional[str] = None


def setup_gym_log_routes() -> APIRouter:
    router = APIRouter(prefix="/api/gym-log", tags=["gym-log"])

    @router.get("")
    async def get_gym_log(request: Request):
        return load_gym_log(get_current_user(request))

    @router.get("/latest")
    async def get_latest_workout(request: Request):
        entries = load_gym_log(get_current_user(request))["entries"]
        return {"entry": entries[0] if entries else None}

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

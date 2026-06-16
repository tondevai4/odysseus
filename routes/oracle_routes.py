"""Authenticated STRNOS Oracle routes."""

from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.oracle_service import (
    OracleError,
    add_gratitude,
    add_important_date,
    add_manifestation,
    add_sign,
    calculate_numerology,
    cosmic_calendar,
    daily_reading,
    load_oracle,
    oracle_summary,
    update_manifestation,
    update_preferences,
    update_profile,
)
from src.auth_helpers import get_current_user


class ProfileBody(BaseModel):
    full_name: str = ""
    date_of_birth: str = ""
    time_of_birth: str = ""
    birth_city: str = ""
    birth_country: str = ""
    timezone: str = ""
    preferred_system: str = "vedic"
    ayanamsa: str = "lahiri"
    house_system: str = "whole_sign"
    manual_placements: str = ""
    notes: str = ""


class PreferencesBody(BaseModel):
    belief_style: list[str] = Field(default_factory=list)
    tone: str = "grounded_mystic"
    manifestation_style: list[str] = Field(default_factory=list)
    avoid_tone: list[str] = Field(default_factory=list)


class GratitudeBody(BaseModel):
    date: str = ""
    grateful_for: list[str] = Field(default_factory=list)
    thankful_before_materialised: list[str] = Field(default_factory=list)
    scripting: str = ""
    signs_seen: list[str] = Field(default_factory=list)
    mood: str = ""
    stress: str = ""
    action_receipt: str = ""


class ManifestationBody(BaseModel):
    category: str = "custom"
    title: str = ""
    statement: str = ""
    status: str = "active"
    target_date: str = ""
    evidence: list[str] = Field(default_factory=list)
    action_receipts: list[str] = Field(default_factory=list)
    notes: str = ""


class ManifestationPatch(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    statement: Optional[str] = None
    status: Optional[str] = None
    target_date: Optional[str] = None
    evidence: Optional[Union[List[str], str]] = None
    action_receipt: Optional[str] = None
    action_receipts: Optional[Union[List[str], str]] = None
    notes: Optional[str] = None


class SignBody(BaseModel):
    date: str = ""
    type: str = "other"
    value: str
    context: str = ""
    meaning: str = ""
    action_prompt: str = ""


class ImportantDateBody(BaseModel):
    date: str
    label: str = ""
    type: str = "custom"
    notes: str = ""


class NumerologyBody(BaseModel):
    date: str
    label: str = ""
    type: str = "custom"
    save: bool = False


class DailyBody(BaseModel):
    date: str = ""
    save: bool = False


def _bad_request(exc: OracleError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def setup_oracle_routes() -> APIRouter:
    router = APIRouter(prefix="/api/oracle", tags=["oracle"])

    @router.get("")
    async def get_oracle(request: Request):
        return load_oracle(get_current_user(request))

    @router.get("/summary")
    async def get_summary(request: Request):
        return oracle_summary(get_current_user(request))

    @router.get("/profile")
    async def get_profile(request: Request):
        return load_oracle(get_current_user(request))["birth_profile"]

    @router.post("/profile")
    async def save_profile(request: Request, body: ProfileBody):
        try:
            return update_profile(get_current_user(request), body.model_dump())
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.post("/settings")
    async def save_settings(request: Request, body: PreferencesBody):
        return update_preferences(get_current_user(request), body.model_dump())

    @router.get("/daily")
    async def get_daily(request: Request, date: str = ""):
        try:
            return daily_reading(get_current_user(request), date or None)
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.post("/daily")
    async def save_daily(request: Request, body: DailyBody):
        try:
            return daily_reading(get_current_user(request), body.date or None, save=body.save)
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.get("/gratitude")
    async def list_gratitude(request: Request):
        return {"entries": load_oracle(get_current_user(request))["gratitude_entries"]}

    @router.post("/gratitude")
    async def create_gratitude(request: Request, body: GratitudeBody):
        try:
            return add_gratitude(get_current_user(request), body.model_dump())
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.get("/manifestations")
    async def list_manifestations(request: Request):
        return {"items": load_oracle(get_current_user(request))["manifestations"]}

    @router.post("/manifestations")
    async def create_manifestation(request: Request, body: ManifestationBody):
        try:
            return add_manifestation(get_current_user(request), body.model_dump())
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.patch("/manifestations/{item_id}")
    async def patch_manifestation(request: Request, item_id: str, body: ManifestationPatch):
        try:
            changes: Dict[str, Any] = body.model_dump(exclude_none=True)
            return update_manifestation(get_current_user(request), item_id, changes)
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.get("/signs")
    async def list_signs(request: Request):
        return {"items": load_oracle(get_current_user(request))["synchronicities"]}

    @router.post("/signs")
    async def create_sign(request: Request, body: SignBody):
        try:
            return add_sign(get_current_user(request), body.model_dump())
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.get("/important-dates")
    async def list_important_dates(request: Request):
        return {"items": load_oracle(get_current_user(request))["important_dates"]}

    @router.post("/important-dates")
    async def create_important_date(request: Request, body: ImportantDateBody):
        try:
            return add_important_date(get_current_user(request), body.model_dump())
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.post("/numerology")
    async def calculate(request: Request, body: NumerologyBody):
        try:
            return calculate_numerology(get_current_user(request), body.model_dump(), persist=body.save)
        except OracleError as exc:
            raise _bad_request(exc) from exc

    @router.get("/cosmic-calendar")
    async def get_cosmic_calendar(request: Request, date: str = ""):
        try:
            return cosmic_calendar(get_current_user(request), date or None)
        except OracleError as exc:
            raise _bad_request(exc) from exc

    return router

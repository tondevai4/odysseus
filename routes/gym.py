# routes/gym.py
"""
REST endpoints for Gym workout logging and progressive overload tracking.
"""
import datetime
import logging
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field

from core.database import SessionLocal, WorkoutEntry, utcnow_naive

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gym & Progressive Overload"])


class CreateWorkoutRequest(BaseModel):
    exercise: str = Field(..., description="Name of the exercise (e.g., Bench Press, Squat)")
    sets: int = Field(default=1, ge=1, description="Number of sets performed")
    reps: int = Field(default=1, ge=1, description="Reps completed")
    weight_kg: float = Field(default=0.0, ge=0.0, description="Weight used in kg")
    rpe: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Rate of Perceived Exertion (1-10)")
    notes: Optional[str] = Field(default="", description="Form notes or remarks")
    timestamp: Optional[datetime.datetime] = Field(default=None, description="Workout timestamp")


@router.post("/api/gym/workout")
async def create_workout_entry(body: CreateWorkoutRequest):
    """Log a completed workout set and exercise."""
    entry_id = f"wo-{uuid.uuid4().hex[:10]}"
    try:
        with SessionLocal() as db:
            entry = WorkoutEntry(
                id=entry_id,
                timestamp=body.timestamp or utcnow_naive(),
                exercise=body.exercise.strip().title(),
                sets=body.sets,
                reps=body.reps,
                weight_kg=body.weight_kg,
                rpe=body.rpe,
                notes=body.notes or "",
            )
            db.add(entry)
            db.commit()

            return {
                "success": True,
                "id": entry_id,
                "workout": {
                    "id": entry_id,
                    "exercise": entry.exercise,
                    "sets": entry.sets,
                    "reps": entry.reps,
                    "weight_kg": entry.weight_kg,
                    "rpe": entry.rpe,
                    "notes": entry.notes,
                    "timestamp": entry.timestamp.isoformat(),
                },
            }
    except Exception as e:
        logger.error(f"Failed to create workout entry: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/api/gym/workouts")
async def list_workouts(exercise: Optional[str] = None, limit: int = Query(default=50, ge=1, le=500)):
    """Retrieve logged workouts, optionally filtered by exercise."""
    try:
        with SessionLocal() as db:
            q = db.query(WorkoutEntry)
            if exercise and exercise.strip():
                q = q.filter(WorkoutEntry.exercise.ilike(f"%{exercise.strip()}%"))
            q = q.order_by(WorkoutEntry.timestamp.desc()).limit(limit)
            entries = q.all()

            return {
                "workouts": [
                    {
                        "id": e.id,
                        "exercise": e.exercise,
                        "sets": e.sets,
                        "reps": e.reps,
                        "weight_kg": e.weight_kg,
                        "rpe": e.rpe,
                        "notes": e.notes,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in entries
                ],
                "total": len(entries),
            }
    except Exception as e:
        logger.error(f"Failed to list workouts: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/api/gym/progressive-overload/{exercise}")
async def get_progressive_overload_stats(exercise: str):
    """Calculate progressive overload progression, estimated 1RM, and total volume."""
    clean_exercise = exercise.strip().title()
    try:
        with SessionLocal() as db:
            entries = (
                db.query(WorkoutEntry)
                .filter(WorkoutEntry.exercise == clean_exercise)
                .order_by(WorkoutEntry.timestamp.asc())
                .all()
            )

            if not entries:
                return {
                    "exercise": clean_exercise,
                    "total_entries": 0,
                    "max_weight_kg": 0.0,
                    "max_estimated_1rm_kg": 0.0,
                    "total_volume_kg": 0.0,
                    "progression": [],
                }

            max_weight = 0.0
            max_1rm = 0.0
            total_volume = 0.0
            progression = []

            for e in entries:
                # Epley Formula for 1RM: weight * (1 + reps / 30.0)
                e_1rm = round(e.weight_kg * (1.0 + (e.reps / 30.0)), 2) if e.weight_kg > 0 else 0.0
                vol = round(e.weight_kg * e.reps * e.sets, 2)
                total_volume += vol

                if e.weight_kg > max_weight:
                    max_weight = e.weight_kg
                if e_1rm > max_1rm:
                    max_1rm = e_1rm

                progression.append({
                    "date": e.timestamp.strftime("%Y-%m-%d"),
                    "weight_kg": e.weight_kg,
                    "reps": e.reps,
                    "sets": e.sets,
                    "estimated_1rm_kg": e_1rm,
                    "volume_kg": vol,
                    "rpe": e.rpe,
                })

            return {
                "exercise": clean_exercise,
                "total_entries": len(entries),
                "max_weight_kg": max_weight,
                "max_estimated_1rm_kg": max_1rm,
                "total_volume_kg": round(total_volume, 2),
                "progression": progression,
            }
    except Exception as e:
        logger.error(f"Failed to calculate progressive overload stats: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


def setup_gym_routes() -> APIRouter:
    return router

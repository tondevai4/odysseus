# routes/system.py
"""
System administration, self-healing repair inspection, Git branch patching,
and Smart Cost Router monitor endpoints for YVES.
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.database import SessionLocal, SystemRepairJob, utcnow_naive
from src.llm_core.cost_router import get_daily_spend, is_budget_exceeded, route_llm_call
from src.agent_loop.repo_refactor import propose_code_patch, list_patch_branches, delete_patch_branch
from core.maintenance import run_nightly_maintenance

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System Administration & Wolverine Self-Repair"])


class ProposePatchRequest(BaseModel):
    task_description: str = Field(..., description="Description of the refactoring task")
    target_files: List[str] = Field(..., description="List of repository files to patch")
    patch_dict: Dict[str, str] = Field(..., description="Mapping of filepath -> new file content")
    test_command: Optional[str] = Field(default="pytest tests/test_dynamic_tooling.py", description="Test suite command")


@router.get("/api/system/repairs")
async def list_repair_jobs(status: Optional[str] = None, limit: int = Query(default=30, ge=1, le=200)):
    """List all auto-repair and self-healing jobs caught by runtime exception traps."""
    try:
        with SessionLocal() as db:
            q = db.query(SystemRepairJob)
            if status and status.strip():
                q = q.filter(SystemRepairJob.status == status.strip())
            q = q.order_by(SystemRepairJob.created_at.desc()).limit(limit)
            jobs = q.all()

            return {
                "jobs": [
                    {
                        "id": j.id,
                        "endpoint": j.endpoint,
                        "error_type": j.error_type,
                        "stack_trace": j.stack_trace[:300] + "..." if len(j.stack_trace) > 300 else j.stack_trace,
                        "proposed_branch": j.proposed_branch,
                        "status": j.status,
                        "diff_preview": j.diff_preview,
                        "created_at": j.created_at.isoformat(),
                    }
                    for j in jobs
                ],
                "total": len(jobs),
            }
    except Exception as e:
        logger.error(f"Failed to list repair jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/api/system/repairs/{job_id}")
async def get_repair_job(job_id: str):
    """Retrieve full details and stack trace for a specific self-repair job."""
    try:
        with SessionLocal() as db:
            job = db.query(SystemRepairJob).filter(SystemRepairJob.id == job_id).first()
            if not job:
                raise HTTPException(status_code=404, detail=f"Repair job '{job_id}' not found")
            return {
                "id": job.id,
                "endpoint": job.endpoint,
                "error_type": job.error_type,
                "stack_trace": job.stack_trace,
                "proposed_branch": job.proposed_branch,
                "status": job.status,
                "diff_preview": job.diff_preview,
                "created_at": job.created_at.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get repair job: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.post("/api/system/refactor/propose")
async def api_propose_patch(body: ProposePatchRequest):
    """Execute a sandboxed Git worktree refactoring patch with test verification."""
    res = propose_code_patch(
        task_description=body.task_description,
        target_files=body.target_files,
        patch_dict=body.patch_dict,
        test_command=body.test_command,
    )
    if not res.get("tests_passed"):
        raise HTTPException(status_code=422, detail=res)
    return res


@router.get("/api/system/cost-router/status")
async def get_cost_router_status():
    """Return live token spend, budget thresholds, and tier assignments."""
    return {
        "daily_spend_usd": get_daily_spend(),
        "budget_exceeded": is_budget_exceeded(),
        "sample_tier_0": route_llm_call("chat"),
        "sample_tier_1": route_llm_call("briefing"),
        "sample_tier_2": route_llm_call("refactor"),
    }


@router.post("/api/system/maintenance/run")
async def api_run_maintenance():
    """Trigger on-demand system maintenance and database vacuuming."""
    res = await run_nightly_maintenance()
    return res


def setup_system_routes() -> APIRouter:
    return router

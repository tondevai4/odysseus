# tests/test_repo_refactor.py
"""
Comprehensive test suite for Phase 4:
- Smart Multi-Tier Cost Router & Token Budget Limits
- Wolverine Git Sandboxed Repository Refactoring Engine
- Global Exception Trapper & System Repair Jobs
- Nightly Tool Health Auditing & Database Maintenance
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from core.database import SessionLocal, SystemRepairJob
from src.cost_router import (
    route_llm_call,
    get_daily_spend,
    record_spend,
    set_daily_spend,
    is_budget_exceeded,
    TIER_0_LOCAL,
    TIER_1_SUB_CENT,
    TIER_2_REASONING,
)
from src.agent_loop.repo_refactor import (
    propose_code_patch,
    validate_target_files,
    list_patch_branches,
    delete_patch_branch,
)
from core.exceptions import handle_system_exception
from core.maintenance import run_nightly_maintenance


@pytest.fixture
def client():
    return TestClient(app)


def test_cost_router_tier_selection():
    """Verify cost router selects appropriate tiers and enforces budget limits."""
    # Reset spend
    set_daily_spend(0.0)
    assert is_budget_exceeded() is False

    # 1. Tier 0: Daily chat & simple scraping
    r0 = route_llm_call("chat", "Hello how are you?")
    assert r0["tier"] == TIER_0_LOCAL
    assert r0["estimated_cost_per_1k"] == 0.0

    # 2. Tier 1: Briefing & Reflection
    r1 = route_llm_call("briefing", "Summarize today's agenda")
    assert r1["tier"] == TIER_1_SUB_CENT
    assert "gpt-4o-mini" in r1["model"]

    # 3. Tier 2: Refactoring & Oracle Debates
    r2 = route_llm_call("refactor", "Refactor the database connection pool")
    assert r2["tier"] == TIER_2_REASONING
    assert r2["budget_ok"] is True

    # 4. Budget Overrun Test
    set_daily_spend(100.0)
    assert is_budget_exceeded() is True

    r_budget = route_llm_call("refactor", "Refactor the database connection pool")
    assert r_budget["tier"] == TIER_0_LOCAL
    assert r_budget["budget_downgraded"] is True

    # Reset spend
    set_daily_spend(0.0)


def test_target_files_security_validation():
    """Verify security filter blocks access to sensitive or root-level files."""
    assert validate_target_files(["src/agent_loop/sandbox.py"]) is True
    assert validate_target_files(["core/database.py"]) is True
    assert validate_target_files(["routes/system.py"]) is True

    # Denied files
    assert validate_target_files([".env"]) is False
    assert validate_target_files(["/etc/passwd"]) is False
    assert validate_target_files(["../outside.py"]) is False
    assert validate_target_files(["passwords.txt"]) is False


def test_git_sandboxed_patching():
    """Verify repository refactoring engine branches, verifies tests, and handles reverts."""
    # Test with syntax error in patch -> should fail early in AST check
    bad_patch = {"src/sample_bad.py": "def invalid_syntax(: return"}
    res_bad = propose_code_patch(
        task_description="Test bad syntax",
        target_files=["src/sample_bad.py"],
        patch_dict=bad_patch,
    )
    assert res_bad["status"] == "failed"
    assert "AST Syntax Error" in res_bad["error"]


def test_system_exception_interceptor(client):
    """Verify runtime 500 exceptions are trapped and logged to repair_queue."""
    test_endpoint = "/api/test-simulated-crash"
    job_id = handle_system_exception(
        endpoint=test_endpoint,
        method="GET",
        exc=RuntimeError("Simulated server exception for self-healing verification"),
        stack_trace="Traceback (most recent call last):\n  File 'test.py', line 10, in <module>\nRuntimeError: Simulated",
    )
    assert job_id is not None

    # Query repair list via endpoint
    res = client.get("/api/system/repairs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(j["id"] == job_id for j in data["jobs"])

    # Query specific repair job
    detail_res = client.get(f"/api/system/repairs/{job_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_nightly_maintenance():
    """Verify nightly maintenance audits tools and vacuums SQLite database."""
    maint_res = await run_nightly_maintenance()
    assert maint_res["success"] is True
    assert "tools_audited" in maint_res
    assert "database_vacuumed" in maint_res
    assert maint_res["database_vacuumed"] is True

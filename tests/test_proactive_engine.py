# tests/test_proactive_engine.py
"""
Comprehensive unit test suite for Phase 2:
- Reflexion Heuristic Extraction & Pre-Flight Injection
- Oracle Multi-Persona Strategic Decision Engine
- Gym Log & Progressive Overload Tracking
- Nightly Memory Evolution Engine & SOUL.md Generator
- Proactive Daemon & Heartbeat Scheduler
"""
import asyncio
import datetime
import os
import pytest
from fastapi.testclient import TestClient

from app import app
from core.database import (
    SessionLocal,
    WorkoutEntry,
    OracleDecision,
    UserPreferenceFact,
    DailyBriefing,
    ChatMessage,
    Session,
    utcnow_naive,
)
from src.agent_loop.reflection import (
    extract_heuristic,
    query_heuristics,
    is_user_correction,
)
from core.evolution import run_nightly_evolution
from core.proactive_daemon import (
    start_proactive_daemon,
    stop_proactive_daemon,
    generate_morning_briefing,
    run_interest_profiler,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_heuristic_extraction_and_injection():
    """Test extracting an imperative constraint rule from a user correction and querying it."""
    # 1. Test correction detector
    assert is_user_correction("No, that's wrong. Always calculate Part-P electrician rates at £300/day.") is True
    assert is_user_correction("Don't use deprecated endpoints") is True
    assert is_user_correction("Hello, can you help me write a Python function?") is False

    # 2. Extract rule
    task = "Estimate electrical rewiring costs for residential property"
    failed_action = "Estimated rate at £150/day standard labor"
    correction = "Always calculate Part-P electrician rates at £300/day ex-VAT"

    rule = await extract_heuristic(
        task=task,
        failed_action=failed_action,
        error_or_feedback=correction,
    )
    assert "Always calculate Part-P electrician rates at £300/day ex-VAT" in rule

    # 3. Query heuristics
    results = query_heuristics("What is the cost for Part-P electrician rewiring?")
    assert len(results) >= 1
    assert any("£300" in r for r in results)


def test_oracle_debate_synthesis(client):
    """Test multi-persona debate matrix evaluation and persistence."""
    payload = {
        "title": "Launch Autonomous Agent Marketplace",
        "premise": "Allow users to monetize custom synthesized tools with 15% platform take-rate.",
        "options": ["Full launch with Stripe Connect", "Private beta with invite codes"],
    }
    response = client.post("/api/oracle/decide", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    decision = data["decision"]
    assert "Growth Persona:" in decision["critique_growth"] or "Growth" in decision["critique_growth"]
    assert "Risk Persona:" in decision["critique_risk"] or "Risk" in decision["critique_risk"]
    assert 0.0 <= decision["synthesis_score"] <= 100.0
    assert len(decision["verdict"]) > 10

    # Query list
    list_res = client.get("/api/oracle/decisions")
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1


def test_gym_database_crud(client):
    """Test workout logging and progressive overload metrics computation."""
    # 1. Log workout set 1
    w1 = {
        "exercise": "Overhead Press",
        "sets": 3,
        "reps": 8,
        "weight_kg": 50.0,
        "rpe": 8.0,
        "notes": "Felt smooth, clean lockout",
    }
    r1 = client.post("/api/gym/workout", json=w1)
    assert r1.status_code == 200
    assert r1.json()["success"] is True

    # 2. Log workout set 2 with progressive overload
    w2 = {
        "exercise": "Overhead Press",
        "sets": 3,
        "reps": 6,
        "weight_kg": 55.0,
        "rpe": 8.5,
        "notes": "New PR",
    }
    r2 = client.post("/api/gym/workout", json=w2)
    assert r2.status_code == 200

    # 3. Query progressive overload calculations
    po_res = client.get("/api/gym/progressive-overload/Overhead%20Press")
    assert po_res.status_code == 200
    stats = po_res.json()

    assert stats["exercise"] == "Overhead Press"
    assert stats["total_entries"] >= 2
    assert stats["max_weight_kg"] == 55.0
    # Epley 1RM for 55kg x 6 = 55 * (1 + 6/30) = 66.0 kg
    assert stats["max_estimated_1rm_kg"] >= 65.0
    assert stats["total_volume_kg"] > 0
    assert len(stats["progression"]) >= 2


@pytest.mark.asyncio
async def test_proactive_daemon_and_briefing():
    """Test proactive daemon lifecycle and morning briefing generation."""
    # 1. Generate morning briefing
    briefing = await generate_morning_briefing()
    assert briefing["success"] is True
    assert len(briefing["bullets"]) == 3

    # Check database persistence
    with SessionLocal() as db:
        today_str = utcnow_naive().strftime("%Y-%m-%d")
        db_briefing = db.query(DailyBriefing).filter(DailyBriefing.date == today_str).first()
        assert db_briefing is not None
        assert "Schedule:" in db_briefing.summary

    # 2. Test daemon task start and stop
    daemon_task = start_proactive_daemon()
    assert daemon_task is not None
    assert not daemon_task.done()

    # Stop daemon cleanly
    stop_proactive_daemon()
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_nightly_evolution_and_soul(tmp_path):
    """Test nightly evolution consolidation and SOUL.md document generation."""
    test_data_dir = str(tmp_path / "data")
    os.makedirs(test_data_dir, exist_ok=True)

    # Seed sample chat message with preference
    with SessionLocal() as db:
        sess = db.query(Session).filter(Session.id == "session-evo-1").first()
        if not sess:
            sess = Session(
                id="session-evo-1",
                name="Evolution Test Session",
                endpoint_url="http://localhost:11434/v1",
                model="test-model",
            )
            db.add(sess)
            db.commit()

        msg = ChatMessage(
            id=f"msg-evo-{int(datetime.datetime.now().timestamp())}",
            session_id="session-evo-1",
            role="user",
            content="I prefer dark mode, always use metric units, and my bench press goal is 120kg.",
            timestamp=utcnow_naive(),
        )
        db.add(msg)
        db.commit()


    evo_res = await run_nightly_evolution(data_dir=test_data_dir, lookback_hours=24)
    assert evo_res["success"] is True
    assert evo_res["soul_updated"] is True

    # Verify SOUL.md exists and contains sections
    soul_file = os.path.join(test_data_dir, "SOUL.md")
    assert os.path.exists(soul_file)
    with open(soul_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# YVES — SOUL" in content
    assert "## 1. System Identity & Mission" in content
    assert "## 2. User Core Profile & Preferences" in content

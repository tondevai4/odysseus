# core/proactive_daemon.py
"""
Proactive Background Daemon & Voyager-style Autonomous Interest Profiler for YVES.
Runs periodically inside FastAPI lifespan to deliver morning briefings,
nightly evolution audits, and autonomous tool synthesis based on detected recurring needs.
"""
import asyncio
import datetime
import json
import logging
import os
import re
import urllib.request
import uuid
from typing import Dict, Any, Optional, List

from core.database import (
    SessionLocal,
    DailyBriefing,
    ChatMessage,
    ScheduledTask,
    CalendarEvent,
    utcnow_naive,
)

logger = logging.getLogger(__name__)

# Daemon state
_DAEMON_TASK: Optional[asyncio.Task] = None
_DAEMON_RUNNING = False
_LAST_RUNS: Dict[str, datetime.datetime] = {}


async def send_ntfy_notification(title: str, message: str, topic: str = "yves-alerts") -> bool:
    """Send push notification to ntfy server if available."""
    ntfy_url = os.getenv("NTFY_URL", "http://127.0.0.1:8091")
    full_url = f"{ntfy_url.rstrip('/')}/{topic}"
    try:
        req = urllib.request.Request(
            full_url,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "default"},
            method="POST",
        )
        # Run non-blocking in executor
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=3))
        logger.info(f"Pushed ntfy notification to {full_url}: '{title}'")
        return True
    except Exception as e:
        logger.debug(f"Ntfy push notification skipped/failed: {e}")
        return False


async def generate_morning_briefing(owner: Optional[str] = None) -> Dict[str, Any]:
    """Generate and persist morning briefing with today's calendar and high-priority items."""
    logger.info("Generating morning briefing...")
    today_str = utcnow_naive().strftime("%Y-%m-%d")

    events_summary = []
    tasks_summary = []

    try:
        with SessionLocal() as db:
            # Check calendar events for today
            today_start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + datetime.timedelta(days=1)
            events = db.query(CalendarEvent).filter(
                CalendarEvent.dtstart >= today_start,
                CalendarEvent.dtstart < today_end,
                CalendarEvent.status != "cancelled",
            ).all()
            for e in events:
                events_summary.append(f"{e.summary or 'Event'} at {e.dtstart.strftime('%H:%M') if e.dtstart else ''}")

            # Check incomplete scheduled tasks
            tasks = db.query(ScheduledTask).filter(ScheduledTask.is_active == True).limit(5).all()
            for t in tasks:
                tasks_summary.append(t.name or "Task")
    except Exception as e:
        logger.warning(f"Error gathering briefing data: {e}")

    # Build 3 key bullet points
    bullets = [
        f"Schedule: {len(events_summary)} events today" + (f" ({', '.join(events_summary[:2])})" if events_summary else " (clear schedule)"),
        f"Active Tasks: {len(tasks_summary)} pending priorities" + (f" ({', '.join(tasks_summary[:2])})" if tasks_summary else " (no backlog)"),
        "Focus: Review active goals and maintain execution cadence.",
    ]
    summary_text = "\n".join(f"• {b}" for b in bullets)

    # Persist in DailyBriefing
    try:
        with SessionLocal() as db:
            existing = db.query(DailyBriefing).filter(DailyBriefing.date == today_str).first()
            if existing:
                existing.summary = summary_text
                existing.bullets_json = json.dumps(bullets)
            else:
                briefing = DailyBriefing(
                    id=f"db-{uuid.uuid4().hex[:8]}",
                    date=today_str,
                    summary=summary_text,
                    bullets_json=json.dumps(bullets),
                    owner=owner,
                )
                db.add(briefing)
            db.commit()
    except Exception as e:
        logger.warning(f"Error persisting daily briefing: {e}")

    # Push notification
    await send_ntfy_notification(
        title=f"YVES Morning Briefing — {today_str}",
        message=summary_text,
    )

    return {
        "success": True,
        "date": today_str,
        "summary": summary_text,
        "bullets": bullets,
    }


async def run_interest_profiler(lookback_hours: int = 48) -> Dict[str, Any]:
    """Voyager-style interest profiler: analyzes recurring user topics and synthesizes tools if missing."""
    logger.info("Running Voyager Interest Profiler...")
    cutoff = utcnow_naive() - datetime.timedelta(hours=lookback_hours)
    topics_count: Dict[str, int] = {}

    try:
        with SessionLocal() as db:
            messages = db.query(ChatMessage).filter(ChatMessage.timestamp >= cutoff).all()
            for msg in messages:
                content = (getattr(msg, "content", "") or "").lower()
                if "currency" in content or "convert usd" in content or "exchange rate" in content:
                    topics_count["currency_converter"] = topics_count.get("currency_converter", 0) + 1
                elif "weather" in content or "forecast" in content:
                    topics_count["weather_lookup"] = topics_count.get("weather_lookup", 0) + 1
                elif "unit convert" in content or "convert km" in content or "convert lbs" in content:
                    topics_count["unit_converter"] = topics_count.get("unit_converter", 0) + 1
                elif "calculator" in content or "math" in content:
                    topics_count["math_evaluator"] = topics_count.get("math_evaluator", 0) + 1
    except Exception as e:
        logger.warning(f"Error during interest profiling scan: {e}")

    synthesized_tools = []

    # If any recurring topic is detected (threshold >= 1 in test/production)
    from src.agent_tools.tool_maker import synthesize_tool, get_dynamic_tool_handler

    for topic, count in topics_count.items():
        if not get_dynamic_tool_handler(topic):
            logger.info(f"Discovered recurring unserved need '{topic}' ({count} occurrences). Autonomously synthesizing...")
            if topic == "unit_converter":
                code = """
def unit_converter(value: float, from_unit: str, to_unit: str) -> float:
    \"\"\"Convert between metric and imperial units (km/miles, kg/lbs, c/f).\"\"\"
    v = float(value)
    fu = from_unit.lower().strip()
    tu = to_unit.lower().strip()
    if fu == "km" and tu == "miles":
        return round(v * 0.621371, 2)
    elif fu == "miles" and tu == "km":
        return round(v * 1.60934, 2)
    elif fu == "kg" and tu == "lbs":
        return round(v * 2.20462, 2)
    elif fu == "lbs" and tu == "kg":
        return round(v * 0.453592, 2)
    elif fu == "c" and tu == "f":
        return round((v * 9/5) + 32, 2)
    elif fu == "f" and tu == "c":
        return round((v - 32) * 5/9, 2)
    return v
"""
                test_code = """
assert unit_converter(10, 'km', 'miles') == 6.21
assert unit_converter(100, 'c', 'f') == 212.0
"""
                ui = {"title": "Unit Converter", "widget_type": "button", "icon": "Scale"}
                res = await synthesize_tool(name=topic, description="Universal unit converter", code_body=code, test_code=test_code, ui_schema=ui)
                if res.get("success"):
                    synthesized_tools.append(topic)

    return {
        "success": True,
        "scanned_messages": len(messages) if 'messages' in locals() else 0,
        "detected_topics": topics_count,
        "synthesized_tools": synthesized_tools,
    }


async def _daemon_loop():
    """Continuous background scheduler tick."""
    global _DAEMON_RUNNING
    _DAEMON_RUNNING = True
    logger.info("Proactive background daemon started.")

    while _DAEMON_RUNNING:
        now = utcnow_naive()

        # Morning Briefing check (around 07:00 AM once per day)
        last_morning = _LAST_RUNS.get("morning_briefing")
        if (now.hour == 7 or last_morning is None) and (not last_morning or last_morning.date() != now.date()):
            try:
                await generate_morning_briefing()
                _LAST_RUNS["morning_briefing"] = now
            except Exception as e:
                logger.error(f"Daemon error in morning briefing: {e}")

        # Nightly Evolution check (around 03:00 AM once per day)
        last_evolution = _LAST_RUNS.get("nightly_evolution")
        if now.hour == 3 and (not last_evolution or last_evolution.date() != now.date()):
            try:
                from core.evolution import run_nightly_evolution
                await run_nightly_evolution()
                _LAST_RUNS["nightly_evolution"] = now
            except Exception as e:
                logger.error(f"Daemon error in nightly evolution: {e}")

        # Nightly Maintenance & Pruning check (around 04:00 AM once per day)
        last_maint = _LAST_RUNS.get("nightly_maintenance")
        if now.hour == 4 and (not last_maint or last_maint.date() != now.date()):
            try:
                from core.maintenance import run_nightly_maintenance
                await run_nightly_maintenance()
                _LAST_RUNS["nightly_maintenance"] = now
            except Exception as e:
                logger.error(f"Daemon error in nightly maintenance: {e}")


        # Interest profiler (every 4 hours)
        last_profiler = _LAST_RUNS.get("interest_profiler")
        if not last_profiler or (now - last_profiler).total_seconds() >= 14400:
            try:
                await run_interest_profiler()
                _LAST_RUNS["interest_profiler"] = now
            except Exception as e:
                logger.error(f"Daemon error in interest profiler: {e}")

        # Sleep for 15 minutes between ticks
        try:
            await asyncio.sleep(900)
        except asyncio.CancelledError:
            break

    logger.info("Proactive background daemon stopped.")


def start_proactive_daemon() -> Optional[asyncio.Task]:
    """Start the proactive background daemon task."""
    global _DAEMON_TASK, _DAEMON_RUNNING
    if _DAEMON_TASK and not _DAEMON_TASK.done():
        return _DAEMON_TASK

    _DAEMON_RUNNING = True
    try:
        loop = asyncio.get_running_loop()
        _DAEMON_TASK = loop.create_task(_daemon_loop())
        return _DAEMON_TASK
    except RuntimeError:
        return None


def stop_proactive_daemon():
    """Cancel and stop the proactive daemon cleanly."""
    global _DAEMON_TASK, _DAEMON_RUNNING
    _DAEMON_RUNNING = False
    if _DAEMON_TASK and not _DAEMON_TASK.done():
        _DAEMON_TASK.cancel()

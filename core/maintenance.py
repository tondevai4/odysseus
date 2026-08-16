# core/maintenance.py
"""
Nightly Maintenance & Pruning Daemon for YVES.
Audits dynamic tools, disables failing ones, vacuums SQLite app.db, and prunes stale repair jobs.
"""
import asyncio
import datetime
import logging
import sqlite3
from typing import Dict, Any, List

from core.database import SessionLocal, DynamicTool, SystemRepairJob, utcnow_naive
from src.agent_tools.tool_maker import list_dynamic_tools

logger = logging.getLogger(__name__)


async def run_nightly_maintenance() -> Dict[str, Any]:
    """Execute nightly system maintenance, tool auditing, and database vacuuming."""
    logger.info("Starting Nightly System Maintenance...")
    tools_audited = 0
    tools_disabled = 0
    jobs_pruned = 0
    db_vacuumed = False

    # 1. Audit dynamic tools
    try:
        with SessionLocal() as db:
            tools = db.query(DynamicTool).all()
            for t in tools:
                tools_audited += 1
                # If tool has missing file or invalid status, disable
                try:
                    import importlib
                    importlib.import_module(f"src.agent_tools.dynamic.{t.name}")
                except Exception as imp_err:
                    logger.warning(f"Disabling unimportable tool '{t.name}': {imp_err}")
                    t.enabled = False
                    tools_disabled += 1
            db.commit()
    except Exception as e:
        logger.warning(f"Tool auditing error during maintenance: {e}")

    # 2. Prune old resolved/failed repair jobs (> 14 days)
    cutoff = utcnow_naive() - datetime.timedelta(days=14)
    try:
        with SessionLocal() as db:
            pruned = db.query(SystemRepairJob).filter(
                SystemRepairJob.created_at < cutoff,
                SystemRepairJob.status.in_(["resolved", "failed"]),
            ).delete()
            db.commit()
            jobs_pruned = pruned
    except Exception as e:
        logger.warning(f"Repair job pruning error: {e}")

    # 3. VACUUM SQLite database
    try:
        from core.database import DATABASE_URL
        if "sqlite" in DATABASE_URL:
            # Extract path from sqlite:///...
            db_path = DATABASE_URL.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            conn.execute("VACUUM")
            conn.close()
            db_vacuumed = True
            logger.info("SQLite app.db VACUUM completed successfully.")
    except Exception as e:
        logger.warning(f"Database VACUUM notice: {e}")

    return {
        "success": True,
        "tools_audited": tools_audited,
        "tools_disabled": tools_disabled,
        "jobs_pruned": jobs_pruned,
        "database_vacuumed": db_vacuumed,
        "timestamp": utcnow_naive().isoformat(),
    }


def run_nightly_maintenance_sync() -> Dict[str, Any]:
    """Synchronous wrapper for run_nightly_maintenance."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, run_nightly_maintenance()).result()
        return loop.run_until_complete(run_nightly_maintenance())
    except RuntimeError:
        return asyncio.run(run_nightly_maintenance())

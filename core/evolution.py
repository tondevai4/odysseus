# core/evolution.py
"""
Nightly Evolution Engine for YVES.
Consolidates user preferences, project context, and fitness data from recent chats,
persisting facts into the database and updating data/SOUL.md.
"""
import asyncio
import datetime
import logging
import os
import pathlib
import re
import uuid
from typing import Dict, Any, List, Optional

from core.database import SessionLocal, UserPreferenceFact, ChatMessage, Session, utcnow_naive

logger = logging.getLogger(__name__)

DATA_DIR_PATH = pathlib.Path("data").resolve()
SOUL_FILE = DATA_DIR_PATH / "SOUL.md"


def _extract_facts_from_text(text: str) -> List[Dict[str, str]]:
    """Heuristic extraction of preferences, metrics, and facts from conversation turns."""
    facts = []
    lines = text.splitlines()
    for line in lines:
        l = line.strip()
        if not l:
            continue

        # Currency / timezone / tech preferences
        if re.search(r"\b(prefer|like|always use|set my)\b", l, re.IGNORECASE):
            facts.append({"category": "preferences", "fact": l})
        # Workout / fitness facts
        elif re.search(r"\b(bench|squat|deadlift|workout|gym|kg|reps|sets)\b", l, re.IGNORECASE):
            facts.append({"category": "fitness", "fact": l})
        # Business / financial / project facts
        elif re.search(r"\b(project|budget|revenue|cost|margin|client|deadline|rate|vat)\b", l, re.IGNORECASE):
            facts.append({"category": "business", "fact": l})
        # General knowledge facts
        elif re.search(r"\b(my name is|i live in|i am a|i work at)\b", l, re.IGNORECASE):
            facts.append({"category": "profile", "fact": l})

    return facts


async def run_nightly_evolution(
    data_dir: Optional[str] = None,
    lookback_hours: int = 24,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the nightly memory consolidation and SOUL.md update.

    Args:
        data_dir: Path to data directory.
        lookback_hours: Number of hours to look back for new conversations.
        owner: Optional user filter.

    Returns:
        Summary dictionary with execution stats.
    """
    logger.info("Starting Nightly Evolution Engine consolidation...")
    cutoff = utcnow_naive() - datetime.timedelta(hours=lookback_hours)
    extracted_facts: List[Dict[str, str]] = []

    # 1. Read recent chat messages from SQLite
    try:
        with SessionLocal() as db:
            query = db.query(ChatMessage).filter(ChatMessage.timestamp >= cutoff)
            messages = query.all()
            for msg in messages:
                content = getattr(msg, "content", "") or ""
                if content and len(content) > 10:
                    found = _extract_facts_from_text(content)
                    for f in found:
                        f["session_id"] = getattr(msg, "session_id", None)
                        extracted_facts.append(f)

            # Deduplicate and persist new facts into UserPreferenceFact table
            for item in extracted_facts:
                fact_text = item["fact"]
                cat = item["category"]
                existing = db.query(UserPreferenceFact).filter(
                    UserPreferenceFact.category == cat,
                    UserPreferenceFact.fact == fact_text,
                ).first()
                if not existing:
                    new_fact = UserPreferenceFact(
                        id=f"upf-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        fact=fact_text,
                        confidence=1.0,
                        source_session_id=item.get("session_id"),
                        owner=owner,
                    )
                    db.add(new_fact)
            db.commit()

            # Retrieve all consolidated facts to build SOUL.md
            all_facts = db.query(UserPreferenceFact).all()
    except Exception as e:
        logger.warning(f"Error querying/updating facts during evolution: {e}")
        all_facts = []

    # 2. Group facts by category
    categorized: Dict[str, List[str]] = {}
    for f in all_facts:
        cat = getattr(f, "category", "general") or "general"
        categorized.setdefault(cat, []).append(f.fact)

    # 3. Generate updated SOUL.md content
    target_data_dir = pathlib.Path(data_dir).resolve() if data_dir else DATA_DIR_PATH
    target_data_dir.mkdir(parents=True, exist_ok=True)
    soul_path = target_data_dir / "SOUL.md"

    now_iso = utcnow_naive().strftime("%Y-%m-%d %H:%M:%S UTC")
    soul_content = [
        "# YVES — SOUL & CONSOLIDATED KNOWLEDGE BASE",
        f"**Last Consolidated:** {now_iso}",
        "",
        "## 1. System Identity & Mission",
        "- **Agent:** YVES (Autonomous AI Assistant & Pair Programmer)",
        "- **Stance:** Grounded, cost-effective, high precision, proactive, and resilient.",
        "",
        "## 2. User Core Profile & Preferences",
    ]

    for cat_name in ("profile", "preferences"):
        facts_list = categorized.get(cat_name, [])
        soul_content.append(f"### {cat_name.title()}")
        if facts_list:
            for fact in facts_list[:15]:
                soul_content.append(f"- {fact}")
        else:
            soul_content.append("- Default personal profile configured.")
        soul_content.append("")

    soul_content.append("## 3. Active Projects & Business Context")
    biz_list = categorized.get("business", [])
    if biz_list:
        for fact in biz_list[:15]:
            soul_content.append(f"- {fact}")
    else:
        soul_content.append("- No active business constraints recorded.")
    soul_content.append("")

    soul_content.append("## 4. Health & Physical Metrics")
    fit_list = categorized.get("fitness", [])
    if fit_list:
        for fact in fit_list[:15]:
            soul_content.append(f"- {fact}")
    else:
        soul_content.append("- Tracking progressive overload workouts.")
    soul_content.append("")

    # Write SOUL.md to disk
    try:
        soul_path.write_text("\n".join(soul_content), encoding="utf-8")
        logger.info(f"Updated SOUL.md successfully at {soul_path}")
        soul_updated = True
    except Exception as e:
        logger.error(f"Failed to write SOUL.md: {e}")
        soul_updated = False

    return {
        "success": True,
        "facts_extracted": len(extracted_facts),
        "total_facts_stored": len(all_facts),
        "soul_updated": soul_updated,
        "soul_path": str(soul_path),
        "timestamp": now_iso,
    }


def run_nightly_evolution_sync(*args, **kwargs) -> Dict[str, Any]:
    """Synchronous wrapper for run_nightly_evolution."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, run_nightly_evolution(*args, **kwargs)).result()
        return loop.run_until_complete(run_nightly_evolution(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(run_nightly_evolution(*args, **kwargs))

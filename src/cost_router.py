# src/cost_router.py
"""
Smart Multi-Tier Model Cost Router for YVES.
Dynamically routes tasks across Local Free (Ollama), Sub-Cent (gpt-4o-mini), and High-Reasoning (o3-mini/gpt-4o)
with automated token budget tracking and daily spending limit guards.
"""
import datetime
import logging
import os
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Daily spend tracking state
_DAILY_SPEND: float = 0.0
_CURRENT_DAY: str = datetime.date.today().isoformat()
_SPEND_LIMIT_USD: float = float(os.getenv("DAILY_SPEND_LIMIT_USD", "5.00"))

TIER_0_LOCAL = 0       # Free local Ollama (Qwen 2.5 Coder, Llama 3)
TIER_1_SUB_CENT = 1    # Fast, cheap cloud API (gpt-4o-mini)
TIER_2_REASONING = 2   # High-reasoning complex tasks (o3-mini, gpt-4o)


def _check_and_reset_day():
    """Reset daily spend tracker on date rollover."""
    global _DAILY_SPEND, _CURRENT_DAY
    today = datetime.date.today().isoformat()
    if today != _CURRENT_DAY:
        _CURRENT_DAY = today
        _DAILY_SPEND = 0.0


def get_daily_spend() -> float:
    """Return total USD spent today."""
    _check_and_reset_day()
    return round(_DAILY_SPEND, 4)


def record_spend(usd: float):
    """Record an API expense towards the daily spend limit."""
    global _DAILY_SPEND
    _check_and_reset_day()
    _DAILY_SPEND += max(0.0, float(usd))


def set_daily_spend(usd: float):
    """Override current day spend (useful for testing budget limits)."""
    global _DAILY_SPEND
    _check_and_reset_day()
    _DAILY_SPEND = float(usd)


def is_budget_exceeded() -> bool:
    """Check if the daily spending limit has been reached."""
    _check_and_reset_day()
    return _DAILY_SPEND >= _SPEND_LIMIT_USD


def route_llm_call(
    task_type: str,
    prompt_text: str = "",
    context_token_count: int = 0,
) -> Dict[str, Any]:
    """Smart dynamic multi-tier model selector based on task complexity and budget limits.

    Args:
        task_type: e.g. 'chat', 'scraping', 'briefing', 'reflection', 'refactor', 'math', 'oracle_debate'
        prompt_text: Raw input prompt string
        context_token_count: Estimated token count for context window

    Returns:
        Dictionary containing tier, model, endpoint, estimated cost, and reasoning.
    """
    _check_and_reset_day()
    budget_exceeded = is_budget_exceeded()

    clean_task = (task_type or "").strip().lower()
    clean_prompt = (prompt_text or "").lower()

    local_model = os.getenv("LOCAL_OLLAMA_MODEL", "qwen2.5-coder:7b")
    local_url = os.getenv("LOCAL_OLLAMA_URL", "http://localhost:11434/v1")
    openai_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # Tier 2 Tasks: Complex Architecture, Code Refactoring, Mathematical Models, Multi-Persona Debates
    is_tier_2 = (
        clean_task in ("refactor", "repo_patch", "math", "oracle_debate", "architecture_audit")
        or "propose_code_patch" in clean_task
        or "amortization" in clean_prompt
        or "solve complex" in clean_prompt
    )

    # Tier 1 Tasks: Morning Briefings, Reflexion Error Synthesis, SDUI Schemas, Email Triage
    is_tier_1 = (
        clean_task in ("briefing", "reflection", "sdui_schema", "email_triage", "heuristic_extraction")
        or "summarize email" in clean_prompt
        or "extract heuristic" in clean_task
    )

    # Resolve target tier
    if is_tier_2:
        target_tier = TIER_2_REASONING
    elif is_tier_1:
        target_tier = TIER_1_SUB_CENT
    else:
        target_tier = TIER_0_LOCAL

    # Check budget constraints: if budget exceeded, downgrade Tier 1 & 2 to Tier 0 (Free Local)
    if target_tier > TIER_0_LOCAL and budget_exceeded:
        logger.warning(
            f"Daily token budget limit (${_SPEND_LIMIT_USD:.2f}) exceeded (Current: ${_DAILY_SPEND:.2f}). "
            f"Downgrading '{task_type}' from Tier {target_tier} to Tier 0 (Local Free)."
        )
        return {
            "tier": TIER_0_LOCAL,
            "model": local_model,
            "endpoint": local_url,
            "reasoning": f"Budget limit (${_SPEND_LIMIT_USD:.2f}) exceeded — downgraded to Local Free",
            "estimated_cost_per_1k": 0.0,
            "budget_ok": False,
            "budget_downgraded": True,
        }

    if target_tier == TIER_2_REASONING:
        return {
            "tier": TIER_2_REASONING,
            "model": os.getenv("TIER_2_MODEL", "o3-mini"),
            "endpoint": openai_url,
            "reasoning": f"High reasoning required for '{task_type}'",
            "estimated_cost_per_1k": 0.0011,
            "budget_ok": True,
            "budget_downgraded": False,
        }
    elif target_tier == TIER_1_SUB_CENT:
        return {
            "tier": TIER_1_SUB_CENT,
            "model": os.getenv("TIER_1_MODEL", "gpt-4o-mini"),
            "endpoint": openai_url,
            "reasoning": f"Sub-cent fast cloud model optimal for '{task_type}'",
            "estimated_cost_per_1k": 0.00015,
            "budget_ok": True,
            "budget_downgraded": False,
        }
    else:
        return {
            "tier": TIER_0_LOCAL,
            "model": local_model,
            "endpoint": local_url,
            "reasoning": f"Local free Ollama/Qwen model sufficient for '{task_type}'",
            "estimated_cost_per_1k": 0.0,
            "budget_ok": True,
            "budget_downgraded": False,
        }

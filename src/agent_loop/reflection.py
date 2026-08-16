# src/agent_loop/reflection.py
"""
Reflexion Memory & Heuristic Rule Engine for YVES.
Captures runtime errors and user corrections, distills them into permanent rules in ChromaDB,
and injects them pre-flight into subsequent prompts.
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# In-memory fallback cache if ChromaDB HTTP service is offline
_HEURISTICS_FALLBACK: List[Dict[str, Any]] = []

CORRECTION_PATTERNS = [
    r"^(no[,\.\s!]|wrong|incorrect|false|nope)",
    r"^(don't|do not|stop|never)\b",
    r"^(that'?s (not|wrong|incorrect|false))",
    r"^(you (made a mistake|failed|got it wrong|are wrong))",
    r"^(not quite|that is (wrong|incorrect|false))",
]


def is_user_correction(text: str) -> bool:
    """Check if the user's message indicates negative feedback or a correction."""
    if not isinstance(text, str) or not text.strip():
        return False
    lowered = text.strip().lower()
    for pat in CORRECTION_PATTERNS:
        if re.search(pat, lowered):
            return True
    return False


def get_heuristics_collection():
    """Retrieve or create the agent_heuristics ChromaDB collection."""
    try:
        from src.chroma_client import get_chroma_client
        client = get_chroma_client()
        return client.get_or_create_collection(name="agent_heuristics")
    except Exception as e:
        logger.debug(f"ChromaDB heuristics collection access notice: {e}")
        return None


def _heuristic_rule_synthesis(task: str, failed_action: str, error_or_feedback: str) -> str:
    """Deterministic rule synthesis fallback when LLM is offline."""
    clean_feedback = error_or_feedback.strip()
    # If feedback is a direct instruction like "always calculate ... at £300/day"
    if clean_feedback.lower().startswith("always ") or clean_feedback.lower().startswith("never "):
        return clean_feedback.capitalize()

    # Extract error type or keyword
    if "SyntaxError" in clean_feedback:
        return f"Always ensure valid Python syntax when generating code for {task or 'the task'}."
    if "ZeroDivisionError" in clean_feedback:
        return "Always check for zero denominator before performing division."
    if "IndexError" in clean_feedback or "KeyError" in clean_feedback:
        return "Always validate list bounds and dictionary keys before access."
    if "403" in clean_feedback or "Forbidden" in clean_feedback:
        return "Never request blocked or authenticated endpoints without valid headers."

    # General rule from user correction
    if clean_feedback:
        return f"When handling '{task or 'this task'}', ensure: {clean_feedback}"
    return f"Avoid previous failure in {task}: {failed_action[:60]}"


async def extract_heuristic(
    task: str,
    failed_action: str,
    error_or_feedback: str,
    llm_endpoint: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_headers: Optional[Dict] = None,
) -> str:
    """Distill a failure or user correction into a single actionable imperative rule and persist it.

    Args:
        task: Context or goal of the user request.
        failed_action: The tool call, generated code, or assistant response that failed.
        error_or_feedback: Stderr, traceback, or user correction message.
        llm_endpoint: Optional LLM endpoint URL.
        llm_model: Optional model name.
        llm_headers: Optional request headers.

    Returns:
        The synthesized imperative rule string.
    """
    rule = None

    if llm_endpoint and llm_model:
        prompt = (
            "You are an expert cognitive evaluator and reflection engine for an AI assistant. "
            "Analyze the following failure or user correction and distill it into EXACTLY ONE concise, "
            "imperative rule for future execution.\n\n"
            f"Goal/Task: {task}\n"
            f"Failed Action: {failed_action}\n"
            f"Error / User Correction: {error_or_feedback}\n\n"
            "Format Requirement: A single line starting with an imperative verb (e.g., 'Always ...', 'Never ...', 'When ...'). "
            "Do not include quotes, markdown fences, or conversational text."
        )
        try:
            from src.llm_core import llm_call_async
            from src.research_utils import strip_thinking

            raw = await llm_call_async(
                url=llm_endpoint,
                model=llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
                headers=llm_headers,
                timeout=20,
            )
            cleaned = strip_thinking(raw).strip().splitlines()[0].strip(' "`-')
            if cleaned and len(cleaned) > 10:
                rule = cleaned
        except Exception as e:
            logger.warning(f"LLM heuristic extraction failed: {e}")

    if not rule:
        rule = _heuristic_rule_synthesis(task, failed_action, error_or_feedback)

    rule_id = f"heur-{uuid.uuid4().hex[:8]}"
    metadata = {
        "task": task[:200],
        "failed_action": failed_action[:200],
        "created_at": time.time(),
    }

    # Store in ChromaDB
    collection = get_heuristics_collection()
    if collection:
        try:
            collection.add(
                documents=[rule],
                metadatas=[metadata],
                ids=[rule_id],
            )
            logger.info(f"Saved heuristic rule to ChromaDB: '{rule}'")
        except Exception as e:
            logger.warning(f"Failed to save heuristic to ChromaDB: {e}")

    # Also store in fallback memory cache
    _HEURISTICS_FALLBACK.append({"id": rule_id, "rule": rule, "metadata": metadata})

    return rule


def extract_heuristic_sync(*args, **kwargs) -> str:
    """Synchronous wrapper for extract_heuristic."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, extract_heuristic(*args, **kwargs)).result()
        return loop.run_until_complete(extract_heuristic(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(extract_heuristic(*args, **kwargs))


def query_heuristics(query_text: str, n_results: int = 3, threshold: float = 0.80) -> List[str]:
    """Query learned heuristics matching the user prompt for pre-flight injection.

    Returns:
        List of matching heuristic rule strings.
    """
    if not query_text or not isinstance(query_text, str):
        return []

    rules = []
    collection = get_heuristics_collection()
    if collection:
        try:
            res = collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
            docs = res.get("documents", [[]])[0]
            for doc in docs:
                if doc and doc not in rules:
                    rules.append(doc)
        except Exception as e:
            logger.debug(f"ChromaDB query heuristics error: {e}")

    # If ChromaDB returned results, return them
    if rules:
        return rules[:n_results]

    # Keyword overlap fallback from memory cache
    query_words = set(re.findall(r"\w{3,}", query_text.lower()))
    for item in reversed(_HEURISTICS_FALLBACK):
        rule = item["rule"]
        rule_words = set(re.findall(r"\w{3,}", rule.lower()))
        if query_words & rule_words and rule not in rules:
            rules.append(rule)
            if len(rules) >= n_results:
                break

    return rules

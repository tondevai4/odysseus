# src/agent_loop/self_heal.py
"""
Self-healing repair loop for agent-synthesized tools and code blocks.
Uses 3-turn error-trace feedback to autonomously fix runtime or syntax errors.
"""
import ast
import asyncio
import logging
import re
from typing import Dict, Any, Optional

from src.agent_loop.sandbox import run_in_sandbox

logger = logging.getLogger(__name__)


def _extract_code_from_markdown(text: str) -> str:
    """Extract python code from a markdown block if present."""
    if not isinstance(text, str):
        return ""
    text = text.strip()
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # If no fences, return text if it starts with valid python keyword or def
    if "def " in text or "class " in text or "import " in text:
        # Strip potential conversational intro before first keyword
        for kw in ("import ", "from ", "def ", "class "):
            idx = text.find(kw)
            if idx != -1:
                return text[idx:].strip()
    return text


def _heuristic_repair(broken_code: str, error_trace: str, tool_name: str) -> Optional[str]:
    """Fallback heuristic repair for common syntax or name errors when LLM is unreachable."""
    if not broken_code:
        return None

    repaired = broken_code

    # 1. Missing colon at def/if/for/while/class
    lines = repaired.splitlines()
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if (
            (stripped.startswith("def ") or stripped.startswith("class ") or
             stripped.startswith("if ") or stripped.startswith("for ") or
             stripped.startswith("while ") or stripped.startswith("elif ") or
             stripped.startswith("else") or stripped.startswith("try") or
             stripped.startswith("except"))
            and not stripped.endswith(":")
            and not stripped.endswith("\\")
        ):
            line = line + ":"
        fixed_lines.append(line)
    repaired = "\n".join(fixed_lines)

    # 2. Syntax check if valid now
    try:
        ast.parse(repaired)
        return repaired
    except Exception:
        pass

    return None


async def heal_and_retry(
    tool_name: str,
    broken_code: str,
    error_trace: str,
    test_code: str = "",
    ui_schema: Optional[Dict] = None,
    target_provider: str = "local",
    max_retries: int = 3,
    llm_endpoint: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Autonomously repair broken Python code using multi-turn feedback.

    Args:
        tool_name: Name of the tool or function being repaired.
        broken_code: The failing Python implementation.
        error_trace: Subprocess stderr or traceback from the sandbox.
        test_code: Test assertions or test function that must pass.
        ui_schema: Optional UI configuration for the tool.
        target_provider: Preferred model router provider.
        max_retries: Maximum number of repair turns (default: 3).

    Returns:
        Structured result dict: {
            "success": bool,
            "repaired_code": str,
            "attempts": int,
            "error": str | None,
            "sandbox": dict,
        }
    """
    current_code = broken_code
    current_error = error_trace

    system_prompt = (
        "You are an expert autonomous software engineer and Python debugger. "
        "Fix the provided broken Python code so that it compiles cleanly and passes all test assertions. "
        "Rules:\n"
        f"1. Ensure the primary function is named '{tool_name}'.\n"
        "2. Fix all syntax errors, indentation issues, type errors, or logic bugs.\n"
        "3. Output ONLY the complete, corrected Python code inside a ```python ``` code block."
    )

    for attempt in range(1, max_retries + 1):
        logger.info(f"Self-heal attempt {attempt}/{max_retries} for tool '{tool_name}'")

        user_prompt = (
            f"### Tool Name: {tool_name}\n\n"
            f"### Broken Code:\n```python\n{current_code}\n```\n\n"
            f"### Test Code:\n```python\n{test_code}\n```\n\n"
            f"### Error / Traceback:\n```\n{current_error}\n```\n\n"
            "Please analyze the failure and provide the full corrected Python code."
        )

        candidate_code = None

        # Attempt LLM repair if endpoint is available
        if llm_endpoint and llm_model:
            try:
                from src.llm_core import llm_call_async
                from src.research_utils import strip_thinking

                raw_resp = await llm_call_async(
                    url=llm_endpoint,
                    model=llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                    headers=llm_headers,
                    timeout=30,
                )
                cleaned = strip_thinking(raw_resp)
                candidate_code = _extract_code_from_markdown(cleaned)
            except Exception as e:
                logger.warning(f"Self-heal LLM call failed: {e}")

        # If LLM wasn't available or didn't produce code, attempt heuristic repair
        if not candidate_code:
            candidate_code = _heuristic_repair(current_code, current_error, tool_name)

        if not candidate_code:
            candidate_code = current_code

        # Run candidate in sandbox
        sandbox_res = run_in_sandbox(candidate_code, test_code)
        if sandbox_res["success"]:
            logger.info(f"Self-heal succeeded on attempt {attempt} for '{tool_name}'!")
            return {
                "success": True,
                "repaired_code": candidate_code,
                "attempts": attempt,
                "error": None,
                "sandbox": sandbox_res,
            }

        # Update trace for next iteration
        current_code = candidate_code
        current_error = sandbox_res.get("error") or sandbox_res.get("stderr") or "Execution failed"

    logger.warning(f"Self-heal exhausted all {max_retries} attempts for '{tool_name}'")
    return {
        "success": False,
        "repaired_code": current_code,
        "attempts": max_retries,
        "error": current_error,
        "sandbox": sandbox_res,
    }


def heal_and_retry_sync(*args, **kwargs) -> Dict[str, Any]:
    """Synchronous wrapper for heal_and_retry."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already inside an async loop, create task or run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, heal_and_retry(*args, **kwargs)).result()
        return loop.run_until_complete(heal_and_retry(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(heal_and_retry(*args, **kwargs))

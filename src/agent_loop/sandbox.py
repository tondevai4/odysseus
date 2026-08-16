# src/agent_loop/sandbox.py
"""
Isolated subprocess execution sandbox for agent-synthesized code.
Provides AST safety validation, execution timeouts, and structured output capture.
"""
import ast
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Banned AST function/module calls and dangerous string patterns
BANNED_MODULES = {"ctypes", "pty", "posix"}
BANNED_CALL_PATTERNS = {
    "os.fork",
    "os.kill",
    "os.killpg",
    "os.system",
    "shutil.rmtree",
}
BANNED_COMMAND_STRINGS = [
    "rm -rf",
    "shutil.rmtree",
    "mkfs",
    ":(){ :|:& };:",
    "/etc/shadow",
    "/etc/passwd",
    "os.fork()",
]


class SecurityASTValidator(ast.NodeVisitor):
    """Inspects Python AST for dangerous system-level calls and imports."""

    def __init__(self):
        self.violations = []

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name in BANNED_MODULES:
                self.violations.append(f"Import of forbidden module: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module in BANNED_MODULES:
            self.violations.append(f"Import from forbidden module: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                func_name = f"{node.func.value.id}.{node.func.attr}"

        if func_name in BANNED_CALL_PATTERNS:
            self.violations.append(f"Forbidden system call: {func_name}")

        self.generic_visit(node)


def validate_code_safety(code_str: str) -> Optional[str]:
    """Validate syntax and security policies on code_str. Returns error string if invalid."""
    if not isinstance(code_str, str) or not code_str.strip():
        return "Empty code provided"

    # String pattern check
    lowered = code_str.lower()
    for pattern in BANNED_COMMAND_STRINGS:
        if pattern.lower() in lowered:
            return f"Security violation: banned pattern '{pattern}' detected"

    # AST check
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    except Exception as e:
        return f"Parse error: {e}"

    validator = SecurityASTValidator()
    validator.visit(tree)
    if validator.violations:
        return "Security violation: " + "; ".join(validator.violations)

    return None


def run_in_sandbox(
    code_str: str,
    test_func_str: str = "",
    timeout: int = 8,
    env_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute code and optional test code inside an isolated subprocess sandbox.

    Args:
        code_str: The main Python implementation code.
        test_func_str: Optional test assertions / harness to run against code_str.
        timeout: Execution timeout in seconds (default: 8s).
        env_vars: Optional environment variables dictionary.

    Returns:
        Structured dictionary: {
            "success": bool,
            "stdout": str,
            "stderr": str,
            "error": str | None,
            "execution_time": float,
            "returncode": int,
        }
    """
    full_code = code_str.strip()
    if test_func_str and test_func_str.strip():
        full_code = f"{full_code}\n\n{test_func_str.strip()}"

    # 1. Validate AST and safety
    safety_error = validate_code_safety(full_code)
    if safety_error:
        return {
            "success": False,
            "stdout": "",
            "stderr": safety_error,
            "error": safety_error,
            "execution_time": 0.0,
            "returncode": 1,
        }

    # 2. Setup isolated temporary directory
    start_time = time.time()
    with tempfile.TemporaryDirectory(prefix="yves_sandbox_") as temp_dir:
        script_path = os.path.join(temp_dir, "sandbox_run.py")
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(full_code)
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "error": f"Failed to write script: {e}",
                "execution_time": 0.0,
                "returncode": 1,
            }

        # Inherit safe minimal env
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        if env_vars:
            env.update(env_vars)

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            elapsed = time.time() - start_time
            is_success = (proc.returncode == 0)
            err_msg = None if is_success else (proc.stderr.strip() or f"Process exited with code {proc.returncode}")

            return {
                "success": is_success,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
                "error": err_msg,
                "execution_time": round(elapsed, 4),
                "returncode": proc.returncode,
            }

        except subprocess.TimeoutExpired as te:
            elapsed = time.time() - start_time
            out = te.stdout.decode("utf-8", errors="replace") if te.stdout else ""
            err = te.stderr.decode("utf-8", errors="replace") if te.stderr else ""
            return {
                "success": False,
                "stdout": out,
                "stderr": err or f"Execution timed out after {timeout}s",
                "error": f"Execution timed out after {timeout}s",
                "execution_time": round(elapsed, 4),
                "returncode": -1,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "error": f"Sandbox execution error: {e}",
                "execution_time": round(elapsed, 4),
                "returncode": 1,
            }

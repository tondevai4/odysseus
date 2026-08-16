# src/agent_loop/repo_refactor.py
"""
Wolverine Repository Refactoring Engine for YVES.
Manages isolated Git worktree branch sandboxing, AST-validated code patching,
and automated test suite verification before committing.
"""
import ast
import logging
import os
import pathlib
import subprocess
import time
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_DIRECTORIES = {"src", "core", "routes", "static", "tests"}
FORBIDDEN_FILES = {".env", ".git", "app.db", "id_rsa", "config.json"}


def get_current_git_branch(repo_dir: str = ".") -> str:
    """Get the name of the active Git branch."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to get current git branch: {e}")
        return "fix-command-center-composer-overhang"


def validate_target_files(target_files: List[str]) -> bool:
    """Validate that target files are safe to modify within permitted repository paths."""
    for tf in target_files:
        clean = os.path.normpath(tf).replace("\\", "/")
        parts = clean.split("/")
        if not parts or parts[0] not in ALLOWED_DIRECTORIES:
            logger.error(f"Security: Target file '{tf}' is outside allowed directories ({ALLOWED_DIRECTORIES})")
            return False
        if any(f in clean for f in FORBIDDEN_FILES):
            logger.error(f"Security: Target file '{tf}' matches protected files")
            return False
    return True


def propose_code_patch(
    task_description: str,
    target_files: List[str],
    patch_dict: Dict[str, str],
    test_command: str = "pytest tests/test_dynamic_tooling.py",
    repo_dir: str = ".",
    base_branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute an isolated Git sandboxed patch with automated test verification.

    Args:
        task_description: Summary of the refactoring task or bug fix.
        target_files: List of file paths to modify.
        patch_dict: Mapping of relative file path -> new file content.
        test_command: Command string to execute test suite.
        repo_dir: Path to git repository root.
        base_branch: Base branch name to return to.

    Returns:
        Result dictionary with status ('ready_for_review' or 'failed'), diff, and branch name.
    """
    if not validate_target_files(target_files):
        return {
            "status": "failed",
            "error": "Target files failed repository security validation",
            "tests_passed": False,
        }

    # AST validation for Python files
    for filepath, content in patch_dict.items():
        if filepath.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as syn_err:
                return {
                    "status": "failed",
                    "error": f"AST Syntax Error in '{filepath}': {syn_err}",
                    "tests_passed": False,
                }

    current_branch = base_branch or get_current_git_branch(repo_dir)
    timestamp = int(time.time())
    branch_name = f"auto/patch-{timestamp}-{uuid.uuid4().hex[:6]}"

    logger.info(f"Creating isolated Git patch branch: {branch_name} from {current_branch}")

    try:
        # 1. Create and switch to new branch
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )

        # 2. Apply modifications to files
        for rel_path, new_code in patch_dict.items():
            full_path = pathlib.Path(repo_dir) / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(new_code, encoding="utf-8")

        # 3. Run verification test suite
        test_args = test_command.split()
        test_res = subprocess.run(
            test_args,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=40,
        )

        if test_res.returncode == 0:
            # Tests passed! Stage and commit
            subprocess.run(["git", "add"] + target_files, cwd=repo_dir, check=True)
            subprocess.run(
                ["git", "commit", "-m", f"Auto-refactor: {task_description}"],
                cwd=repo_dir,
                capture_output=True,
                check=True,
            )

            # Generate diff
            diff_res = subprocess.run(
                ["git", "show", "HEAD", "--stat", "--patch"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
            )
            diff_output = diff_res.stdout

            # Switch back to base branch
            subprocess.run(["git", "checkout", current_branch], cwd=repo_dir, check=True)

            logger.info(f"Refactor patch '{branch_name}' passed tests and is ready for review.")
            return {
                "status": "ready_for_review",
                "branch": branch_name,
                "task_description": task_description,
                "diff": diff_output,
                "files_modified": target_files,
                "tests_passed": True,
            }
        else:
            # Tests failed: Clean up branch and revert to base
            subprocess.run(["git", "checkout", current_branch], cwd=repo_dir, check=True)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_dir, check=True)

            error_trace = test_res.stderr or test_res.stdout
            logger.warning(f"Refactor patch '{branch_name}' failed test verification: {error_trace[:200]}")
            return {
                "status": "failed",
                "branch": branch_name,
                "error": error_trace,
                "tests_passed": False,
            }

    except Exception as exc:
        # Revert on any fatal exception
        try:
            subprocess.run(["git", "checkout", current_branch], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_dir, capture_output=True)
        except Exception:
            pass
        return {
            "status": "failed",
            "error": str(exc),
            "tests_passed": False,
        }


def list_patch_branches(repo_dir: str = ".") -> List[str]:
    """List all pending auto-patch branches."""
    try:
        res = subprocess.run(
            ["git", "branch", "--list", "auto/patch-*"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        lines = [l.strip().lstrip("* ") for l in res.stdout.splitlines() if l.strip()]
        return lines
    except Exception as e:
        logger.warning(f"Failed to list patch branches: {e}")
        return []


def delete_patch_branch(branch_name: str, repo_dir: str = ".") -> bool:
    """Delete a specified patch branch."""
    if not branch_name.startswith("auto/patch-"):
        logger.error(f"Cannot delete non-patch branch: {branch_name}")
        return False
    try:
        subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_dir, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.warning(f"Failed to delete branch '{branch_name}': {e}")
        return False

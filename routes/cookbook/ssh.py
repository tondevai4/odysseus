"""Cookbook routes — model download, serve, cache scanning, and cookbook state sync."""

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Depends

from src.auth_helpers import require_user
from src.constants import COOKBOOK_STATE_FILE
from pydantic import BaseModel

from core.middleware import require_admin
from routes._validators import validate_remote_host, validate_ssh_port
from core.platform_compat import (
    IS_WINDOWS,
    detached_popen_kwargs,
    find_bash,
    kill_process_tree,
    pid_alive,
    safe_chmod,
    which_tool,
)
from routes.shell_routes import TMUX_LOG_DIR
from routes.cookbook_output import error_aware_output_tail

logger = logging.getLogger(__name__)

from routes.cookbook_helpers import (
    _SESSION_ID_RE, _validate_repo_id, _validate_serve_model_id, _validate_include, _validate_token,
    _validate_local_dir, _validate_gpus, _shell_path,
    _ps_squote, _bash_squote, _validate_serve_cmd, _parse_serve_phase,
    _safe_env_prefix, _local_tooling_path_export, _append_serve_preflight_exit_lines,
    _append_serve_exit_code_lines, _append_llama_cpp_linux_accel_build_lines, _cached_model_scan_script,
    load_stored_hf_token,
    _append_vllm_linux_preflight_lines, _ollama_bind_from_cmd, _pip_install_fallback_chain,
    _pip_install_no_cache, _user_shell_path_bootstrap, _venv_safe_local_pip_install_cmd,
    _diagnose_serve_output, run_ssh_command_async,
    _ollama_bind_from_cmd, _pip_install_fallback_chain, _pip_install_no_cache,
    _user_shell_path_bootstrap, _venv_safe_local_pip_install_cmd,
    ModelDownloadRequest, ServeRequest,
)

_HF_TOKEN_STATUS_SNIPPET = (
    'if [ -n "$HF_TOKEN" ]; then '
    'echo "[odysseus] HF token: applied"; '
    'else '
    'echo "[odysseus] HF token: NOT SET — gated/private models will be denied. '
    'Add one in Odysseus Settings -> Cookbook -> HuggingFace Token."; '
    'fi'
)


from .utils import _mask_secret, _decrypt_secret, _encrypt_secret, _strip_task_secrets, _diagnose_serve_output, _state_for_client, _state_for_storage, _load_stored_hf_token, _needs_binary, _missing_binary_message, _remote_binary_available, _binary_available, _launch_local_detached, _maybe_sweep_orphans, _sync_sweep_orphans

router = APIRouter()
_cookbook_state_path = Path(COOKBOOK_STATE_FILE)

def _cookbook_ssh_dir() -> Path:
    # The Docker image keeps cookbook keys under /app/.ssh; that path only
    # exists inside the container. On Windows (and any non-container host)
    # fall back to the user profile's ~/.ssh, which OpenSSH on Win10+ uses.
    if not IS_WINDOWS:
        app_ssh = Path("/app/.ssh")
        if Path("/app").exists():
            return app_ssh
    return Path.home() / ".ssh"

def _cookbook_ssh_key_path() -> Path:
    return _cookbook_ssh_dir() / "id_ed25519"

def _read_cookbook_public_key() -> str:
    pub = _cookbook_ssh_key_path().with_suffix(".pub")
    if not pub.exists():
        return ""
    return pub.read_text(encoding="utf-8", errors="replace").strip()

async def get_cookbook_ssh_key(request: Request):
    require_admin(request)
    public_key = _read_cookbook_public_key()
    return {
        "configured": bool(public_key),
        "public_key": public_key,
    }

async def generate_cookbook_ssh_key(request: Request):
    require_admin(request)
    ssh_dir = _cookbook_ssh_dir()
    key_path = _cookbook_ssh_key_path()
    ssh_dir.mkdir(parents=True, exist_ok=True)
    # safe_chmod no-ops on Windows (~/.ssh is already ACL-restricted to the
    # user profile); applies 0o700 on POSIX.
    safe_chmod(ssh_dir, 0o700)
    if not key_path.exists():
        # ssh-keygen ships with the OpenSSH client on Win10+; resolve it via
        # which_tool so the .exe is found even when PATHEXT is unusual.
        ssh_keygen = which_tool("ssh-keygen") or "ssh-keygen"
        proc = await asyncio.create_subprocess_exec(
            ssh_keygen, "-t", "ed25519", "-N", "", "-C", "odysseus-cookbook", "-f", str(key_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()[-500:]
            return {"ok": False, "error": detail or "Failed to generate SSH key"}
    safe_chmod(key_path, 0o600)
    safe_chmod(key_path.with_suffix(".pub"), 0o644)
    return {"ok": True, "public_key": _read_cookbook_public_key()}


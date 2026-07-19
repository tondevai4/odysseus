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

class SetupRequest(BaseModel):
    host: str
    ssh_port: str = "22"

async def server_setup(request: Request, req: SetupRequest):
    """Install required dependencies on a remote server via SSH."""
    require_admin(request)
    host = validate_remote_host(req.host)
    if not host:
        raise HTTPException(400, "host is required")
    port = req.ssh_port
    port = validate_ssh_port(port)
    pf = f"-p {port} " if port and port != "22" else ""

    # Detect platform: Windows first (echo %OS% → Windows_NT), then Termux, then Linux
    detect_cmd = f'ssh {pf}{host} "echo %OS%"'
    platform = "linux"
    try:
        proc = await asyncio.create_subprocess_shell(
            detect_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        out = stdout.decode().strip()
        if "Windows_NT" in out:
            platform = "windows"
        else:
            # Check for Termux
            detect_cmd2 = f"ssh {pf}{host} 'test -d /data/data/com.termux && echo termux || echo linux'"
            proc2 = await asyncio.create_subprocess_shell(
                detect_cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=10)
            platform = stdout2.decode().strip()
    except Exception:
        platform = "linux"

    if platform == "windows":
        # Windows setup: ensure Python + pip + huggingface-hub via PowerShell
        # Also create the session directory for background tasks
        setup_script = (
            'powershell -Command "'
            "New-Item -ItemType Directory -Force -Path $env:TEMP\\odysseus-sessions | Out-Null; "
            "try { python --version } catch { Write-Host 'ERROR: Python not found — install from python.org'; exit 1 }; "
            "python -m pip install -q huggingface-hub 2>$null; "
            "python -c \\\"from huggingface_hub import snapshot_download; print('OK')\\\""
            '"'
        )
        cmd = f'ssh {pf}{host} {setup_script}'
    elif platform == "termux":
        setup_script = (
            "pkg install -y python tmux 2>/dev/null; "
            "pip install --no-deps -q huggingface-hub 2>/dev/null; "
            "pip install -q filelock fsspec packaging pyyaml tqdm typer httpx requests 2>/dev/null; "
            "python3 -c 'from huggingface_hub import snapshot_download; print(\"OK\")'"
        )
        cmd = f"ssh {pf}{host} '{setup_script}'"
    else:
        # Linux: auto-install tmux (via whichever package manager is available)
        # and huggingface_hub + hf_transfer (falling back to --user/--break-system-packages
        # on PEP-668 locked distros like Arch / newer Debian).
        setup_script = (
            # Install tmux if missing — try common package managers; skip if no sudo
            "if ! command -v tmux >/dev/null 2>&1; then "
            "  if command -v apt-get >/dev/null 2>&1; then sudo -n apt-get install -y tmux 2>/dev/null; "
            "  elif command -v pacman >/dev/null 2>&1; then sudo -n pacman -S --noconfirm tmux 2>/dev/null; "
            "  elif command -v dnf >/dev/null 2>&1; then sudo -n dnf install -y tmux 2>/dev/null; "
            "  elif command -v apk >/dev/null 2>&1; then sudo -n apk add --no-interactive tmux 2>/dev/null; "
            "  elif command -v zypper >/dev/null 2>&1; then sudo -n zypper --non-interactive install tmux 2>/dev/null; "
            "  fi; "
            "fi; "
            "command -v tmux >/dev/null 2>&1 || echo 'WARNING: tmux missing and auto-install failed (need passwordless sudo). Install manually.'; "
            # Install Python bits. Try system install first; fall back to --user --break-system-packages on PEP 668 systems.
            "pip install -q huggingface_hub hf_transfer 2>/dev/null || "
            "pip install --user --break-system-packages -q huggingface_hub hf_transfer 2>/dev/null || "
            "pip3 install --user --break-system-packages -q huggingface_hub hf_transfer 2>/dev/null; "
            "python3 -c 'from huggingface_hub import snapshot_download; print(\"OK\")'"
        )
        cmd = f"ssh {pf}{host} '{setup_script}'"

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = stdout.decode() + stderr.decode()
        ok = "OK" in output
        return {"ok": ok, "output": output.strip(), "platform": platform}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Setup timed out (120s)", "platform": platform}
    except Exception as e:
        return {"ok": False, "error": str(e), "platform": platform}


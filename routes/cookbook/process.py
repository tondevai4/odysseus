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

from pydantic import BaseModel

class KillPidRequest(BaseModel):
    host: str
    pid: int
    signal: str = "TERM"
    ssh_port: str = "22"

async def kill_pid(request: Request, req: KillPidRequest):
    """Kill a PID that's holding GPU memory.

    Admin-gated. Validates PID is positive int, signal is TERM/KILL, and
    forbids low PIDs (<100) to avoid accidentally signalling init/system
    daemons. Uses `kill -<sig> <pid>` locally or over SSH.
    """
    require_admin(request)
    if req.pid < 100:
        raise HTTPException(400, f"Refusing to signal PID {req.pid} (<100, likely system process)")
    sig = (req.signal or "TERM").upper()
    if sig not in ("TERM", "KILL", "INT"):
        raise HTTPException(400, "signal must be TERM, KILL, or INT")
    host = validate_remote_host(req.host)
    req.ssh_port = validate_ssh_port(req.ssh_port)
    kill_cmd = f"kill -{sig} {req.pid}"
    try:
        if host:
            pf = f"-p {req.ssh_port} " if req.ssh_port and req.ssh_port != "22" else ""
            cmd = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {pf}{host} '{kill_cmd}'"
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        elif IS_WINDOWS:
            # No `kill` binary / POSIX signals on Windows. taskkill /F /T tears
            # down the PID and its children. There's no graceful-vs-force
            # distinction, so TERM/KILL/INT all map to the same forced kill.
            # NB: never use os.kill(pid, 0) to probe here — on Windows that
            # routes to TerminateProcess and would kill the process.
            if not pid_alive(req.pid):
                return {"ok": False, "error": f"PID {req.pid} is not running"}
            await asyncio.to_thread(kill_process_tree, req.pid)
            return {"ok": True, "pid": req.pid, "signal": sig}
        else:
            proc = await asyncio.create_subprocess_exec(
                "kill", f"-{sig}", str(req.pid),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            err = (stderr.decode("utf-8", errors="replace") or "").strip()[:200]
            return {"ok": False, "error": err or f"kill returned {proc.returncode}"}
        return {"ok": True, "pid": req.pid, "signal": sig}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "kill command timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


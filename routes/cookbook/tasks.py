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

async def cookbook_tasks_status(request: Request):
    """Check status of all active cookbook tmux sessions.

    Critical: every subprocess.run inside this handler is a sync blocking
    call that — when this was a plain async def — froze the entire server
    event loop. Now the whole body runs in a worker thread via
    asyncio.to_thread so other requests stay responsive."""
    require_admin(request)
    return await asyncio.to_thread(_cookbook_tasks_status_sync)

def _cookbook_tasks_status_sync():
    import subprocess

    def _download_cache_complete(repo_id: str, remote_host: str = "", ssh_port: str = "") -> bool:
        """Best-effort check for a completed HF cache entry.

        tmux output can stop at a stale progress line if the pane/session
        disappears before Cookbook captures the final DOWNLOAD_OK marker.
        In that case, trust the cache shape: a snapshot directory with files
        and no *.incomplete blobs means HuggingFace finished materializing the
        model.
        """
        if not repo_id or "/" not in repo_id:
            return False
        py = (
            "import os,sys;"
            "repo=sys.argv[1];"
            "base=os.environ.get('HUGGINGFACE_HUB_CACHE') or os.path.join(os.environ.get('HF_HOME', os.path.expanduser('~/.cache/huggingface')), 'hub');"
            "d=os.path.join(base,'models--'+repo.replace('/','--'));"
            "snap=os.path.join(d,'snapshots');"
            "ok=os.path.isdir(snap) and any(os.path.isdir(os.path.join(snap,x)) and os.listdir(os.path.join(snap,x)) for x in os.listdir(snap));"
            "inc=False;"
            "blobs=os.path.join(d,'blobs');"
            "inc=os.path.isdir(blobs) and any(x.endswith('.incomplete') for x in os.listdir(blobs));"
            "sys.exit(0 if ok and not inc else 1)"
        )
        cmd = ["python3", "-c", py, repo_id]
        try:
            if remote_host:
                ssh_base = ["ssh"]
                if ssh_port and ssh_port != "22":
                    ssh_base.extend(["-p", str(ssh_port)])
                shell_cmd = " ".join(shlex.quote(x) for x in cmd)
                proc = subprocess.run(ssh_base + [remote_host, shell_cmd], timeout=12, capture_output=True)
            else:
                proc = subprocess.run(cmd, timeout=12, capture_output=True)
            return proc.returncode == 0
        except Exception:
            return False

    def _download_cache_incomplete(repo_id: str, remote_host: str = "", ssh_port: str = "") -> bool:
        """Best-effort check for resumable HF partial blobs.

        A lost SSH/tmux session can leave a real download still incomplete.
        Treat any *.incomplete blob as stronger evidence than stale
        "100%" lines in the captured pane output.
        """
        if not repo_id or "/" not in repo_id:
            return False
        py = (
            "import os,sys;"
            "repo=sys.argv[1];"
            "base=os.environ.get('HUGGINGFACE_HUB_CACHE') or os.path.join(os.environ.get('HF_HOME', os.path.expanduser('~/.cache/huggingface')), 'hub');"
            "d=os.path.join(base,'models--'+repo.replace('/','--'));"
            "blobs=os.path.join(d,'blobs');"
            "inc=os.path.isdir(blobs) and any(x.endswith('.incomplete') for x in os.listdir(blobs));"
            "sys.exit(0 if inc else 1)"
        )
        cmd = ["python3", "-c", py, repo_id]
        try:
            if remote_host:
                ssh_base = ["ssh"]
                if ssh_port and ssh_port != "22":
                    ssh_base.extend(["-p", str(ssh_port)])
                shell_cmd = " ".join(shlex.quote(x) for x in cmd)
                proc = subprocess.run(ssh_base + [remote_host, shell_cmd], timeout=12, capture_output=True)
            else:
                proc = subprocess.run(cmd, timeout=12, capture_output=True)
            return proc.returncode == 0
        except Exception:
            return False

    # Load saved tasks from cookbook state
    tasks = []
    state = {}
    if _cookbook_state_path.exists():
        try:
            state = json.loads(_cookbook_state_path.read_text(encoding="utf-8"))
            saved_tasks = state.get("tasks", [])
            if isinstance(saved_tasks, list):
                tasks = saved_tasks
            elif isinstance(saved_tasks, dict):
                tasks = list(saved_tasks.values())
        except Exception:
            pass

    # Orphan-tmux auto-adoption sweep. When the agent (or anyone)
    # SSH-launches a `serve-*` tmux session — usually because
    # serve_model rejected `source ... && vllm ...` or because of a
    # manual relaunch via tmux send-keys — that session is invisible
    # to the cookbook UI even though it's a live model server. The
    # sweep finds those orphans on each configured remote host and
    # writes them into state.tasks with _adoptedExternally=True, so
    # they show up in the UI on the next poll without anyone having
    # to remember to call adopt_served_model. Rate-limited via the
    # module-level _last_orphan_sweep so we don't SSH every 3s.
    try:
        _maybe_sweep_orphans(tasks, state)
    except Exception as _sweep_e:
        logger.warning(f"orphan sweep failed (non-fatal): {_sweep_e!r}")

    results = []
    for task in tasks:
        session_id = task.get("sessionId", "")
        if not session_id:
            continue
        remote = task.get("remoteHost", "")
        task_type = task.get("type", "download")  # "download" or "serve"
        # Field name varies depending on whether the task was added
        # via the download flow (`repoId`), the serve flow (`modelId`),
        # or the UI-side serve preset (which uses `name` + `payload.repo_id`).
        _payload = task.get("payload") or {}
        model = (
            task.get("modelId")
            or task.get("repoId")
            or task.get("name")
            or _payload.get("repo_id")
            or _payload.get("modelId")
            or ""
        )
        task_platform = task.get("platform", "")

        # Check if session is alive + capture output
        _tport = task.get("sshPort", "")
        # Defense-in-depth: cookbook state is admin-writable but the values
        # land in shell-interpolated commands below. Reject anything that
        # isn't a benign session-id / hostname / port.
        if not _SESSION_ID_RE.match(session_id):
            logger.warning(f"Skipping task with unsafe session_id: {session_id!r}")
            continue
        if remote:
            try:
                remote = validate_remote_host(remote)
            except HTTPException:
                logger.warning(f"Skipping task with unsafe remoteHost: {remote!r}")
                continue
        if _tport:
            try:
                _tport = validate_ssh_port(str(_tport))
            except HTTPException:
                logger.warning(f"Skipping task with unsafe sshPort: {_tport!r}")
                continue
        if task_platform == "windows" and remote:
            # Windows: check PID file + Get-Process, read log tail
            sd = "$env:TEMP\\odysseus-sessions"
            ssh_base = ["ssh"]
            if _tport and _tport != "22":
                ssh_base.extend(["-p", str(_tport)])
            check_cmd = ssh_base + [
                remote,
                "powershell",
                "-Command",
                f"$pid = Get-Content \"{sd}\\{session_id}.pid\" -ErrorAction SilentlyContinue; "
                "if ($pid) {{ Get-Process -Id $pid -ErrorAction SilentlyContinue | Out-Null; if ($?) {{ exit 0 }} else {{ exit 1 }} }} else {{ exit 1 }}"
            ]
            capture_cmd = ssh_base + [
                remote,
                "powershell",
                "-Command",
                f"Get-Content \"{sd}\\{session_id}.log\" -Tail 10 -ErrorAction SilentlyContinue",
            ]
        elif remote:
            ssh_base = ["ssh"]
            if _tport and _tport != "22":
                ssh_base.extend(["-p", str(_tport)])
            check_cmd = ssh_base + [remote, "tmux", "has-session", "-t", session_id]
            # Capture 500 lines (was 50) so a Python traceback survives
            # the post-crash neofetch banner + bash prompt that otherwise
            # fills the visible tail. Without this, output_tail ends up
            # as just "Locale: C / Ubuntu_Odysseus ❯" and the agent
            # can't diagnose the actual error.
            capture_cmd = ssh_base + [remote, "tmux", "capture-pane", "-t", session_id, "-p", "-S", "-500"]
        elif IS_WINDOWS:
            # LOCAL Windows task: launched as a detached process (no tmux).
            # Liveness comes from the <session>.pid file, output from the
            # <session>.log file the wrapper redirects into. No subprocess.
            check_cmd = None
            capture_cmd = None
        else:
            check_cmd = ["tmux", "has-session", "-t", session_id]
            capture_cmd = ["tmux", "capture-pane", "-t", session_id, "-p", "-S", "-500"]

        local_win_task = (not remote) and IS_WINDOWS

        progress_text = ""
        full_snapshot = ""

        if local_win_task:
            # File-based liveness + output for the detached-process model.
            pid_path = TMUX_LOG_DIR / f"{session_id}.pid"
            log_path = TMUX_LOG_DIR / f"{session_id}.log"
            task_pid = None
            try:
                task_pid = int(pid_path.read_text(encoding="utf-8").strip())
            except Exception:
                task_pid = None
            is_alive = pid_alive(task_pid)
            try:
                if log_path.exists():
                    full_snapshot = log_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()[-12000:]
                    lines = [l.strip() for l in full_snapshot.split('\n') if l.strip()]
                    downloading_lines = [l for l in lines if l.startswith("Downloading")]
                    if downloading_lines:
                        progress_text = downloading_lines[-1]
                    elif lines:
                        progress_text = lines[-1]
            except Exception:
                pass
        else:
            # Skip the live SSH check entirely for tasks already in a
            # terminal state — they won't change, and 10s timeouts
            # stacked per task were the dominant cost of this whole
            # status endpoint (3+ minute stalls with ~8 accumulated
            # stopped tasks). The agent's `list_served_models` call
            # was blocking the chat stream every time.
            _task_status = (task.get("status") or "").lower()
            if _task_status in {"stopped", "done", "completed",
                                "crashed", "error", "failed",
                                "ended", "killed"}:
                is_alive = False
                # Keep the persisted output_tail for the UI — it's
                # what the agent uses to diagnose past failures.
                full_snapshot = (task.get("output") or "")[-12000:]
            else:
                try:
                    alive = subprocess.run(check_cmd, timeout=4, capture_output=True)
                    is_alive = alive.returncode == 0
                except Exception:
                    is_alive = False

                # Capture last lines for progress. Prefer the "Downloading" line
                # (real aggregate bytes) over "Fetching N files" (whole-file count that
                # lags with hf_transfer). Falls back to the true last line otherwise.
                if is_alive:
                    try:
                        cap = subprocess.run(capture_cmd, timeout=4, capture_output=True, text=True)
                        if cap.returncode == 0:
                            full_snapshot = cap.stdout.strip()
                            lines = [l.strip() for l in full_snapshot.split('\n') if l.strip()]
                            downloading_lines = [l for l in lines if l.startswith("Downloading")]
                            if downloading_lines:
                                progress_text = downloading_lines[-1]
                            elif lines:
                                progress_text = lines[-1]
                    except Exception:
                        pass

        # Determine status. For the local-Windows detached model the log file
        # persists after the process exits, so a finished download still has a
        # snapshot to classify (DOWNLOAD_OK / exit marker) — evaluate it even
        # when the PID is gone instead of blindly reporting "stopped".
        download_zero_files = False
        exit_code = None
        status = "unknown"
        download_has_ok = task_type == "download" and "DOWNLOAD_OK" in full_snapshot
        download_has_failed = task_type == "download" and "DOWNLOAD_FAILED" in full_snapshot
        download_has_incomplete_evidence = (
            task_type == "download"
            and (
                ".incomplete" in full_snapshot
                or bool(re.search(r'model-\d+-of-\d+\.[A-Za-z0-9_.-]+:\s+(?:[0-9]|[1-8][0-9])%', full_snapshot))
                or _download_cache_incomplete(_payload.get("repo_id") or model, remote, str(_tport or ""))
            )
        )
        if is_alive or (local_win_task and full_snapshot):
            lower = full_snapshot.lower()
            exit_match = re.search(r"=== process exited with code\s+(-?\d+)", full_snapshot, re.I)
            has_exit = exit_match is not None
            exit_code = int(exit_match.group(1)) if exit_match else None
            has_error = "error" in lower or "failed" in lower or "traceback" in lower
            if has_exit and task_type == "serve":
                # Serve tasks that exit are always errors — they should run indefinitely
                status = "error"
            elif has_exit and task_type == "download":
                # Dependency installs are tracked as download tasks but only
                # emit the generic runner exit marker, not HF download markers.
                if download_has_incomplete_evidence and not download_has_ok:
                    status = "running" if is_alive else "stopped"
                else:
                    status = "completed" if exit_code == 0 else "error"
            elif has_exit and "unrecognized arguments" in lower:
                status = "error"
            elif has_error and not ("application startup complete" in lower):
                status = "error"
            elif task_type == "download" and download_has_ok:
                if re.search(r"Fetching\s+0\s+files", full_snapshot, re.IGNORECASE):
                    status = "error"
                    download_zero_files = True
                else:
                    status = "completed"
            elif task_type == "download" and download_has_failed:
                status = "error"
            elif task_type == "download" and download_has_incomplete_evidence:
                status = "running" if is_alive else "stopped"
            elif "application startup complete" in lower:
                status = "ready"
            elif not is_alive:
                # local-Windows: process gone, log has no success/ready marker.
                status = "stopped"
            else:
                status = "running"
        else:
            # Session is dead — check if it completed or crashed
            if (
                task_type == "download"
                and not download_has_incomplete_evidence
                and _download_cache_complete(_payload.get("repo_id") or model, remote, str(_tport or ""))
            ):
                status = "completed"
                if not progress_text:
                    progress_text = "Download complete"
                if not full_snapshot:
                    full_snapshot = "DOWNLOAD_OK"
            else:
                status = "stopped"

        # Parse structured phase info — single source of truth for the UI
        phase_info = _parse_serve_phase(full_snapshot, task_type) if (task_type == "serve" and full_snapshot) else {}
        if phase_info.get("status") == "ready":
            status = "ready"
        serve_phase = phase_info.get("phase", "")
        diagnosis = _diagnose_serve_output(full_snapshot) if task_type == "serve" and full_snapshot else None
        if diagnosis and status in {"running", "unknown", "stopped"} and phase_info.get("status") != "ready":
            status = "error"
        if download_zero_files:
            diagnosis = {"message": "No matching files were downloaded. The model repo or filename/quant pattern may be wrong (for example a ':Q4_K_M' tag that does not exist in the repo). Check the repo and the include/quant pattern."}
        output_tail = error_aware_output_tail(full_snapshot, status)

        results.append({
            "session_id": session_id,
            "type": task_type,
            "model": model.split("/")[-1] if "/" in model else model,
            "status": status,
            "progress": serve_phase if task_type == "serve" else progress_text[:120],
            "phase": serve_phase,
            "diagnosis": diagnosis,
            "output_tail": output_tail,
            "exit_code": exit_code,
            "cmd": _payload.get("_cmd") or "",
            "tps": phase_info.get("tps"),
            "reqs": phase_info.get("reqs"),
            "pct": phase_info.get("pct"),
            "remote": remote or "local",
        })

    return {"tasks": results}


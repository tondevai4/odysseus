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


router = APIRouter()
_cookbook_state_path = Path(COOKBOOK_STATE_FILE)

def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "stored"
    return f"{value[:4]}...{value[-4:]}"

def _decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    from src.secret_storage import decrypt
    return decrypt(value)

def _encrypt_secret(value: str) -> str:
    from src.secret_storage import encrypt
    return encrypt(value)

def _strip_task_secrets(state):
    tasks = state.get("tasks") if isinstance(state, dict) else None
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict) and isinstance(task.get("payload"), dict):
                task["payload"].pop("hf_token", None)
    return state

def _diagnose_serve_output(text: str) -> dict | None:
    """Server-side mirror of the Cookbook UI's common serve diagnoses.

    The browser uses cookbook-diagnosis.js for clickable fixes. This gives
    the agent/tool path the same structured signal so it can retry with an
    adjusted command instead of guessing from raw tmux output.
    """
    if not text:
        return None
    tail = text[-6000:]
    patterns = [
        (
            r"No available memory for the cache blocks|Available KV cache memory:.*-",
            "No GPU memory left for KV cache after loading model.",
            [
                {"label": "retry with GPU memory utilization 0.95", "op": "replace", "flag": "--gpu-memory-utilization", "value": "0.95"},
                {"label": "retry with context 2048", "op": "replace", "flag": "--max-model-len", "value": "2048"},
            ],
        ),
        (
            r"CUDA out of memory|torch\.cuda\.OutOfMemoryError|CUDA error: out of memory|warming up sampler|max_num_seqs.*gpu_memory_utilization",
            "GPU ran out of memory during startup or warmup.",
            [
                {"label": "retry with context 4096", "op": "replace", "flag": "--max-model-len", "value": "4096"},
                {"label": "retry with GPU memory utilization 0.80", "op": "replace", "flag": "--gpu-memory-utilization", "value": "0.80"},
                {"label": "retry with --enforce-eager", "op": "append", "arg": "--enforce-eager"},
            ],
        ),
        (
            r"not divisib|must be divisible|attention heads.*divisible",
            "Tensor parallel size is incompatible with the model.",
            [
                {"label": "retry with tensor parallel size 1", "op": "replace", "flag": "--tensor-parallel-size", "value": "1"},
                {"label": "retry with tensor parallel size 2", "op": "replace", "flag": "--tensor-parallel-size", "value": "2"},
            ],
        ),
        (
            r"KV cache.*too (small|large)|max_model_len.*exceeds|maximum.*context",
            "Context length is too large for available GPU memory.",
            [
                {"label": "retry with context 8192", "op": "replace", "flag": "--max-model-len", "value": "8192"},
                {"label": "retry with context 4096", "op": "replace", "flag": "--max-model-len", "value": "4096"},
            ],
        ),
        (
            r"enable-auto-tool-choice requires --tool-call-parser",
            "Auto tool choice requires an explicit tool call parser.",
            [{"label": "retry with Hermes tool parser", "op": "append", "arg": "--tool-call-parser hermes"}],
        ),
        (
            r"Please pass.*trust.remote.code=True|contains custom code which must be executed to correctly load|does not recognize this architecture|model type.*but Transformers does not",
            "Model requires custom code or newer model support.",
            [{"label": "retry with --trust-remote-code", "op": "append", "arg": "--trust-remote-code"}],
        ),
        (
            r"Either a revision or a version must be specified|transformers\.integrations\.hub_kernels|kernels/layer",
            "vLLM/Transformers kernel package mismatch.",
            [{"label": "update vLLM, Transformers, and kernels on this server", "op": "dependency", "package": "vllm transformers kernels"}],
        ),
        (
            r"Address already in use|bind.*address.*in use",
            "Port is already in use.",
            [{"label": "retry on port 8001", "op": "replace", "flag": "--port", "value": "8001"}],
        ),
        (
            r"No CUDA GPUs are available|no GPU.*found|CUDA_VISIBLE_DEVICES.*invalid",
            "No GPUs are visible to the serve process.",
            [{"label": "clear Cookbook GPU selection or choose available GPUs", "op": "settings", "field": "gpus", "value": ""}],
        ),
        (
            r"Failed to infer device type|NVML Shared Library Not Found|No module named 'amdsmi'|platform is not available",
            "vLLM could not find a supported GPU (CUDA or ROCm). "
            "This machine may have integrated or unsupported graphics only.",
            [
                {"label": "switch to llama.cpp (CPU/Metal, works without a discrete GPU)", "op": "manual"},
                {"label": "switch to Ollama (CPU/Metal, works without a discrete GPU)", "op": "manual"},
            ],
        ),
        (
            r"vllm.*command not found|No module named vllm|ERROR: vLLM is not installed",
            "vLLM is not installed or not in PATH on this server.",
            [{"label": "install vLLM in Cookbook Dependencies", "op": "dependency", "package": "vllm"}],
        ),
        (
            r"sglang.*command not found|No module named sglang|SGLang is not installed",
            "SGLang is not installed or not in PATH on this server.",
            [{"label": "install SGLang in Cookbook Dependencies", "op": "dependency", "package": "sglang[all]"}],
        ),
        (
            r"llama-server.*command not found|llama\.cpp.*not found|No module named.*llama_cpp|No module named 'starlette_context'|git: command not found|cmake: command not found",
            "llama.cpp / llama-cpp-python dependencies are missing.",
            [{"label": "install llama.cpp dependencies or llama-cpp-python[server]", "op": "dependency", "package": "llama-cpp-python[server]"}],
        ),
        (
            r"No GGUF found on this host|no \.gguf file|No GGUF file found",
            "No GGUF file found for this model on this host. The llama.cpp backend needs a .gguf file.",
            [{"label": "download a GGUF build of this model (repo name usually ends in -GGUF, file like Q4_K_M.gguf)", "op": "manual"}],
        ),
        (
            r"No module named 'torch'|No module named torch|No module named 'diffusers'|No module named diffusers",
            "Diffusion serving requires PyTorch and diffusers.",
            [{"label": "install diffusers[torch] in Cookbook Dependencies", "op": "dependency", "package": "diffusers[torch]"}],
        ),
        (
            r"403 Forbidden|401 Unauthorized|Access to model.*is restricted|gated repo|not in the authorized list|awaiting a review",
            "Model access is gated or unauthorized.",
            [{"label": "set HF token and request model access on HuggingFace", "op": "manual"}],
        ),
    ]
    for pattern, message, suggestions in patterns:
        if re.search(pattern, tail, re.I):
            return {"message": message, "suggestions": suggestions}
    if re.search(r"Traceback \(most recent call last\)", tail, re.I) and not re.search(
        r"Application startup complete|GET /v1/|Uvicorn running on", tail, re.I
    ):
        return {
            "message": "Python traceback detected during serve startup.",
            "suggestions": [{"label": "inspect traceback and retry with adjusted backend/settings", "op": "manual"}],
        }
    return None

def _state_for_client(state):
    """Return cookbook state without raw secrets for browser clients."""
    _strip_task_secrets(state)
    env = state.get("env") if isinstance(state, dict) else None
    if isinstance(env, dict):
        token = _decrypt_secret(env.get("hfToken"))
        env.pop("hfToken", None)
        env["hfTokenConfigured"] = bool(token)
        env["hfTokenMasked"] = _mask_secret(token)
    return state

def _state_for_storage(state, on_disk=None):
    """Encrypt cookbook secrets before writing state to disk."""
    _strip_task_secrets(state)
    env = state.get("env") if isinstance(state, dict) else None
    disk_env = on_disk.get("env") if isinstance(on_disk, dict) and isinstance(on_disk.get("env"), dict) else {}
    if isinstance(env, dict):
        incoming = env.get("hfToken")
        if incoming:
            _validate_token(incoming)
            env["hfToken"] = _encrypt_secret(incoming)
        elif disk_env.get("hfToken"):
            env["hfToken"] = disk_env["hfToken"]
        else:
            env.pop("hfToken", None)
        env.pop("hfTokenMasked", None)
        env.pop("hfTokenConfigured", None)
    return state

def _load_stored_hf_token() -> str:
    return load_stored_hf_token(state_path=_cookbook_state_path)

def _needs_binary(cmd: str, binary: str) -> bool:
    return bool(re.search(rf"(^|[\s;&|()]){re.escape(binary)}($|[\s;&|()])", cmd or ""))

def _missing_binary_message(binary: str, target: str) -> str:
    if binary == "tmux":
        return (
            f"tmux is required for Cookbook background downloads/serves on {target}. "
            "Install it with your OS package manager, or run Cookbook server setup for that server."
        )
    if binary == "docker":
        return (
            f"Docker is required by this Cookbook launch command on {target}, but the docker CLI was not found. "
            "Install Docker and make sure this user can run `docker`, then retry."
        )
    return f"{binary} is required on {target}, but it was not found."

async def _remote_binary_available(remote: str, ssh_port: str | None, binary: str, *, windows: bool = False) -> bool:
    _port = ssh_port or ""
    _pf = ["-p", _port] if _port and _port != "22" else []
    if windows:
        check = f"powershell -NoProfile -Command \"if (Get-Command {binary} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 127 }}\""
    else:
        check = f"command -v {shlex.quote(binary)} >/dev/null 2>&1"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no",
            *_pf, remote, check,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return proc.returncode == 0
    except Exception:
        return False

async def _binary_available(binary: str, remote: str | None, ssh_port: str | None, *, windows: bool = False) -> bool:
    if remote:
        return await _remote_binary_available(remote, ssh_port, binary, windows=windows)
    return shutil.which(binary) is not None

def _launch_local_detached(session_id: str, bash_lines: list[str]) -> dict:
    """Windows-native stand-in for a LOCAL tmux session (tmux doesn't exist
    on Windows). Mirrors shell_routes._generate_win_detached / bg_jobs.launch:
    runs the wrapper detached so it survives a browser/SSE disconnect (the
    whole point of the tmux feature for long downloads/serves), writing a
    <session>.log the status poller tails and a <session>.pid for liveness.

    `bash_lines` is the same bash wrapper used on POSIX. Prefers Git Bash
    for full command-syntax parity; falls back to a cmd.exe wrapper that
    runs the script through whatever bash is reachable, else best-effort
    directly (simple commands only). Returns the launched job record."""
    log_path = TMUX_LOG_DIR / f"{session_id}.log"
    pid_path = TMUX_LOG_DIR / f"{session_id}.pid"
    bash = find_bash()
    if bash:
        # Run the existing bash wrapper verbatim through Git Bash, redirecting
        # all output to the log the poller reads. Paths handed to bash use
        # POSIX form + shell-quoting so drive paths / spaces survive.
        inner = TMUX_LOG_DIR / f"{session_id}_run.sh"
        inner.write_text("\n".join(bash_lines) + "\n", encoding="utf-8")
        lp = shlex.quote(log_path.as_posix())
        ip = shlex.quote(inner.as_posix())
        script_path = TMUX_LOG_DIR / f"{session_id}.sh"
        script_path.write_text(
            f"bash {ip} > {lp} 2>&1\n",
            encoding="utf-8",
        )
        argv = [bash, str(script_path)]
    else:
        # No bash on this Windows host: the bash wrapper can't run. Fall back
        # to a cmd.exe wrapper that just records a clear error to the log so
        # the UI surfaces "install Git Bash" instead of silently hanging.
        script_path = TMUX_LOG_DIR / f"{session_id}.cmd"
        script_path.write_text(
            "@echo off\r\n"
            f'echo Cookbook LOCAL execution on Windows needs Git Bash ^(bash.exe^) on PATH. > "{log_path}" 2>&1\r\n'
            f'echo Install Git for Windows, then retry. >> "{log_path}"\r\n',
            encoding="utf-8",
        )
        argv = [os.environ.get("ComSpec", "cmd.exe"), "/c", str(script_path)]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
        **detached_popen_kwargs(),
    )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    return {"pid": proc.pid, "log_path": str(log_path)}

def _maybe_sweep_orphans(tasks: list, state: dict) -> None:
    """Scan each configured cookbook server for `serve-*` tmux sessions
    the cookbook doesn't know about and adopt them into state.tasks.

    Heavy SSH work runs in a background thread via asyncio.to_thread so
    it never blocks the request that triggered it. Was previously
    disabled because the sync implementation pegged uvicorn CPU during
    active cookbook polling — re-enabled now with the work pushed off
    the event loop and a slower (60s) cadence.
    """
    import time as _time
    now = _time.monotonic()
    if _orphan_sweep_inflight[0]:
        return
    if now - _last_orphan_sweep_ts[0] < _ORPHAN_SWEEP_MIN_INTERVAL_S:
        return
    _last_orphan_sweep_ts[0] = now
    _orphan_sweep_inflight[0] = True
    # Snapshot inputs so the worker doesn't race with state mutations.
    try:
        tasks_snap = list(tasks or [])
    except Exception:
        tasks_snap = []
    state_snap = state if isinstance(state, dict) else {}

    # Caller is _cookbook_tasks_status_sync (sync context, no event
    # loop). Use a plain background thread — no asyncio needed.
    import threading
    def _run_sweep() -> None:
        try:
            _sync_sweep_orphans(tasks_snap, state_snap)
        except Exception as _e:
            logger.warning(f"orphan sweep thread failed: {_e!r}")
        finally:
            _orphan_sweep_inflight[0] = False
    try:
        threading.Thread(target=_run_sweep, daemon=True, name="orphan-sweep").start()
    except Exception as _e:
        logger.warning(f"orphan sweep thread spawn failed: {_e!r}")
        _orphan_sweep_inflight[0] = False
    return

def _sync_sweep_orphans(tasks: list, state: dict) -> None:
    """The actual sync sweep — never call this on the event loop."""
    import subprocess
    env = state.get("env") if isinstance(state, dict) else {}
    servers = env.get("servers") if isinstance(env, dict) else []
    logger.info(f"orphan sweep starting: {len(servers) if isinstance(servers, list) else 0} server(s), known_sids={len([t for t in tasks if isinstance(t, dict) and t.get('sessionId')])}")
    if not isinstance(servers, list):
        return

    known_sids = {
        t.get("sessionId") for t in tasks
        if isinstance(t, dict) and t.get("sessionId")
    }

    adopted_any = False
    for srv in servers:
        if not isinstance(srv, dict):
            continue
        host = (srv.get("host") or "").strip()
        if not host:
            continue  # local-only entry; the /proc scan handles it
        try:
            host = validate_remote_host(host)
        except HTTPException:
            continue
        sport = str(srv.get("port") or "").strip()
        ssh_base = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no"]
        if sport and sport != "22":
            try:
                sport = validate_ssh_port(sport)
            except HTTPException:
                continue
            if sport != "22":
                ssh_base.extend(["-p", sport])

        try:
            ls = subprocess.run(
                ssh_base + [host, "tmux ls 2>/dev/null"],
                timeout=6, capture_output=True, text=True,
            )
        except Exception:
            continue
        for line in (ls.stdout or "").splitlines():
            sid = line.split(":", 1)[0].strip()
            if not sid or not _SESSION_ID_RE.match(sid):
                continue
            if sid in known_sids:
                continue
            # Adopt any session whose pane is currently running a
            # known model-server process (checked below). The earlier
            # prefix gate (serve-/cookbook-) dropped legitimate
            # serves whenever tmux fell back to numeric IDs, leaving
            # them invisible in the Cookbook UI — so the user could
            # neither see nor stop them.
            # Skip zombie / idle-shell sessions. A tmux session left
            # over from a crashed vllm just shows a bash prompt —
            # adopting it would pollute the UI with "running" tasks
            # that aren't actually serving anything. pane_current_command
            # is the foreground process in the pane right now; only
            # real model serves leave a python/vllm/etc. process there.
            try:
                pc = subprocess.run(
                    ssh_base + [host, "tmux", "list-panes", "-t", sid,
                                "-F", "#{pane_current_command}"],
                    timeout=4, capture_output=True, text=True,
                )
                cur = (pc.stdout or "").strip().splitlines()
            except Exception:
                cur = []
            LIVE_PROCS = {"python", "python3", "vllm", "llama-server",
                          "llama_cpp_main", "sglang", "lmdeploy",
                          "ollama", "node", "uvicorn"}
            if not any(c in LIVE_PROCS for c in cur):
                continue
            # Try to recover a plausible repo_id + port from the
            # pane buffer. Cheap heuristic — if we can't, register
            # with placeholder fields; the UI still shows it.
            try:
                cap = subprocess.run(
                    ssh_base + [host, "tmux", "capture-pane", "-t", sid, "-p", "-S", "-300"],
                    timeout=6, capture_output=True, text=True,
                )
                pane = cap.stdout or ""
            except Exception:
                pane = ""
            import re as _re_orphan
            # vLLM banner: "model   /path/...". Falls back to the
            # raw vllm-serve command if the banner already scrolled.
            m_model = _re_orphan.search(r"model\s+(\S+)", pane)
            model = m_model.group(1) if m_model else ""
            if not model:
                m_serve = _re_orphan.search(r"vllm\s+serve\s+(\S+)", pane)
                model = m_serve.group(1) if m_serve else f"adopted:{sid}"
            m_port = _re_orphan.search(r"--port\s+(\d+)", pane)
            port = int(m_port.group(1)) if m_port else 0

            import time as _t2
            tasks.append({
                "id": sid,
                "sessionId": sid,
                "name": model.split("/")[-1] if "/" in model else model,
                "type": "serve",
                "status": "running",
                "output": f"Auto-adopted from orphan tmux session on {host}. "
                          "Open the task to see live output.",
                "ts": int(_t2.time() * 1000),
                "payload": {
                    "repo_id": model,
                    "remote_host": host,
                    "_cmd": "(orphan tmux session — original launch cmd unknown)",
                    "port": port,
                },
                "remoteHost": host,
                "sshPort": sport,
                "platform": "linux",
                "_serveReady": False,
                "_endpointAdded": False,
                "_adoptedExternally": True,
            })
            known_sids.add(sid)
            adopted_any = True
            logger.info(f"auto-adopted orphan tmux session {sid!r} on {host}")

    if adopted_any:
        try:
            from core.atomic_io import atomic_write_json
            state["tasks"] = tasks
            atomic_write_json(_cookbook_state_path, state)
        except Exception as e:
            logger.warning(f"orphan sweep: state write failed: {e}")


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

async def model_download(request: Request, req: ModelDownloadRequest):
    """Download a HuggingFace model in a tmux session.
    Uses `hf download` CLI directly — runs in tmux via `script -qc`
    for real TTY progress, streams ANSI-stripped output via log file."""
    require_admin(request)
    # Defence-in-depth: even though this endpoint is admin-gated, refuse
    # values that would land in shell contexts with metacharacters.
    backend = (req.backend or "").strip().lower()
    is_ollama_download = backend == "ollama" or ("/" not in req.repo_id and ":" in req.repo_id)
    if is_ollama_download:
        _validate_serve_model_id(req.repo_id)
        req.include = None
        req.local_dir = None
    else:
        _validate_repo_id(req.repo_id)
        _validate_include(req.include)
    validate_remote_host(req.remote_host)
    req.ssh_port = validate_ssh_port(req.ssh_port)
    req.local_dir = _validate_local_dir(req.local_dir)
    req.hf_token = "" if is_ollama_download else (req.hf_token or _load_stored_hf_token())
    _validate_token(req.hf_token)
    TMUX_LOG_DIR.mkdir(parents=True, exist_ok=True)
    session_id = f"cookbook-{uuid.uuid4().hex[:8]}"
    wrapper_script = TMUX_LOG_DIR / f"{session_id}.sh"

    # Custom download dir: point the HF cache at <dir>/hub via env vars
    # (HF_HOME + HUGGINGFACE_HUB_CACHE) instead of --local-dir. local_dir
    # produces a flat layout (<dir>/<name>/<file>) and the local-dir
    # bookkeeping files (.cache/huggingface/.gitignore.lock), and it
    # also breaks robust resume on flaky transfers — the blob-based hub
    # cache survives SSL ReadError mid-stream by reusing <sha>.incomplete,
    # local_dir does not. See issue #2722.
    _dl_hf_home_shell = _shell_path(req.local_dir.rstrip("/")) if req.local_dir else None
    _dl_pyarg = ""  # snapshot_download honors the env vars too — no kwarg needed

    # Build the hf download command. Redirection to suppress the interactive
    # "update available? [Y/n]" prompt is added per-platform further down
    # (< /dev/null on bash, $null | on PowerShell).
    hf_cmd = f"hf download {req.repo_id}"
    if req.include:
        hf_cmd += f" --include '{req.include}'"
    ollama_cmd = f"ollama pull {shlex.quote(req.repo_id)}"

    # Build the shell wrapper — runs hf download directly in tmux (which is a TTY)
    # No script/tee needed — we'll use tmux capture-pane to read output
    lines = ["#!/bin/bash"]
    lines.extend(_user_shell_path_bootstrap())
    if req.hf_token:
        lines.append(f"export HF_TOKEN='{_bash_squote(req.hf_token)}'")
    if _dl_hf_home_shell and not is_ollama_download:
        # Make hf download / snapshot_download honor the chosen dir via the
        # standard HF cache (gives us the models--org--name/blobs/... layout
        # with resumable .incomplete blobs).
        lines.append(f"export HF_HOME={_dl_hf_home_shell}")
        lines.append(f"export HUGGINGFACE_HUB_CACHE={_dl_hf_home_shell}/hub")
        lines.append(f"export HF_HUB_CACHE={_dl_hf_home_shell}/hub")
    # Ensure pip-user scripts (e.g. hf CLI installed via --user) are on PATH
    lines.append('export PATH="$HOME/.local/bin:$HOME/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"')
    # When Odysseus runs from a venv (e.g. native macOS install), put its bin
    # on PATH so the tmux shell finds the bundled `hf`/`python3` without an
    # activated venv. Local bash runs only — meaningless over SSH.
    if not req.remote_host:
        lines.append(_local_tooling_path_export(sys.executable))
    # Best-effort install hf CLI (always). hf_transfer (Rust parallel downloader)
    # is fast but flaky on large files — it tends to crash near the end at high
    # throughput. Retries set disable_hf_transfer to fall back to the plain,
    # slower-but-reliable downloader (resumes cleanly from the .incomplete files).
    # Use `python3 -m pip` not `pip` — macOS has no bare `pip` command.
    if is_ollama_download:
        lines.append('if command -v ollama >/dev/null 2>&1; then')
        lines.append(f'  ODYSSEUS_OLLAMA_PULL_CMD={shlex.quote(ollama_cmd)}')
        lines.append('elif command -v docker >/dev/null 2>&1; then')
        lines.append('  ODYSSEUS_OLLAMA_CONTAINER="$(docker ps --format \'{{.Names}}\' 2>/dev/null | grep -E \'^(ollama-rocm|ollama-test)$\' | head -1)"')
        lines.append('  if [ -n "$ODYSSEUS_OLLAMA_CONTAINER" ]; then')
        lines.append(f'    ODYSSEUS_OLLAMA_PULL_CMD={shlex.quote("docker exec ${ODYSSEUS_OLLAMA_CONTAINER} " + ollama_cmd)}')
        lines.append('  fi')
        lines.append('fi')
        lines.append('if [ -z "$ODYSSEUS_OLLAMA_PULL_CMD" ]; then echo "ERROR: Ollama not found on this server. Install Ollama or start an ollama-rocm/ollama-test container."; exit 127; fi')
    else:
        lines.append(f"command -v hf >/dev/null 2>&1 || {_pip_install_fallback_chain('huggingface_hub', upgrade=True)}")
        if req.disable_hf_transfer:
            lines.append("export HF_HUB_ENABLE_HF_TRANSFER=0")
            lines.append("export HF_HUB_DOWNLOAD_MAX_WORKERS=4")
        else:
            lines.append(f"python3 -c 'import hf_transfer' 2>/dev/null || {_pip_install_fallback_chain('hf_transfer')}")
            lines.append("python3 -c 'import hf_transfer' 2>/dev/null && export HF_HUB_ENABLE_HF_TRANSFER=1")
            lines.append("export HF_HUB_DOWNLOAD_MAX_WORKERS=8")

    remote = req.remote_host  # None for local
    is_windows = req.platform == "windows"
    # LOCAL execution on a native-Windows host never uses tmux (it uses the
    # detached-process path below), regardless of the UI-supplied platform.
    local_windows = IS_WINDOWS and not remote
    logger.info(f"Download request: repo={req.repo_id}, remote={remote}, ssh_port={req.ssh_port}, platform={req.platform}")

    if not is_windows and not local_windows and not await _binary_available("tmux", remote, req.ssh_port):
        return {
            "ok": False,
            "error": _missing_binary_message("tmux", remote or "local server"),
            "session_id": session_id,
        }

    if remote and is_windows:
        # ── Windows remote: generate .ps1 runner, use Start-Process for background ──
        remote_runner = f".{session_id}_run.ps1"
        ps_lines = []
        ps_lines.append('$sessionDir = "$env:TEMP\\odysseus-sessions"')
        ps_lines.append('New-Item -ItemType Directory -Force -Path $sessionDir | Out-Null')
        if req.hf_token:
            ps_lines.append(f"$env:HF_TOKEN = '{_ps_squote(req.hf_token)}'")
        if req.local_dir and not is_ollama_download:
            # Mirror the bash branch — point the HF cache at the user's dir
            # via env vars instead of --local-dir, so resume works on flaky
            # transfers (issue #2722).
            _dl_ps = _ps_squote(req.local_dir.rstrip("/"))
            ps_lines.append(f"$env:HF_HOME = '{_dl_ps}'")
            ps_lines.append(f"$env:HUGGINGFACE_HUB_CACHE = '{_dl_ps}/hub'")
            ps_lines.append(f"$env:HF_HUB_CACHE = '{_dl_ps}/hub'")
        if req.env_prefix:
            ps_lines.append(_safe_env_prefix(req.env_prefix))
        if is_ollama_download:
            ps_lines.append('if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Host "ERROR: Ollama not found. Install from https://ollama.com/download/windows"; exit 127 }')
            ps_lines.append(f"$null | ollama pull '{_ps_squote(req.repo_id)}'")
            ps_lines.append('if ($LASTEXITCODE -eq 0) { Write-Host ""; Write-Host "DOWNLOAD_OK" } else { Write-Host ""; Write-Host "DOWNLOAD_FAILED (exit $LASTEXITCODE)" }')
        else:
            # Try hf CLI, fall back to Python huggingface_hub, then auto-install
            ps_lines.append('try {{')
            ps_lines.append('  $hfPath = Get-Command hf -ErrorAction SilentlyContinue')
            ps_lines.append('  if ($hfPath) {{')
            # Pipe $null to stdin to suppress interactive "update available? [Y/n]" prompt
            ps_lines.append(f'    $null | {hf_cmd}')
            ps_lines.append('  }} else {{')
            ps_lines.append('    python -c "import huggingface_hub" 2>$null')
            ps_lines.append('    if ($LASTEXITCODE -eq 0) {{')
            ps_lines.append('      Write-Host "hf CLI not found, using Python huggingface_hub..."')
            ps_lines.append('      python -m pip install -q hf_transfer 2>$null')
            ps_lines.append('      $env:HF_HUB_ENABLE_HF_TRANSFER = "1"')
            ps_lines.append(f"      python -c \"import os; from huggingface_hub import snapshot_download; snapshot_download('{req.repo_id}'{_dl_pyarg}, max_workers=8)\"")
            ps_lines.append('    }} else {{')
            ps_lines.append('      Write-Host "Installing huggingface-hub..."')
            ps_lines.append('      python -m pip install -q huggingface-hub hf_transfer')
            ps_lines.append('      $env:HF_HUB_ENABLE_HF_TRANSFER = "1"')
            ps_lines.append(f"      python -c \"import os; from huggingface_hub import snapshot_download; snapshot_download('{req.repo_id}'{_dl_pyarg}, max_workers=8)\"")
            ps_lines.append('    }}')
            ps_lines.append('  }}')
            ps_lines.append('  if ($LASTEXITCODE -eq 0) {{ Write-Host ""; Write-Host "DOWNLOAD_OK" }}')
            ps_lines.append('  else {{ Write-Host ""; Write-Host "DOWNLOAD_FAILED (exit $LASTEXITCODE)" }}')
            ps_lines.append('}} catch {{')
            ps_lines.append('  Write-Host ""; Write-Host "DOWNLOAD_FAILED ($_)"')
            ps_lines.append('}}')
        ps_lines.append(f'Remove-Item -Force "$HOME\\{remote_runner}" -ErrorAction SilentlyContinue')
        runner_path = TMUX_LOG_DIR / f"{session_id}_run.ps1"
        runner_path.write_text("\r\n".join(ps_lines) + "\r\n", encoding="utf-8")

        # scp the .ps1 script, then launch it as a detached process with log + pid files
        _port = req.ssh_port
        _Pf = f"-P {_port} " if _port and _port != "22" else ""
        _pf = f"-p {_port} " if _port and _port != "22" else ""
        # Start-Process creates a fully detached process that survives SSH disconnect
        launch_ps = (
            "$sd = \\\"$env:TEMP\\odysseus-sessions\\\"; "
            f"Start-Process powershell -ArgumentList '-ExecutionPolicy','Bypass','-File','$HOME\\{remote_runner}' "
            f"-RedirectStandardOutput \\\"$sd\\{session_id}.log\\\" "
            f"-RedirectStandardError \\\"$sd\\{session_id}.err.log\\\" "
            f"-NoNewWindow -PassThru | ForEach-Object {{ $_.Id | Out-File \\\"$sd\\{session_id}.pid\\\" }}"
        )
        setup_cmd = (
            f"scp -O {_Pf}-q '{runner_path}' {remote}:{remote_runner} && "
            f'ssh {_pf}{remote} "powershell -Command \\"{launch_ps}\\""'
        )

    elif remote:
        # ── Linux/Termux remote: create tmux session ON the remote host ──
        remote_runner = f".{session_id}_run.sh"
        runner_lines = ["#!/bin/bash"]
        runner_lines.extend(_user_shell_path_bootstrap())
        runner_lines.append("# Auto-detect environment")
        runner_lines.append("deactivate 2>/dev/null; hash -r")
        if req.hf_token:
            runner_lines.append(f"export HF_TOKEN='{_bash_squote(req.hf_token)}'")
        if _dl_hf_home_shell and not is_ollama_download:
            runner_lines.append(f"export HF_HOME={_dl_hf_home_shell}")
            runner_lines.append(f"export HUGGINGFACE_HUB_CACHE={_dl_hf_home_shell}/hub")
            runner_lines.append(f"export HF_HUB_CACHE={_dl_hf_home_shell}/hub")
        if req.env_prefix:
            runner_lines.append(_safe_env_prefix(req.env_prefix))
        else:
            # Fallback: find a venv with hf CLI, or install huggingface-hub
            runner_lines.append(
                'for p in ~/vllm-env ~/venv ~/.venv; do '
                'if [ -f "$p/bin/activate" ]; then source "$p/bin/activate"; break; fi; '
                'done'
            )
        # Ensure pip-user scripts (e.g. hf CLI installed via --user) are on PATH
        runner_lines.append('export PATH="$HOME/.local/bin:$HOME/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"')
        # Install hf CLI + optional hf_transfer best-effort. Retries disable
        # hf_transfer because the Rust parallel path is fast but has been
        # flaky near the end of very large multi-file downloads.
        # Use --break-system-packages on PEP-668 systems (Arch, newer Debian) so it doesn't bail.
        if is_ollama_download:
            runner_lines.append('if command -v ollama >/dev/null 2>&1; then')
            runner_lines.append(f'  ODYSSEUS_OLLAMA_PULL_CMD={shlex.quote(ollama_cmd)}')
            runner_lines.append('elif command -v docker >/dev/null 2>&1; then')
            runner_lines.append('  ODYSSEUS_OLLAMA_CONTAINER="$(docker ps --format \'{{.Names}}\' 2>/dev/null | grep -E \'^(ollama-rocm|ollama-test)$\' | head -1)"')
            runner_lines.append('  if [ -n "$ODYSSEUS_OLLAMA_CONTAINER" ]; then')
            runner_lines.append(f'    ODYSSEUS_OLLAMA_PULL_CMD={shlex.quote("docker exec ${ODYSSEUS_OLLAMA_CONTAINER} " + ollama_cmd)}')
            runner_lines.append('  fi')
            runner_lines.append('fi')
            runner_lines.append('if [ -z "$ODYSSEUS_OLLAMA_PULL_CMD" ]; then echo "ERROR: Ollama not found on this server. Install Ollama or start an ollama-rocm/ollama-test container."; exit 127; fi')
        else:
            runner_lines.append(f"command -v hf >/dev/null 2>&1 || {_pip_install_fallback_chain('huggingface_hub', python_cmd='pip', upgrade=True)}")
            if req.disable_hf_transfer:
                runner_lines.append("export HF_HUB_ENABLE_HF_TRANSFER=0")
                runner_lines.append("export HF_HUB_DOWNLOAD_MAX_WORKERS=4")
            else:
                runner_lines.append(f"python3 -c 'import hf_transfer' 2>/dev/null || {_pip_install_fallback_chain('hf_transfer', python_cmd='pip')}")
                runner_lines.append("python3 -c 'import hf_transfer' 2>/dev/null && export HF_HUB_ENABLE_HF_TRANSFER=1")
                runner_lines.append("export HF_HUB_DOWNLOAD_MAX_WORKERS=8")
            # Surface whether the HF token actually reached THIS server, so a gated
            # download's "not authorized" failure can be told apart from a missing
            # token (the token is masked — we only print applied / not-set).
            runner_lines.append(_HF_TOKEN_STATUS_SNIPPET)
        # Wrap the download in a retry loop. Large HF/Ollama transfers can
        # hit transient network failures; both backends resume cached partials.
        mw = 4 if req.disable_hf_transfer else 8
        runner_lines.append('_max_retries=10; _attempt=0; _ec=0')
        runner_lines.append('while [ $_attempt -lt $_max_retries ]; do')
        runner_lines.append('  _attempt=$((_attempt+1))')
        if is_ollama_download:
            runner_lines.append('  eval "$ODYSSEUS_OLLAMA_PULL_CMD" < /dev/null')
        else:
            runner_lines.append('  if command -v hf &>/dev/null; then')
            runner_lines.append(f'    {hf_cmd} < /dev/null')
            runner_lines.append('  elif python3 -c "import huggingface_hub" 2>/dev/null; then')
            runner_lines.append('    [ $_attempt -eq 1 ] && echo "hf CLI not found, using Python huggingface_hub..."')
            runner_lines.append(f'    python3 -c "import os; from huggingface_hub import snapshot_download; snapshot_download(\'{req.repo_id}\'{_dl_pyarg}, max_workers={mw})"')
            runner_lines.append('  else')
            runner_lines.append('    echo "Installing huggingface-hub and dependencies..."')
            runner_lines.append('    pip install --no-deps -q huggingface-hub 2>/dev/null')
            if req.disable_hf_transfer:
                runner_lines.append('    pip install -q filelock fsspec packaging pyyaml tqdm typer httpx requests 2>/dev/null')
                runner_lines.append('    export HF_HUB_ENABLE_HF_TRANSFER=0')
            else:
                runner_lines.append('    pip install -q filelock fsspec packaging pyyaml tqdm typer httpx requests hf_transfer 2>/dev/null')
                runner_lines.append("    python3 -c 'import hf_transfer' 2>/dev/null && export HF_HUB_ENABLE_HF_TRANSFER=1")
            runner_lines.append(f'    python3 -c "import os; from huggingface_hub import snapshot_download; snapshot_download(\'{req.repo_id}\'{_dl_pyarg}, max_workers={mw})"')
            runner_lines.append('  fi')
        runner_lines.append('  _ec=$?')
        runner_lines.append('  if [ $_ec -eq 0 ]; then break; fi')
        runner_lines.append('  if [ $_attempt -lt $_max_retries ]; then')
        runner_lines.append('    echo ""; echo "Download attempt $_attempt failed (exit $_ec) — retrying in 30s..."')
        runner_lines.append('    sleep 30')
        runner_lines.append('  fi')
        runner_lines.append('done')
        runner_lines.append('if [ $_ec -eq 0 ]; then echo ""; echo "DOWNLOAD_OK"; else echo ""; echo "DOWNLOAD_FAILED (exit $_ec after $_attempt attempts)"; fi')
        runner_lines.append(f"rm -f {remote_runner}")
        runner_lines.append('exec "${SHELL:-/bin/bash}"')
        runner_path = TMUX_LOG_DIR / f"{session_id}_run.sh"
        runner_path.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
        # Local temp file is scp'd then chmod'd on the remote; the local bit
        # is irrelevant (no-op on Windows).
        safe_chmod(runner_path, 0o755)

        # scp the runner script, then create tmux session on the remote
        _port = req.ssh_port
        _pf = f"-P {_port} " if _port and _port != "22" else ""
        _spf = f"-p {_port} " if _port and _port != "22" else ""
        setup_cmd = (
            f"scp -O {_pf}-q '{runner_path}' {remote}:{remote_runner} && "
            f"ssh {_spf}{remote} 'chmod +x {remote_runner} && tmux new-session -d -s {session_id} \"./{remote_runner}\"'"
        )
    else:
        # Local: run hf download in the background (tmux on POSIX, a detached
        # process + logfile on Windows where tmux doesn't exist).
        if req.env_prefix:
            lines.append(_safe_env_prefix(req.env_prefix))
        else:
            lines.append("deactivate 2>/dev/null; hash -r")
        # Show whether the HF token reached this run (masked) — tells a gated
        # "not authorized" failure apart from a missing token.
        if not is_ollama_download:
            lines.append(_HF_TOKEN_STATUS_SNIPPET)
        # Retry loop — same rationale as the remote-bash path. Issue #2722.
        _hf_invoke = 'eval "$ODYSSEUS_OLLAMA_PULL_CMD" < /dev/null' if is_ollama_download else (hf_cmd if IS_WINDOWS else f"{hf_cmd} < /dev/null")
        lines.append('_max_retries=10; _attempt=0; _ec=0')
        lines.append('while [ $_attempt -lt $_max_retries ]; do')
        lines.append('  _attempt=$((_attempt+1))')
        lines.append(f'  {_hf_invoke}')
        lines.append('  _ec=$?')
        lines.append('  if [ $_ec -eq 0 ]; then break; fi')
        lines.append('  if [ $_attempt -lt $_max_retries ]; then')
        lines.append('    echo ""; echo "Download attempt $_attempt failed (exit $_ec) — retrying in 30s..."')
        lines.append('    sleep 30')
        lines.append('  fi')
        lines.append('done')
        lines.append('if [ $_ec -eq 0 ]; then echo ""; echo "DOWNLOAD_OK"; else echo ""; echo "DOWNLOAD_FAILED (exit $_ec after $_attempt attempts)"; fi')
        if not IS_WINDOWS:
            lines.append(f"rm -f '{wrapper_script}'")
            lines.append('exec "${SHELL:-/bin/bash}"')
            wrapper_script.write_text("\n".join(lines) + "\n", encoding="utf-8")
            wrapper_script.chmod(0o755)
        setup_cmd = None if IS_WINDOWS else f"tmux new-session -d -s {session_id} {shlex.quote(str(wrapper_script))}"

    logger.info(f"Model download: {req.repo_id} (backend={'ollama' if is_ollama_download else 'hf'}, include={req.include}, session={session_id}, remote={remote})")
    logger.info(f"Download setup_cmd: {setup_cmd}")

    if setup_cmd is None:
        # LOCAL Windows: launch the bash wrapper detached; no tmux setup_cmd.
        try:
            _launch_local_detached(session_id, lines)
        except Exception as e:
            logger.error(f"Local detached download launch failed: {e}")
            return {"ok": False, "error": str(e), "session_id": session_id}
    else:
        proc = await asyncio.create_subprocess_shell(
            setup_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

        if proc.returncode != 0:
            stderr = (await proc.stderr.read()).decode(errors="replace")
            logger.error(f"Download failed (rc={proc.returncode}): {stderr}")
            return {"ok": False, "error": stderr, "session_id": session_id}

    # Log to assistant
    try:
        from src.assistant_log import log_to_assistant
        from src.auth_helpers import get_current_user
        owner = get_current_user(request)
        log_to_assistant(
            owner,
            f"Started downloading {req.repo_id} to {remote or 'local'}",
            category="Download",
        )
    except Exception:
        pass

    return {"ok": True, "session_id": session_id, "remote": remote or "local"}


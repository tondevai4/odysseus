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

def _auto_register_image_endpoint(req: ServeRequest, remote: str | None) -> str | None:
    """Register a diffusion model as an image endpoint so it appears in the model selector."""
    import re
    from core.database import SessionLocal, ModelEndpoint

    # Parse port from command (--port NNNN), default 8100 for diffusion_server
    port_match = re.search(r'--port\s+(\d+)', req.cmd)
    port = int(port_match.group(1)) if port_match else 8100

    # Determine host
    if remote:
        # SSH alias — use as hostname (Tailscale resolves it later)
        host = remote.split("@")[-1] if "@" in remote else remote
    else:
        host = "localhost"

    base_url = f"http://{host}:{port}/v1"

    # Friendly display name from repo_id
    short_name = req.repo_id.split("/")[-1] if "/" in req.repo_id else req.repo_id
    display_name = f"{short_name} (image)"

    db = SessionLocal()
    try:
        # Check for existing endpoint with same base_url — update it
        existing = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base_url).first()
        if existing:
            existing.is_enabled = True
            existing.model_type = "image"
            existing.name = display_name
            db.commit()
            logger.info(f"Updated existing image endpoint: {base_url}")
            return existing.id

        ep_id = f"img-{uuid.uuid4().hex[:8]}"
        ep = ModelEndpoint(
            id=ep_id,
            name=display_name,
            base_url=base_url,
            api_key=None,
            is_enabled=True,
            model_type="image",
        )
        db.add(ep)
        db.commit()
        logger.info(f"Auto-registered image endpoint: {display_name} @ {base_url}")
        return ep_id
    except Exception as e:
        logger.error(f"Failed to auto-register image endpoint: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def _pick_free_port_for_ollama(
    remote: str | None, ssh_port: str | None, start_port: int, max_offset: int
) -> int | None:
    """Return the first free port in [start_port, start_port+max_offset] on
    the target host. Used to pick a real bind for `ollama serve` so we
    don't reattach to an external systemd ollama (or other listener) the
    Cookbook Stop button can't kill."""
    import socket
    if remote:
        # Probe over SSH. Bash's /dev/tcp gives a portable "is anything
        # listening" check without requiring ss/netstat/nmap.
        ssh_base = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no"]
        if ssh_port and str(ssh_port) != "22":
            try:
                ssh_port = validate_ssh_port(ssh_port)
            except HTTPException:
                return None
            ssh_base.extend(["-p", str(ssh_port)])
        try:
            host_arg = validate_remote_host(remote)
        except HTTPException:
            return None
        if not host_arg:
            return None
        probe_ports = " ".join(str(start_port + i) for i in range(max_offset + 1))
        script = (
            f"for p in {probe_ports}; do "
            "if ! (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then "
            "echo $p; exit 0; fi; exec 3<&-; exec 3>&-; done; exit 1"
        )
        try:
            import subprocess
            r = subprocess.run(
                ssh_base + [host_arg, script],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                out = (r.stdout or "").strip().splitlines()
                if out and out[0].isdigit():
                    return int(out[0])
        except Exception:
            return None
        return None
    # Local: just try to connect.
    for off in range(max_offset + 1):
        p = start_port + off
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            try:
                s.connect(("127.0.0.1", p))
            except (ConnectionRefusedError, socket.timeout, OSError):
                return p
    return None

async def _serve_crash_watchdog(
    endpoint_id: str,
    session_id: str,
    remote: str | None,
    ssh_port: str | None,
    is_windows: bool,
) -> None:
    """Drop a freshly-registered endpoint when the cookbook serve dies early.

    The runner script always emits ``=== Process exited with code N ===``
    when the launched cmd terminates (success or failure). We poll the
    tmux pane periodically; on a non-zero exit detected within the watch
    window, the endpoint row is deleted so the picker doesn't keep a
    dead model around. A zero exit (rare for a long-running serve, but
    possible for fast-failing builds that the runner reports as code 0)
    and "missing exit marker" both leave the endpoint alone — that's
    the loading-but-not-yet-bound state, which the probe-marks-offline
    logic already handles.

    Times are picked to outlast realistic vLLM load times (Qwen3.5-122B
    takes ~3 min to load) without burning resources on a stuck-forever
    wait. After the last check, the watchdog gives up — the picker's
    per-endpoint probe takes over from there.
    """
    # Cumulative wait points: 25 s, 60 s, 2 min, 5 min.
    _waits = [25, 35, 60, 180]
    # Tmux capture-pane equivalent of the polling path used elsewhere in
    # this file. Build it once and reuse on each tick. Skip the watchdog
    # entirely on native-Windows local runs (no tmux). The Windows
    # detached-process path writes its log to a known file and has its
    # own lifecycle tracking; punting here keeps the code simple.
    local_win = is_windows and not remote
    if local_win:
        return
    if remote:
        ssh_args = ["ssh"]
        if ssh_port and ssh_port != "22":
            ssh_args.extend(["-p", str(ssh_port)])
        capture_cmd = ssh_args + [remote, "tmux", "capture-pane", "-t", session_id, "-p", "-S", "-200"]
    else:
        capture_cmd = ["tmux", "capture-pane", "-t", session_id, "-p", "-S", "-200"]

    _exit_re = re.compile(r"=== Process exited with code (-?\d+) ===")
    for wait_s in _waits:
        await asyncio.sleep(wait_s)
        try:
            proc = await asyncio.create_subprocess_exec(
                *capture_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            output = stdout.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"crash-watchdog: capture-pane failed (will retry): {e!r}")
            continue
        # Last occurrence wins — a serve that exits/restarts under the
        # runner's "exec bash -i" trail will emit multiple markers; the
        # most-recent code is the one that matters.
        matches = list(_exit_re.finditer(output))
        if not matches:
            continue
        try:
            exit_code = int(matches[-1].group(1))
        except (ValueError, IndexError):
            continue
        if exit_code == 0:
            # Exit 0 on a long-running serve is unusual (a normal "loaded
            # then ready" path keeps the process alive) but it happens for
            # commands like "ollama pull" the user might launch through
            # the same form. Don't drop the endpoint on a clean exit;
            # let the probe layer mark it offline if nothing's listening.
            logger.info(f"crash-watchdog: serve {session_id} exited cleanly (0); leaving endpoint {endpoint_id}")
            return
        # Non-zero exit — drop the endpoint.
        try:
            from core.database import SessionLocal as _SL, ModelEndpoint as _ME
            db = _SL()
            try:
                ep = db.query(_ME).filter(_ME.id == endpoint_id).first()
                if ep:
                    logger.info(
                        f"crash-watchdog: dropping endpoint {endpoint_id} "
                        f"({ep.name} @ {ep.base_url}) — serve exited {exit_code}"
                    )
                    db.delete(ep)
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"crash-watchdog: endpoint cleanup failed: {e!r}")
        return
    logger.debug(f"crash-watchdog: no exit marker for {session_id} within window; leaving endpoint {endpoint_id}")

def _auto_register_llm_endpoint(req: ServeRequest, remote: str | None) -> str | None:
    """Register a freshly-served LLM as a model endpoint so it appears in the
    model picker without a manual /setup step — the text-model sibling of
    _auto_register_image_endpoint.

    Cookbook serve commands launch an OpenAI-compatible server (llama.cpp's
    llama-server, vLLM, SGLang, or Ollama) on a known port. We point an
    endpoint at that server's /v1; the picker auto-discovers the model id by
    probing /v1/models and dims the endpoint until the server is reachable,
    so registering immediately (before the server finishes loading) is safe.
    """
    logger.info(
        f"_auto_register_llm_endpoint: ENTRY repo_id={req.repo_id!r} "
        f"remote={remote!r} cmd_prefix={req.cmd[:80]!r}"
    )
    import re
    from core.database import SessionLocal, ModelEndpoint

    # Port: ordered fallbacks so we match whatever the user actually
    # asked for, not a hardcoded default:
    #   1. explicit `--port N`  (vllm / sglang / llama-server)
    #   2. `OLLAMA_HOST=host:port`  (the way Ollama specifies its bind)
    #   3. fallback by backend (11434 ollama / 8080 llama.cpp)
    # Previously the OLLAMA_HOST form was silently ignored and we
    # registered every Ollama endpoint at 11434 — even if the user
    # set OLLAMA_HOST=0.0.0.0:11435 to avoid colliding with an
    # existing systemd Ollama, the registered endpoint pointed at
    # the OLD port and showed as offline.
    port_match = re.search(r'--port\s+(\d+)', req.cmd)
    ollama_host_match = re.search(r'OLLAMA_HOST=[^\s]*?:(\d+)', req.cmd)
    if port_match:
        port = int(port_match.group(1))
    elif ollama_host_match:
        port = int(ollama_host_match.group(1))
    elif "ollama" in req.cmd:
        port = 11434
    else:
        port = 8080  # llama.cpp's llama-server default — the Apple Silicon path

    # Determine host. The cookbook tmux for `local=true` serves runs INSIDE
    # the odysseus container — so the right URL for the in-container
    # backend to reach it is `localhost`, NOT `host.docker.internal`
    # (the latter points at the docker HOST, which doesn't have a server
    # on that port). The previous host.docker.internal fallback only made
    # sense for /setup-added external services like systemd Ollama on the
    # host — and those go through manual setup, not this auto-register
    # code path. For remote serves we still use the SSH host alias.
    if remote:
        host = remote.split("@")[-1] if "@" in remote else remote
    elif re.search(r"\bdocker\s+exec\s+(?:ollama-rocm|ollama-test)\b", req.cmd or ""):
        host = "host.docker.internal"
    else:
        host = "localhost"

    base_url = f"http://{host}:{port}/v1"

    short_name = req.repo_id.split("/")[-1] if "/" in req.repo_id else req.repo_id
    display_name = short_name or "Local model"

    # If the serve command opts models into OpenAI tool-calling, record it so
    # agent_loop trusts emitted tool_calls instead of the name heuristic.
    is_ollama_endpoint = "ollama" in (req.cmd or "").lower()
    supports_tools = True if "--enable-auto-tool-choice" in req.cmd else None
    pinned_models = [req.repo_id] if is_ollama_endpoint and req.repo_id else []

    db = SessionLocal()
    try:
        # Reuse an endpoint already pointed at this URL instead of duplicating.
        existing = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base_url).first()
        if existing:
            existing.is_enabled = True
            existing.model_type = "llm"
            existing.name = display_name
            if is_ollama_endpoint:
                existing.endpoint_kind = "ollama"
                if pinned_models:
                    existing.cached_models = json.dumps(pinned_models)
                    existing.pinned_models = json.dumps(pinned_models)
            if supports_tools is not None:
                existing.supports_tools = supports_tools
            db.commit()
            logger.info(f"Updated existing local model endpoint: {base_url}")
            # Re-probe so cached_models matches what the server actually
            # serves right now (the URL may have stayed the same but the
            # model behind it changed across launches).
            try:
                from routes.model.shared import _probe_endpoint
                import json as _json2
                probed = _probe_endpoint(base_url, existing.api_key, timeout=5)
                if probed:
                    existing.cached_models = _json2.dumps(probed)
                    db.commit()
            except Exception as _pe:
                logger.warning(f"Re-probe failed for {base_url}: {_pe!r}")
            # Sweep stale dupes: other endpoints with the same display name
            # at DIFFERENT URLs (likely failed earlier-attempt ports) get
            # deleted so the picker doesn't show an offline ghost next to
            # the working one. Only sweeps endpoints whose id starts with
            # `local-` so we never touch a user's hand-added DeepSeek/OpenAI/
            # etc. entry with a coincidentally matching name.
            stale = (db.query(ModelEndpoint)
                     .filter(ModelEndpoint.name == display_name)
                     .filter(ModelEndpoint.base_url != base_url)
                     .filter(ModelEndpoint.id.like("local-%"))
                     .all())
            for s in stale:
                logger.info(f"Sweeping stale local endpoint {s.id} ({s.base_url})")
                db.delete(s)
            if stale:
                db.commit()
            return existing.id

        ep_id = f"local-{uuid.uuid4().hex[:8]}"
        ep = ModelEndpoint(
            id=ep_id,
            name=display_name,
            base_url=base_url,
            api_key=None,
            is_enabled=True,
            model_type="llm",
            endpoint_kind="ollama" if is_ollama_endpoint else "auto",
            cached_models=json.dumps(pinned_models) if pinned_models else None,
            pinned_models=json.dumps(pinned_models) if pinned_models else None,
            supports_tools=supports_tools,
        )
        db.add(ep)
        db.commit()
        logger.info(f"Auto-registered local model endpoint: {display_name} @ {base_url}")
        # Same sweep on first-register path: drop any pre-existing local-*
        # endpoints with this display name pointed elsewhere.
        stale = (db.query(ModelEndpoint)
                 .filter(ModelEndpoint.name == display_name)
                 .filter(ModelEndpoint.id != ep_id)
                 .filter(ModelEndpoint.id.like("local-%"))
                 .all())
        for s in stale:
            logger.info(f"Sweeping stale local endpoint {s.id} ({s.base_url})")
            db.delete(s)
        if stale:
            db.commit()
        # Probe /v1/models NOW and write cached_models so the chat
        # picker actually shows the model on the next /api/models
        # call. Without this immediate probe, the endpoint has empty
        # cached_models until the next background refresh fires (up
        # to a minute later) and the picker shows nothing — even
        # though the endpoint is in the DB and the server is up.
        try:
            from routes.model.shared import _probe_endpoint
            import json as _json2
            probed = _probe_endpoint(base_url, None, timeout=5)
            if probed:
                ep.cached_models = _json2.dumps(probed)
                db.commit()
                logger.info(f"Auto-register: probed {len(probed)} models @ {base_url}")
        except Exception as _pe:
            logger.warning(f"Auto-register: probe-after-create failed for {base_url}: {_pe!r}")
        return ep_id
    except Exception as e:
        logger.error(f"Failed to auto-register local model endpoint: {e}")
        db.rollback()
        return None
    finally:
        db.close()

async def model_serve(request: Request, req: ServeRequest):
    """Launch a model server in a tmux session (or PowerShell background process on Windows).

    `repo_id` is dual-purpose: a HuggingFace repo (`<org>/<name>`) for
    model-serve commands, a cached local-model id (the folder name reported
    by `/api/model/cached`) for models scanned from a custom model dir, OR a
    bare pip package name when the cmd is a `python -m pip install …`. We
    keep strict validation, but serving local cached models must not require
    a fake org/name wrapper.
    """
    require_admin(request)
    # Defence-in-depth: reject values that could break out of shell contexts.
    validate_remote_host(req.remote_host)
    req.ssh_port = validate_ssh_port(req.ssh_port)
    req.gpus = _validate_gpus(req.gpus)
    req.hf_token = req.hf_token or _load_stored_hf_token()
    _validate_token(req.hf_token)
    # Normalize away backslash-newline continuations (multi-line pasted
    # serve commands) so the cleaned single-line command is what gets
    # written into the runner script and used for engine auto-detection.
    # `_validate_serve_cmd` returns None for empty input; coerce to "" so the
    # many downstream `"engine" in req.cmd` membership checks can't hit
    # `TypeError: argument of type 'NoneType'` (a 500 instead of a clean 400).
    req.cmd = _validate_serve_cmd(req.cmd) or ""
    req.cmd = _venv_safe_local_pip_install_cmd(
        req.cmd,
        local=not bool(req.remote_host),
        in_venv=sys.prefix != sys.base_prefix,
    )
    is_pip_install = bool(req.cmd and "pip install" in req.cmd)
    if is_pip_install:
        # Keep big dependency wheel builds (vLLM, …) off the home filesystem's
        # pip cache so they don't fail mid-build with "No space left" (#1219)
        # and leave the dep installed-but-unusable (#1459).
        req.cmd = _pip_install_no_cache(req.cmd)
        # Accept common aliases and enforce server extras for llama-cpp so
        # `python -m llama_cpp.server` has all runtime dependencies.
        req.cmd = re.sub(r"(?<![A-Za-z0-9_.-])llama_cpp(?![A-Za-z0-9_.-])", "llama-cpp-python[server]", req.cmd)
        req.cmd = re.sub(r"(?<![A-Za-z0-9_.-])llama-cpp-python(?!\[)", "llama-cpp-python[server]", req.cmd)
        if "llama-cpp-python" in req.cmd and "--extra-index-url" not in req.cmd:
            req.cmd += " --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu"
        # PEP-508-style package spec — letters, digits, `.-_` for the
        # name; `[` `]` for extras; `<>=!~,` for version specifiers.
        # v2 review HIGH-14: tightened from the previous regex which
        # also allowed spaces and `+`, both of which can be abused to
        # introduce extra shell tokens once interpolated into the
        # serve command. We now use `re.fullmatch` and drop space/`+`.
        if not req.repo_id or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._\-\[\]<>=!,~]{0,200}", req.repo_id
        ):
            raise HTTPException(400, "Invalid pip package name")
    else:
        _validate_serve_model_id(req.repo_id)
    TMUX_LOG_DIR.mkdir(parents=True, exist_ok=True)
    session_id = f"serve-{uuid.uuid4().hex[:8]}"
    remote = req.remote_host
    is_windows = req.platform == "windows"

    # Ollama: if the user didn't pin a port, resolve the actual port we'll
    # bind to here (before runner construction) by probing the target host.
    # Otherwise the runner script picks one at runtime and `_auto_register`
    # below still registers the stale 11434 default — which on a host with
    # a systemd ollama lands on the wrong (unreachable-from-docker) service.
    # Match "ollama serve" as a phrase (with optional flags after), not
    # any substring containing "ollama" — otherwise commands like
    # `docker exec ollama-test ollama-import …` get wrapped as if they
    # were native `ollama serve`, prepending OLLAMA_HOST=… and then
    # running the ollama-not-found preflight which exits 127.
    if re.search(r"\bollama\s+serve\b", req.cmd) and "OLLAMA_HOST=" not in req.cmd:
        _ollama_bind_host = "0.0.0.0" if remote else "127.0.0.1"
        _ollama_chosen_port = _pick_free_port_for_ollama(
            remote, req.ssh_port, start_port=11434, max_offset=10,
        )
        if _ollama_chosen_port:
            req.cmd = f"OLLAMA_HOST={_ollama_bind_host}:{_ollama_chosen_port} {req.cmd}"
    # LOCAL execution on a native-Windows host never uses tmux (detached
    # process path below), regardless of the UI-supplied platform.
    local_windows = IS_WINDOWS and not remote

    if not is_windows and not local_windows and not await _binary_available("tmux", remote, req.ssh_port):
        return {
            "ok": False,
            "error": _missing_binary_message("tmux", remote or "local server"),
            "session_id": session_id,
        }
    if _needs_binary(req.cmd, "docker") and not await _binary_available("docker", remote, req.ssh_port, windows=is_windows):
        return {
            "ok": False,
            "error": _missing_binary_message("docker", remote or "local server"),
            "session_id": session_id,
        }

    if is_windows and remote:
        # ── Windows remote: generate .ps1 serve runner ──
        remote_runner = f".{session_id}_run.ps1"
        ps_lines = []
        ps_lines.append('$sessionDir = "$env:TEMP\\odysseus-sessions"')
        ps_lines.append('New-Item -ItemType Directory -Force -Path $sessionDir | Out-Null')
        if req.hf_token:
            ps_lines.append(f"$env:HF_TOKEN = '{_ps_squote(req.hf_token)}'")
        if req.gpus:
            ps_lines.append(f"$env:CUDA_VISIBLE_DEVICES = '{req.gpus}'")
        if req.env_prefix:
            ps_lines.append(_safe_env_prefix(req.env_prefix))
        # Auto-install ollama if the command uses it
        if "ollama" in req.cmd:
            ps_lines.append('# Check if ollama is available')
            ps_lines.append('if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {')
            ps_lines.append('  Write-Host "Ollama not found. Please install from https://ollama.com/download/windows"')
            ps_lines.append('  exit 1')
            ps_lines.append('}')
        elif "llama_cpp" in req.cmd or "llama-server" in req.cmd:
            ps_lines.append('# Auto-install llama-cpp-python if missing')
            ps_lines.append('try { python -c "import llama_cpp" 2>$null } catch {}')
            ps_lines.append('if ($LASTEXITCODE -ne 0) {')
            ps_lines.append('  Write-Host "Installing llama-cpp-python..."')
            ps_lines.append('  python -m pip install llama-cpp-python[server]')
            ps_lines.append('}')
        elif "vllm" in req.cmd:
            ps_lines.append('Write-Host "ERROR: vLLM is not supported on Windows. Use Ollama or llama.cpp instead."')
            ps_lines.append('exit 1')
        ps_lines.append(req.cmd)
        if is_pip_install:
            ps_lines.append('if ($LASTEXITCODE -eq 0) { Write-Host ""; Write-Host "DOWNLOAD_OK" }')
        ps_lines.append('Write-Host ""')
        ps_lines.append('Write-Host "=== Process exited with code $LASTEXITCODE ==="')
        runner_path = TMUX_LOG_DIR / f"{session_id}_run.ps1"
        runner_path.write_text("\r\n".join(ps_lines) + "\r\n", encoding="utf-8")

        _port = req.ssh_port
        _Pf = f"-P {_port} " if _port and _port != "22" else ""
        _pf = f"-p {_port} " if _port and _port != "22" else ""
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
    else:
        # ── Linux/Termux: bash + tmux (existing flow) ──
        runner_lines = ["#!/bin/bash"]
        # Mirror every line of stdout+stderr into a persistent log file
        # on the host running the serve. This is the file tail_serve_output
        # reads when the tmux pane has been overwritten by the post-crash
        # bash prompt — without it, the agent's diagnostic tool sees the
        # neofetch banner instead of the actual Python traceback.
        # We save the original fds to 3/4 so we can RESTORE them before
        # `exec ${SHELL}` at the end of the script. Without that restore,
        # the post-crash interactive shell's neofetch banner ALSO gets
        # teed into the log file and `tail -N` returns ONLY the banner —
        # the actual traceback ends up earlier than the tail window.
        runner_lines.append("mkdir -p /tmp/odysseus-tmux 2>/dev/null || true")
        runner_lines.append("exec 3>&1 4>&2")
        runner_lines.append(
            f"exec > >(tee -a /tmp/odysseus-tmux/{session_id}.log) 2>&1"
        )
        runner_lines.extend(_user_shell_path_bootstrap())
        runner_lines.append('ODYSSEUS_PREFLIGHT_EXIT=""')
        # Put Odysseus's own venv bin on PATH (local runs only) so the serve
        # shell resolves the bundled python3/hf, mirroring the download flow.
        if not remote:
            runner_lines.append(_local_tooling_path_export(sys.executable))
        runner_lines.append("export FLASHINFER_DISABLE_VERSION_CHECK=1")
        if req.hf_token:
            runner_lines.append(f"export HF_TOKEN='{_bash_squote(req.hf_token)}'")
        if req.gpus:
            runner_lines.append(f"export CUDA_VISIBLE_DEVICES='{req.gpus}'")
        if req.env_prefix:
            runner_lines.append(_safe_env_prefix(req.env_prefix))
        else:
            runner_lines.append("deactivate 2>/dev/null; hash -r")
        # Show whether the HF token reached this server (masked) — a gated
        # model vLLM has to download will be denied without it.
        runner_lines.append(_HF_TOKEN_STATUS_SNIPPET)
        handled_ollama_serve = False
        # Auto-install inference engine if missing
        if "llama_cpp" in req.cmd or "llama-server" in req.cmd:
            # Prefer the NATIVE llama-server binary — its minja templating
            # renders modern GGUF chat templates that the Python bindings'
            # Jinja2 rejects (do_tojson ensure_ascii). Build it once from
            # source if missing; keep llama-cpp-python only as a fallback.
            runner_lines.append('# Ensure a llama.cpp server (prefer native llama-server)')
            # Include the Homebrew bin dirs so a brew-installed llama-server /
            # ollama is found (otherwise macOS falls back to a slow source build).
            # /opt/homebrew = Apple Silicon, /usr/local = Intel; harmless on Linux.
            runner_lines.append('export PATH="$HOME/.local/bin:$HOME/bin:$HOME/llama.cpp/build/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"')
            runner_lines.append('if [ -d /data/data/com.termux ]; then')
            runner_lines.append('  # Termux: no native build — use the Python bindings (CPU).')
            runner_lines.append('  if ! python3 -c "import llama_cpp" 2>/dev/null; then')
            runner_lines.append('    pkg install -y cmake 2>/dev/null')
            runner_lines.append('    pip install numpy diskcache jinja2 2>/dev/null')
            runner_lines.append('    CMAKE_ARGS="-DGGML_BLAS=OFF -DGGML_LLAMAFILE=OFF" pip install \'llama-cpp-python[server]\' --no-build-isolation --no-cache-dir 2>&1 || true')
            runner_lines.append('  fi')
            runner_lines.append('elif ! command -v llama-server &>/dev/null; then')
            runner_lines.append('  echo "Native llama-server not found — building from source (one-time, may take a few minutes)..."')
            runner_lines.append('  mkdir -p ~/bin')
            runner_lines.append('  cd ~ && [ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp')
            # Build with the right accelerator: Metal on macOS (llama.cpp
            # enables it automatically, no flag), CUDA on Linux when present,
            # else a plain CPU build. nproc is Linux-only — fall back to
            # `sysctl hw.ncpu` on macOS. (Tip: `brew install llama.cpp` ships
            # a prebuilt llama-server and skips this whole source build.)
            runner_lines.append('  NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"')
            runner_lines.append('  if [ "$(uname -s)" = "Darwin" ]; then')
            runner_lines.append('    command -v cmake >/dev/null 2>&1 || echo "WARNING: cmake not found — install it with: brew install cmake (or: brew install llama.cpp for a prebuilt llama-server)."')
            # Start from a clean cache: a prior failed configure (e.g. a CUDA
            # attempt) poisons build/CMakeCache.txt, so a plain `cmake -B build`
            # would reuse the bad settings and fail again. CMAKE_BUILD_TYPE is
            # explicit so the binary is optimized (Metal auto-enables on macOS).
            runner_lines.append('    cd ~/llama.cpp && rm -rf build && cmake -B build -DCMAKE_BUILD_TYPE=Release \\')
            runner_lines.append('      && cmake --build build -j"$NPROC" --target llama-server \\')
            runner_lines.append('      && ln -sf ~/llama.cpp/build/bin/llama-server ~/bin/llama-server')
            runner_lines.append('  else')
            _append_llama_cpp_linux_accel_build_lines(runner_lines)
            runner_lines.append('  fi')
            runner_lines.append('  # If the native build failed, fall back to the Python bindings.')
            runner_lines.append('  if ! command -v llama-server &>/dev/null && ! python3 -c "import llama_cpp" 2>/dev/null; then')
            runner_lines.append('    echo "llama-server build failed — installing Python bindings as fallback..."')
            runner_lines.append(f"    {_pip_install_fallback_chain('llama-cpp-python[server]', python_cmd='pip')} || true")
            runner_lines.append('  fi')
            runner_lines.append('  if ! command -v llama-server &>/dev/null && ! python3 -c "import llama_cpp" 2>/dev/null; then')
            runner_lines.append('    echo "ERROR: llama.cpp serving is not available after install/build attempts."')
            runner_lines.append('    ODYSSEUS_PREFLIGHT_EXIT=127')
            runner_lines.append('  fi')
            runner_lines.append('fi')
        elif re.search(r"\bollama\s+serve\b", req.cmd):
            handled_ollama_serve = True
            _ollama_default_host = "0.0.0.0" if remote else "127.0.0.1"
            _ollama_host, _ollama_port = _ollama_bind_from_cmd(
                req.cmd,
                default_host=_ollama_default_host,
            )
            # Always launch a fresh ollama under tmux so Stop reliably
            # kills it. If the requested port is busy (e.g. a systemd
            # ollama on 11434), scan upward for a free one rather than
            # silently reattaching to an external service that Stop
            # can't reach.
            runner_lines.append(f'ODYSSEUS_OLLAMA_HOST={_bash_squote(_ollama_host)}')
            runner_lines.append(f'ODYSSEUS_OLLAMA_PORT="{_ollama_port}"')
            runner_lines.append('for _ody_off in 0 1 2 3 4 5 6 7 8 9; do')
            runner_lines.append('  _ody_try_port=$((ODYSSEUS_OLLAMA_PORT + _ody_off))')
            runner_lines.append('  if ! (exec 3<>/dev/tcp/127.0.0.1/$_ody_try_port) 2>/dev/null; then')
            runner_lines.append('    exec 3<&-; exec 3>&-')
            runner_lines.append('    ODYSSEUS_OLLAMA_PORT="$_ody_try_port"')
            runner_lines.append('    break')
            runner_lines.append('  fi')
            runner_lines.append('  exec 3<&-; exec 3>&-')
            runner_lines.append('done')
            runner_lines.append('if ! command -v ollama &>/dev/null; then')
            runner_lines.append('  echo "ERROR: Ollama not found on this server. Install it from https://ollama.com/download or `curl -fsSL https://ollama.com/install.sh | sh`."')
            runner_lines.append('  echo')
            runner_lines.append('  echo "=== Process exited with code 127 ==="')
            runner_lines.append('  exec bash -i')
            runner_lines.append('fi')
            runner_lines.append('ODYSSEUS_OLLAMA_URL="http://${ODYSSEUS_OLLAMA_HOST}:${ODYSSEUS_OLLAMA_PORT}"')
            if remote and _ollama_host in ("0.0.0.0", "::"):
                runner_lines.append('echo "[odysseus] WARNING: remote Ollama will bind to ${ODYSSEUS_OLLAMA_HOST}:${ODYSSEUS_OLLAMA_PORT} so Odysseus can reach it from this host."')
                runner_lines.append('echo "[odysseus] Ollama has no built-in authentication; expose this only on a trusted LAN/VPN or provide an explicit OLLAMA_HOST with your own access controls."')
            runner_lines.append('echo "Starting ollama server on ${ODYSSEUS_OLLAMA_HOST}:${ODYSSEUS_OLLAMA_PORT}..."')
            runner_lines.append('OLLAMA_HOST="${ODYSSEUS_OLLAMA_HOST}:${ODYSSEUS_OLLAMA_PORT}" ollama serve')
            runner_lines.append('_ody_exit=$?')
            runner_lines.append('echo')
            runner_lines.append('echo "=== Process exited with code ${_ody_exit} ==="')
            runner_lines.append('exec bash -i')
        elif "vllm serve" in req.cmd:
            # vLLM is CUDA/ROCm-only and does not run on macOS at all.
            runner_lines.append('if [ "$(uname -s)" = "Darwin" ]; then')
            runner_lines.append('  echo "ERROR: vLLM does not run on macOS. Use Ollama or llama.cpp (Metal) instead."')
            runner_lines.append('  ODYSSEUS_PREFLIGHT_EXIT=1')
            runner_lines.append('fi')
            # Put ~/.local/bin on PATH first — without a venv, vllm installs
            # there via --user and the non-login serve shell otherwise can't
            # find the `vllm` CLI ("command not found"). Mirrors llama.cpp above.
            runner_lines.append('export PATH="$HOME/.local/bin:$PATH"')
            runner_lines.append('if ! command -v vllm &>/dev/null; then')
            runner_lines.append('  echo "ERROR: vLLM is not installed."')
            runner_lines.append('  ODYSSEUS_PREFLIGHT_EXIT=127')
            runner_lines.append('fi')
        elif "sglang.launch_server" in req.cmd:
            runner_lines.append('export PATH="$HOME/.local/bin:$PATH"')
            runner_lines.append('if ! command -v sglang &>/dev/null; then')
            runner_lines.append('  echo "ERROR: SGLang is not installed."')
            runner_lines.append('  ODYSSEUS_PREFLIGHT_EXIT=127')
            runner_lines.append('elif ! ODYSSEUS_SGLANG_IMPORT_ERROR="$(python3 -c "import sglang" 2>&1)"; then')
            runner_lines.append('  echo "ERROR: SGLang is installed but failed to import."')
            runner_lines.append('  printf "%s\\n" "$ODYSSEUS_SGLANG_IMPORT_ERROR"')
            runner_lines.append('  ODYSSEUS_PREFLIGHT_EXIT=127')
            runner_lines.append('fi')
        elif "scripts/diffusion_server.py" in req.cmd or ".diffusion_server.py" in req.cmd:
            runner_lines.append('export PATH="$HOME/.local/bin:$PATH"')
            runner_lines.append('if ! ODYSSEUS_DIFFUSION_IMPORT_ERROR="$(python3 -c "import torch, diffusers" 2>&1)"; then')
            runner_lines.append('  echo "ERROR: Diffusion serving requires PyTorch + diffusers."')
            runner_lines.append('  printf "%s\\n" "$ODYSSEUS_DIFFUSION_IMPORT_ERROR"')
            runner_lines.append('  ODYSSEUS_PREFLIGHT_EXIT=127')
            runner_lines.append('fi')

        handled_ollama_sidecar_probe = False
        if (not handled_ollama_serve
            and re.search(r"\bdocker\s+exec\s+(?:ollama-rocm|ollama-test)\s+ollama\s+show\b", req.cmd or "")):
            handled_ollama_sidecar_probe = True
            _append_serve_preflight_exit_lines(
                runner_lines,
                keep_shell_open=not local_windows,
            )
            runner_lines.append(req.cmd)
            runner_lines.append('_ody_exit=$?')
            runner_lines.append('echo')
            runner_lines.append('echo "=== Process exited with code ${_ody_exit} ==="')
            runner_lines.append('if [ "$_ody_exit" -eq 0 ]; then')
            runner_lines.append('  echo "[odysseus] Ollama sidecar model is available; keeping Cookbook task attached to the persistent Ollama daemon."')
            runner_lines.append('  while true; do sleep 3600; done')
            runner_lines.append('fi')
            runner_lines.append('exec bash -i')

        if not handled_ollama_serve and not handled_ollama_sidecar_probe:
            _append_serve_preflight_exit_lines(
                runner_lines,
                keep_shell_open=not local_windows,
            )
            runner_lines.append(req.cmd)
            if local_windows:
                # Detached background process — no interactive shell to keep open.
                # Print the exit marker the status poller looks for, then stop.
                _append_serve_exit_code_lines(
                    runner_lines,
                    keep_shell_open=False,
                    is_pip_install=is_pip_install,
                )
            else:
                # Keep shell open after exit so user can see errors
                _append_serve_exit_code_lines(
                    runner_lines,
                    keep_shell_open=True,
                    is_pip_install=is_pip_install,
                )

        runner_path = TMUX_LOG_DIR / f"{session_id}_run.sh"
        runner_path.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
        # chmod is a no-op on Windows; bash on Windows runs the script
        # regardless of the executable bit.
        safe_chmod(runner_path, 0o755)

        if local_windows:
            # LOCAL Windows: launch the bash runner detached (tmux replacement).
            setup_cmd = None
        elif remote:
            remote_runner = f".{session_id}_run.sh"
            # If command references scripts/, scp those too
            scp_extras = ""
            _port = req.ssh_port
            _Pf = f"-P {_port} " if _port and _port != "22" else ""
            _pf = f"-p {_port} " if _port and _port != "22" else ""
            if "scripts/diffusion_server.py" in req.cmd:
                from core.constants import BASE_DIR
                diff_script = Path(BASE_DIR) / "scripts" / "diffusion_server.py"
                if diff_script.exists():
                    scp_extras = f"scp -O {_Pf}-q '{diff_script}' {remote}:.diffusion_server.py && "
                    runner_path.write_text(
                        runner_path.read_text(encoding="utf-8").replace(
                            "scripts/diffusion_server.py", ".diffusion_server.py"
                        ),
                        encoding="utf-8",
                    )
            setup_cmd = (
                f"{scp_extras}"
                f"scp -O {_Pf}-q '{runner_path}' {remote}:{remote_runner} && "
                f"ssh {_pf}{remote} 'chmod +x {remote_runner} && tmux new-session -d -s {session_id} \"./{remote_runner}\"'"
            )
        else:
            setup_cmd = f"tmux new-session -d -s {session_id} {shlex.quote(str(runner_path))}"

    if setup_cmd is None:
        # LOCAL Windows: launch the bash runner detached; no tmux setup_cmd.
        try:
            _launch_local_detached(session_id, runner_lines)
        except Exception as e:
            logger.error(f"Local detached serve launch failed: {e}")
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
            return {"ok": False, "error": stderr, "session_id": session_id}

    # Auto-register a model endpoint so the served model shows up in the model
    # picker with no manual /setup step. Diffusion models get an image
    # endpoint; any other real model serve (i.e. not a pip-install task) gets
    # a local LLM endpoint pointed at its /v1.
    endpoint_id = None
    is_diffusion = "diffusion_server.py" in req.cmd
    if is_diffusion:
        endpoint_id = _auto_register_image_endpoint(req, remote)
    elif not is_pip_install:
        endpoint_id = _auto_register_llm_endpoint(req, remote)

    # Crash watchdog: the auto-register above writes the endpoint row
    # IMMEDIATELY (before the server has even bound its port) so the
    # picker shows the model as it warms up. When the serve process
    # crashes right at startup (missing module, bad cmd, port collision,
    # ModuleNotFoundError on llama_cpp, etc.), the endpoint is left
    # dangling — every subsequent chat returns 503 or an empty response.
    # Schedule a background task to read the tmux output for the
    # "=== Process exited with code N ===" marker the runner emits;
    # if N != 0 within the watch window, delete the endpoint we just
    # created. Skipped for diffusion (different image-endpoint cleanup
    # path) and pip-install tasks (no endpoint to drop).
    if endpoint_id and not is_diffusion and not is_pip_install:
        asyncio.create_task(_serve_crash_watchdog(
            endpoint_id=endpoint_id,
            session_id=session_id,
            remote=remote,
            ssh_port=req.ssh_port,
            is_windows=is_windows,
        ))

    # Log to assistant
    try:
        from src.assistant_log import log_to_assistant
        from src.auth_helpers import get_current_user
        owner = get_current_user(request)
        short = req.repo_id.split("/")[-1] if "/" in req.repo_id else req.repo_id
        log_to_assistant(
            owner,
            f"Started serving {short} on {remote or 'local'}",
            category="Serve",
        )
    except Exception:
        pass

    return {"ok": True, "session_id": session_id, "remote": remote or "local",
            "endpoint_id": endpoint_id}


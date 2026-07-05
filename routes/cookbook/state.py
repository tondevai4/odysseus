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

async def get_cookbook_state(request: Request):
    """Load saved cookbook state (tasks, servers, presets, settings)."""
    require_admin(request)
    if _cookbook_state_path.exists():
        try:
            return _state_for_client(json.loads(_cookbook_state_path.read_text(encoding="utf-8")))
        except Exception:
            return {}
    return {}

async def save_cookbook_state(request: Request):
    """Save cookbook state for cross-device sync.

    Admin-gated because cookbook state is read back into shell-quoting
    contexts when polling tmux session status (see status handler).

    Merge guard: the UI debounces a `_syncToServer` POST every few
    seconds with whatever localStorage has. The agent's tool layer
    writes server-side tasks (e.g. `download_model` registering a
    task). Without a merge, every UI sync wipes the agent's recent
    additions. We preserve any on-disk task that the incoming body
    omits but was added in the last RACE_WINDOW seconds — that's a
    race, not an intentional delete.
    """
    require_admin(request)
    RACE_WINDOW_MS = 60_000
    try:
        from core.atomic_io import atomic_write_json
        data = await request.json()
        if not isinstance(data, dict):
            data = {}
        try:
            if _cookbook_state_path.exists():
                on_disk = json.loads(_cookbook_state_path.read_text(encoding="utf-8"))
            else:
                on_disk = {}
        except Exception:
            on_disk = {}
        # Anti-wipe guard for env servers. The UI debounces a
        # sync of whatever is in memory; if it fires before the state has
        # hydrated from GET /state (a load-time race) or during a render
        # glitch, `env.servers` would be empty and silently overwrite the
        # saved servers on disk. Never let an empty/absent incoming
        # env.servers clobber a populated on-disk one — preserve the disk
        # values while still accepting the rest of the incoming env.
        disk_env = on_disk.get("env") if isinstance(on_disk, dict) and isinstance(on_disk.get("env"), dict) else None
        if disk_env:
            inc_env = data.get("env") if isinstance(data.get("env"), dict) else None
            if inc_env is None:
                data["env"] = disk_env
                logger.warning("cookbook state POST: incoming body had no env; preserved on-disk env (anti-wipe guard)")
            elif disk_env.get("servers") and not inc_env.get("servers"):
                inc_env["servers"] = disk_env["servers"]
                logger.warning("cookbook state POST: incoming env.servers empty; preserved on-disk servers (anti-wipe guard)")

        disk_tasks = on_disk.get("tasks") or [] if isinstance(on_disk, dict) else []
        incoming_tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        # Anti-poisoning guard: a stale browser tab can keep POSTing a
        # download task as status='done' from before the strict-finish
        # fix landed, undoing any server-side correction. For each
        # incoming "done" download, override to "running" if the last
        # shard pattern says N<total AND no DOWNLOAD_OK/DOWNLOAD_FAILED/
        # /snapshots/ sentinel is in the output.
        import re as _re_dl
        for _it in incoming_tasks:
            if (not isinstance(_it, dict)) or _it.get("type") != "download" or _it.get("status") != "done":
                continue
            _out = _it.get("output") or ""
            if ("DOWNLOAD_OK" in _out) or ("DOWNLOAD_FAILED" in _out) or ("/snapshots/" in _out):
                continue
            _shards = _re_dl.findall(r"model-(\d+)-of-(\d+)\.safetensors", _out)
            if _shards:
                _n, _tot = _shards[-1]
                if int(_n) < int(_tot):
                    logger.info(f"cookbook state POST: rejecting stale done for {_it.get('sessionId')} "
                                f"(last shard {_n}/{_tot}, no DOWNLOAD_OK)")
                    _it["status"] = "running"
            else:
                _completed = _out.count("Download complete")
                _starts = _out.count("Downloading '")
                if _starts > _completed:
                    logger.info(f"cookbook state POST: rejecting stale done for {_it.get('sessionId')} "
                                f"({_completed}/{_starts} files complete, no DOWNLOAD_OK)")
                    _it["status"] = "running"
        incoming_ids = {t.get("sessionId") for t in incoming_tasks if isinstance(t, dict) and t.get("sessionId")}
        import time as _t
        now_ms = int(_t.time() * 1000)
        preserved = []
        for t in disk_tasks:
            if not isinstance(t, dict):
                continue
            sid = t.get("sessionId")
            if not sid or sid in incoming_ids:
                continue  # client's version wins
            ts = t.get("ts") or 0
            if isinstance(ts, (int, float)) and (now_ms - ts) <= RACE_WINDOW_MS:
                preserved.append(t)
        if preserved:
            logger.info(f"cookbook state POST: preserving {len(preserved)} recent task(s) "
                        f"not in incoming body (race guard): "
                        f"{[t.get('sessionId') for t in preserved]}")
            data["tasks"] = incoming_tasks + preserved
        atomic_write_json(str(_cookbook_state_path), _state_for_storage(data, on_disk), indent=2)
        return {"ok": True, "preserved": len(preserved)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


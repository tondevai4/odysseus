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

async def _run_nvidia_smi(query: str, host: str | None, ssh_port: str | None, timeout: int = 8):
    """Run nvidia-smi locally or over SSH. Returns (stdout, error_or_None)."""
    if host:
        pf = f"-p {ssh_port} " if ssh_port and ssh_port != "22" else ""
        cmd = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {pf}{host} '{query}'"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(query),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "nvidia-smi timed out"
    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or "").strip()[:200]
        return None, err or "nvidia-smi failed"
    return stdout.decode("utf-8", errors="replace"), None

async def _run_gpu_shell(cmd_text: str, host: str | None, ssh_port: str | None, timeout: int = 8):
    """Run a small GPU probe shell command locally or over SSH."""
    if host:
        pf = f"-p {ssh_port} " if ssh_port and ssh_port != "22" else ""
        quoted_cmd = shlex.quote(cmd_text)
        remote_cmd = (
            f"if command -v sh >/dev/null 2>&1; then sh -lc {quoted_cmd}; "
            f"elif command -v bash >/dev/null 2>&1; then bash -lc {quoted_cmd}; "
            f"elif command -v zsh >/dev/null 2>&1; then zsh -lc {quoted_cmd}; "
            "else echo 'No POSIX shell found for GPU probe' >&2; exit 127; fi"
        )
        cmd = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no {pf}{host} {shlex.quote(remote_cmd)}"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd_text, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None, "GPU probe timed out"
    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or "").strip()[:200]
        return None, err or f"GPU probe failed ({proc.returncode})"
    return stdout.decode("utf-8", errors="replace"), None

async def _gpu_read_file(path: str, host: str | None, ssh_port: str | None) -> str | None:
    out, err = await _run_gpu_shell(f"cat {shlex.quote(path)} 2>/dev/null", host, ssh_port, timeout=4)
    if err is not None or out is None:
        return None
    return out.strip()

async def _probe_gpu_device_processes(host: str | None, ssh_port: str | None) -> list[dict]:
    pid_cmd = (
        "{ command -v lsof >/dev/null 2>&1 && "
        "lsof -w -t /dev/kfd /dev/dri/renderD* 2>/dev/null || true; "
        "command -v fuser >/dev/null 2>&1 && "
        "fuser /dev/kfd /dev/dri/renderD* 2>/dev/null || true; } "
        "| tr ' ' '\\n' | sed '/^[0-9][0-9]*$/!d' | sort -n -u"
    )
    out, err = await _run_gpu_shell(pid_cmd, host, ssh_port, timeout=5)
    if err is not None or not out:
        return []
    processes = []
    seen = set()
    for raw in out.splitlines():
        try:
            pid = int(raw.strip())
        except ValueError:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        name_out, _ = await _run_gpu_shell(f"ps -p {pid} -o comm= 2>/dev/null", host, ssh_port, timeout=3)
        name = (name_out or "").strip().splitlines()[0] if (name_out or "").strip() else "process"
        processes.append({"pid": pid, "name": name[:80], "used_mb": 0})
    return processes

async def _probe_amd_sysfs(host: str | None, ssh_port: str | None) -> list[dict]:
    out, err = await _run_gpu_shell("ls -1 /sys/class/drm 2>/dev/null", host, ssh_port, timeout=4)
    if err is not None or not out:
        return []
    gpus = []
    for entry in out.split():
        if not entry.startswith("card") or "-" in entry:
            continue
        base = f"/sys/class/drm/{entry}/device"
        vendor = await _gpu_read_file(f"{base}/vendor", host, ssh_port)
        if vendor != "0x1002":
            continue
        vram_raw = await _gpu_read_file(f"{base}/mem_info_vram_total", host, ssh_port)
        vis_raw = await _gpu_read_file(f"{base}/mem_info_vis_vram_total", host, ssh_port)
        gtt_raw = await _gpu_read_file(f"{base}/mem_info_gtt_total", host, ssh_port)
        vram_bytes = int(vram_raw) if vram_raw and vram_raw.isdigit() else 0
        vis_bytes = int(vis_raw) if vis_raw and vis_raw.isdigit() else 0
        gtt_bytes = int(gtt_raw) if gtt_raw and gtt_raw.isdigit() else 0
        total_bytes = max(vram_bytes, vis_bytes)
        used_attr = "mem_info_vis_vram_used" if vis_bytes and vis_bytes >= vram_bytes else "mem_info_vram_used"
        unified = bool(vis_bytes and vis_bytes >= vram_bytes)
        if total_bytes <= 0:
            total_bytes = gtt_bytes
            used_attr = "mem_info_gtt_used"
            unified = True
        if total_bytes <= 0:
            continue
        used_raw = await _gpu_read_file(f"{base}/{used_attr}", host, ssh_port)
        used_bytes = int(used_raw) if used_raw and used_raw.isdigit() else 0
        name = await _gpu_read_file(f"{base}/product_name", host, ssh_port)
        if not name:
            device = await _gpu_read_file(f"{base}/device", host, ssh_port)
            name = f"AMD GPU {device or entry}"
        total_mb = max(0, int(total_bytes / (1024 * 1024)))
        used_mb = max(0, min(total_mb, int(used_bytes / (1024 * 1024))))
        free_mb = max(0, total_mb - used_mb)
        # GTT = the system-RAM pool the GPU pages into when VRAM is full.
        # On a discrete card a large gtt_used means the model spilled past
        # VRAM into RAM over PCIe — much slower. Surface it so the UI can
        # warn "spilling to RAM" instead of the user wondering why it's slow.
        gtt_used_raw = await _gpu_read_file(f"{base}/mem_info_gtt_used", host, ssh_port)
        gtt_used_mb = max(0, int(int(gtt_used_raw) / (1024 * 1024))) if (gtt_used_raw and gtt_used_raw.isdigit()) else 0
        gpus.append({
            "index": len(gpus), "name": name, "uuid": entry,
            "free_mb": free_mb, "total_mb": total_mb, "used_mb": used_mb,
            "gtt_used_mb": gtt_used_mb,
            "util_pct": 0, "busy": bool(total_mb and (free_mb / total_mb) < 0.85),
            "processes": [], "backend": "rocm", "source": "amd-sysfs",
            "unified_memory": unified,
        })
    if gpus:
        processes = await _probe_gpu_device_processes(host, ssh_port)
        if processes:
            gpus[0]["processes"] = processes
            gpus[0]["busy"] = True
    return gpus

async def list_gpus(request: Request, host: str | None = None, ssh_port: str | None = None):
    """Probe GPU memory/process state locally or via SSH.

    Probe order:
        1. NVIDIA via nvidia-smi
        2. AMD/ROCm and unified-memory APUs via /sys/class/drm
        3. Generic GPU device holders via /dev/kfd and /dev/dri/renderD*

    Returned shape:
        { "ok": True, "gpus": [
            {"index": 0, "name": "...", "free_mb": int, "total_mb": int,
             "used_mb": int, "util_pct": int, "busy": bool,
             "uuid": "GPU-...",
             "processes": [{"pid": int, "name": str, "used_mb": int}, ...]
            }, ...
        ]}
    `busy` is True when free_mb/total_mb < 0.5.
    """
    require_admin(request)
    host = validate_remote_host(host)
    ssh_port = validate_ssh_port(ssh_port)
    gpu_query = "nvidia-smi --query-gpu=index,name,memory.free,memory.total,memory.used,utilization.gpu,uuid --format=csv,noheader,nounits"
    nvidia_error = None
    try:
        gpu_out, err = await _run_nvidia_smi(gpu_query, host, ssh_port)
        if err is not None:
            nvidia_error = err
            gpu_out = ""
    except FileNotFoundError:
        nvidia_error = "nvidia-smi not found"
        gpu_out = ""
    except Exception as e:
        nvidia_error = str(e)[:200]
        gpu_out = ""

    gpus = []
    uuid_to_idx: dict[str, int] = {}
    for line in (gpu_out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            free_mb = int(float(parts[2]))
            total_mb = int(float(parts[3]))
            used_mb = int(float(parts[4]))
            util_pct = int(float(parts[5]))
            gpu_uuid = parts[6]
        except (ValueError, IndexError):
            continue
        busy = total_mb > 0 and (free_mb / total_mb) < 0.5
        uuid_to_idx[gpu_uuid] = idx
        gpus.append({
            "index": idx, "name": name, "uuid": gpu_uuid,
            "free_mb": free_mb, "total_mb": total_mb,
            "used_mb": used_mb, "util_pct": util_pct,
            "busy": busy, "processes": [],
        })

    # Best-effort process listing — skip silently if it fails
    proc_query = "nvidia-smi --query-compute-apps=pid,gpu_uuid,process_name,used_memory --format=csv,noheader,nounits"
    try:
        proc_out, proc_err = await _run_nvidia_smi(proc_query, host, ssh_port, timeout=5)
        if proc_err is None and proc_out:
            gpus_by_idx = {g["index"]: g for g in gpus}
            for line in proc_out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 4:
                    continue
                try:
                    pid = int(parts[0])
                    pname = parts[2]
                    pmem = int(float(parts[3]))
                except (ValueError, IndexError):
                    continue
                idx = uuid_to_idx.get(parts[1])
                if idx is None or idx not in gpus_by_idx:
                    continue
                gpus_by_idx[idx]["processes"].append({
                    "pid": pid, "name": pname, "used_mb": pmem,
                })
    except Exception:
        pass

    if gpus:
        return {"ok": True, "gpus": gpus, "backend": "cuda", "source": "nvidia-smi"}

    # Local Apple Silicon / Metal fallback. macOS has no nvidia-smi and no
    # Linux /sys/class/drm tree, but services.hwfit.hardware already knows
    # how to size the shared unified-memory GPU budget. Keep this route in
    # sync so Cookbook's GPU picker doesn't show "nvidia-smi not found" on
    # native Mac launches.
    if not host and sys.platform == "darwin":
        try:
            from services.hwfit.hardware import detect_system
            info = detect_system(fresh=True)
            backend = str(info.get("backend") or "").lower()
            if backend in {"metal", "mps", "apple"} and info.get("gpu_count", 0) > 0:
                total_mb = int(float(info.get("gpu_vram_gb") or info.get("total_ram_gb") or 0) * 1024)
                free_mb = int(float(info.get("available_ram_gb") or 0) * 1024)
                if total_mb and (free_mb <= 0 or free_mb > total_mb):
                    free_mb = total_mb
                used_mb = max(0, total_mb - max(0, free_mb))
                return {
                    "ok": True,
                    "gpus": [{
                        "index": 0,
                        "name": info.get("gpu_name") or info.get("cpu_name") or "Apple Silicon GPU",
                        "uuid": "apple-metal-0",
                        "free_mb": max(0, free_mb),
                        "total_mb": max(0, total_mb),
                        "used_mb": used_mb,
                        "util_pct": 0,
                        "busy": bool(total_mb and (free_mb / total_mb) < 0.5),
                        "processes": [],
                        "backend": "metal",
                        "source": "apple-metal",
                        "unified_memory": True,
                    }],
                    "backend": "metal",
                    "source": "apple-metal",
                    "fallback_from": "nvidia-smi",
                    "nvidia_error": nvidia_error,
                }
        except Exception as e:
            logger.warning("Apple Metal GPU fallback failed: %s", e)

    amd_gpus = await _probe_amd_sysfs(host, ssh_port)
    if amd_gpus:
        return {
            "ok": True,
            "gpus": amd_gpus,
            "backend": "rocm",
            "source": "amd-sysfs",
            "fallback_from": "nvidia-smi",
            "nvidia_error": nvidia_error,
        }

    processes = await _probe_gpu_device_processes(host, ssh_port)
    if processes:
        return {
            "ok": True,
            "gpus": [{
                "index": 0, "name": "GPU device holders", "uuid": "dev-dri",
                "free_mb": 0, "total_mb": 0, "used_mb": 0, "util_pct": 0,
                "busy": True, "processes": processes,
                "backend": "generic", "source": "gpu-devices",
            }],
            "backend": "generic",
            "source": "gpu-devices",
            "fallback_from": "nvidia-smi",
            "nvidia_error": nvidia_error,
        }

    return {"ok": False, "error": nvidia_error or "No GPU memory probe available", "gpus": []}


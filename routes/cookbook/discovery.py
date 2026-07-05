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

async def model_cached(request: Request, host: str | None = None, model_dir: str | None = None, ssh_port: str | None = None, platform: str | None = None):
    """List cached models. Scans HF cache + optional model directory."""
    require_admin(request)
    # Validate shell-bound inputs, matching the sibling list_gpus endpoint —
    # `host`/`ssh_port` are interpolated into an ssh command below, so an
    # unvalidated value (e.g. "x'; rm -rf ~ #") would be command injection.
    host = validate_remote_host(host)
    ssh_port = validate_ssh_port(ssh_port)
    TMUX_LOG_DIR.mkdir(parents=True, exist_ok=True)

    model_dirs = []
    if model_dir:
        for d in model_dir.split(','):
            d = d.strip()
            if d:
                model_dirs.append(d)
    paths_code = _cached_model_scan_script(model_dirs)

    scan_py = TMUX_LOG_DIR / "scan_cache.py"
    scan_py.write_text(paths_code, encoding="utf-8")

    if host:
        _pf = f"-p {ssh_port} " if ssh_port and ssh_port != "22" else ""
        if platform == "windows":
            # Windows: use 'python' and pipe via stdin with double-quote wrapping
            cmd = f'ssh {_pf}{host} "python -" < \'{scan_py}\''
        else:
            cmd = f"ssh {_pf}{host} 'python3 -' < '{scan_py}'"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home()),
        )
    else:
        # LOCAL scan: use sys.executable (the venv Python Odysseus is already
        # running under) — it's guaranteed real Python on all platforms.
        # Falling back to which_tool on Windows risks hitting the Microsoft
        # Store stub alias for "python3"/"python", which prints
        # "Python was not found; run without arguments to install from the
        # Microsoft Store" and exits 9009, producing empty stdout and a
        # JSON parse error. sys.executable bypasses PATH entirely.
        local_py = sys.executable or (
            which_tool("python3") or which_tool("python")
            or which_tool("py") or "python"
        )
        proc = await asyncio.create_subprocess_exec(
            local_py, str(scan_py),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home()),
        )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60)

    models = []
    try:
        raw = json.loads(stdout_b.decode(errors="replace").strip())
        for m in raw:
            size_gb = m["size_bytes"] / (1024 ** 3)
            if size_gb >= 1:
                size_str = f"{size_gb:.1f} GB"
            else:
                size_str = f"{m['size_bytes'] / (1024**2):.0f} MB"
            entry = {
                "repo_id": m["repo_id"],
                "size": size_str,
                "nb_files": m["nb_files"],
                "has_incomplete": m["has_incomplete"],
                "status": "downloading" if m["has_incomplete"] else "ready",
                "path": m.get("path", ""),
                "is_diffusion": m.get("is_diffusion", False),
            }
            if m.get("is_local_dir"):
                entry["is_local_dir"] = True
            if m.get("is_gguf"):
                entry["is_gguf"] = True
            if m.get("backend"):
                entry["backend"] = m.get("backend")
            if m.get("is_ollama"):
                entry["is_ollama"] = True
            if isinstance(m.get("gguf_files"), list):
                entry["gguf_files"] = m["gguf_files"]
            models.append(entry)
    except Exception as e:
        logger.warning(f"Failed to parse cached models: {e}")
        logger.warning(f"stderr: {stderr_b.decode(errors='replace')[:500]}")

    return {"models": models, "host": host or "local"}

async def hf_latest(vram_gb: float = 0, limit: int = 10, pipeline: str = "text-generation", owner: str = Depends(require_user)):
    """Fetch latest HuggingFace models, filtered by what fits in available VRAM.

    vram_gb: total available VRAM in GB. 0 = no filter (return everything).
    limit:   how many models to return (default 10).
    pipeline: HF pipeline_tag filter (text-generation, text-to-image, etc.).
    """
    import re
    import httpx

    # Fetch a larger pool so we have enough to filter from (we drop ~80%)
    pool_size = max(limit * 15, 100)
    url = (
        "https://huggingface.co/api/models"
        f"?sort=trendingScore&direction=-1&limit={pool_size}&filter={pipeline}"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"models": [], "error": f"HF API HTTP {resp.status_code}"}
            raw = resp.json()
    except Exception as e:
        return {"models": [], "error": str(e)}

    # Estimate VRAM from the model id. Looks for patterns like "7B", "70B", "1.5B" etc.
    # Returns approx VRAM in GB at fp16 (params*2). Caller adjusts for quant.
    def _est_vram_fp16(repo_id: str) -> float | None:
        m = re.search(r'[-_/](\d+(?:\.\d+)?)\s*[Bb](?![a-zA-Z])', repo_id)
        if not m:
            return None
        params_b = float(m.group(1))
        return params_b * 2.0  # fp16 baseline

    # Detect quantization from repo_id / tags. Returns a multiplier on fp16 size.
    def _quant_factor(repo_id: str, tags: list) -> float:
        text = (repo_id + " " + " ".join(tags or [])).lower()
        if "fp4" in text or "nf4" in text or "int4" in text or "4bit" in text or "q4" in text or "awq" in text or "gptq" in text:
            return 0.25
        if "int8" in text or "8bit" in text or "q8" in text or "fp8" in text:
            return 0.5
        if "bf16" in text or "fp16" in text:
            return 1.0
        return 1.0  # default fp16

    # Exclude adapters, LoRAs, datasets, GGUF-only repos, and other non-runnable artifacts
    EXCLUDE_TAG_SUBSTRINGS = (
        "lora", "adapter", "peft", "qlora",
        "dataset", "embeddings",
        "merge", "control-lora",
        "diffusion-lora", "stable-diffusion-lora",
        "text-classification", "token-classification",
        "feature-extraction", "sentence-similarity",
    )
    EXCLUDE_NAME_SUBSTRINGS = (
        "lora", "adapter", "peft", "qlora",
        "embedding", "embed-",
        "dataset",
    )

    def _is_excluded(repo_id: str, tags: list) -> bool:
        text = repo_id.lower()
        for s in EXCLUDE_NAME_SUBSTRINGS:
            if s in text:
                return True
        tag_text = " ".join(t.lower() for t in (tags or []))
        for s in EXCLUDE_TAG_SUBSTRINGS:
            if s in tag_text:
                return True
        return False

    out = []
    for entry in raw:
        repo_id = entry.get("modelId") or entry.get("id") or ""
        if not repo_id:
            continue
        tags = entry.get("tags") or []
        pipeline_tag = entry.get("pipeline_tag") or ""

        # Hard filter: only the requested pipeline (HF's filter param is loose)
        if pipeline and pipeline_tag and pipeline_tag != pipeline:
            continue
        # Skip adapters, LoRAs, datasets, etc.
        if _is_excluded(repo_id, tags):
            continue

        est_fp16 = _est_vram_fp16(repo_id)
        quant_mult = _quant_factor(repo_id, tags)
        est_vram = (est_fp16 * quant_mult) if est_fp16 else None
        # Add 30% headroom for KV cache, activations, etc.
        needed_vram = (est_vram * 1.3) if est_vram else None

        if vram_gb > 0 and needed_vram is not None and needed_vram > vram_gb:
            continue
        # Unknown-size models (e.g. MiniMax-M2.7, DeepSeek-V4-Flash) have no
        # "NB" in the repo id, so the regex above can't extract their
        # param count. Previously we dropped them entirely, which made
        # brand-new flagship releases silently vanish from this list even
        # on rigs with hundreds of GB of VRAM. Adapters/LoRAs are already
        # filtered by _is_excluded(), so what falls through here is
        # overwhelmingly full models — keep them, just without a size
        # badge (the frontend handles needed_vram_gb=null gracefully).

        out.append({
            "repo_id": repo_id,
            "downloads": entry.get("downloads", 0),
            "likes": entry.get("likes", 0),
            "createdAt": entry.get("createdAt", ""),
            "tags": tags[:5],  # trim
            "pipeline_tag": pipeline_tag,
            "est_vram_gb": round(est_vram, 1) if est_vram else None,
            "needed_vram_gb": round(needed_vram, 1) if needed_vram else None,
        })
        if len(out) >= limit:
            break

    return {"models": out}

async def ollama_library(refresh: int = 0, request: Request = None, owner: str = Depends(require_user)):
    """List popular Ollama library models for the Browse picker.

    Tries a 1-hour-cached fetch of ollama.com/library, falls back to a
    curated hard-coded list so the picker always renders something."""
    import time as _time
    import httpx as _httpx
    TTL = 3600.0
    now = _time.time()
    if refresh or (now - _ollama_library_cache["fetched_at"]) > TTL or not _ollama_library_cache["models"]:
        models: list[dict] = []
        err = None
        try:
            async with _httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                resp = await client.get(
                    "https://ollama.com/search?sort=popular",
                    headers={"User-Agent": "odysseus-cookbook/1.0"},
                )
            if resp.status_code == 200:
                html = resp.text
                # ollama.com renders each model card as a single anchor:
                #   <a href="/library/<name>" class="group w-full"> … </a>
                # The description + sizes live inside that anchor. Pull
                # the whole block then extract pieces individually.
                block_re = re.compile(
                    r'<a[^>]*href="/library/([A-Za-z0-9._-]+)"[^>]*>(.*?)</a>',
                    re.DOTALL,
                )
                desc_re = re.compile(r'<p[^>]*>([^<]{4,400})</p>', re.DOTALL)
                # Size tags on ollama.com cards look like "0.5b", "14b",
                # "8x7b", "27b". Pulled from short <span>-wrapped chips.
                size_re = re.compile(r'>\s*(\d+(?:\.\d+)?(?:x\d+)?[bBmM])\s*<')
                seen: set[str] = set()
                for bm in block_re.finditer(html):
                    name = bm.group(1).strip()
                    if name in seen:
                        continue
                    seen.add(name)
                    body = bm.group(2)
                    dm = desc_re.search(body)
                    desc = (dm.group(1).strip() if dm else "").replace("\n", " ")
                    sizes_raw = size_re.findall(body)
                    # Dedup sizes preserving order
                    sizes: list[str] = []
                    for s in sizes_raw:
                        s_low = s.lower()
                        if s_low not in sizes:
                            sizes.append(s_low)
                    models.append({"name": name, "description": desc, "sizes": sizes})
                    if len(models) >= 80:
                        break
            else:
                err = f"HTTP {resp.status_code}"
        except Exception as e:
            err = str(e)[:160]
        # Merge curated fallback so classics (qwen2.5, llama3, deepseek-r1,
        # …) stay reachable even when ollama.com's front page is dominated
        # by brand-new releases the user might not be looking for.
        live_names = {m["name"] for m in models}
        for fb in _OLLAMA_FALLBACK_LIBRARY:
            if fb["name"] not in live_names:
                models.append(fb)
        if not models:
            models = list(_OLLAMA_FALLBACK_LIBRARY)
            if err is None:
                err = "parsed 0 results — using fallback list"
        _ollama_library_cache["models"] = models
        _ollama_library_cache["fetched_at"] = now
        _ollama_library_cache["error"] = err
    return {
        "models": _ollama_library_cache["models"],
        "fetched_at": _ollama_library_cache["fetched_at"],
        "error": _ollama_library_cache["error"],
    }


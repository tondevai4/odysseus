import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from src.constants import MAX_READ_CHARS, DEEP_RESEARCH_DIR, VAULT_FILE
from src.tool_utils import get_mcp_manager
from core.constants import internal_api_base

logger = logging.getLogger(__name__)

def _parse_tool_args(content):
    """Parse a tool-call argument blob.

    Accepts either a JSON string or an already-decoded dict. Unwraps the
    common `{"body": {...}}` envelope that smaller models emit when they
    read tool descriptions like "Body is JSON: {...}" literally — they
    pass `body` as a field name rather than treating it as a noun.

    Returns a dict on success, raises ValueError on bad JSON.
    """
    if isinstance(content, str):
        try:
            args = json.loads(content) if content.strip() else {}
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(str(e))
    elif isinstance(content, dict):
        args = content
    else:
        args = {}
    # Unwrap {"body": {...}} envelope — but only if `body` is the sole key
    # and points at a dict. We don't want to clobber a legitimate `body`
    # field on tools where it's a real arg (e.g. send_email body text).
    if (
        isinstance(args, dict)
        and len(args) == 1
        and "body" in args
        and isinstance(args["body"], dict)
        and "action" in args["body"]  # extra safety: only unwrap if the inner dict looks like a tool call
    ):
        args = args["body"]
    return args

def _skill_dump(sk) -> Dict:
    """Translate a parsed Skill back into the kwargs `update_skill` expects."""
    return {
        "name": sk.name,
        "description": sk.description,
        "version": sk.version,
        "category": sk.category,
        "tags": sk.tags,
        "platforms": sk.platforms,
        "requires_toolsets": sk.requires_toolsets,
        "fallback_for_toolsets": sk.fallback_for_toolsets,
        "status": sk.status,
        "confidence": sk.confidence,
        "source": sk.source,
        "teacher_model": sk.teacher_model,
        "owner": sk.owner,
        "when_to_use": sk.when_to_use,
        "procedure": sk.procedure,
        "pitfalls": sk.pitfalls,
        "verification": sk.verification,
        "body_extra": sk.body_extra,
    }

_INTERNAL_BASE = internal_api_base()

def _internal_headers(owner: Optional[str] = None) -> Dict[str, str]:
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
    headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
    if owner:
        headers["X-Odysseus-Owner"] = owner
    return headers

async def _cookbook_servers() -> Dict[str, Any]:
    """Return the cookbook's configured servers + the currently-selected
    default host. Shape: {default_host, hosts: [{host, platform, env, envPath}]}.
    The agent uses this to route downloads/serves to the right machine
    instead of silently defaulting to localhost."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_INTERNAL_BASE}/api/cookbook/state", headers=_internal_headers())
            state = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        return {"default_host": "", "hosts": []}
    env = (state or {}).get("env") or {}
    if not isinstance(env, dict):
        return {"default_host": "", "hosts": []}
    hosts = []
    for s in (env.get("servers") or []):
        if isinstance(s, dict):
            hosts.append({
                "name": s.get("name") or "",
                "host": s.get("host") or "",   # "" = Local
                "platform": s.get("platform") or "",
                "env": s.get("env") or "",
                "envPath": s.get("envPath") or "",
                "port": s.get("port") or "",
            })
    return {"default_host": env.get("remoteHost") or "", "hosts": hosts}

async def _resolve_cookbook_host(name_or_host: str) -> str:
    """Map a friendly server NAME ('gpu-box', 'workstation') to its ssh host
    string ('user@192.0.2.10'). If the input already looks like an
    ssh host (contains '@' or matches a known host), or matches nothing,
    it's returned unchanged. 'local'/'localhost' → '' (this machine)."""
    if not name_or_host:
        return ""
    val = name_or_host.strip()
    low = val.lower()
    if low in ("local", "localhost", "this machine", "here"):
        return ""
    servers = await _cookbook_servers()
    # Exact host match → already an ssh host
    for h in servers.get("hosts") or []:
        if h.get("host") and h["host"] == val:
            return val
    # Name match (case-insensitive)
    for h in servers.get("hosts") or []:
        if (h.get("name") or "").lower() == low:
            return h.get("host") or ""   # "" for the Local entry
    # Substring name match as a fallback
    for h in servers.get("hosts") or []:
        if low and low in (h.get("name") or "").lower():
            return h.get("host") or ""
    # No match — assume the caller passed a raw host/alias; return as-is
    # (ssh can resolve aliases from ~/.ssh/config).
    return val

async def _cookbook_env_for_host(host: str) -> Dict[str, Any]:
    """Resolve env_prefix / gpus / platform / hf_token / ssh_port for a
    given host by looking it up in cookbook_state.env. The user
    configures these per-host in the Cookbook UI; without them, raw
    `vllm serve …` fails with 'command not found' because vLLM lives
    inside a venv that has to be sourced first.

    Returns a dict with keys ready to drop into the /api/model/serve
    payload: env_prefix, gpus, platform, hf_token, ssh_port.
    Falls back to the top-level env settings if no per-host entry exists.
    """
    import httpx
    headers = _internal_headers()
    state: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_INTERNAL_BASE}/api/cookbook/state", headers=headers)
            state = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        logger.debug(f"cookbook env lookup failed for host={host!r}: {e}")
        return {}
    if not isinstance(state, dict):
        return {}
    env_root = state.get("env") or {}
    if not isinstance(env_root, dict):
        return {}

    # Per-host entry takes precedence over top-level.
    per_host: Dict[str, Any] = {}
    for s in (env_root.get("servers") or []):
        if isinstance(s, dict) and (s.get("host") or "") == (host or ""):
            per_host = s
            break

    env_kind = per_host.get("env") or env_root.get("env") or "none"
    env_path = per_host.get("envPath") or env_root.get("envPath") or ""
    platform = per_host.get("platform") or env_root.get("platform") or "linux"
    ssh_port = per_host.get("sshPort") or env_root.get("sshPort") or ""

    env_prefix = ""
    if env_kind == "venv" and env_path:
        if platform == "windows":
            activate = env_path if env_path.endswith("\\Scripts\\Activate.ps1") else env_path.rstrip("\\") + "\\Scripts\\Activate.ps1"
            env_prefix = f"& {activate}"
        else:
            activate = env_path if env_path.endswith("/bin/activate") else env_path.rstrip("/") + "/bin/activate"
            env_prefix = f"source {activate}"
    elif env_kind == "conda" and env_path:
        if platform == "windows":
            env_prefix = f"conda activate {env_path}"
        else:
            env_prefix = f'eval "$(conda shell.bash hook)" && conda activate {env_path}'

    from routes.cookbook_helpers import load_stored_hf_token
    return {
        "env_prefix": env_prefix,
        "env_type": env_kind,
        "env_path": env_path,
        "gpus": env_root.get("gpus") or "",
        "platform": platform,
        "hf_token": load_stored_hf_token(),
        "ssh_port": ssh_port,
    }

def _infer_serve_port(cmd: str) -> int:
    """Infer likely listen port from a serve command."""
    if not cmd:
        return 8080
    m = re.search(r"--port\\s+(\\d+)", cmd)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    m = re.search(r"OLLAMA_HOST=[^\\s]*?:(\\d+)", cmd)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    if "ollama" in cmd:
        return 11434
    return 8080

def _infer_serve_host(host: str | None) -> tuple[str, bool]:
    """Return (host, container_local) for registering a served endpoint."""
    if not (host or "").strip():
        return "localhost", True
    base_host = host.split("@", 1)[-1] if "@" in host else host
    return base_host, False

async def _ensure_served_endpoint(
    *,
    model: str,
    cmd: str,
    host: str | None,
) -> Dict[str, Any]:
    """Register/fetch a model endpoint for a running serve session."""
    import httpx
    endpoint_host, container_local = _infer_serve_host(host)
    port = _infer_serve_port(cmd)
    base_url = f"http://{endpoint_host}:{port}/v1"
    short_name = model.split("/")[-1] if "/" in model else model
    is_image = "diffusion_server.py" in (cmd or "")
    payload = {
        "name": short_name if not is_image else f"{short_name} (image)",
        "base_url": base_url,
        "skip_probe": "true",
        "model_type": "image" if is_image else "llm",
        "container_local": "true" if container_local else "false",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_INTERNAL_BASE}/api/model-endpoints",
                data=payload,
                headers=_internal_headers(),
            )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code >= 400:
            logger.debug(
                f"ensure endpoint failed for {model!r}: status={resp.status_code} data={data}"
            )
            return {"added": False, "endpoint_id": "", "base_url": base_url, "error": data}
        ep_id = data.get("id") if isinstance(data, dict) else None
        return {
            "added": bool(ep_id),
            "endpoint_id": ep_id or "",
            "base_url": base_url,
            "data": data,
        }
    except Exception as e:
        logger.debug(f"ensure endpoint exception for {model!r}: {e}")
        return {"added": False, "endpoint_id": "", "base_url": base_url, "error": str(e)}

async def _cookbook_register_task(
    session_id: str,
    model: str,
    host: str,
    cmd: str,
    task_type: str = "serve",
    *,
    endpoint_added: bool = False,
    endpoint_id: str = "",
) -> bool:
    """Append a task entry to cookbook_state.json after the agent
    launches via /api/model/serve or /api/model/download. The route
    spawns tmux but leaves state-writing to the UI; the agent needs to
    do that here so the task shows up in the Cookbook tab.
    Returns True on success, False if the write failed (best-effort)."""
    import httpx
    import time as _time
    headers = _internal_headers()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_INTERNAL_BASE}/api/cookbook/state", headers=headers)
            state = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as e:
        logger.debug(f"cookbook state read failed: {e}")
        return False
    if not isinstance(state, dict):
        state = {}
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    # Skip duplicate (same session_id) entries
    if any(isinstance(t, dict) and t.get("sessionId") == session_id for t in tasks):
        return True
    display_name = model.split("/")[-1] if "/" in model else model
    # Placeholder output — the cookbook UI's CSS hides empty <pre>
    # via `.cookbook-output-pre:empty { display: none }`, so an
    # empty-string output makes the expansion appear broken until the
    # frontend's reconnect-polling loop captures tmux output. A short
    # placeholder gives the user something to see immediately; it gets
    # replaced by real tmux output within a few seconds.
    target = f"{host}:" if host else "local:"
    placeholder = (
        f"Launched via agent — waiting for tmux output…\n"
        f"  session: {session_id}\n"
        f"  target:  {target}{(cmd.split() or [''])[0] if cmd else ''}\n"
        f"  cmd:     {cmd[:200]}{'…' if len(cmd) > 200 else ''}"
    )
    tasks.append({
        "id": session_id,
        "sessionId": session_id,
        "name": display_name,
        "modelId": model,
        "type": task_type,
        "status": "running",
        "output": placeholder,
        "ts": int(_time.time() * 1000),
        "payload": {"repo_id": model, "remote_host": host or "", "_cmd": cmd},
        "remoteHost": host or "",
        "sshPort": "",
        "platform": "linux",
        "_serveReady": False,
        "_endpointAdded": bool(endpoint_added),
        "_endpointId": endpoint_id or "",
    })
    state["tasks"] = tasks
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{_INTERNAL_BASE}/api/cookbook/state",
                                  json=state, headers=headers)
        return r.status_code < 400
    except Exception as e:
        logger.debug(f"cookbook state write failed: {e}")
        return False

def _cookbook_apply_retry_suggestion(cmd: str, suggestion: Dict[str, Any]) -> str:
    """Apply a structured Cookbook diagnosis suggestion to a serve command."""
    if not cmd or not suggestion:
        return cmd
    op = suggestion.get("op")
    if op == "append":
        arg = (suggestion.get("arg") or "").strip()
        if not arg or arg in cmd:
            return cmd
        return f"{cmd.rstrip()} {arg}"
    if op == "remove":
        flag = (suggestion.get("flag") or "").strip()
        if not flag:
            return cmd
        return re.sub(rf"\s*{re.escape(flag)}(?:\s+\S+)?", "", cmd).strip()
    if op == "replace":
        flag = (suggestion.get("flag") or "").strip()
        value = str(suggestion.get("value") or "").strip()
        if not flag or not value:
            return cmd
        repl = f"{flag} {value}"
        if re.search(rf"(^|\s){re.escape(flag)}(\s+\S+)?", cmd):
            return re.sub(rf"(^|\s){re.escape(flag)}(?:\s+\S+)?", lambda m: (m.group(1) or " ") + repl, cmd).strip()
        return f"{cmd.rstrip()} {repl}"
    return cmd

def _scan_running_model_processes() -> List[Dict[str, Any]]:
    """Scan /proc for running model server processes. Linux-only; returns
    [] on other platforms or if /proc isn't accessible. Each match returns
    a dict shaped like a cookbook task so the caller can merge cleanly.
    """
    import os
    if not os.path.isdir("/proc"):
        return []
    out: List[Dict[str, Any]] = []
    seen_keys = set()
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/cmdline", "rb") as f:
                    raw = f.read()
            except (OSError, PermissionError):
                continue
            if not raw:
                continue
            # cmdline is NUL-separated; join with spaces for matching/display
            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            if not cmdline:
                continue
            lower = cmdline.lower()
            for label, needles in _MODEL_PROCESS_PATTERNS:
                if any(n.lower() in lower for n in needles):
                    # Dedupe by (label, first-arg) — multi-worker servers
                    # spawn N processes; only show one row per server.
                    key = (label, cmdline.split(" ")[0])
                    if key in seen_keys:
                        break
                    seen_keys.add(key)
                    # Try to pluck a model name out of the cmdline.
                    model = ""
                    for tok in cmdline.split():
                        if "/" in tok and any(s in tok.lower() for s in (
                            "model", "checkpoint", ".safetensors", ".gguf", ".bin", "huggingface"
                        )):
                            model = tok
                            break
                    out.append({
                        "session_id": f"pid-{pid_dir}",
                        "model": model or label,
                        "phase": "running (external)",
                        "type": "serve",
                        "remote": "local",
                        "pid": int(pid_dir),
                        "label": label,
                        "cmdline_preview": cmdline[:140] + ("…" if len(cmdline) > 140 else ""),
                        "external": True,
                    })
                    break
    except Exception as e:
        logger.debug(f"_scan_running_model_processes failed: {e}")
    return out

async def _cookbook_kill_session(session_id: str, *, remote_host: str = "",
                                 ssh_port: str = "", verb: str = "Stopped") -> Dict:
    """Kill a cookbook tmux session — remote-aware — AND mark the task
    stopped in cookbook_state.json. Shared by stop_served_model and
    cancel_download so both behave identically.

    Resolves the task's remote host from state when not passed in. A
    local-only `tmux kill-session` silently no-ops for remote tasks —
    that's the bug where "stop the download" appeared to work but the
    download kept running on the remote host.
    """
    import httpx
    import shlex
    headers = _internal_headers()
    remote = remote_host or ""
    sport = ssh_port or ""

    # Look up the task's host + confirm it exists in state.
    state: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_INTERNAL_BASE}/api/cookbook/state", headers=headers)
            state = resp.json() or {}
    except Exception as e:
        logger.debug(f"cookbook state lookup failed for {session_id}: {e}")
    if not isinstance(state, dict):
        state = {}
    matched = None
    for t in (state.get("tasks") or []):
        if isinstance(t, dict) and (t.get("sessionId") == session_id or t.get("id") == session_id):
            matched = t
            if not remote:
                remote = t.get("remoteHost") or ""
            if not sport:
                sport = t.get("sshPort") or ""
            break

    if remote:
        _pf = f"-p {shlex.quote(str(sport))} " if sport and str(sport) != "22" else ""
        cmd = (
            f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "
            f"{_pf}{shlex.quote(remote)} 'tmux kill-session -t {shlex.quote(session_id)}'"
        )
        target_label = f"{session_id} on {remote}"
    else:
        cmd = f"tmux kill-session -t {shlex.quote(session_id)}"
        target_label = session_id

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{_INTERNAL_BASE}/api/shell/exec",
                                     json={"command": cmd}, headers=headers)
        if resp.status_code >= 400:
            return {"error": f"shell/exec returned HTTP {resp.status_code}: {resp.text[:200]}", "exit_code": 1}
        try:
            data = resp.json()
        except Exception:
            data = {}
        kill_failed = isinstance(data, dict) and data.get("exit_code") not in (None, 0)
        kill_err = ((data.get("stderr") or data.get("error") or "").strip() if isinstance(data, dict) else "")
        # "no server running" / "can't find session" means it was already
        # gone — treat as success (the goal is "not running").
        already_gone = any(s in kill_err.lower() for s in ("no server running", "can't find session", "session not found"))
        if kill_failed and not already_gone:
            return {"error": f"Failed to {verb.lower()} {target_label}: {kill_err or 'kill-session returned non-zero'}", "exit_code": 1}

        # Update state: mark stopped (so the UI + list reflect reality).
        if matched is not None:
            try:
                matched["status"] = "stopped"
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(f"{_INTERNAL_BASE}/api/cookbook/state",
                                      json=state, headers=headers)
            except Exception as e:
                logger.debug(f"failed to mark {session_id} stopped in state: {e}")

        suffix = " (was already gone)" if already_gone else ""
        return {"output": f"{verb} {target_label}{suffix}", "exit_code": 0}
    except Exception as e:
        return {"error": str(e), "exit_code": 1}

def _load_vault_config() -> Dict:
    """Load Vaultwarden config from data/vault.json."""
    from pathlib import Path
    p = Path(VAULT_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

async def _run_bw(args: list, session: Optional[str] = None, input_text: Optional[str] = None) -> tuple:
    """Run a bw CLI command with optional session + stdin. Returns (stdout, stderr, returncode)."""
    import asyncio
    env = {}
    import os as _os
    env.update(_os.environ)
    if session:
        env["BW_SESSION"] = session

    proc = await asyncio.create_subprocess_exec(
        "bw", *args,
        stdin=asyncio.subprocess.PIPE if input_text else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate(input=input_text.encode() if input_text else None)
    return stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip(), proc.returncode

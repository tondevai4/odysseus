# src/agent_tools/tool_maker.py
"""
Dynamic Tool Maker & Runtime Synthesizer for YVES.
Synthesizes, tests, sandboxes, heals, loads, and persists agent-created Python tools.
"""
import ast
import asyncio
import importlib
import inspect
import json
import logging
import os
import pathlib
import re
import uuid
from typing import Dict, Any, Optional, Callable, List

from src.agent_loop.sandbox import run_in_sandbox
from src.agent_loop.self_heal import heal_and_retry

logger = logging.getLogger(__name__)

# Active in-memory registry of dynamically loaded tools
DYNAMIC_TOOLS_REGISTRY: Dict[str, Dict[str, Any]] = {}

DYNAMIC_DIR = pathlib.Path(__file__).parent / "dynamic"


def _sanitize_tool_name(name: str) -> str:
    """Ensure tool name is a valid lowercase python identifier."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", (name or "dynamic_tool").strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean or clean[0].isdigit():
        clean = f"tool_{clean}"
    return clean


def register_dynamic_module(name: str, module: Any, description: str = "", schema: Optional[Dict] = None) -> bool:
    """Inspect and register a loaded dynamic module into the active runtime tool registry."""
    func = getattr(module, name, None)
    if not func or not callable(func):
        # Look for any callable function defined inside the module
        for attr_name in dir(module):
            if not attr_name.startswith("_"):
                candidate = getattr(module, attr_name)
                if callable(candidate) and inspect.getmodule(candidate) == module:
                    func = candidate
                    break

    if not func or not callable(func):
        logger.warning(f"No callable entrypoint found in dynamic module '{name}'")
        return False

    DYNAMIC_TOOLS_REGISTRY[name] = {
        "func": func,
        "module": module,
        "description": description or inspect.getdoc(func) or f"Dynamic tool {name}",
        "schema": schema,
        "name": name,
    }

    # Register in agent_tools.TOOL_HANDLERS if available
    try:
        from src.agent_tools import TOOL_HANDLERS
        # Wrapper to handle string/JSON args
        async def _dynamic_wrapper(content: Any, **kwargs):
            try:
                if isinstance(content, str):
                    content = content.strip()
                    if content.startswith("{") and content.endswith("}"):
                        kwargs.update(json.loads(content))
                    elif content:
                        kwargs["input"] = content
                elif isinstance(content, dict):
                    kwargs.update(content)

                if inspect.iscoroutinefunction(func):
                    out = await func(**kwargs)
                else:
                    out = func(**kwargs)
                return {"output": str(out), "exit_code": 0, "result": out}
            except Exception as exc:
                return {"error": str(exc), "exit_code": 1}

        TOOL_HANDLERS[name] = _dynamic_wrapper
    except Exception:
        pass

    return True


def get_dynamic_tool_handler(name: str) -> Optional[Callable]:
    """Retrieve runtime callable for a dynamic tool."""
    entry = DYNAMIC_TOOLS_REGISTRY.get(name)
    return entry.get("func") if entry else None


def list_dynamic_tools() -> List[Dict[str, Any]]:
    """List all currently active dynamic tools in memory."""
    tools = []
    for name, entry in DYNAMIC_TOOLS_REGISTRY.items():
        tools.append({
            "name": name,
            "description": entry.get("description", ""),
            "schema": entry.get("schema"),
        })
    return tools


async def synthesize_tool(
    name: str,
    description: str,
    code_body: str,
    test_code: str = "",
    ui_schema: Optional[Dict] = None,
    author: str = "ai",
) -> Dict[str, Any]:
    """Synthesize, test in sandbox, self-heal, dynamically load, and persist a new Python tool.

    Args:
        name: Name of the tool function.
        description: Plain text description of what the tool does.
        code_body: Complete Python source code implementing the tool.
        test_code: Optional test assertions to run against the tool.
        ui_schema: Optional UI configuration dict for Server-Driven UI (SDUI).
        author: Creator tag ('ai' or username).

    Returns:
        Structured result dict: {
            "success": bool,
            "tool_name": str,
            "description": str,
            "file_path": str,
            "module_path": str,
            "widget": dict | None,
            "error": str | None
        }
    """
    clean_name = _sanitize_tool_name(name)
    current_code = code_body.strip()

    # 1. Run in isolated subprocess sandbox
    logger.info(f"Synthesizing dynamic tool '{clean_name}'...")
    sandbox_res = run_in_sandbox(current_code, test_code)

    # 2. If sandbox test fails, trigger autonomous self-healing loop
    if not sandbox_res["success"]:
        err_msg = sandbox_res.get("error") or sandbox_res.get("stderr") or "Validation error"
        logger.warning(f"Initial sandbox test failed for '{clean_name}': {err_msg}. Triggering self-heal...")
        heal_res = await heal_and_retry(
            tool_name=clean_name,
            broken_code=current_code,
            error_trace=err_msg,
            test_code=test_code,
            ui_schema=ui_schema,
        )
        if not heal_res["success"]:
            return {
                "success": False,
                "tool_name": clean_name,
                "error": f"Tool test failed and self-healing was unable to repair it: {heal_res.get('error')}",
                "phase": "sandbox_validation",
                "sandbox": sandbox_res,
            }
        current_code = heal_res["repaired_code"]

    # 3. Write verified code to src/agent_tools/dynamic/{name}.py
    DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)
    init_py = DYNAMIC_DIR / "__init__.py"
    if not init_py.exists():
        init_py.write_text("# Dynamic tools package\n", encoding="utf-8")

    file_path = DYNAMIC_DIR / f"{clean_name}.py"
    try:
        file_path.write_text(current_code, encoding="utf-8")
    except Exception as e:
        return {
            "success": False,
            "tool_name": clean_name,
            "error": f"Failed to write tool file: {e}",
            "phase": "file_write",
        }

    # 4. Dynamically import the module into Python runtime memory
    module_path = f"src.agent_tools.dynamic.{clean_name}"
    try:
        if module_path in importlib.sys.modules:
            mod = importlib.import_module(module_path)
            importlib.reload(mod)
        else:
            mod = importlib.import_module(module_path)
    except Exception as e:
        return {
            "success": False,
            "tool_name": clean_name,
            "error": f"Dynamic import failed: {e}",
            "phase": "runtime_import",
        }

    # 5. Register in active runtime tool registry
    registered = register_dynamic_module(clean_name, mod, description=description, schema=ui_schema)
    if not registered:
        return {
            "success": False,
            "tool_name": clean_name,
            "error": f"Could not find callable entrypoint for '{clean_name}' in generated module",
            "phase": "registration",
        }

    # 6. Persist tool and SDUI widget into SQLite database
    widget_info = None
    try:
        from core.database import SessionLocal, DynamicTool, DynamicWidget

        tool_id = f"dt-{uuid.uuid4().hex[:10]}"
        with SessionLocal() as db:
            existing = db.query(DynamicTool).filter(DynamicTool.name == clean_name).first()
            if existing:
                existing.description = description
                existing.file_path = str(file_path)
                existing.enabled = True
                existing.version = (existing.version or 1) + 1
                tool_id = existing.id
            else:
                new_tool = DynamicTool(
                    id=tool_id,
                    name=clean_name,
                    description=description,
                    file_path=str(file_path),
                    enabled=True,
                    author=author,
                )
                db.add(new_tool)

            # Create or update corresponding SDUI widget
            ui_conf = ui_schema or {}
            widget_title = ui_conf.get("title") or clean_name.replace("_", " ").title()
            widget_type = ui_conf.get("widget_type") or "metric_card"
            widget_icon = ui_conf.get("icon") or "Wrench"
            endpoint = f"/api/ui/execute-tool/{clean_name}"

            existing_widget = db.query(DynamicWidget).filter(DynamicWidget.tool_id == tool_id).first()
            if existing_widget:
                existing_widget.title = widget_title
                existing_widget.widget_type = widget_type
                existing_widget.icon = widget_icon
                existing_widget.endpoint = endpoint
                widget_id = existing_widget.id
            else:
                widget_id = f"dw-{uuid.uuid4().hex[:10]}"
                widget = DynamicWidget(
                    id=widget_id,
                    tool_id=tool_id,
                    title=widget_title,
                    widget_type=widget_type,
                    endpoint=endpoint,
                    icon=widget_icon,
                    position=0,
                )
                db.add(widget)

            db.commit()

            widget_info = {
                "id": widget_id,
                "title": widget_title,
                "widget_type": widget_type,
                "endpoint": endpoint,
                "icon": widget_icon,
            }
    except Exception as e:
        logger.warning(f"Database persistence for dynamic tool '{clean_name}' failed: {e}")

    logger.info(f"Dynamic tool '{clean_name}' synthesized and loaded successfully!")
    return {
        "success": True,
        "tool_name": clean_name,
        "description": description,
        "file_path": str(file_path),
        "module_path": module_path,
        "widget": widget_info,
        "error": None,
    }


def synthesize_tool_sync(*args, **kwargs) -> Dict[str, Any]:
    """Synchronous wrapper for synthesize_tool."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, synthesize_tool(*args, **kwargs)).result()
        return loop.run_until_complete(synthesize_tool(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(synthesize_tool(*args, **kwargs))

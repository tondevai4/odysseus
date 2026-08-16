# src/agent_tools/dynamic/__init__.py
"""
Dynamic tools package namespace.
Contains agent-synthesized tools that can be imported and executed at runtime.
"""
import importlib
import logging
import os
import pathlib
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

DYNAMIC_TOOLS_DIR = pathlib.Path(__file__).parent.resolve()


def list_dynamic_tool_files() -> List[str]:
    """Return all synthesized tool module names on disk."""
    if not DYNAMIC_TOOLS_DIR.exists():
        return []
    modules = []
    for f in DYNAMIC_TOOLS_DIR.glob("*.py"):
        if f.name != "__init__.py" and not f.name.startswith("_"):
            modules.append(f.stem)
    return modules


def load_all_dynamic_tools() -> int:
    """Scan and dynamically load all verified dynamic tools into Python runtime memory.

    Called during application boot and on-demand tool synthesis.
    """
    count = 0
    from src.agent_tools.tool_maker import register_dynamic_module

    # 1. Load from disk
    for name in list_dynamic_tool_files():
        try:
            module_name = f"src.agent_tools.dynamic.{name}"
            mod = importlib.import_module(module_name)
            importlib.reload(mod)
            if register_dynamic_module(name, mod):
                count += 1
                logger.info(f"Loaded dynamic tool '{name}' into runtime memory.")
        except Exception as e:
            logger.warning(f"Failed to load dynamic tool module '{name}': {e}")

    # 2. Sync database enabled states if DB available
    try:
        from core.database import SessionLocal, DynamicTool
        with SessionLocal() as db:
            tools = db.query(DynamicTool).filter(DynamicTool.enabled == True).all()
            for t in tools:
                if t.name not in list_dynamic_tool_files():
                    continue
                # Ensure tool is registered
                try:
                    mod = importlib.import_module(f"src.agent_tools.dynamic.{t.name}")
                    register_dynamic_module(t.name, mod, description=t.description)
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"DB sync during dynamic tool loading: {e}")

    return count

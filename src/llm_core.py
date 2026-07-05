# src/llm_core.py — backward-compatibility shim.
# Canonical location: src/llm/core.py

from src.llm.core import *  # noqa: F401,F403

import src.llm.core as _core
for _name in dir(_core):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_core, _name)

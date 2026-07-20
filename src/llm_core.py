# src/llm_core.py — backward-compatibility shim.
# Canonical location: src/llm/core.py
import sys
from src.llm import core
sys.modules[__name__] = core

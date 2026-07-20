# src/agent_loop.py — backward-compatibility shim.
# Canonical location: src/agent/loop.py
import sys
from src.agent import loop
sys.modules[__name__] = loop

# src/builtin_actions.py — backward-compatibility shim.
# Canonical location: src/agent/builtin_actions.py
import sys
import src.agent.builtin_actions
sys.modules[__name__] = src.agent.builtin_actions

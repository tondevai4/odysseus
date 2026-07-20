# src/context_budget.py — backward-compatibility shim.
# Canonical location: src/llm/context_budget.py
import sys
import src.llm.context_budget
sys.modules[__name__] = src.llm.context_budget

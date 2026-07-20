# src/context_compactor.py — backward-compatibility shim.
# Canonical location: src/llm/context_compactor.py
import sys
import src.llm.context_compactor
sys.modules[__name__] = src.llm.context_compactor

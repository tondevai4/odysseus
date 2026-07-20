# src/model_context.py — backward-compatibility shim.
# Canonical location: src/llm/model_context.py
import sys
import src.llm.model_context
sys.modules[__name__] = src.llm.model_context

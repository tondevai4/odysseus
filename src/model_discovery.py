# src/model_discovery.py — backward-compatibility shim.
# Canonical location: src/llm/model_discovery.py
import sys
import src.llm.model_discovery
sys.modules[__name__] = src.llm.model_discovery

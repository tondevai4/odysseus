# src/endpoint_resolver.py — backward-compatibility shim.
# Canonical location: src/llm/endpoint_resolver.py
import sys
import src.llm.endpoint_resolver
sys.modules[__name__] = src.llm.endpoint_resolver

# src/research_handler.py — backward-compatibility shim.
# Canonical location: src/research/handler.py
import sys
import src.research.handler
sys.modules[__name__] = src.research.handler

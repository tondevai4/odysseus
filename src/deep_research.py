# src/deep_research.py — backward-compatibility shim.
# Canonical location: src/research/engine.py
import sys
import src.research.engine
sys.modules[__name__] = src.research.engine

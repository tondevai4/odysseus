# src/research_utils.py — backward-compatibility shim.
# Canonical location: src/research/utils.py
import sys
import src.research.utils
sys.modules[__name__] = src.research.utils

# src/visual_report.py — backward-compatibility shim.
# Canonical location: src/research/visual_report.py
import sys
import src.research.visual_report
sys.modules[__name__] = src.research.visual_report

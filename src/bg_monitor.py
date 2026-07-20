# src/bg_monitor.py — backward-compatibility shim.
# Canonical location: src/scheduling/bg_monitor.py
import sys
import src.scheduling.bg_monitor
sys.modules[__name__] = src.scheduling.bg_monitor

# src/event_bus.py — backward-compatibility shim.
# Canonical location: src/scheduling/event_bus.py
import sys
import src.scheduling.event_bus
sys.modules[__name__] = src.scheduling.event_bus

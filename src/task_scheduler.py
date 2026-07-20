# src/task_scheduler.py — backward-compatibility shim.
# Canonical location: src/scheduling/scheduler.py
import sys
import src.scheduling.scheduler
sys.modules[__name__] = src.scheduling.scheduler

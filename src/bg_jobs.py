# src/bg_jobs.py — backward-compatibility shim.
# Canonical location: src/scheduling/bg_jobs.py
import sys
import src.scheduling.bg_jobs
sys.modules[__name__] = src.scheduling.bg_jobs

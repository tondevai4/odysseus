# src/caldav_sync.py — backward-compatibility shim.
# Canonical location: src/email_cal/caldav_sync.py
import sys
import src.email_cal.caldav_sync
sys.modules[__name__] = src.email_cal.caldav_sync

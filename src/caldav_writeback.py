# src/caldav_writeback.py — backward-compatibility shim.
# Canonical location: src/email_cal/caldav_writeback.py
import sys
import src.email_cal.caldav_writeback
sys.modules[__name__] = src.email_cal.caldav_writeback

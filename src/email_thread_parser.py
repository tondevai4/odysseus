# src/email_thread_parser.py — backward-compatibility shim.
# Canonical location: src/email_cal/thread_parser.py
import sys
import src.email_cal.thread_parser
sys.modules[__name__] = src.email_cal.thread_parser

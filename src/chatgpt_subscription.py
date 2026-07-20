# src/chatgpt_subscription.py — backward-compatibility shim.
# Canonical location: src/email_cal/chatgpt_subscription.py
import sys
import src.email_cal.chatgpt_subscription
sys.modules[__name__] = src.email_cal.chatgpt_subscription

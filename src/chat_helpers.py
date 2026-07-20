# src/chat_helpers.py — backward-compatibility shim.
# Canonical location: src/chat/helpers.py
import sys
import src.chat.helpers
sys.modules[__name__] = src.chat.helpers

# src/chat_handler.py — backward-compatibility shim.
# Canonical location: src/chat/handler.py
import sys
import src.chat.handler
sys.modules[__name__] = src.chat.handler

# src/youtube_handler.py — backward-compatibility shim.
# Canonical location: src/integrations/youtube_handler.py
import sys
import src.integrations.youtube_handler
sys.modules[__name__] = src.integrations.youtube_handler

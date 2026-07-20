# src/webhook_manager.py — backward-compatibility shim.
# Canonical location: src/integrations/webhook_manager.py
import sys
import src.integrations.webhook_manager
sys.modules[__name__] = src.integrations.webhook_manager

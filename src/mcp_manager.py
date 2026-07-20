# src/mcp_manager.py — backward-compatibility shim.
# Canonical location: src/integrations/mcp_manager.py
import sys
import src.integrations.mcp_manager
sys.modules[__name__] = src.integrations.mcp_manager

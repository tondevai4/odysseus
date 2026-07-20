# src/mcp_oauth.py — backward-compatibility shim.
# Canonical location: src/integrations/mcp_oauth.py
import sys
import src.integrations.mcp_oauth
sys.modules[__name__] = src.integrations.mcp_oauth

from fastapi import APIRouter, HTTPException, Request, Response, Form, Query, Body
from typing import List, Dict, Any, Optional
import json
import uuid
import logging
from datetime import datetime
from pydantic import BaseModel
from core.database import SessionLocal, ModelEndpoint
from core.middleware import require_admin
from src.auth_helpers import _auth_disabled, owner_filter

from .shared import *
from .state import *

def setup_tools_routes(router: APIRouter):
    @router.get("/tools")
    def list_tools():
        """List all available tools with their enabled/disabled status."""
        from src.agent_tools import TOOL_TAGS
        settings = _load_settings()
        disabled = set(settings.get("disabled_tools", []))
        tools = []
        for tag in sorted(TOOL_TAGS):
            tools.append({"id": tag, "enabled": tag not in disabled})
        return {"tools": tools}

    class ToolsUpdate(BaseModel):
        disabled: list = []


    @router.post("/tools")
    def update_tools(body: ToolsUpdate, request: Request):
        """Update which tools are disabled."""
        require_admin(request)
        settings = _load_settings()
        settings["disabled_tools"] = body.disabled
        _save_settings(settings)
        return {"ok": True, "disabled": body.disabled}



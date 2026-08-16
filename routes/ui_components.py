# routes/ui_components.py
"""
Server-Driven UI (SDUI) endpoints for dynamic toolbars and dashboard widgets in YVES.
"""
import inspect
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import SessionLocal, DynamicTool, DynamicWidget
from src.agent_tools.tool_maker import synthesize_tool, get_dynamic_tool_handler, list_dynamic_tools

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Server-Driven UI"])


class SynthesizeToolRequest(BaseModel):
    name: str = Field(..., description="Tool function name")
    description: str = Field(default="", description="Description of the tool")
    code_body: str = Field(..., description="Python source code implementing the tool")
    test_code: str = Field(default="", description="Optional test assertions to run against the tool")
    ui_schema: Optional[Dict[str, Any]] = Field(default=None, description="SDUI widget configuration")


class DynamicToolExecutionRequest(BaseModel):
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Parameters to pass to the tool")


@router.get("/api/ui/toolbar")
async def get_ui_toolbar():
    """Return active dynamic tools and tabs configured for the frontend toolbar."""
    items = []
    try:
        with SessionLocal() as db:
            widgets = (
                db.query(DynamicWidget)
                .join(DynamicTool)
                .filter(DynamicTool.enabled == True)
                .order_by(DynamicWidget.position.asc())
                .all()
            )
            for w in widgets:
                tool_name = w.tool.name if w.tool else ""
                items.append({
                    "id": w.id,
                    "tool_id": w.tool_id,
                    "tool_name": tool_name,
                    "title": w.title,
                    "icon": w.icon or "Wrench",
                    "widget_type": w.widget_type,
                    "endpoint": w.endpoint or f"/api/ui/execute-tool/{tool_name}",
                })
    except Exception as e:
        logger.warning(f"Failed to query dynamic widgets for toolbar: {e}")
        # Fallback to in-memory registry
        for t in list_dynamic_tools():
            items.append({
                "id": f"dw-mem-{t['name']}",
                "tool_id": t["name"],
                "tool_name": t["name"],
                "title": t["name"].replace("_", " ").title(),
                "icon": "Wrench",
                "widget_type": "button",
                "endpoint": f"/api/ui/execute-tool/{t['name']}",
            })

    return {"items": items, "count": len(items)}


@router.get("/api/ui/widgets")
async def get_ui_widgets():
    """Return dynamic dashboard widgets to render inside the Command Center."""
    widgets_list = []
    try:
        with SessionLocal() as db:
            widgets = (
                db.query(DynamicWidget)
                .join(DynamicTool)
                .filter(DynamicTool.enabled == True)
                .order_by(DynamicWidget.position.asc())
                .all()
            )
            for w in widgets:
                widgets_list.append({
                    "id": w.id,
                    "tool_id": w.tool_id,
                    "title": w.title,
                    "widget_type": w.widget_type,
                    "endpoint": w.endpoint,
                    "icon": w.icon,
                    "position": w.position,
                    "config": json.loads(w.config_json) if w.config_json else {},
                })
    except Exception as e:
        logger.warning(f"Failed to query dynamic widgets: {e}")

    return {"widgets": widgets_list, "total": len(widgets_list)}


@router.post("/api/ui/synthesize-tool")
async def api_synthesize_tool(body: SynthesizeToolRequest):
    """Synthesize, test in sandbox, self-heal, dynamically load, and register a new tool."""
    result = await synthesize_tool(
        name=body.name,
        description=body.description,
        code_body=body.code_body,
        test_code=body.test_code,
        ui_schema=body.ui_schema,
    )
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Synthesis failed"))
    return result


@router.post("/api/ui/execute-tool/{name}")
async def api_execute_dynamic_tool(name: str, body: Optional[DynamicToolExecutionRequest] = None):
    """Execute a dynamic tool by name with arguments."""
    handler = get_dynamic_tool_handler(name)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Dynamic tool '{name}' not found or not loaded")

    params = (body.params if body else {}) or {}
    try:
        if inspect.iscoroutinefunction(handler):
            res = await handler(**params)
        else:
            res = handler(**params)
        return {"success": True, "tool": name, "result": res}
    except Exception as e:
        logger.error(f"Execution error in dynamic tool '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}")


def setup_ui_components_routes() -> APIRouter:
    """Factory function for router registration in app.py."""
    return router

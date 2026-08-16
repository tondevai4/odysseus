# tests/test_sdui_endpoints.py
"""
Comprehensive test suite for Phase 3:
Server-Driven UI (SDUI) schema endpoints, dynamic tab generation, and tool disable/delete lifecycle.
"""
import pytest
from fastapi.testclient import TestClient

from app import app
from core.database import SessionLocal, DynamicTool, DynamicWidget


@pytest.fixture
def client():
    return TestClient(app)


def test_get_ui_toolbar_schema(client):
    """Verify GET /api/ui/toolbar returns valid SDUI structure."""
    response = client.get("/api/ui/toolbar")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
    assert isinstance(data["items"], list)

    for item in data["items"]:
        assert "id" in item
        assert "tool_id" in item
        assert "title" in item
        assert "widget_type" in item
        assert "endpoint" in item


def test_synthesize_and_get_tab_schema(client):
    """Verify tool synthesis creates SDUI widgets and GET /api/ui/tab/{id} returns components."""
    tool_name = "sdui_calc_square"
    payload = {
        "name": tool_name,
        "description": "Calculate square of a number",
        "code_body": """
def sdui_calc_square(n: float = 2.0) -> float:
    \"\"\"Compute square.\"\"\"
    return float(n) ** 2
""",
        "test_code": """
assert sdui_calc_square(4) == 16.0
""",
        "ui_schema": {
            "title": "Square Calculator",
            "widget_type": "metric_card",
            "icon": "Calculator",
            "config": {"value": "Ready", "subtitle": "Compute x^2"},
        },
    }

    # 1. Synthesize
    synth_res = client.post("/api/ui/synthesize-tool", json=payload)
    assert synth_res.status_code == 200
    synth_data = synth_res.json()
    assert synth_data["success"] is True

    # 2. Query Tab Schema
    tab_res = client.get(f"/api/ui/tab/{tool_name}")
    assert tab_res.status_code == 200
    tab_data = tab_res.json()

    assert tab_data["name"] == tool_name
    assert tab_data["title"] == "Square Calculator" or "Square" in tab_data["title"]
    assert len(tab_data["components"]) >= 1

    comp = tab_data["components"][0]
    assert "type" in comp
    assert "title" in comp
    assert "endpoint" in comp

    # 3. Test execution via endpoint
    exec_res = client.post(f"/api/ui/execute-tool/{tool_name}", json={"params": {"n": 5}})
    assert exec_res.status_code == 200
    assert exec_res.json()["result"] == 25.0


def test_delete_and_disable_dynamic_tool(client):
    """Verify DELETE /api/ui/tool/{id} disables the tool and hides it from toolbar."""
    tool_name = "sdui_temp_tool"
    payload = {
        "name": tool_name,
        "description": "Temporary tool to be deleted",
        "code_body": """
def sdui_temp_tool() -> str:
    return "ok"
""",
        "test_code": "assert sdui_temp_tool() == 'ok'",
        "ui_schema": {
            "title": "Temp Tool",
            "widget_type": "button",
            "icon": "Trash",
        },
    }

    client.post("/api/ui/synthesize-tool", json=payload)

    # Verify tool is initially in toolbar
    tb_before = client.get("/api/ui/toolbar").json()
    assert any(item["tool_name"] == tool_name for item in tb_before["items"])

    # Disable tool via DELETE endpoint
    del_res = client.delete(f"/api/ui/tool/{tool_name}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "disabled"

    # Verify tool is excluded from toolbar
    tb_after = client.get("/api/ui/toolbar").json()
    assert not any(item["tool_name"] == tool_name for item in tb_after["items"])

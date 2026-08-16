# tests/test_dynamic_tooling.py
"""
Comprehensive test suite for Phase 1 Dynamic Tool Synthesizer,
Subprocess Sandbox, Self-Healing Loop, and Server-Driven UI (SDUI).
"""
import asyncio
import os
import pytest
from fastapi.testclient import TestClient

from src.agent_loop.sandbox import run_in_sandbox, validate_code_safety
from src.agent_loop.self_heal import heal_and_retry
from src.agent_tools.tool_maker import (
    synthesize_tool,
    get_dynamic_tool_handler,
    DYNAMIC_TOOLS_REGISTRY,
)
from app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_sandbox_valid_execution():
    """Test sandbox execution with valid Python code and test assertions."""
    code = """
def add_numbers(a: int, b: int) -> int:
    return a + b
"""
    test_code = """
assert add_numbers(2, 3) == 5
assert add_numbers(-1, 1) == 0
print("ADD_NUMBERS_OK")
"""
    result = run_in_sandbox(code, test_code, timeout=5)
    assert result["success"] is True
    assert "ADD_NUMBERS_OK" in result["stdout"]
    assert result["error"] is None
    assert result["execution_time"] > 0


def test_sandbox_syntax_error():
    """Test sandbox catching syntax errors before running subprocess."""
    broken_code = "def broken(a, b\n    return a + b"
    result = run_in_sandbox(broken_code, timeout=5)
    assert result["success"] is False
    assert "SyntaxError" in (result["error"] or "")


def test_sandbox_runtime_error():
    """Test sandbox reporting runtime exception and traceback."""
    code = """
def divide(a, b):
    return a / b
"""
    test_code = """
divide(10, 0)
"""
    result = run_in_sandbox(code, test_code, timeout=5)
    assert result["success"] is False
    assert "ZeroDivisionError" in result["stderr"] or "ZeroDivisionError" in (result["error"] or "")


def test_sandbox_timeout():
    """Test sandbox killing infinite loops exceeding timeout."""
    code = """
import time
def infinite():
    while True:
        time.sleep(0.1)
"""
    test_code = "infinite()"
    result = run_in_sandbox(code, test_code, timeout=1)
    assert result["success"] is False
    assert "timed out" in (result["error"] or "").lower()


def test_sandbox_security_blocks():
    """Test sandbox blocking dangerous system wiping and forbidden modules."""
    banned_code_1 = "import os; os.system('rm -rf /')"
    res1 = run_in_sandbox(banned_code_1)
    assert res1["success"] is False
    assert "security violation" in (res1["error"] or "").lower()

    banned_code_2 = "import ctypes"
    res2 = run_in_sandbox(banned_code_2)
    assert res2["success"] is False
    assert "forbidden module" in (res2["error"] or "").lower()

    banned_code_3 = "import shutil; shutil.rmtree('/tmp')"
    res3 = run_in_sandbox(banned_code_3)
    assert res3["success"] is False
    assert "security violation" in (res3["error"] or "").lower()


@pytest.mark.asyncio
async def test_synthesize_fibonacci_tool():
    """Test synthesizing a new tool 'fibonacci_calc', sandboxing it, dynamically importing and executing it."""
    tool_name = "fibonacci_calc"
    code = """
def fibonacci_calc(n: int) -> int:
    \"\"\"Calculate the nth Fibonacci number.\"\"\"
    n = int(n)
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
"""
    test_code = """
assert fibonacci_calc(0) == 0
assert fibonacci_calc(1) == 1
assert fibonacci_calc(7) == 13
assert fibonacci_calc(10) == 55
"""
    ui_schema = {
        "title": "Fibonacci Calculator",
        "widget_type": "metric_card",
        "icon": "Calculator",
    }

    result = await synthesize_tool(
        name=tool_name,
        description="Calculates nth Fibonacci number",
        code_body=code,
        test_code=test_code,
        ui_schema=ui_schema,
    )

    assert result["success"] is True
    assert result["tool_name"] == tool_name
    assert os.path.exists(result["file_path"])

    # Verify dynamic execution via registered handler
    handler = get_dynamic_tool_handler(tool_name)
    assert handler is not None
    assert handler(7) == 13
    assert handler(10) == 55


@pytest.mark.asyncio
async def test_self_healing_loop():
    """Test self-healing on broken syntax code (e.g. missing colon in def statement)."""
    tool_name = "sample_healed_tool"
    broken_code = """
def sample_healed_tool(x)
    return x * 2
"""
    test_code = """
assert sample_healed_tool(5) == 10
assert sample_healed_tool(0) == 0
"""
    heal_res = await heal_and_retry(
        tool_name=tool_name,
        broken_code=broken_code,
        error_trace="SyntaxError: expected ':'",
        test_code=test_code,
        max_retries=3,
    )
    assert heal_res["success"] is True
    assert heal_res["attempts"] >= 1
    assert "def sample_healed_tool(x):" in heal_res["repaired_code"]


def test_sdui_toolbar_and_widgets(client):
    """Test Server-Driven UI endpoints return the synthesized tool widgets."""
    # 1. Synthesize a tool to guarantee at least one widget exists
    code = "def sdui_metric_test():\n    return 42\n"
    test_code = "assert sdui_metric_test() == 42"
    asyncio.run(synthesize_tool(
        name="sdui_metric_test",
        description="Metric test for SDUI",
        code_body=code,
        test_code=test_code,
        ui_schema={"title": "SDUI Metric", "widget_type": "metric_card", "icon": "Activity"},
    ))

    # 2. Test GET /api/ui/toolbar
    res_tb = client.get("/api/ui/toolbar")
    assert res_tb.status_code == 200
    tb_data = res_tb.json()
    assert "items" in tb_data
    assert any(item["tool_name"] == "sdui_metric_test" for item in tb_data["items"])

    # 3. Test GET /api/ui/widgets
    res_w = client.get("/api/ui/widgets")
    assert res_w.status_code == 200
    w_data = res_w.json()
    assert "widgets" in w_data
    assert any(w["title"] == "SDUI Metric" for w in w_data["widgets"])

    # 4. Test POST /api/ui/execute-tool/{name}
    res_exec = client.post("/api/ui/execute-tool/sdui_metric_test", json={"params": {}})
    assert res_exec.status_code == 200
    assert res_exec.json()["result"] == 42

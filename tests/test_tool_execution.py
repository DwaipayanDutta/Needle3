from __future__ import annotations

import time

import pytest

from needle_engine.exceptions import (
    ToolExecutionError,
    ToolLimitError,
    ToolNotFoundError,
    ToolValidationError,
)
from needle_engine.tool_executor import ToolExecutor, execute_planned_calls
from needle_engine.tool_registry import ToolRegistry, ToolSpec, default_registry


def test_execute_valid_tool(registry):
    executor = ToolExecutor(registry)
    record = executor.execute("get_current_time", {"timezone": "UTC"})
    assert record.error is None
    assert record.output["timezone"] == "UTC"
    assert executor.trace.results()[0]["ok"] is True


def test_unknown_argument_is_rejected(registry):
    executor = ToolExecutor(registry)
    with pytest.raises(ToolValidationError):
        executor.execute("control_device", {"device": "lamp", "action": "on", "extra": 1})
    assert executor.trace.records[-1].status == "validation_error"


def test_wrong_argument_type_is_rejected(registry):
    executor = ToolExecutor(registry)
    with pytest.raises(ToolValidationError):
        executor.execute("control_device", {"device": "lamp", "action": "dim", "value": "30"})


def test_unknown_tool(registry):
    executor = ToolExecutor(registry)
    with pytest.raises(ToolNotFoundError):
        executor.execute("nope", {})


def test_call_limit(registry):
    executor = ToolExecutor(registry, max_calls=1)
    executor.execute("get_current_time", {})
    with pytest.raises(ToolLimitError):
        executor.execute("get_current_time", {})


def test_timeout(tmp_path):
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="slow_tool",
            description="Sleep for longer than its timeout.",
            parameters={"type": "object", "properties": {}, "required": []},
            implementation=lambda: time.sleep(0.3) or {"ok": True},
            timeout=0.05,
        )
    )
    executor = ToolExecutor(registry)
    with pytest.raises(ToolExecutionError):
        executor.execute("slow_tool", {})
    assert executor.trace.records[-1].status == "timeout"


def test_planned_calls_continue_after_failure(registry):
    executor = ToolExecutor(registry)
    calls = [
        {"name": "get_current_time", "arguments": {}},
        {"name": "control_device", "arguments": {"device": "", "action": "on"}},
    ]
    function_calls, results, errors = execute_planned_calls(executor, calls)
    assert len(function_calls) == 2
    assert len(results) == 2
    assert errors
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False


def test_no_shell_tool(settings):
    registry = default_registry(settings)
    assert "shell" not in registry.names()
    assert "exec" not in registry.names()

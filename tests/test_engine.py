from __future__ import annotations

import dataclasses
import types

import pytest

import needle_engine.runtime as runtime_module
from needle_engine.agent import NeedleAgent
from needle_engine.configuration import Settings
from needle_engine.exceptions import EngineUnavailableError
from needle_engine.runtime import NativeRuntime, RuntimeState, SimulationRuntime
from needle_engine.sessions import SessionManager
from needle_engine.tool_registry import default_registry


class FakeNeedle:
    def __init__(self, tools=None, **kwargs):
        self.functions = {
            function._needle_tool["name"]: function
            for function in (tools or [])
        }
        self.closed = False

    def run(self, prompt, **kwargs):
        if "get_current_time" in self.functions:
            self.functions["get_current_time"](timezone="UTC")
            return {
                "type": "respond",
                "success": True,
                "function_calls": [],
                "results": [{"timezone": "UTC"}],
                "reasoning": "fake model",
                "confidence": 0.75,
                "prefill_tps": 10.0,
                "decode_tps": 20.0,
                "peak_ram_mb": 30.0,
            }
        return {
            "type": "respond",
            "success": True,
            "function_calls": [],
            "results": [],
            "reasoning": "no tools declared",
            "confidence": None,
        }

    def close(self):
        self.closed = True


def fake_module():
    module = types.SimpleNamespace(__version__="3.2.10")
    module.tool = lambda function=None, **kwargs: function
    module.Needle = FakeNeedle
    return module


def native_settings(settings):
    return dataclasses.replace(settings, mode="native", eager_init=False)


def test_native_runtime_initializes_and_traces_tools(settings, monkeypatch, sessions):
    monkeypatch.setattr(runtime_module.importlib, "import_module", lambda name: fake_module())
    registry = default_registry(settings)
    native = NativeRuntime(native_settings(settings), registry)
    simulation = SimulationRuntime(settings, registry)
    agent = NeedleAgent(native_settings(settings), native, simulation, registry, sessions)

    assert native.initialize() is True
    assert native.state == RuntimeState.READY
    status = native.status()
    assert status["native_available"] is True
    assert status["package_version"] == "3.2.10"

    response = agent.process("What time is it?", mode="native")
    assert response["success"] is True
    assert response["mode"] == "native"
    assert response["function_calls"][0]["name"] == "get_current_time"
    assert response["results"][0]["output"]["timezone"] == "UTC"
    assert response["confidence"] == 0.75
    assert response["metrics"]["prefill_tps"] == 10.0
    assert "Current time" in response["response"]
    native.close()


def test_native_tools_disabled(settings, monkeypatch, sessions):
    monkeypatch.setattr(runtime_module.importlib, "import_module", lambda name: fake_module())
    registry = default_registry(settings)
    native = NativeRuntime(native_settings(settings), registry)
    simulation = SimulationRuntime(settings, registry)
    agent = NeedleAgent(native_settings(settings), native, simulation, registry, sessions)

    assert native.initialize() is True
    response = agent.process("What time is it?", mode="native", tools_enabled=False)
    assert response["mode"] == "native"
    assert response["function_calls"] == []
    assert response["results"] == []
    assert response["response"] == ""
    assert "no tools" in response["reasoning"]
    native.close()


def test_native_initialization_failure(settings, monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no engine for this platform")

    module = types.SimpleNamespace(__version__="3.2.10")
    module.tool = lambda function=None, **kwargs: function
    module.Needle = Broken
    monkeypatch.setattr(runtime_module.importlib, "import_module", lambda name: module)

    registry = default_registry(settings)
    native = NativeRuntime(native_settings(settings), registry)
    assert native.initialize() is False
    assert native.state == RuntimeState.UNAVAILABLE
    assert "no engine" in native.status()["last_error"]

    simulation = SimulationRuntime(settings, registry)
    agent = NeedleAgent(
        native_settings(settings),
        native,
        simulation,
        registry,
        SessionManager(ttl_seconds=60),
    )
    with pytest.raises(EngineUnavailableError):
        agent.process("What time is it?", mode="native")


def test_native_schema_generation(settings):
    registry = default_registry(settings)
    module = fake_module()
    functions = registry.build_native_functions(module)
    assert len(functions) == 8
    assert {function._needle_tool["name"] for function in functions} == set(registry.names())
    assert all("parameters" in function._needle_tool for function in functions)


def test_native_status_unavailable_without_package(settings, monkeypatch):
    def missing(name):
        raise ImportError("no module named needle")

    monkeypatch.setattr(runtime_module.importlib, "import_module", missing)
    runtime = NativeRuntime(native_settings(settings), default_registry(settings))
    assert runtime.initialize() is False
    assert runtime.state == RuntimeState.UNAVAILABLE

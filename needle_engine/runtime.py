"""Runtime lifecycle for native Needle inference and explicit simulation."""

from __future__ import annotations

import importlib
import logging
import threading
import time
from enum import Enum
from typing import Any

from .configuration import Settings
from .exceptions import (
    EngineBusyError,
    EngineUnavailableError,
    RequestTimeoutError,
)
from .simulation import simulate
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry

LOGGER = logging.getLogger("needle3.runtime")

_NATIVE_ENGINE_LOCK = threading.Lock()
_NATIVE_INIT_LOCK = threading.Lock()

SYSTEM_PROMPT = (
    "You are the tool router for a local assistant. Call the minimum set of tools "
    "needed, fill arguments only from the user's words, and return an empty call "
    "list when no tool fits. Never call a tool for weather, jokes, general "
    "knowledge, or anything not explicitly covered by a tool. Never invent values."
)


class RuntimeState(str, Enum):
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    SHUTTING_DOWN = "shutting_down"
    CLOSED = "closed"


class BaseRuntime:
    mode = "unknown"

    def initialize(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self, prompt: str, executor: ToolExecutor, *, tools_enabled: bool = True) -> dict:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def status(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class NativeRuntime(BaseRuntime):
    mode = "native"

    def __init__(self, settings: Settings, registry: ToolRegistry):
        self.settings = settings
        self.registry = registry
        self._state = RuntimeState.UNINITIALIZED
        self._state_lock = threading.RLock()
        self._agent = None
        self._needle = None
        self._last_error: str | None = None
        self._started_at: float | None = None
        self._last_latency_ms: float | None = None
        self._last_metrics: dict | None = None
        self._ready_event = threading.Event()
        self._pool = None

    @property
    def state(self) -> RuntimeState:
        with self._state_lock:
            return self._state

    def _set_state(self, state: RuntimeState, error: str | None = None) -> None:
        with self._state_lock:
            self._state = state
            if error is not None:
                self._last_error = error

    def initialize(self) -> bool:
        with _NATIVE_INIT_LOCK:
            if self.state in {RuntimeState.READY, RuntimeState.BUSY}:
                return True
            if self.state == RuntimeState.INITIALIZING:
                self._ready_event.wait(timeout=self.settings.request_timeout)
                return self.state in {RuntimeState.READY, RuntimeState.BUSY}

            if not _NATIVE_ENGINE_LOCK.acquire(timeout=self.settings.request_timeout):
                message = "native engine is busy during initialization"
                self._last_error = message
                self._set_state(RuntimeState.DEGRADED, message)
                self._ready_event.set()
                return False

            try:
                self._set_state(RuntimeState.INITIALIZING)
                self._ready_event.clear()
                started = time.perf_counter()
                try:
                    self.settings.apply_environment()
                    self._needle = importlib.import_module("needle")
                    version = getattr(self._needle, "__version__", "unknown")
                    if not hasattr(self._needle, "Needle"):
                        raise RuntimeError(
                            "installed needle package does not expose needle.Needle; "
                            "install cactus-needle >= 3.2"
                        )

                    if self._agent is not None:
                        try:
                            self._agent.close()
                        except Exception:
                            pass
                        self._agent = None

                    functions = self.registry.build_native_functions(self._needle)
                    self._agent = self._needle.Needle(
                        tools=functions,
                        system=SYSTEM_PROMPT,
                        weights=self.settings.model_weights,
                        generation=self.settings.model_generation,
                        stateless=True,
                    )
                    self._started_at = time.time()
                    self._last_error = None
                    self._set_state(RuntimeState.READY)
                    LOGGER.info(
                        "Native Needle %s ready in %.2fs (generation %s, %d tools)",
                        version,
                        time.perf_counter() - started,
                        self.settings.model_generation,
                        len(functions),
                    )
                    return True
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    self._last_error = message
                    self._set_state(RuntimeState.UNAVAILABLE, message)
                    LOGGER.warning("Native Needle unavailable: %s", message)
                    return False
                finally:
                    self._ready_event.set()
            finally:
                _NATIVE_ENGINE_LOCK.release()

    def wait_ready(self, timeout: float | None = None) -> None:
        deadline = time.monotonic() + (timeout or self.settings.request_timeout)
        if self.state in {RuntimeState.UNINITIALIZED, RuntimeState.DEGRADED}:
            if not self.initialize():
                raise EngineUnavailableError(self._last_error or "native engine unavailable")
            return
        if self.state == RuntimeState.INITIALIZING:
            remaining = max(0.0, deadline - time.monotonic())
            self._ready_event.wait(timeout=remaining)
        if self.state not in {RuntimeState.READY, RuntimeState.BUSY}:
            raise EngineUnavailableError(self._last_error or "native engine is not ready")

    def _run_locked(self, prompt: str, executor: ToolExecutor, tools_enabled: bool) -> dict:
        assert self._agent is not None
        try:
            with executor.bind():
                if tools_enabled:
                    response = self._agent.run(
                        prompt,
                        max_steps=self.settings.max_tool_calls,
                        max_new_tokens=self.settings.max_new_tokens,
                        strict=True,
                    )
                else:
                    # No-tools mode uses a temporary agent. The native engine is
                    # process-global, so the main agent rebinds on its next run.
                    no_tools = self._needle.Needle(
                        tools=[],
                        system=SYSTEM_PROMPT,
                        weights=self.settings.model_weights,
                        generation=self.settings.model_generation,
                        stateless=True,
                    )
                    try:
                        response = no_tools.run(
                            prompt,
                            max_steps=0,
                            max_new_tokens=self.settings.max_new_tokens,
                            strict=True,
                        )
                    finally:
                        no_tools.close()
            metrics = {}
            for key in ("prefill_tps", "decode_tps", "peak_ram_mb"):
                if key in response:
                    metrics[key] = response[key]
            self._last_metrics = metrics or None
            return response
        finally:
            self._set_state(RuntimeState.READY)
            _NATIVE_ENGINE_LOCK.release()

    def run(self, prompt: str, executor: ToolExecutor, *, tools_enabled: bool = True) -> dict:
        self.wait_ready()
        if not _NATIVE_ENGINE_LOCK.acquire(timeout=self.settings.request_timeout):
            raise EngineBusyError("native engine is busy; retry shortly")
        self._set_state(RuntimeState.BUSY)
        if self._pool is None:
            import concurrent.futures

            self._pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="needle3-native"
            )
        started = time.perf_counter()
        try:
            future = self._pool.submit(self._run_locked, prompt, executor, tools_enabled)
        except Exception as exc:
            self._set_state(RuntimeState.READY)
            _NATIVE_ENGINE_LOCK.release()
            raise EngineUnavailableError(f"could not schedule native inference: {exc}") from exc
        try:
            response = future.result(timeout=self.settings.request_timeout)
        except TimeoutError:
            # The worker still owns the native lock; keep BUSY rather than
            # reinitializing the engine underneath a running inference call.
            self._set_state(RuntimeState.BUSY, "native inference timed out; worker still running")
            raise RequestTimeoutError(
                f"native inference exceeded {self.settings.request_timeout:.0f}s"
            ) from None
        except Exception as exc:
            self._set_state(RuntimeState.DEGRADED, f"native inference failed: {exc}")
            raise EngineUnavailableError(f"native inference failed: {exc}") from exc
        finally:
            self._last_latency_ms = (time.perf_counter() - started) * 1000.0
        return response

    def close(self) -> None:
        with self._state_lock:
            if self._state == RuntimeState.CLOSED:
                return
            self._state = RuntimeState.SHUTTING_DOWN
        if self._agent is not None:
            try:
                self._agent.close()
            except Exception:
                pass
            self._agent = None
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None
        self._set_state(RuntimeState.CLOSED)

    def status(self) -> dict:
        needle_version = None
        if self._needle is not None:
            needle_version = getattr(self._needle, "__version__", None)
        return {
            "mode": self.mode,
            "state": self.state.value,
            "native_available": self.state in {
                RuntimeState.READY,
                RuntimeState.BUSY,
            },
            "package_version": needle_version,
            "generation": self.settings.model_generation,
            "model_weights": self.settings.model_weights,
            "initialized_at": self._started_at,
            "last_error": self._last_error,
            "last_latency_ms": round(self._last_latency_ms, 2) if self._last_latency_ms else None,
            "metrics": self._last_metrics,
        }


class SimulationRuntime(BaseRuntime):
    mode = "simulation"

    def __init__(self, settings: Settings, registry: ToolRegistry):
        self.settings = settings
        self.registry = registry
        self._state = RuntimeState.READY
        self._lock = threading.Lock()

    @property
    def state(self) -> RuntimeState:
        return self._state

    def initialize(self) -> bool:
        self._state = RuntimeState.READY
        return True

    def run(self, prompt: str, executor: ToolExecutor, *, tools_enabled: bool = True) -> dict:
        if not self.settings.allow_simulation:
            raise EngineUnavailableError("simulation mode is disabled")
        with self._lock:
            self._state = RuntimeState.BUSY
            try:
                if tools_enabled:
                    return simulate(prompt, executor, self.registry)
                return {
                    "type": "none",
                    "success": True,
                    "error": None,
                    "function_calls": [],
                    "suppressed_calls": [],
                    "reasoning": "Simulation mode: tools disabled for this request.",
                    "confidence": None,
                    "results": [],
                    "mode": "simulation",
                }
            finally:
                self._state = RuntimeState.READY

    def close(self) -> None:
        self._state = RuntimeState.CLOSED

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "state": self._state.value,
            "native_available": False,
            "simulated": True,
            "package_version": None,
            "generation": None,
            "model_weights": None,
            "initialized_at": None,
            "last_error": None,
            "last_latency_ms": None,
            "metrics": None,
        }


class UnavailableRuntime(BaseRuntime):
    mode = "unavailable"

    def __init__(self, message: str = "native engine unavailable"):
        self.message = message
        self._state = RuntimeState.UNAVAILABLE

    @property
    def state(self) -> RuntimeState:
        return self._state

    def initialize(self) -> bool:
        return False

    def run(self, prompt: str, executor: ToolExecutor, *, tools_enabled: bool = True) -> dict:
        raise EngineUnavailableError(self.message)

    def close(self) -> None:
        self._state = RuntimeState.CLOSED

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "state": self._state.value,
            "native_available": False,
            "simulated": False,
            "package_version": None,
            "generation": None,
            "model_weights": None,
            "initialized_at": None,
            "last_error": self.message,
            "last_latency_ms": None,
            "metrics": None,
        }


def build_runtime(settings: Settings, registry: ToolRegistry) -> BaseRuntime:
    if settings.mode == "simulation":
        if not settings.allow_simulation:
            raise EngineUnavailableError("simulation mode is disabled")
        return SimulationRuntime(settings, registry)
    return NativeRuntime(settings, registry)


def build_simulation_runtime(settings: Settings, registry: ToolRegistry) -> SimulationRuntime:
    return SimulationRuntime(settings, registry)

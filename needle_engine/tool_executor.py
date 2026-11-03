"""Validated, timeout-bounded tool execution with per-request tracing."""

from __future__ import annotations

import concurrent.futures as _futures
import contextvars
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .exceptions import (
    ToolExecutionError,
    ToolLimitError,
    ToolNotFoundError,
    ToolValidationError,
)
from .schemas import validate_arguments
from .tool_registry import ToolRegistry, ToolSpec

_ACTIVE_EXECUTOR: contextvars.ContextVar["ToolExecutor | None"] = contextvars.ContextVar(
    "needle3_active_executor", default=None
)

_POOL = _futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="needle3-tool")


def active_executor() -> "ToolExecutor | None":
    return _ACTIVE_EXECUTOR.get()


def bind_executor(executor: "ToolExecutor") -> contextvars.Token:
    return _ACTIVE_EXECUTOR.set(executor)


def unbind_executor(token: contextvars.Token) -> None:
    _ACTIVE_EXECUTOR.reset(token)


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    status: str = "ok"

    def function_call(self) -> dict:
        return {"name": self.name, "arguments": dict(self.arguments)}

    def public(self) -> dict:
        return {
            "name": self.name,
            "arguments": dict(self.arguments),
            "ok": self.error is None,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class ToolTrace:
    records: list[ToolCallRecord] = field(default_factory=list)

    def function_calls(self) -> list[dict]:
        return [record.function_call() for record in self.records]

    def results(self) -> list[dict]:
        return [record.public() for record in self.records]

    def errors(self) -> list[str]:
        return [record.error for record in self.records if record.error]


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_calls: int = 8,
        default_timeout: float = 10.0,
    ) -> None:
        self.registry = registry
        self.max_calls = max(1, int(max_calls))
        self.default_timeout = max(0.1, float(default_timeout))
        self._lock = threading.Lock()
        self._count = 0
        self.trace = ToolTrace()

    @property
    def calls_used(self) -> int:
        with self._lock:
            return self._count

    def _reserve_call(self) -> None:
        with self._lock:
            if self._count >= self.max_calls:
                raise ToolLimitError(
                    f"tool call limit reached ({self.max_calls}); refusing further calls"
                )
            self._count += 1

    def execute(self, name: str, arguments: dict | None = None) -> ToolCallRecord:
        spec: ToolSpec = self.registry.get(name)
        args = dict(arguments or {})
        issues = validate_arguments(spec.parameters, args)
        if issues:
            message = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            record = ToolCallRecord(name=name, arguments=args, error=message, status="validation_error")
            self.trace.records.append(record)
            raise ToolValidationError(message)

        self._reserve_call()
        timeout = spec.timeout or self.default_timeout
        started = time.perf_counter()
        try:
            future = _POOL.submit(spec.implementation, **args)
            output = future.result(timeout=timeout)
        except _futures.TimeoutError:
            elapsed = (time.perf_counter() - started) * 1000.0
            message = f"tool {name} timed out after {timeout:.1f}s"
            record = ToolCallRecord(
                name=name,
                arguments=args,
                error=message,
                latency_ms=elapsed,
                status="timeout",
            )
            self.trace.records.append(record)
            raise ToolExecutionError(message) from None
        except ToolValidationError:
            raise
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            message = f"tool {name} failed: {exc}"
            record = ToolCallRecord(
                name=name,
                arguments=args,
                error=message,
                latency_ms=elapsed,
                status="error",
            )
            self.trace.records.append(record)
            raise ToolExecutionError(message) from exc

        elapsed = (time.perf_counter() - started) * 1000.0
        record = ToolCallRecord(
            name=name,
            arguments=args,
            output=output,
            latency_ms=elapsed,
            status="ok",
        )
        self.trace.records.append(record)
        return record

    @contextmanager
    def bind(self) -> Iterator["ToolExecutor"]:
        token = bind_executor(self)
        try:
            yield self
        finally:
            unbind_executor(token)


def execute_planned_calls(
    executor: ToolExecutor, calls: list[dict]
) -> tuple[list[dict], list[dict], list[str]]:
    """Execute planned calls, continuing past individual failures.

    Returns (function_calls, results, errors). Used by the simulation runtime.
    """
    function_calls: list[dict] = []
    results: list[dict] = []
    errors: list[str] = []
    for call in calls:
        name = str(call.get("name", ""))
        arguments = call.get("arguments") or {}
        function_calls.append({"name": name, "arguments": dict(arguments)})
        try:
            record = executor.execute(name, arguments)
            results.append(record.public())
        except (ToolNotFoundError, ToolValidationError, ToolExecutionError, ToolLimitError) as exc:
            errors.append(exc.message)
            results.append(
                {
                    "name": name,
                    "arguments": dict(arguments),
                    "ok": False,
                    "status": getattr(exc, "code", "error"),
                    "output": None,
                    "error": exc.message,
                    "latency_ms": 0.0,
                }
            )
    return function_calls, results, errors

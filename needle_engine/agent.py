"""Request orchestration: sessions, runtime selection, tracing, and envelopes."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from . import __version__
from .configuration import Settings
from .exceptions import EngineUnavailableError, ToolValidationError
from .runtime import (
    BaseRuntime,
    RuntimeState,
    SimulationRuntime,
)
from .sessions import SessionManager
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry

LOGGER = logging.getLogger("needle3.agent")

_VALID_MODES = {"auto", "native", "simulation"}


class NeedleAgent:
    def __init__(
        self,
        settings: Settings,
        runtime: BaseRuntime,
        simulation_runtime: SimulationRuntime,
        registry: ToolRegistry,
        sessions: SessionManager,
        *,
        started_at: float | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.simulation_runtime = simulation_runtime
        self.registry = registry
        self.sessions = sessions
        self.started_at = started_at or time.time()

    def process(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        mode: str = "auto",
        tools_enabled: bool = True,
    ) -> dict:
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ToolValidationError("prompt must not be empty")
        if len(prompt) > self.settings.max_prompt_chars:
            raise ToolValidationError(
                f"prompt exceeds {self.settings.max_prompt_chars} characters"
            )
        mode = (mode or "auto").strip().lower()
        if mode not in _VALID_MODES:
            raise ToolValidationError("mode must be auto, native, or simulation")
        if not isinstance(tools_enabled, bool):
            raise ToolValidationError("tools_enabled must be a boolean")

        selected = self._select_runtime(mode)
        session = self.sessions.get_or_create(session_id)
        executor = ToolExecutor(
            self.registry,
            max_calls=self.settings.max_tool_calls,
            default_timeout=min(10.0, self.settings.request_timeout),
        )

        with session.lock:
            context = self.sessions.context_prompt(session.id)
            runtime_prompt = (
                f"{context}\n\nCurrent request: {prompt}" if context else prompt
            )
            raw = selected.run(runtime_prompt, executor, tools_enabled=tools_enabled)
            latency_ms = (time.perf_counter() - started) * 1000.0

            response = self._envelope(
                raw=raw,
                executor=executor,
                prompt=prompt,
                session_id=session.id,
                mode=selected.mode,
                tools_enabled=tools_enabled,
                request_id=request_id,
                latency_ms=latency_ms,
            )
            self.sessions.append(
                session.id,
                "user",
                prompt,
            )
            self.sessions.append(
                session.id,
                "assistant",
                response.get("response") or "",
                function_calls=response.get("function_calls") or [],
                results=response.get("results") or [],
                mode=response.get("mode"),
            )
            LOGGER.info(
                "request %s mode=%s tools=%d latency=%.1fms success=%s",
                request_id,
                response.get("mode"),
                len(response.get("function_calls") or []),
                latency_ms,
                response.get("success"),
            )
            return response

    def _select_runtime(self, mode: str) -> BaseRuntime:
        if mode == "simulation":
            if not self.settings.allow_simulation:
                raise EngineUnavailableError("simulation mode is disabled")
            return self.simulation_runtime
        if mode == "native":
            if self.runtime.mode != "native":
                raise EngineUnavailableError(
                    "native mode is not configured; set NEEDLE_MODE=auto or native"
                )
            return self.runtime
        # auto: use the configured runtime. If native is unavailable this raises
        # EngineUnavailableError instead of silently switching to simulation.
        return self.runtime

    def _envelope(
        self,
        *,
        raw: dict,
        executor: ToolExecutor,
        prompt: str,
        session_id: str,
        mode: str,
        tools_enabled: bool,
        request_id: str,
        latency_ms: float,
    ) -> dict:
        trace = executor.trace
        function_calls = trace.function_calls()
        if not function_calls:
            function_calls = list(raw.get("function_calls") or [])
        results = trace.results()
        if not results:
            raw_results = raw.get("results") or []
            results = [
                {
                    "name": (function_calls[index]["name"] if index < len(function_calls) else None),
                    "arguments": (function_calls[index].get("arguments", {}) if index < len(function_calls) else {}),
                    "ok": not (isinstance(item, dict) and "error" in item),
                    "status": "error" if isinstance(item, dict) and "error" in item else "ok",
                    "output": item,
                    "error": item.get("error") if isinstance(item, dict) and "error" in item else None,
                    "latency_ms": 0.0,
                }
                for index, item in enumerate(raw_results)
            ]

        errors = trace.errors()
        result_errors = [result["error"] for result in results if result.get("error")]
        all_errors = list(dict.fromkeys(errors + result_errors))
        success = bool(raw.get("success", True)) and not all_errors
        response_text = self._response_text(raw, results)
        runtime_status = self.runtime.status() if mode == "native" else self.simulation_runtime.status()

        return {
            "success": success,
            "session_id": session_id,
            "request_id": request_id,
            "response": response_text,
            "function_calls": function_calls,
            "suppressed_calls": list(raw.get("suppressed_calls") or []),
            "results": results,
            "reasoning": raw.get("reasoning"),
            "confidence": raw.get("confidence"),
            "mode": mode,
            "simulated": mode == "simulation",
            "tools_enabled": tools_enabled,
            "latency_ms": round(latency_ms, 2),
            "error": raw.get("error") or ("; ".join(all_errors) if all_errors else None),
            "error_code": raw.get("error_code") or ("tool_error" if all_errors else None),
            "errors": all_errors,
            "model": {
                "generation": runtime_status.get("generation"),
                "package_version": runtime_status.get("package_version"),
                "weights": runtime_status.get("model_weights"),
            },
            "metrics": {
                key: raw[key]
                for key in ("prefill_tps", "decode_tps", "peak_ram_mb")
                if key in raw
            }
            or None,
            "app_version": __version__,
        }

    @staticmethod
    def _summarize_output(name: str | None, output: Any) -> str:
        if not isinstance(output, dict):
            return str(output)
        if name == "get_current_time":
            return f"Current time: {output.get('display')} ({output.get('timezone')})"
        if name == "control_device":
            text = f"{output.get('device')}: {output.get('action')}"
            if output.get("value") is not None:
                text += f" {output['value']}%"
            if output.get("simulated"):
                text += " (simulated device)"
            return text
        if name == "parse_invoice_text":
            bits = [str(output.get("merchant") or "Invoice")]
            if output.get("amount") is not None:
                bits.append(f"{output.get('currency') or ''} {output['amount']}".strip())
            if output.get("due_date"):
                bits.append(f"due {output['due_date']}")
            return " · ".join(bits)
        if name == "extract_structured_data":
            fields = output.get("fields") or {}
            if not isinstance(fields, dict):
                return json.dumps(output, ensure_ascii=False)
            return " · ".join(f"{key}: {len(value) if isinstance(value, list) else value}" for key, value in fields.items()) or "No fields found"
        if name == "get_system_info":
            return (
                f"{output.get('system')} {output.get('release')} · "
                f"Python {output.get('python_version')} · {output.get('cpu_count')} CPUs"
            )
        if name == "get_current_directory":
            return f"Working directory: {output.get('cwd')}"
        if name == "list_directory":
            entries = output.get("entries") or []
            suffix = " (truncated)" if output.get("truncated") else ""
            return f"{len(entries)} entries in {output.get('path')}{suffix}"
        if name == "search_files":
            matches = output.get("results") or []
            return f"{len(matches)} match(es) for “{output.get('query')}”"
        return json.dumps(output, ensure_ascii=False)

    @staticmethod
    def _response_text(raw: dict, results: list[dict]) -> str:
        for key in ("response", "text", "answer"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if not results:
            return ""
        lines = []
        for result in results:
            output = result.get("output")
            if output is None:
                continue
            name = result.get("name")
            lines.append(f"{name or 'tool'}: {NeedleAgent._summarize_output(name, output)}")
        return "\n".join(lines)

    def health(self) -> dict:
        runtime_status = self.runtime.status()
        state = runtime_status.get("state")
        ready = state == RuntimeState.READY.value
        if ready:
            app_status = "ok"
        elif state in {RuntimeState.UNAVAILABLE.value, RuntimeState.DEGRADED.value}:
            app_status = "degraded"
        else:
            app_status = "starting"
        return {
            "status": app_status,
            "app_version": __version__,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "engine": runtime_status,
            "native_engine": bool(runtime_status.get("native_available")),
            "mode": self.runtime.mode,
            "ready": ready,
            "tools": self.registry.names(),
            "sessions": self.sessions.count(),
        }

    def ready(self) -> bool:
        return self.runtime.state == RuntimeState.READY

    def status(self) -> dict:
        return {
            "app_version": __version__,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "engine": self.runtime.status(),
            "simulation": self.simulation_runtime.status(),
            "capabilities": {
                "native_inference": (
                    self.runtime.mode == "native"
                    and self.runtime.state in {RuntimeState.READY, RuntimeState.BUSY}
                ),
                "native_mode": self.runtime.mode == "native",
                "simulation": self.settings.allow_simulation,
                "sessions": True,
                "tools": True,
                "streaming": False,
                "shell": False,
                "file_root": str(self.settings.file_root),
            },
            "tools": self.registry.schemas(),
            "sessions": self.sessions.count(),
            "limits": {
                "max_tool_calls": self.settings.max_tool_calls,
                "request_timeout_seconds": self.settings.request_timeout,
                "max_prompt_chars": self.settings.max_prompt_chars,
                "max_request_bytes": self.settings.max_request_bytes,
            },
        }

    def reset_session(self, session_id: str) -> dict:
        session = self.sessions.reset(session_id)
        return session.public()

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.simulation_runtime.close()

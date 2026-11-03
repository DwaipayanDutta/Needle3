"""Flask application factory and HTTP API for Needle3."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import __version__
from .agent import NeedleAgent
from .configuration import Settings, configure_logging
from .exceptions import Needle3Error
from .runtime import (
    RuntimeState,
    build_runtime,
    build_simulation_runtime,
)
from .schemas import validate_tool_schema
from .sessions import SessionManager
from .tool_registry import ToolRegistry, default_registry

LOGGER = logging.getLogger("needle3.api")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _json_error(
    message: str,
    status: int,
    *,
    error_code: str = "request_error",
    request_id: str | None = None,
    session_id: str | None = None,
    mode: str | None = None,
) -> tuple[Any, int]:
    payload = {
        "success": False,
        "session_id": session_id,
        "request_id": request_id,
        "response": "",
        "function_calls": [],
        "suppressed_calls": [],
        "results": [],
        "reasoning": None,
        "confidence": None,
        "mode": mode,
        "simulated": mode == "simulation",
        "tools_enabled": True,
        "latency_ms": 0.0,
        "error": message,
        "error_code": error_code,
        "errors": [message],
        "model": None,
        "metrics": None,
        "app_version": __version__,
    }
    return jsonify(payload), status


def create_app(
    settings: Settings | None = None,
    *,
    runtime: Any | None = None,
    simulation_runtime: Any | None = None,
    registry: ToolRegistry | None = None,
    sessions: SessionManager | None = None,
    agent: NeedleAgent | None = None,
    start_initialization: bool | None = None,
) -> Flask:
    settings = settings or Settings.from_env()
    configure_logging(settings)

    registry = registry or default_registry(settings)
    sessions = sessions or SessionManager(
        ttl_seconds=settings.session_timeout,
        max_sessions=settings.max_sessions,
        max_history=settings.max_history,
        context_turns=settings.session_context_turns,
    )
    simulation_runtime = simulation_runtime or build_simulation_runtime(settings, registry)
    runtime = runtime or build_runtime(settings, registry)
    agent = agent or NeedleAgent(
        settings,
        runtime,
        simulation_runtime,
        registry,
        sessions,
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_request_bytes
    app.config["NEEDLE3_SETTINGS"] = settings
    app.json.sort_keys = False
    app.extensions["needle3"] = {
        "settings": settings,
        "runtime": runtime,
        "simulation_runtime": simulation_runtime,
        "registry": registry,
        "sessions": sessions,
        "agent": agent,
        "started_at": agent.started_at,
    }

    should_initialize = settings.eager_init if start_initialization is None else start_initialization
    if should_initialize and runtime.mode == "native" and runtime.state == RuntimeState.UNINITIALIZED:
        init_thread = threading.Thread(
            target=runtime.initialize,
            name="needle3-init",
            daemon=True,
        )
        init_thread.start()

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def _security_and_cors(response):
        # CORS is disabled by default. Operators must name allowed origins.
        origin = request.headers.get("Origin")
        allowed = settings.cors_origins
        if origin and ("*" in allowed or origin.rstrip("/") in allowed):
            response.headers["Access-Control-Allow-Origin"] = "*" if "*" in allowed else origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'",
        )
        if request.path.startswith("/api") or request.path in {"/chat", "/health", "/ready"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response

    def _serve_ui(filename: str):
        path = _REPO_ROOT / filename
        if not path.is_file():
            return _json_error(f"{filename} is missing from the repository", 404)
        response = send_from_directory(_REPO_ROOT, filename)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return _serve_ui("sandbox.html")

    @app.get("/sandbox")
    def sandbox_page():
        return _serve_ui("sandbox.html")

    @app.get("/classic")
    def classic_page():
        return _serve_ui("classic.html")

    @app.get("/health")
    def health():
        return jsonify(agent.health()), 200

    @app.get("/ready")
    def ready():
        healthy = agent.health()
        status = 200 if agent.ready() else 503
        return jsonify({"ready": healthy["ready"], "engine": healthy["engine"]}), status

    @app.get("/api/status")
    def api_status():
        payload = agent.status()
        payload["config"] = settings.public_dict()
        return jsonify(payload), 200

    @app.post("/chat")
    def chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_error(
                "request body must be a JSON object",
                400,
                error_code="invalid_json",
                request_id=g.request_id,
            )
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _json_error(
                "prompt must be a non-empty string",
                400,
                error_code="invalid_prompt",
                request_id=g.request_id,
            )
        session_value = payload.get("session_id")
        if session_value is not None:
            if not isinstance(session_value, str) or not _SESSION_ID_RE.match(session_value):
                return _json_error(
                    "session_id must match [A-Za-z0-9_-]{1,64}",
                    400,
                    error_code="invalid_session",
                    request_id=g.request_id,
                )
        mode = payload.get("mode", "auto")
        if not isinstance(mode, str) or mode not in {"auto", "native", "simulation"}:
            return _json_error(
                "mode must be auto, native, or simulation",
                400,
                error_code="invalid_mode",
                request_id=g.request_id,
            )
        tools_enabled = payload.get("tools_enabled", True)
        if not isinstance(tools_enabled, bool):
            return _json_error(
                "tools_enabled must be a boolean",
                400,
                error_code="invalid_tools_flag",
                request_id=g.request_id,
            )

        try:
            result = agent.process(
                prompt,
                session_id=session_value,
                mode=mode,
                tools_enabled=tools_enabled,
            )
        except Needle3Error as exc:
            LOGGER.warning("request %s failed: %s", g.request_id, exc.message)
            return _json_error(
                exc.message,
                exc.status_code,
                error_code=exc.code,
                request_id=g.request_id,
                session_id=session_value,
                mode=mode,
            )
        except ValueError as exc:
            return _json_error(
                str(exc),
                400,
                error_code="invalid_request",
                request_id=g.request_id,
                session_id=session_value,
                mode=mode,
            )
        except Exception:
            LOGGER.exception("request %s failed unexpectedly", g.request_id)
            return _json_error(
                "internal server error",
                500,
                error_code="internal_error",
                request_id=g.request_id,
                session_id=session_value,
                mode=mode,
            )

        response = jsonify(result)
        response.headers["X-Request-ID"] = result.get("request_id") or g.request_id
        return response, 200

    @app.post("/chat/reset")
    def chat_reset():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            return _json_error(
                "session_id must match [A-Za-z0-9_-]{1,64}",
                400,
                error_code="invalid_session",
                request_id=g.request_id,
            )
        try:
            session = agent.reset_session(session_id)
        except Needle3Error as exc:
            return _json_error(
                exc.message,
                exc.status_code,
                error_code=exc.code,
                request_id=g.request_id,
                session_id=session_id,
            )
        return jsonify({"success": True, "session": session}), 200

    @app.post("/sessions")
    def create_session():
        payload = request.get_json(silent=True) or {}
        requested = payload.get("session_id")
        if requested is not None and not isinstance(requested, str):
            return _json_error(
                "session_id must be a string",
                400,
                error_code="invalid_session",
                request_id=g.request_id,
            )
        try:
            session = sessions.create(requested)
        except ValueError as exc:
            return _json_error(
                str(exc),
                400,
                error_code="invalid_session",
                request_id=g.request_id,
            )
        except Needle3Error as exc:
            return _json_error(
                exc.message,
                exc.status_code,
                error_code=exc.code,
                request_id=g.request_id,
            )
        return jsonify({"success": True, "session": session.public()}), 201

    @app.get("/sessions/<session_id>")
    def get_session(session_id: str):
        if not _SESSION_ID_RE.match(session_id):
            return _json_error(
                "invalid session id",
                400,
                error_code="invalid_session",
                request_id=g.request_id,
            )
        try:
            payload = sessions.public(session_id)
        except Needle3Error as exc:
            return _json_error(
                exc.message,
                exc.status_code,
                error_code=exc.code,
                request_id=g.request_id,
                session_id=session_id,
            )
        return jsonify({"success": True, "session": payload}), 200

    @app.delete("/sessions/<session_id>")
    def delete_session(session_id: str):
        if not _SESSION_ID_RE.match(session_id):
            return _json_error(
                "invalid session id",
                400,
                error_code="invalid_session",
                request_id=g.request_id,
            )
        try:
            sessions.delete(session_id)
        except Needle3Error as exc:
            return _json_error(
                exc.message,
                exc.status_code,
                error_code=exc.code,
                request_id=g.request_id,
                session_id=session_id,
            )
        return jsonify({"success": True, "deleted": session_id}), 200

    @app.get("/tools")
    def tools():
        return jsonify({"success": True, "tools": registry.schemas()}), 200

    @app.post("/tools/validate")
    def validate_tools():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            return _json_error(
                "body must contain a tools array",
                400,
                error_code="invalid_tools",
                request_id=g.request_id,
            )
        errors: list[str] = []
        for index, tool in enumerate(payload["tools"]):
            errors.extend(validate_tool_schema(tool, index))
        if errors:
            return jsonify({"success": False, "valid": False, "errors": errors}), 400
        return jsonify({"success": True, "valid": True, "errors": [], "count": len(payload["tools"])}), 200

    @app.errorhandler(413)
    def request_too_large(_error):
        return _json_error(
            f"request body exceeds {settings.max_request_bytes} bytes",
            413,
            error_code="request_too_large",
            request_id=getattr(g, "request_id", None),
        )

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api") or request.path in {"/chat", "/health", "/ready"}:
            return _json_error("not found", 404, error_code="not_found", request_id=getattr(g, "request_id", None))
        return error

    @app.errorhandler(405)
    def method_not_allowed(error):
        return _json_error(
            "method not allowed",
            405,
            error_code="method_not_allowed",
            request_id=getattr(g, "request_id", None),
        )

    @app.errorhandler(Exception)
    def unhandled(error):
        if isinstance(error, HTTPException):
            return error
        LOGGER.exception("unhandled error on %s %s", request.method, request.path)
        if settings.debug:
            raise error
        return _json_error(
            "internal server error",
            500,
            error_code="internal_error",
            request_id=getattr(g, "request_id", None),
        )

    return app

"""Exception hierarchy for Needle3."""

from __future__ import annotations


class Needle3Error(Exception):
    """Base class for expected application errors."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error": self.message,
            "error_code": self.code,
            "details": self.details,
        }


class ConfigurationError(Needle3Error):
    status_code = 500
    code = "configuration_error"


class EngineUnavailableError(Needle3Error):
    status_code = 503
    code = "engine_unavailable"


class EngineInitializationError(EngineUnavailableError):
    code = "engine_initialization_failed"


class EngineBusyError(Needle3Error):
    status_code = 503
    code = "engine_busy"


class RequestTimeoutError(Needle3Error):
    status_code = 504
    code = "request_timeout"


class ToolNotFoundError(Needle3Error):
    status_code = 400
    code = "tool_not_found"


class ToolValidationError(Needle3Error):
    status_code = 400
    code = "tool_validation_error"


class ToolExecutionError(Needle3Error):
    status_code = 500
    code = "tool_execution_error"


class ToolLimitError(Needle3Error):
    status_code = 400
    code = "tool_limit_exceeded"


class SessionNotFoundError(Needle3Error):
    status_code = 404
    code = "session_not_found"


class SessionLimitError(Needle3Error):
    status_code = 429
    code = "session_limit_exceeded"

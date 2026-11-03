"""Needle3 engine: native runtime, safe tools, sessions, and Flask API."""

__version__ = "1.0.0"

from .configuration import Settings, load_env_file  # noqa: F401
from .exceptions import (  # noqa: F401
    ConfigurationError,
    EngineBusyError,
    EngineInitializationError,
    EngineUnavailableError,
    Needle3Error,
    RequestTimeoutError,
    SessionNotFoundError,
    ToolExecutionError,
    ToolLimitError,
    ToolNotFoundError,
    ToolValidationError,
)

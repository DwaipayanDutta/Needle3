"""Configuration loading and validation for Needle3."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ConfigurationError

LOGGER = logging.getLogger("needle3.config")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def load_env_file(path: str | os.PathLike[str] = ".env") -> None:
    """Load a simple KEY=VALUE file without overriding real environment variables."""
    env_path = Path(path)
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        LOGGER.warning("Could not read %s: %s", env_path, exc)
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None else value


def _as_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigurationError(f"{name} must be one of: true/false, 1/0, yes/no, on/off")


def _as_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _as_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _as_origins(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    values = tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    if "*" in values:
        return ("*",)
    return values


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration.

    Defaults are local-only and safe: loopback binding, same-origin CORS, no shell.
    """

    host: str = "127.0.0.1"
    port: int = 5000
    open_browser: bool = True
    mode: str = "auto"
    telemetry: bool = True
    max_tool_calls: int = 8
    request_timeout: float = 30.0
    session_timeout: int = 3600
    enable_shell: bool = False
    log_level: str = "INFO"
    max_prompt_chars: int = 4000
    max_request_bytes: int = 65536
    file_root: Path = field(default_factory=Path.cwd)
    cors_origins: tuple[str, ...] = ()
    session_context_turns: int = 0
    eager_init: bool = True
    model_weights: str | None = None
    model_generation: int = 3
    debug: bool = False
    allow_simulation: bool = True
    max_sessions: int = 100
    max_history: int = 40
    max_new_tokens: int = 512
    pid_file: Path = field(default_factory=lambda: Path(".needle3") / "needle3.pid")

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] = ".env") -> "Settings":
        load_env_file(env_file)

        mode = (_env("NEEDLE_MODE", "auto") or "auto").strip().lower()
        if mode not in {"auto", "native", "simulation"}:
            raise ConfigurationError("NEEDLE_MODE must be auto, native, or simulation")

        host = (_env("FLASK_HOST", "127.0.0.1") or "127.0.0.1").strip()
        if not host:
            raise ConfigurationError("FLASK_HOST must not be empty")

        port = _as_int("FLASK_PORT", _as_int("PORT", 5000, 1, 65535), 1, 65535)
        log_level = (_env("NEEDLE_LOG_LEVEL", "INFO") or "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("NEEDLE_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

        file_root = Path(_env("NEEDLE_FILE_ROOT", str(Path.cwd())) or Path.cwd()).expanduser()
        try:
            file_root = file_root.resolve()
        except OSError as exc:
            raise ConfigurationError(f"NEEDLE_FILE_ROOT is not a usable path: {exc}") from exc
        if not file_root.is_dir():
            raise ConfigurationError(f"NEEDLE_FILE_ROOT is not a directory: {file_root}")

        generation = _as_int("NEEDLE_GENERATION", 3, 2, 3)
        weights = (_env("NEEDLE_MODEL", "") or "").strip() or None
        if weights:
            weights_path = Path(weights).expanduser()
            if not weights_path.is_file():
                raise ConfigurationError(f"NEEDLE_MODEL does not exist: {weights_path}")
            weights = str(weights_path.resolve())

        settings = cls(
            host=host,
            port=port,
            open_browser=_as_bool("NEEDLE_OPEN_BROWSER", True),
            mode=mode,
            telemetry=_as_bool("NEEDLE_TELEMETRY", True),
            max_tool_calls=_as_int("NEEDLE_MAX_TOOL_CALLS", 8, 1, 32),
            request_timeout=_as_float("NEEDLE_REQUEST_TIMEOUT", 30.0, 1.0, 300.0),
            session_timeout=_as_int("NEEDLE_SESSION_TIMEOUT", 3600, 30, 604800),
            enable_shell=_as_bool("NEEDLE_ENABLE_SHELL", False),
            log_level=log_level,
            max_prompt_chars=_as_int("NEEDLE_MAX_PROMPT_CHARS", 4000, 1, 32000),
            max_request_bytes=_as_int("NEEDLE_MAX_REQUEST_BYTES", 65536, 1024, 1048576),
            file_root=file_root,
            cors_origins=_as_origins("NEEDLE_CORS_ORIGINS"),
            session_context_turns=_as_int("NEEDLE_SESSION_CONTEXT_TURNS", 0, 0, 20),
            eager_init=_as_bool("NEEDLE_EAGER_INIT", True),
            model_weights=weights,
            model_generation=generation,
            debug=_as_bool("NEEDLE_DEBUG", False),
            allow_simulation=_as_bool("NEEDLE_ALLOW_SIMULATION", True),
            max_sessions=_as_int("NEEDLE_MAX_SESSIONS", 100, 1, 10000),
            max_history=_as_int("NEEDLE_MAX_HISTORY", 40, 2, 500),
            max_new_tokens=_as_int("NEEDLE_MAX_NEW_TOKENS", 512, 16, 4096),
            pid_file=Path(_env("NEEDLE_PID_FILE", ".needle3/needle3.pid") or ".needle3/needle3.pid"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.enable_shell:
            raise ConfigurationError(
                "NEEDLE_ENABLE_SHELL is not supported: this build deliberately exposes no "
                "arbitrary shell tool. Use the terminal client for local shell work."
            )
        if self.mode == "simulation" and not self.allow_simulation:
            raise ConfigurationError("NEEDLE_MODE=simulation requires NEEDLE_ALLOW_SIMULATION=true")
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            LOGGER.warning(
                "Binding to %s exposes the API beyond this machine. Use NEEDLE_CORS_ORIGINS "
                "and network controls deliberately.",
                self.host,
            )

    def apply_environment(self) -> None:
        """Configure third-party telemetry before importing the native package."""
        if not self.telemetry:
            os.environ["NEEDLE_TELEMETRY"] = "0"
            os.environ["DO_NOT_TRACK"] = "1"

    def public_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "mode": self.mode,
            "telemetry": self.telemetry,
            "max_tool_calls": self.max_tool_calls,
            "request_timeout_seconds": self.request_timeout,
            "session_timeout_seconds": self.session_timeout,
            "max_prompt_chars": self.max_prompt_chars,
            "max_request_bytes": self.max_request_bytes,
            "cors_origins": list(self.cors_origins),
            "session_context_turns": self.session_context_turns,
            "allow_simulation": self.allow_simulation,
            "debug": self.debug,
        }


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

"""Safe, explicitly registered tools for Needle3."""

from __future__ import annotations

import datetime as _dt
import os
import platform
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .configuration import Settings
from .exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from .schemas import validate_tool_schema


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    implementation: Callable[..., Any]
    triggers: tuple[str, ...] = ()
    category: str = "safe"
    destructive: bool = False
    timeout: float = 10.0

    def native_schema(self) -> dict:
        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if self.triggers:
            schema["triggers"] = list(self.triggers)
        return schema

    def public_schema(self) -> dict:
        schema = self.native_schema()
        schema["category"] = self.category
        schema["destructive"] = self.destructive
        schema["timeout_seconds"] = self.timeout
        return schema


class DeviceStore:
    """In-memory smart-home simulator.

    This is the only device integration shipped by default. It never touches
    real hardware, a hub, or the network; callers must opt into a real
    integration before claiming production device control.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}

    def apply(self, device: str, action: str, value: int | None = None) -> dict:
        key = device.strip().lower()
        if not key:
            raise ToolExecutionError("device must not be empty")
        if len(key) > 80:
            raise ToolExecutionError("device name is too long")

        with self._lock:
            state = self._devices.setdefault(key, {"power": "off", "level": 50, "locked": False})
            if action in {"on", "off"}:
                state["power"] = action
            elif action == "toggle":
                state["power"] = "off" if state["power"] == "on" else "on"
            elif action in {"dim", "brighten", "set"}:
                if value is None:
                    if action == "set":
                        raise ToolExecutionError("value is required for the 'set' action")
                    value = 30 if action == "dim" else 80
                state["level"] = int(value)
                state["power"] = "on" if state["level"] > 0 else "off"
            elif action == "lock":
                state["locked"] = True
            elif action == "unlock":
                state["locked"] = False
            else:
                raise ToolExecutionError(f"unsupported action: {action}")
            snapshot = dict(state)
            snapshot.update({"device": device, "action": action, "simulated": True})
            return snapshot


_DEVICES = DeviceStore()

_TIMEZONE_OFFSETS = {
    "utc": 0.0,
    "gmt": 0.0,
    "kolkata": 5.5,
    "india": 5.5,
    "mumbai": 5.5,
    "delhi": 5.5,
    "bengaluru": 5.5,
    "bangalore": 5.5,
    "chennai": 5.5,
    "hyderabad": 5.5,
    "pune": 5.5,
    "asia/kolkata": 5.5,
    "asia/calcutta": 5.5,
    "new york": -5.0,
    "america/new_york": -5.0,
    "los angeles": -8.0,
    "america/los_angeles": -8.0,
    "london": 0.0,
    "europe/london": 0.0,
    "paris": 1.0,
    "europe/paris": 1.0,
    "berlin": 1.0,
    "europe/berlin": 1.0,
    "dubai": 4.0,
    "asia/dubai": 4.0,
    "singapore": 8.0,
    "asia/singapore": 8.0,
    "tokyo": 9.0,
    "asia/tokyo": 9.0,
    "sydney": 10.0,
    "australia/sydney": 10.0,
}

_CITY_ZONES = {
    "bengaluru": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "calcutta": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "tokyo": "Asia/Tokyo",
    "sydney": "Australia/Sydney",
}


def _now_for_timezone(timezone: str) -> tuple[_dt.datetime, str]:
    requested = (timezone or "local").strip()
    key = requested.lower()
    if key in {"", "local"}:
        now = _dt.datetime.now().astimezone()
        return now, "local"
    if key in {"utc", "gmt", "z"}:
        return _dt.datetime.now(_dt.timezone.utc), "UTC"
    requested = _CITY_ZONES.get(key, requested)
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(requested)
        return _dt.datetime.now(zone), requested
    except Exception:
        offset = _TIMEZONE_OFFSETS.get(key) or _TIMEZONE_OFFSETS.get(requested.lower())
        if offset is None:
            raise ToolExecutionError(
                f"unknown timezone: {requested}. Use local, UTC, or an IANA name such as Asia/Kolkata."
            ) from None
        tz = _dt.timezone(_dt.timedelta(hours=offset))
        return _dt.datetime.now(tz), f"{requested} (fixed offset)"


def _get_current_time(timezone: str = "local") -> dict:
    now, label = _now_for_timezone(timezone)
    return {
        "timezone": label,
        "iso": now.isoformat(timespec="seconds"),
        "display": now.strftime("%Y-%m-%d %H:%M:%S %Z").strip(),
        "epoch": int(now.timestamp()),
    }


def _control_device(
    device: str,
    action: str,
    value: int | None = None,
) -> dict:
    return _DEVICES.apply(device, action, value)


def _parse_invoice_text(text: str) -> dict:
    source = str(text).strip()
    if not source:
        raise ToolValidationError("invoice text must not be empty")
    amount_match = re.search(
        r"(?P<symbol>[$\u20ac\u00a3\u20b9])?\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)",
        source,
    )
    amount = None
    currency = None
    if amount_match:
        amount = float(amount_match.group("amount").replace(",", ""))
        symbol = amount_match.group("symbol")
        currency = {"$": "USD", "\u20ac": "EUR", "\u00a3": "GBP", "\u20b9": "INR"}.get(symbol)
        if currency is None:
            currency = "USD" if re.search(r"\bUSD?\b", source, re.I) else None
    date_match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"(?:\s+(\d{4}))?\b",
        source,
        re.I,
    )
    due_date = None
    if date_match:
        day, month, year = date_match.group(1), date_match.group(2), date_match.group(3)
        due_date = f"{int(day)} {month.title()}" + (f" {year}" if year else "")

    merchant_match = re.match(r"^\s*([A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)?)", source)
    merchant = merchant_match.group(1) if merchant_match else source.split()[0]

    return {
        "status": "extracted",
        "merchant": merchant,
        "amount": amount,
        "currency": currency,
        "due_date": due_date,
        "source_length": len(source),
    }


def _extract_structured_data(text: str, fields: list[str] | None = None) -> dict:
    source = str(text)
    extracted: dict[str, Any] = {
        "emails": sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", source))),
        "amounts": sorted(set(re.findall(r"[$\u20ac\u00a3\u20b9]?\s*\d[\d,]*(?:\.\d{1,2})?", source))),
        "dates": sorted(
            set(
                re.findall(
                    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
                    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
                    r"(?:\s+\d{4})?\b",
                    source,
                    re.I,
                )
            )
        ),
        "phone_numbers": sorted(set(re.findall(r"(?<!\d)(?:\+?\d[\d .-]{7,}\d)(?!\d)", source))),
    }
    if fields:
        allowed = {field.strip().lower() for field in fields}
        extracted = {key: value for key, value in extracted.items() if key in allowed}
    return {"status": "extracted", "fields": extracted, "source_length": len(source)}


def _get_system_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "cwd": str(Path.cwd()),
        "pid": os.getpid(),
    }


def _get_current_directory() -> dict:
    return {"cwd": str(Path.cwd())}


class FilesToolset:
    """Filesystem tools restricted to a configured root directory."""

    def __init__(self, root: Path, *, timeout: float = 10.0) -> None:
        self.root = Path(root).resolve()
        self.timeout = timeout

    def _resolve(self, path: str) -> Path:
        raw = Path(str(path or ".")).expanduser()
        candidate = raw if raw.is_absolute() else self.root / raw
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise ToolExecutionError(f"could not resolve path: {exc}") from exc
        if resolved != self.root and self.root not in resolved.parents:
            raise ToolExecutionError(
                f"path is outside the configured file root ({self.root})"
            )
        return resolved

    def list_directory(self, path: str = ".") -> dict:
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolExecutionError(f"not a directory: {path}")
        entries = []
        try:
            with os.scandir(target) as iterator:
                for entry in sorted(iterator, key=lambda item: item.name.lower())[:200]:
                    stat = entry.stat(follow_symlinks=False)
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                            "size": stat.st_size,
                            "modified": int(stat.st_mtime),
                            "symlink": entry.is_symlink(),
                        }
                    )
        except OSError as exc:
            raise ToolExecutionError(f"could not list directory: {exc}") from exc
        return {
            "path": str(target.relative_to(self.root)) or ".",
            "entries": entries,
            "truncated": len(entries) >= 200,
        }

    def search_files(self, query: str, path: str = ".", max_results: int = 50) -> dict:
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolExecutionError(f"not a directory: {path}")
        needle = str(query).strip().lower()
        if not needle:
            raise ToolValidationError("query must not be empty")
        results = []
        scanned = 0
        truncated = False
        skip_dirs = {".git", "__pycache__", ".venv", "node_modules", ".needle3", ".mypy_cache"}
        for current, dirs, files in os.walk(target):
            dirs[:] = [name for name in dirs if name not in skip_dirs]
            for name in files:
                scanned += 1
                if scanned > 5000:
                    truncated = True
                    break
                if needle in name.lower():
                    full = Path(current) / name
                    try:
                        stat = full.stat()
                    except OSError:
                        continue
                    results.append(
                        {
                            "path": str(full.relative_to(self.root)),
                            "size": stat.st_size,
                            "modified": int(stat.st_mtime),
                        }
                    )
                    if len(results) >= max_results:
                        truncated = True
                        break
            if truncated:
                break
        return {
            "query": query,
            "path": str(target.relative_to(self.root)) or ".",
            "results": results,
            "scanned": scanned,
            "truncated": truncated,
        }


def _tool_schemas() -> dict[str, dict]:
    return {
        "get_current_time": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "local, UTC, or an IANA name such as Asia/Kolkata.",
                    "default": "local",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
        "control_device": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "minLength": 1, "maxLength": 80},
                "action": {
                    "type": "string",
                    "enum": ["on", "off", "toggle", "dim", "brighten", "lock", "unlock", "set"],
                },
                "value": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["device", "action"],
            "additionalProperties": False,
        },
        "parse_invoice_text": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 4000}
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "extract_structured_data": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 8000},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "get_system_info": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "get_current_directory": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "list_directory": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."}
            },
            "required": [],
            "additionalProperties": False,
        },
        "search_files": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ToolSpec) -> None:
        errors = validate_tool_schema(spec.public_schema())
        if errors:
            raise ToolValidationError("; ".join(errors))
        with self._lock:
            if spec.name in self._tools:
                raise ToolValidationError(f"duplicate tool name: {spec.name}")
            self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        with self._lock:
            try:
                return self._tools[name]
            except KeyError as exc:
                raise ToolNotFoundError(f"unknown tool: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[name] for name in self.names()]

    def schemas(self) -> list[dict]:
        return [spec.public_schema() for spec in self.all()]

    def build_native_functions(self, needle_module: Any) -> list[Callable]:
        """Create callables that delegate execution back to the active executor."""
        from .tool_executor import active_executor

        functions = []
        for spec in self.all():
            def make(spec: ToolSpec) -> Callable:
                def native_tool(**kwargs):
                    executor = active_executor()
                    if executor is None:
                        raise ToolExecutionError("no active tool executor")
                    record = executor.execute(spec.name, kwargs)
                    if record.error:
                        raise ToolExecutionError(record.error)
                    return record.output

                native_tool.__name__ = spec.name
                native_tool.__doc__ = spec.description
                native_tool = needle_module.tool(native_tool, triggers=list(spec.triggers) or None)
                # The explicit schema is the source of truth for the UI and validator.
                native_tool._needle_tool = spec.native_schema()
                return native_tool

            functions.append(make(spec))
        return functions


def default_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    files = FilesToolset(settings.file_root, timeout=min(10.0, settings.request_timeout))

    registry.register(
        ToolSpec(
            name="get_current_time",
            description=(
                "Get the current time for the user's timezone or a named timezone. "
                "Use only for explicit time/date questions, never for weather or general questions."
            ),
            parameters=_tool_schemas()["get_current_time"],
            implementation=_get_current_time,
            triggers=[r"\b(what(?:'s| is)? the time|what time is it|current time|tell me the time|time is it)\b"],
            category="information",
        )
    )
    registry.register(
        ToolSpec(
            name="control_device",
            description=(
                "Switch, dim, brighten, lock or unlock a named smart-home device. "
                "The default implementation is an explicitly simulated device store."
            ),
            parameters=_tool_schemas()["control_device"],
            implementation=_control_device,
            triggers=[r"\b(turn|switch|dim|brighten|lock|unlock)\b.*\b(lights?|lamps?|fan|thermostat|door|blinds?)\b"],
            category="device",
            destructive=False,
        )
    )
    registry.register(
        ToolSpec(
            name="parse_invoice_text",
            description="Extract merchant, amount, currency and due date from a plain-text invoice or receipt.",
            parameters=_tool_schemas()["parse_invoice_text"],
            implementation=_parse_invoice_text,
            triggers=[r"\b(extract|parse|pull out)\b.*\b(invoice|receipt|bill)\b"],
            category="extraction",
        )
    )
    registry.register(
        ToolSpec(
            name="extract_structured_data",
            description="Extract emails, amounts, dates and phone numbers from text; optionally limit the fields.",
            parameters=_tool_schemas()["extract_structured_data"],
            implementation=_extract_structured_data,
            triggers=[r"\b(extract|pull out|find all)\b.*\b(emails?|dates?|amounts?|phone numbers?)\b"],
            category="extraction",
        )
    )
    registry.register(
        ToolSpec(
            name="get_system_info",
            description="Report safe host diagnostics: OS, Python version, CPU count, working directory and PID.",
            parameters=_tool_schemas()["get_system_info"],
            implementation=_get_system_info,
            triggers=[r"\b(system info|system information|os version|python version|platform|cpu count)\b"],
            category="information",
        )
    )
    registry.register(
        ToolSpec(
            name="get_current_directory",
            description="Return the process working directory.",
            parameters=_tool_schemas()["get_current_directory"],
            implementation=_get_current_directory,
            triggers=[r"\b(current directory|working directory|where am i|pwd)\b"],
            category="filesystem",
        )
    )
    registry.register(
        ToolSpec(
            name="list_directory",
            description=f"List files and folders under the configured file root ({settings.file_root}).",
            parameters=_tool_schemas()["list_directory"],
            implementation=files.list_directory,
            triggers=[r"\b(list|show|ls|dir)\b.*\b(files?|folder|directory|contents?)\b"],
            category="filesystem",
            timeout=files.timeout,
        )
    )
    registry.register(
        ToolSpec(
            name="search_files",
            description=f"Search file and folder names under the configured file root ({settings.file_root}).",
            parameters=_tool_schemas()["search_files"],
            implementation=files.search_files,
            triggers=[r"\b(find|search|look for|locate)\b.*\b(files?|documents?|readme|folder)\b"],
            category="filesystem",
            timeout=files.timeout,
        )
    )
    return registry

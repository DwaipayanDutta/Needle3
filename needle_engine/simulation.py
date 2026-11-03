"""Deterministic, explicitly selected simulation runtime.

This is not model inference. It exists so the UI, API, and demos remain usable
when the native engine or its platform wheel is unavailable. It never reports a
confidence score because no calibrated model produced the call.
"""

from __future__ import annotations

import re
from typing import Any

from .tool_executor import ToolExecutor, execute_planned_calls
from .tool_registry import ToolRegistry

_DEVICE_RE = re.compile(
    r"\b(lights?|lamps?|fan|thermostat|heater|blinds?|curtains?|door|lock)\b", re.I
)
_TIME_QUERY_RE = re.compile(
    r"\b(what(?:'s| is)? the time|what time is it|current time|tell me the time|time is it)\b",
    re.I,
)
_SYSTEM_RE = re.compile(
    r"\b(system info|system information|os version|operating system|python version|platform|cpu count)\b",
    re.I,
)
_CWD_RE = re.compile(r"\b(current directory|working directory|where am i|pwd)\b", re.I)
_LIST_RE = re.compile(r"\b(list|show|ls|dir)\b.*\b(files?|folder|directory|contents?)\b", re.I)
_SEARCH_RE = re.compile(r"\b(find|search|look for|locate)\b.*\b(files?|documents?|readme|folder)\b", re.I)
_INVOICE_RE = re.compile(r"\b(extract|parse|pull out)\b.*\b(invoice|receipt|bill)\b", re.I)
_STRUCTURED_RE = re.compile(r"\b(extract|pull out|find all)\b.*\b(emails?|dates?|amounts?|phone numbers?)\b", re.I)


def _split_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*(?:;|,|\bthen\b|\band\b)\s+", text, flags=re.I) if part.strip()]


def _number(text: str) -> int | None:
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return int(float(match.group(1))) if match else None


def _timezone_from(text: str) -> str:
    match = re.search(r"\b(?:in|for)\s+([A-Za-z][A-Za-z /_-]{1,40})", text, re.I)
    if not match:
        return "local"
    candidate = match.group(1).strip()
    candidate = re.sub(r"\b(right now|now|please)\b", "", candidate, flags=re.I).strip(" ?.!")
    if not candidate or candidate.lower() in {"the morning", "the afternoon", "the evening"}:
        return "local"
    return candidate


def _time_call(text: str, tools: set[str]) -> list[dict] | None:
    if "get_current_time" not in tools or not _TIME_QUERY_RE.search(text):
        return None
    return [{"name": "get_current_time", "arguments": {"timezone": _timezone_from(text)}}]


def _device_call(text: str, tools: set[str]) -> list[dict] | None:
    if "control_device" not in tools or not _DEVICE_RE.search(text):
        return None
    lowered = text.lower()
    action = None
    if re.search(r"\bunlock\b", lowered):
        action = "unlock"
    elif re.search(r"\block\b", lowered):
        action = "lock"
    elif re.search(r"\b(turn|switch|put)\s+off\b|\bswitch off\b", lowered):
        action = "off"
    elif re.search(r"\b(turn|switch|put)\s+on\b|\bswitch on\b", lowered):
        action = "on"
    elif re.search(r"\bdim\b", lowered):
        action = "dim"
    elif re.search(r"\bbrighten\b", lowered):
        action = "brighten"
    elif re.search(r"\btoggle\b", lowered):
        action = "toggle"
    elif re.search(r"\bset\b", lowered):
        action = "set"
    if not action:
        return None

    named = re.search(
        r"\b(?:the|my|all)\s+([a-z0-9 ]+?(?:lights?|lamps?|fan|thermostat|heater|blinds?|curtains?|door|lock))\b",
        lowered,
    )
    device = named.group(1) if named else _DEVICE_RE.search(lowered).group(1)
    device = re.sub(r"\b(to|at)\s+\d+.*$", "", device).strip()
    arguments: dict[str, Any] = {"device": device, "action": action}
    value = _number(lowered)
    if value is not None:
        arguments["value"] = value
    return [{"name": "control_device", "arguments": arguments}]


def _invoice_call(text: str, tools: set[str]) -> list[dict] | None:
    if "parse_invoice_text" not in tools or not _INVOICE_RE.search(text):
        return None
    source = text.split(":", 1)[1].strip() if ":" in text else text.strip()
    if not source:
        return None
    return [{"name": "parse_invoice_text", "arguments": {"text": source}}]


def _structured_call(text: str, tools: set[str]) -> list[dict] | None:
    if "extract_structured_data" not in tools or not _STRUCTURED_RE.search(text):
        return None
    lowered = text.lower()
    fields = []
    if "email" in lowered:
        fields.append("emails")
    if "amount" in lowered:
        fields.append("amounts")
    if "date" in lowered:
        fields.append("dates")
    if "phone" in lowered:
        fields.append("phone_numbers")
    arguments: dict[str, Any] = {"text": text}
    if fields:
        arguments["fields"] = fields
    return [{"name": "extract_structured_data", "arguments": arguments}]


def _system_call(text: str, tools: set[str]) -> list[dict] | None:
    if "get_system_info" in tools and _SYSTEM_RE.search(text):
        return [{"name": "get_system_info", "arguments": {}}]
    return None


def _cwd_call(text: str, tools: set[str]) -> list[dict] | None:
    if "get_current_directory" in tools and _CWD_RE.search(text):
        return [{"name": "get_current_directory", "arguments": {}}]
    return None


def _list_call(text: str, tools: set[str]) -> list[dict] | None:
    if "list_directory" not in tools or not _LIST_RE.search(text):
        return None
    match = re.search(r"\b(?:in|under|inside)\s+(?:the\s+)?([\w./-]+)", text, re.I)
    path = match.group(1) if match else "."
    if path.lower() in {"current", "current-directory", "directory"}:
        path = "."
    return [{"name": "list_directory", "arguments": {"path": path}}]


def _search_call(text: str, tools: set[str]) -> list[dict] | None:
    if "search_files" not in tools or not _SEARCH_RE.search(text):
        return None
    match = re.search(r"\b(?:find|search for|search|look for|locate)\b\s+(.+)", text, re.I)
    if not match:
        return None
    query = re.sub(r"\b(the|a|an|file|files|document|documents|folder|in|my)\b", " ", match.group(1), flags=re.I)
    query = re.sub(r"\s+", " ", query).strip(" ?.!")
    if not query:
        return None
    return [{"name": "search_files", "arguments": {"query": query}}]


_HANDLERS = (
    _invoice_call,
    _structured_call,
    _search_call,
    _list_call,
    _system_call,
    _cwd_call,
    _time_call,
    _device_call,
)


def _match(text: str, tools: set[str]) -> list[dict] | None:
    for handler in _HANDLERS:
        calls = handler(text, tools)
        if calls:
            return calls
    return None


def plan_calls(prompt: str, registry: ToolRegistry) -> list[dict]:
    raw = str(prompt or "").strip()
    if not raw:
        return []
    tools = set(registry.names())

    # Whole-query text consumers first: commas and colons belong to their text.
    for handler in (_invoice_call, _structured_call):
        calls = handler(raw, tools)
        if calls:
            return calls

    calls: list[dict] = []
    for part in _split_clauses(raw):
        matched = _match(part, tools)
        if matched:
            calls.extend(matched)
    if calls:
        return _dedupe(calls)

    whole = _match(raw, tools)
    return [whole] if whole else []


def _dedupe(calls: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for call in calls:
        key = (call["name"], repr(sorted(call["arguments"].items())))
        if key in seen:
            continue
        seen.add(key)
        output.append(call)
    return output


def _reasoning(calls: list[dict]) -> str:
    if not calls:
        return (
            "Simulation mode: no tool description or trigger matched the request; "
            "returning an empty call list instead of guessing."
        )
    rendered = []
    for call in calls:
        arguments = ", ".join(f"{key}={value!r}" for key, value in call["arguments"].items())
        rendered.append(f"{call['name']}({arguments})")
    return "Simulation mode: matched " + " -> ".join(rendered) + "."


def simulate(prompt: str, executor: ToolExecutor, registry: ToolRegistry) -> dict:
    calls = plan_calls(prompt, registry)
    function_calls, results, errors = execute_planned_calls(executor, calls)
    return {
        "type": "call" if function_calls else "none",
        "success": not errors,
        "error": "; ".join(errors) if errors else None,
        "error_code": "tool_error" if errors else None,
        "function_calls": function_calls,
        "suppressed_calls": [],
        "reasoning": _reasoning(calls),
        "confidence": None,
        "results": results,
        "mode": "simulation",
        "errors": errors,
    }

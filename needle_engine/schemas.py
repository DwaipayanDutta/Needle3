"""Small JSON Schema validator for tool arguments.

This intentionally supports the subset the app publishes: objects, scalar values,
enums, arrays, required properties, and numeric/string bounds. It is not a
general-purpose JSON Schema implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def to_dict(self) -> dict:
        return {"path": self.path, "message": self.message}


def _path(parent: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}" if parent else str(key)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate(schema: dict, value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(schema, dict):
        return

    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            issues.append(ValidationIssue(path or "arguments", "must be an object"))
            return
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for name in required:
            if name not in value:
                issues.append(ValidationIssue(_path(path, name), "is required"))
        additional = schema.get("additionalProperties", False)
        for name, item in value.items():
            if name in properties:
                _validate(properties[name], item, _path(path, name), issues)
            elif additional is False:
                issues.append(ValidationIssue(_path(path, name), "is not a recognised argument"))
            elif isinstance(additional, dict):
                _validate(additional, item, _path(path, name), issues)
        return

    if expected == "array":
        if not isinstance(value, list):
            issues.append(ValidationIssue(path or "arguments", "must be an array"))
            return
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            issues.append(ValidationIssue(path, f"must contain at least {minimum} item(s)"))
        if isinstance(maximum, int) and len(value) > maximum:
            issues.append(ValidationIssue(path, f"must contain at most {maximum} item(s)"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item_schema, item, _path(path, index), issues)
        return

    if expected == "string":
        if not isinstance(value, str):
            issues.append(ValidationIssue(path, "must be a string"))
            return
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            issues.append(ValidationIssue(path, f"must be at least {minimum} character(s)"))
        if isinstance(maximum, int) and len(value) > maximum:
            issues.append(ValidationIssue(path, f"must be at most {maximum} character(s)"))
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    issues.append(ValidationIssue(path, "does not match the required pattern"))
            except re.error:
                issues.append(ValidationIssue(path, "schema contains an invalid pattern"))
        _validate_enum(schema, value, path, issues)
        return

    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            issues.append(ValidationIssue(path, "must be an integer"))
            return
        _validate_bounds(schema, value, path, issues)
        _validate_enum(schema, value, path, issues)
        return

    if expected == "number":
        if not _is_number(value):
            issues.append(ValidationIssue(path, "must be a number"))
            return
        _validate_bounds(schema, value, path, issues)
        _validate_enum(schema, value, path, issues)
        return

    if expected == "boolean":
        if not isinstance(value, bool):
            issues.append(ValidationIssue(path, "must be a boolean"))
            return
        _validate_enum(schema, value, path, issues)
        return

    if expected is None:
        _validate_enum(schema, value, path, issues)
        return

    issues.append(ValidationIssue(path, f"unsupported schema type: {expected}"))


def _validate_enum(schema: dict, value: Any, path: str, issues: list[ValidationIssue]) -> None:
    values = schema.get("enum")
    if isinstance(values, list) and value not in values:
        issues.append(ValidationIssue(path, f"must be one of: {', '.join(map(str, values))}"))


def _validate_bounds(schema: dict, value: Any, path: str, issues: list[ValidationIssue]) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if _is_number(minimum) and value < minimum:
        issues.append(ValidationIssue(path, f"must be >= {minimum}"))
    if _is_number(maximum) and value > maximum:
        issues.append(ValidationIssue(path, f"must be <= {maximum}"))


def validate_arguments(schema: dict, arguments: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate(schema, arguments if arguments is not None else {}, "arguments", issues)
    return issues


def validate_tool_schema(tool: Any, index: int = 0) -> list[str]:
    """Validate a proposed tool definition without registering it."""
    errors: list[str] = []
    if not isinstance(tool, dict):
        return [f"tool {index}: must be an object"]
    name = tool.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", name or ""):
        errors.append(f"tool {index}: name must match [a-zA-Z_][a-zA-Z0-9_]{{0,63}}")
    description = tool.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"tool {index}: description is required")
    parameters = tool.get("parameters")
    if not isinstance(parameters, dict):
        errors.append(f"tool {index}: parameters must be a JSON Schema object")
    elif parameters.get("type") != "object":
        errors.append(f"tool {index}: parameters.type must be 'object'")
    elif not isinstance(parameters.get("properties", {}), dict):
        errors.append(f"tool {index}: parameters.properties must be an object")
    triggers = tool.get("triggers")
    if triggers is not None:
        if not isinstance(triggers, list) or not all(isinstance(item, str) for item in triggers):
            errors.append(f"tool {index}: triggers must be an array of strings")
        else:
            for trigger in triggers:
                try:
                    re.compile(trigger)
                except re.error as exc:
                    errors.append(f"tool {index}: invalid trigger regex: {exc}")
    return errors

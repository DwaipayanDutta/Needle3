from __future__ import annotations

import pytest

from needle_engine.exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolValidationError,
)
from needle_engine.tool_registry import (
    FilesToolset,
    ToolSpec,
    default_registry,
)


def test_default_registry_has_safe_tools(registry):
    names = set(registry.names())
    assert names == {
        "get_current_time",
        "control_device",
        "parse_invoice_text",
        "extract_structured_data",
        "get_system_info",
        "get_current_directory",
        "list_directory",
        "search_files",
    }
    assert "shell" not in names
    schemas = registry.schemas()
    assert len(schemas) == 8
    assert all(schema["parameters"]["type"] == "object" for schema in schemas)


def test_duplicate_and_invalid_registration(registry):
    with pytest.raises(ToolValidationError):
        registry.register(registry.get("get_current_time"))

    bad = ToolSpec(
        name="bad name",
        description="invalid name",
        parameters={"type": "object", "properties": {}},
        implementation=lambda: None,
    )
    with pytest.raises(ToolValidationError):
        registry.register(bad)


def test_unknown_tool(registry):
    with pytest.raises(ToolNotFoundError):
        registry.get("does_not_exist")


def test_time_tool(registry):
    output = registry.get("get_current_time").implementation(timezone="UTC")
    assert output["timezone"] == "UTC"
    assert "iso" in output and "display" in output


def test_time_tool_accepts_city_alias(registry):
    output = registry.get("get_current_time").implementation(timezone="Kolkata")
    assert output["timezone"] in {"Asia/Kolkata", "Kolkata (fixed offset)"}
    assert "+05:30" in output["iso"]


def test_device_tool(registry):
    output = registry.get("control_device").implementation("test lamp", "dim", 25)
    assert output["device"] == "test lamp"
    assert output["action"] == "dim"
    assert output["level"] == 25
    assert output["simulated"] is True


def test_invoice_tool(registry):
    output = registry.get("parse_invoice_text").implementation(
        "Acme charged $42.50 on 12 November"
    )
    assert output["merchant"] == "Acme"
    assert output["amount"] == 42.5
    assert output["currency"] == "USD"
    assert output["due_date"] == "12 November"


def test_structured_extraction(registry):
    output = registry.get("extract_structured_data").implementation(
        "Mail ada@example.com about $19.99 on 5 June",
        ["emails", "amounts", "dates"],
    )
    assert output["fields"]["emails"] == ["ada@example.com"]
    assert output["fields"]["amounts"]
    assert output["fields"]["dates"]


def test_files_tools_are_restricted(settings):
    files = FilesToolset(settings.file_root)
    listing = files.list_directory(".")
    names = {entry["name"] for entry in listing["entries"]}
    assert "README.md" in names
    found = files.search_files("README")
    assert found["results"][0]["path"] == "README.md"

    with pytest.raises(ToolExecutionError):
        files.list_directory("..")
    with pytest.raises(ToolExecutionError):
        files.search_files("x", "../")

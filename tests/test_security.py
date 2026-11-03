from __future__ import annotations

import json

import pytest

from needle_engine.configuration import Settings
from needle_engine.exceptions import ConfigurationError, ToolExecutionError
from needle_engine.tool_registry import FilesToolset


def test_default_bind_is_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("FLASK_HOST", raising=False)
    monkeypatch.delenv("FLASK_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("NEEDLE_FILE_ROOT", raising=False)
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.host == "127.0.0.1"
    assert settings.port == 5000


def test_shell_setting_is_rejected():
    settings = Settings(enable_shell=True)
    with pytest.raises(ConfigurationError):
        settings.validate()


def test_path_traversal_is_rejected(settings):
    files = FilesToolset(settings.file_root)
    for path in ("..", "../", "/", "C:\\Windows"):
        with pytest.raises(ToolExecutionError):
            files.list_directory(path)
        with pytest.raises(ToolExecutionError):
            files.search_files("anything", path)


def test_status_does_not_leak_environment(client, monkeypatch):
    monkeypatch.setenv("NEEDLE_API_KEY", "super-secret-value")
    response = client.get("/api/status")
    assert response.status_code == 200
    assert "super-secret-value" not in response.get_data(as_text=True)
    assert "NEEDLE_API_KEY" not in response.get_data(as_text=True)


def test_request_id_and_security_headers(client):
    response = client.get("/health")
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors" in response.headers["Content-Security-Policy"]


def test_browser_tools_cannot_add_server_tools(client):
    before = {tool["name"] for tool in client.get("/tools").get_json()["tools"]}
    response = client.post(
        "/chat",
        json={
            "prompt": "hello",
            "tools": [
                {
                    "name": "evil_shell",
                    "description": "should never register",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        },
    )
    assert response.status_code == 200
    after = {tool["name"] for tool in client.get("/tools").get_json()["tools"]}
    assert after == before
    assert "evil_shell" not in after


def test_no_shell_capability(client):
    capabilities = client.get("/api/status").get_json()["capabilities"]
    assert capabilities["shell"] is False
    names = {tool["name"] for tool in client.get("/tools").get_json()["tools"]}
    assert "shell" not in names


def test_invalid_tool_schema_is_reported(client):
    response = client.post(
        "/tools/validate",
        json={"tools": [{"name": "bad", "description": "", "parameters": []}]},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["valid"] is False
    assert any("description" in error for error in payload["errors"])


def test_file_root_must_exist(monkeypatch):
    monkeypatch.setenv("NEEDLE_FILE_ROOT", "definitely-not-a-real-directory-12345")
    with pytest.raises(ConfigurationError):
        Settings.from_env()

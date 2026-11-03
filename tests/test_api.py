from __future__ import annotations

import dataclasses

from needle_engine.api import create_app
from needle_engine.runtime import UnavailableRuntime


def test_health_and_readiness(client):
    health = client.get("/health")
    assert health.status_code == 200
    payload = health.get_json()
    assert payload["status"] == "ok"
    assert payload["ready"] is True
    assert payload["engine"]["mode"] == "simulation"
    assert payload["native_engine"] is False
    assert len(payload["tools"]) == 8

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.get_json()["ready"] is True


def test_status_exposes_tools_without_shell(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["capabilities"]["shell"] is False
    assert payload["capabilities"]["simulation"] is True
    names = {tool["name"] for tool in payload["tools"]}
    assert "shell" not in names
    assert "get_current_time" in names
    assert payload["config"]["host"] == "127.0.0.1"


def test_chat_time_and_session(client):
    response = client.post("/chat", json={"prompt": "What time is it in Kolkata?"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["mode"] == "simulation"
    assert payload["confidence"] is None
    assert payload["function_calls"][0]["name"] == "get_current_time"
    assert payload["results"][0]["ok"] is True
    assert "Current time" in payload["response"]
    session_id = payload["session_id"]
    assert session_id

    history = client.get(f"/sessions/{session_id}")
    assert history.status_code == 200
    assert history.get_json()["session"]["message_count"] == 2


def test_chat_multiple_calls(client):
    response = client.post(
        "/chat",
        json={"prompt": "Dim the bedroom lights to 30% and tell me the time"},
    )
    payload = response.get_json()
    assert response.status_code == 200
    names = [call["name"] for call in payload["function_calls"]]
    assert names == ["control_device", "get_current_time"]
    assert len(payload["results"]) == 2
    assert payload["results"][0]["output"]["level"] == 30


def test_chat_off_topic_is_empty_not_guessed(client):
    response = client.post("/chat", json={"prompt": "What's the weather in Bengaluru?"})
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["function_calls"] == []
    assert payload["results"] == []
    assert payload["response"] == ""
    assert "empty call list" in payload["reasoning"]


def test_chat_validation(client):
    assert client.post("/chat", json={}).status_code == 400
    assert client.post("/chat", json={"prompt": "   "}).status_code == 400
    assert client.post("/chat", json={"prompt": 1}).status_code == 400
    assert client.post("/chat", json={"prompt": "hi", "mode": "bogus"}).status_code == 400
    assert client.post("/chat", json={"prompt": "hi", "tools_enabled": "yes"}).status_code == 400
    assert client.post("/chat", data="not json", content_type="text/plain").status_code == 400


def test_prompt_length_limit(settings):
    narrow = dataclasses.replace(settings, max_prompt_chars=10)
    app = create_app(narrow, start_initialization=False)
    response = app.test_client().post("/chat", json={"prompt": "x" * 11})
    assert response.status_code == 400
    assert "exceeds" in response.get_json()["error"]


def test_request_size_limit(settings):
    narrow = dataclasses.replace(settings, max_request_bytes=1024)
    app = create_app(narrow, start_initialization=False)
    response = app.test_client().post(
        "/chat",
        data='{"prompt":"' + ("x" * 2000) + '"}',
        content_type="application/json",
    )
    assert response.status_code == 413
    assert response.get_json()["error_code"] == "request_too_large"


def test_session_endpoints(client):
    created = client.post("/sessions")
    assert created.status_code == 201
    session_id = created.get_json()["session"]["id"]

    fetched = client.get(f"/sessions/{session_id}")
    assert fetched.status_code == 200
    assert fetched.get_json()["session"]["id"] == session_id

    reset = client.post("/chat/reset", json={"session_id": session_id})
    assert reset.status_code == 200
    assert reset.get_json()["session"]["message_count"] == 0

    deleted = client.delete(f"/sessions/{session_id}")
    assert deleted.status_code == 200
    assert client.get(f"/sessions/{session_id}").status_code == 404


def test_session_validation(client):
    assert client.get("/sessions/not valid").status_code == 400
    assert client.post("/chat/reset", json={}).status_code == 400
    assert client.post("/chat/reset", json={"session_id": "does-not-exist"}).status_code == 404


def test_tools_endpoints(client):
    tools = client.get("/tools")
    assert tools.status_code == 200
    assert len(tools.get_json()["tools"]) == 8

    valid = client.post("/tools/validate", json={"tools": tools.get_json()["tools"]})
    assert valid.status_code == 200
    assert valid.get_json()["valid"] is True

    invalid = client.post("/tools/validate", json={"tools": [{"name": "bad name"}]})
    assert invalid.status_code == 400
    assert invalid.get_json()["valid"] is False
    assert invalid.get_json()["errors"]


def test_ui_routes(client):
    root = client.get("/")
    assert root.status_code == 200
    assert b"Needle 3" in root.data
    assert b"Sandbox" in root.data

    sandbox = client.get("/sandbox")
    assert sandbox.status_code == 200

    classic = client.get("/classic")
    assert classic.status_code == 200
    assert b"Classic chat" in classic.data


def test_cors_is_opt_in(settings, client):
    default = client.get("/health", headers={"Origin": "https://example.com"})
    assert "Access-Control-Allow-Origin" not in default.headers

    allowed_settings = dataclasses.replace(settings, cors_origins=("https://example.com",))
    allowed_app = create_app(allowed_settings, start_initialization=False)
    allowed = allowed_app.test_client().get(
        "/health", headers={"Origin": "https://example.com"}
    )
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://example.com"


def test_security_headers(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "Content-Security-Policy" in response.headers


def test_api_errors_are_json(client):
    missing = client.get("/api/not-a-route")
    assert missing.status_code == 404
    assert missing.is_json
    method = client.post("/health")
    assert method.status_code == 405
    assert method.is_json


def test_unavailable_native_returns_503(settings, registry):
    from needle_engine.sessions import SessionManager
    from needle_engine.tool_registry import default_registry

    registry = default_registry(settings)
    unavailable = UnavailableRuntime("native package not installed")
    app = create_app(
        settings,
        registry=registry,
        runtime=unavailable,
        start_initialization=False,
    )
    client = app.test_client()
    assert client.get("/ready").status_code == 503
    response = client.post("/chat", json={"prompt": "What time is it?"})
    assert response.status_code == 503
    assert response.get_json()["error_code"] == "engine_unavailable"

    # Simulation remains explicitly selectable.
    simulation = client.post("/chat", json={"prompt": "What time is it?", "mode": "simulation"})
    assert simulation.status_code == 200
    assert simulation.get_json()["mode"] == "simulation"

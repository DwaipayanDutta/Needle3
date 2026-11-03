from __future__ import annotations

import time

import pytest

from needle_engine.exceptions import SessionNotFoundError
from needle_engine.sessions import SessionManager


def test_session_lifecycle(sessions):
    session = sessions.create()
    assert session.id
    assert sessions.get(session.id).id == session.id

    sessions.append(session.id, "user", "hello")
    sessions.append(session.id, "assistant", "hi", mode="simulation")
    public = sessions.public(session.id)
    assert public["message_count"] == 2
    assert public["history"][0]["content"] == "hello"

    sessions.reset(session.id)
    assert sessions.public(session.id)["message_count"] == 0

    sessions.delete(session.id)
    with pytest.raises(SessionNotFoundError):
        sessions.get(session.id)


def test_session_isolation(sessions):
    first = sessions.create()
    second = sessions.create()
    sessions.append(first.id, "user", "first only")
    sessions.append(second.id, "user", "second only")
    assert sessions.public(first.id)["history"][0]["content"] == "first only"
    assert sessions.public(second.id)["history"][0]["content"] == "second only"


def test_context_prompt():
    manager = SessionManager(ttl_seconds=60, max_sessions=10, max_history=20, context_turns=1)
    session = manager.create()
    manager.append(session.id, "user", "first question")
    manager.append(session.id, "assistant", "first answer")
    manager.append(session.id, "user", "second question")
    context = manager.context_prompt(session.id)
    assert "User: second question" in context
    assert "first question" not in context


def test_ttl_cleanup(sessions):
    session = sessions.create()
    session.updated_at = time.time() - 120
    with pytest.raises(SessionNotFoundError):
        sessions.get(session.id)
    assert sessions.count() == 0


def test_max_sessions_eviction():
    manager = SessionManager(ttl_seconds=60, max_sessions=2, max_history=20)
    first = manager.create()
    second = manager.create()
    third = manager.create()
    assert manager.count() == 2
    with pytest.raises(SessionNotFoundError):
        manager.get(first.id)
    assert manager.get(second.id).id == second.id
    assert manager.get(third.id).id == third.id


def test_invalid_session_id(sessions):
    with pytest.raises(ValueError):
        sessions.create("bad id")

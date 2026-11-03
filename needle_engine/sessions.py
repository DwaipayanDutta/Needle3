"""Lightweight, isolated in-memory sessions with TTL and bounded history."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .exceptions import SessionLimitError, SessionNotFoundError

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def public(self, include_history: bool = True) -> dict:
        payload = {
            "id": self.id,
            "created_at": datetime.fromtimestamp(self.created_at, timezone.utc).isoformat(timespec="seconds"),
            "updated_at": datetime.fromtimestamp(self.updated_at, timezone.utc).isoformat(timespec="seconds"),
            "message_count": len(self.history),
        }
        if include_history:
            payload["history"] = list(self.history)
        return payload


class SessionManager:
    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_sessions: int = 100,
        max_history: int = 40,
        context_turns: int = 0,
    ) -> None:
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self.max_history = max(2, int(max_history))
        self.context_turns = max(0, int(context_turns))
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def _cleanup_locked(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        expired = [key for key, session in self._sessions.items() if session.updated_at < cutoff]
        for key in expired:
            self._sessions.pop(key, None)

    def _evict_locked(self) -> None:
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda session: session.updated_at)
            self._sessions.pop(oldest.id, None)

    def create(self, session_id: str | None = None) -> Session:
        with self._lock:
            self._cleanup_locked()
            if session_id is not None:
                if not _SESSION_ID_RE.match(session_id):
                    raise ValueError("session_id must match [A-Za-z0-9_-]{1,64}")
                if session_id in self._sessions:
                    raise SessionLimitError(f"session already exists: {session_id}")
            else:
                session_id = uuid.uuid4().hex
                while session_id in self._sessions:
                    session_id = uuid.uuid4().hex
            self._evict_locked()
            session = Session(id=session_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str, *, touch: bool = False) -> Session:
        with self._lock:
            self._cleanup_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"session not found: {session_id}")
            if touch:
                session.updated_at = time.time()
            return session

    def get_or_create(self, session_id: str | None) -> Session:
        if not session_id:
            return self.create()
        with self._lock:
            self._cleanup_locked()
            session = self._sessions.get(session_id)
            if session is not None:
                session.updated_at = time.time()
                return session
        return self.create(session_id)

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        function_calls: list[dict] | None = None,
        results: list[dict] | None = None,
        mode: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "role": role,
            "content": str(content),
            "timestamp": _utc_now(),
            "epoch": time.time(),
        }
        if function_calls:
            entry["function_calls"] = function_calls
        if results:
            entry["results"] = results
        if mode:
            entry["mode"] = mode
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"session not found: {session_id}")
            session.history.append(entry)
            if len(session.history) > self.max_history:
                session.history[:] = session.history[-self.max_history :]
            session.updated_at = time.time()

    def reset(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(f"session not found: {session_id}")
            session.history.clear()
            session.updated_at = time.time()
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(f"session not found: {session_id}")
            del self._sessions[session_id]

    def public(self, session_id: str, *, include_history: bool = True) -> dict:
        session = self.get(session_id)
        payload = session.public(include_history=include_history)
        payload["context_turns"] = self.context_turns
        return payload

    def context_prompt(self, session_id: str) -> str | None:
        if self.context_turns <= 0:
            return None
        session = self.get(session_id)
        messages = [
            entry
            for entry in session.history
            if entry.get("role") in {"user", "assistant"} and entry.get("content")
        ]
        if not messages:
            return None
        selected = messages[-(self.context_turns * 2) :]
        lines = ["Conversation so far:"]
        for entry in selected:
            label = "User" if entry["role"] == "user" else "Assistant"
            lines.append(f"{label}: {entry['content']}")
        return "\n".join(lines)

    def count(self) -> int:
        with self._lock:
            self._cleanup_locked()
            return len(self._sessions)

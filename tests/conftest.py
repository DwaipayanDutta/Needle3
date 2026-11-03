from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from needle_engine.api import create_app  # noqa: E402
from needle_engine.configuration import Settings  # noqa: E402
from needle_engine.sessions import SessionManager  # noqa: E402
from needle_engine.tool_registry import default_registry  # noqa: E402


@pytest.fixture
def file_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "README.md").write_text("Needle3 test readme", encoding="utf-8")
    (root / "notes.txt").write_text("hello needle", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    (docs / "lease.pdf").write_text("lease agreement", encoding="utf-8")
    return root


@pytest.fixture
def settings(file_root: Path) -> Settings:
    return Settings(
        mode="simulation",
        eager_init=False,
        host="127.0.0.1",
        port=5000,
        file_root=file_root,
        allow_simulation=True,
        max_prompt_chars=500,
        max_request_bytes=65536,
        session_context_turns=0,
    )


@pytest.fixture
def registry(settings: Settings):
    return default_registry(settings)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings, start_initialization=False)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sessions() -> SessionManager:
    return SessionManager(ttl_seconds=60, max_sessions=10, max_history=20, context_turns=0)

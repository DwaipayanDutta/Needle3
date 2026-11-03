"""Needle3 entry point.

Run `python app.py` for the managed local server (PID file, safe port check,
optional browser launch), or point a WSGI server at the module-level `app`.
"""

from needle_engine.server import run_server

if __name__ == "__main__":
    raise SystemExit(run_server())

from needle_engine.api import create_app  # noqa: E402

app = create_app()

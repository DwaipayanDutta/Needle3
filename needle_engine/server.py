"""Cross-platform server lifecycle: PID file, safe port checks, browser launch."""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from .api import create_app
from .configuration import Settings, configure_logging

LOGGER = logging.getLogger("needle3.server")

_cleanup_lock = threading.Lock()
_cleaned = False


def _pid_path(settings: Settings) -> Path:
    path = Path(settings.pid_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _read_pid(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "pid" in data:
            return data
    except json.JSONDecodeError:
        pass
    try:
        return {"pid": int(text)}
    except ValueError:
        return None


def read_pid_file(path: str | os.PathLike[str]) -> dict | None:
    """Public PID-file reader used by scripts/stop.py and health checks."""
    return _read_pid(Path(path))


def pid_alive(pid: int) -> bool:
    """Public, read-only process liveness check."""
    return _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            return False
        return str(pid) in output
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _port_available(host: str, port: int) -> bool:
    """Return True when nothing is listening on the configured port.

    A connect probe is used instead of a bind probe: on Windows an exclusive
    bind can remain blocked by TIME_WAIT sockets after a server restart, while
    the Flask listener itself can reuse the address.
    """
    probe_host = "127.0.0.1" if host in {"0.0.0.0", ""} else "::1" if host == "::" else host
    family = socket.AF_INET6 if ":" in probe_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) != 0


def _port_owner(port: int) -> str | None:
    """Best-effort, read-only identification of the process holding a TCP port."""
    try:
        if sys.platform.startswith("win"):
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
                    local = parts[1]
                    if local.rsplit(":", 1)[-1] == str(port):
                        return f"PID {parts[4]}"
        else:
            output = subprocess.check_output(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
            if output:
                return f"PID {output.splitlines()[0]}"
    except Exception:
        return None
    return None


def _write_pid(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "app": "needle3",
        "pid": os.getpid(),
        "started_at": time.time(),
        "host": settings.host,
        "port": settings.port,
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _remove_pid(path: Path) -> None:
    try:
        data = _read_pid(path)
        if data and int(data.get("pid", -1)) == os.getpid():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _open_browser(url: str) -> None:
    try:
        LOGGER.info("Opening %s", url)
        if not webbrowser.open(url):
            LOGGER.info("No browser was available; open %s manually.", url)
    except Exception as exc:
        LOGGER.warning("Could not open a browser: %s", exc)


def run_server(settings: Settings | None = None, app: Any | None = None) -> int:
    global _cleaned
    settings = settings or Settings.from_env()
    configure_logging(settings)
    settings.apply_environment()

    pid_path = _pid_path(settings)
    existing = _read_pid(pid_path) if pid_path.exists() else None
    if existing:
        pid = int(existing.get("pid", 0))
        if _pid_alive(pid):
            LOGGER.error(
                "Needle3 is already running (PID %s). Stop it with "
                "`python scripts/stop.py` or set a different NEEDLE_PID_FILE.",
                pid,
            )
            return 1
        LOGGER.warning("Removing stale PID file %s", pid_path)
        pid_path.unlink(missing_ok=True)

    if not _port_available(settings.host, settings.port):
        owner = _port_owner(settings.port)
        suffix = f" ({owner})" if owner else ""
        LOGGER.error(
            "Port %s on %s is already in use%s. Stop that process or choose "
            "another FLASK_PORT. Needle3 does not kill arbitrary processes.",
            settings.port,
            settings.host,
            suffix,
        )
        return 1

    if app is None:
        app = create_app(settings)

    _write_pid(pid_path, settings)

    def cleanup() -> None:
        global _cleaned
        with _cleanup_lock:
            if _cleaned:
                return
            _cleaned = True
            try:
                agent = app.extensions.get("needle3", {}).get("agent")
                if agent is not None:
                    agent.close()
            except Exception:
                pass
            _remove_pid(pid_path)

    atexit.register(cleanup)

    def _terminate(_signum, _frame):
        cleanup()
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _terminate)
    except (ValueError, OSError):
        pass

    display_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    url = f"http://{display_host}:{settings.port}/"
    LOGGER.info("Needle3 listening on http://%s:%s/ (mode=%s)", settings.host, settings.port, settings.mode)
    if display_host != settings.host:
        LOGGER.info("Phone/LAN URL: http://<this-machine-ip>:%s/", settings.port)
    if settings.open_browser:
        opener = threading.Timer(1.2, _open_browser, args=(url,))
        opener.daemon = True
        opener.start()

    try:
        app.run(
            host=settings.host,
            port=settings.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        LOGGER.error("Could not start the server: %s", exc)
        return 1
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_server())

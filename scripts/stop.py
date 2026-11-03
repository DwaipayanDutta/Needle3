#!/usr/bin/env python3
"""Stop only the Needle3 process recorded in the PID file.

This script never scans for or kills arbitrary processes holding a port.
Use --force only when you have confirmed the PID belongs to Needle3.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from needle_engine.server import pid_alive, read_pid_file  # noqa: E402


def _pid_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _stop(pid: int, force: bool) -> bool:
    if sys.platform.startswith("win"):
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode == 0:
            return True
        if not force:
            # Console processes often ignore the graceful WM_CLOSE request.
            # The fallback is still scoped to the PID recorded by Needle3.
            fallback = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
            if fallback.returncode == 0:
                print("Graceful stop was unavailable; forced the recorded PID.")
                return True
        print(
            "The process did not exit. Verify the PID and re-run with --force.",
            file=sys.stderr,
        )
        return False

    os.kill(pid, signal.SIGTERM if not force else signal.SIGKILL)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop the recorded Needle3 server")
    parser.add_argument(
        "--pid-file",
        default=os.environ.get("NEEDLE_PID_FILE", ".needle3/needle3.pid"),
        help="PID file path (default: NEEDLE_PID_FILE or .needle3/needle3.pid)",
    )
    parser.add_argument("--force", action="store_true", help="Send a forced termination")
    parser.add_argument("--timeout", type=float, default=5.0, help="Seconds to wait for exit")
    args = parser.parse_args()

    path = _pid_path(args.pid_file)
    record = read_pid_file(path)
    if not record:
        print(f"No running Needle3 PID file found at {path}", file=sys.stderr)
        return 1
    try:
        pid = int(record.get("pid", 0))
    except (TypeError, ValueError):
        print(f"Invalid PID file: {path}", file=sys.stderr)
        return 1
    if record.get("app") not in {None, "needle3"}:
        print(
            f"Refusing to stop PID {pid}: {path} is not a Needle3 PID file.",
            file=sys.stderr,
        )
        return 1
    if not pid_alive(pid):
        print(f"PID {pid} is not running; removing stale PID file.")
        path.unlink(missing_ok=True)
        return 0

    print(f"Stopping Needle3 PID {pid}...")
    if not _stop(pid, args.force):
        return 1
    deadline = time.time() + max(0.5, args.timeout)
    while time.time() < deadline:
        if not pid_alive(pid):
            break
        time.sleep(0.2)
    if pid_alive(pid):
        print(
            f"PID {pid} is still running after {args.timeout:.1f}s. "
            "Verify it is Needle3, then use --force.",
            file=sys.stderr,
        )
        return 1
    path.unlink(missing_ok=True)
    print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

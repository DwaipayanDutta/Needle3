#!/usr/bin/env python3
"""Check the Needle3 health and readiness endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _get(url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body}
            return response.status, payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        return exc.code, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Needle3 health and readiness")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL (default: http://FLASK_HOST:FLASK_PORT)",
    )
    args = parser.parse_args()
    base = (args.base_url or "").rstrip("/")
    if not base:
        host = os.environ.get("FLASK_HOST", "127.0.0.1")
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = os.environ.get("FLASK_PORT", os.environ.get("PORT", "5000"))
        base = f"http://{host}:{port}"

    health_status, health = _get(base + "/health")
    ready_status, ready = _get(base + "/ready")
    print(json.dumps({"health": health, "ready": ready}, indent=2))

    if health_status != 200:
        print(f"Health endpoint returned HTTP {health_status}", file=sys.stderr)
        return 1
    if ready_status != 200 or not ready.get("ready"):
        print("Server is not ready to process AI requests.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Needle3 terminal client using the same engine, tools, and sessions as the web app."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from needle_engine.agent import NeedleAgent
from needle_engine.configuration import Settings, configure_logging
from needle_engine.runtime import RuntimeState, build_runtime, build_simulation_runtime
from needle_engine.sessions import SessionManager
from needle_engine.tool_registry import default_registry

BANNER = """
==================================================
  Needle 3 CLI · real engine, safe tools, sessions
  :help for commands · :quit to exit
==================================================
"""

HELP = """
:help                 show this help
:quit, :exit          close the client
:mode auto|native|simulation
                      choose the runtime for subsequent requests
:tools                list registered tools
:session              start a new session
:history              show the current session history
:reset                clear the current session history
"""


def _print_response(response: dict) -> None:
    mode = response.get("mode") or "unknown"
    prefix = "[simulation] " if mode == "simulation" else ""
    text = response.get("response") or ""
    if text:
        print(prefix + text)
    elif response.get("error"):
        print(f"Error: {response['error']}")

    for call, result in zip(response.get("function_calls") or [], response.get("results") or []):
        args = json.dumps(call.get("arguments") or {}, ensure_ascii=False)
        print(f"  tool  {call.get('name')}({args})")
        output = result.get("output")
        if output is not None:
            rendered = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            print(f"  result {rendered}")
        elif result.get("error"):
            print(f"  error  {result['error']}")

    if response.get("reasoning"):
        print(f"  why    {response['reasoning']}")
    if response.get("confidence") is not None:
        print(f"  confidence {response['confidence']:.2f}")
    if response.get("errors"):
        print(f"  errors {', '.join(response['errors'])}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Needle3 terminal client")
    parser.add_argument(
        "--mode",
        choices=["auto", "native", "simulation"],
        default=None,
        help="runtime mode (default: NEEDLE_MODE or auto)",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.mode:
        settings = dataclasses.replace(settings, mode=args.mode)
    if "NEEDLE_LOG_LEVEL" not in os.environ:
        settings = dataclasses.replace(settings, log_level="WARNING")
    settings.validate()
    configure_logging(settings)

    registry = default_registry(settings)
    native = build_runtime(settings, registry)
    simulation = build_simulation_runtime(settings, registry)
    sessions = SessionManager(
        ttl_seconds=settings.session_timeout,
        max_sessions=settings.max_sessions,
        max_history=settings.max_history,
        context_turns=settings.session_context_turns,
    )
    agent = NeedleAgent(settings, native, simulation, registry, sessions)
    session_id = sessions.create().id
    request_mode = settings.mode

    print(BANNER)
    if settings.mode != "simulation":
        print("Loading the native engine (first run may download it)...", flush=True)
        if native.initialize():
            print("Native engine ready.\n")
        else:
            print(f"Native engine unavailable: {native.status().get('last_error')}\n")
            if settings.mode == "auto":
                print("Requests will fail until you select ':mode simulation'.\n")
    else:
        print("Explicit simulation mode; no native model will be loaded.\n")

    try:
        while True:
            try:
                line = input("You > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break
            if not line:
                continue
            if line in {":quit", ":exit", "exit", "quit"}:
                break
            if line == ":help":
                print(HELP)
                continue
            if line == ":tools":
                for spec in registry.all():
                    print(f"  {spec.name}: {spec.description}")
                print()
                continue
            if line == ":session":
                session_id = sessions.create().id
                print(f"New session: {session_id}\n")
                continue
            if line == ":history":
                payload = sessions.public(session_id)
                for entry in payload.get("history", []):
                    print(f"  {entry['role']}: {entry['content']}")
                print()
                continue
            if line == ":reset":
                sessions.reset(session_id)
                print("Session cleared.\n")
                continue
            if line.startswith(":mode"):
                parts = line.split(maxsplit=1)
                if len(parts) != 2 or parts[1] not in {"auto", "native", "simulation"}:
                    print("Usage: :mode auto|native|simulation\n")
                    continue
                request_mode = parts[1]
                if request_mode == "simulation" and not settings.allow_simulation:
                    print("Simulation is disabled by NEEDLE_ALLOW_SIMULATION=0.\n")
                    request_mode = settings.mode
                    continue
                if request_mode in {"auto", "native"} and (
                    native.mode != "native"
                    or native.state not in {RuntimeState.READY, RuntimeState.BUSY}
                ):
                    print("Native engine is not ready; use ':mode simulation' for an explicit demo.\n")
                    continue
                print(f"Mode set to {request_mode}.\n")
                continue
            if line.startswith(":"):
                print("Unknown command. Type :help.\n")
                continue

            try:
                response = agent.process(line, session_id=session_id, mode=request_mode)
            except Exception as exc:
                print(f"Error: {exc}\n")
                continue
            _print_response(response)
    finally:
        agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

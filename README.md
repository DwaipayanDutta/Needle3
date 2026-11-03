# Needle 3 — Local Tool-Calling Assistant

A local-first, mobile-friendly application around **Cactus Compute Needle 3**, the 8–29 MB on-device model for tool calls and structured extraction. The app runs the **real native engine** when the platform supports it, executes a validated set of safe tools, keeps isolated sessions, and exposes the same backend to a browser sandbox, a classic chat page, and a terminal client.

Simulation is available, but only as an **explicitly selected mode**. It is never used silently when native inference fails.

## Verified status

| Check | Result |
| --- | --- |
| Native package | `cactus-needle==3.2.10` (Python 3.11.9, Windows 11) |
| Native load | ~10.4 s on first run (engine + weights download); ~0.6–1.3 s per request once cached |
| Real tool calls | `get_current_time`, `control_device`, `parse_invoice_text`, filesystem tools exercised through `needle.Needle` |
| Automated tests | 54 passed (`python -m pytest`) |
| Sandbox | Backend + explicit Demo modes verified in a real browser |
| Classic chat | Native backend, sessions and tool events verified in a real browser |

> Needle 3 is a **tool router**, not a chat model. The API's `response` field is a deterministic rendering of the actual tool outputs. The server does not invent assistant prose, confidence scores, or tool calls.

## Architecture

```text
Browser: sandbox.html (Backend / Demo)      Browser: classic.html
                 │                                  │
                 └──────────────┬───────────────────┘
                                ▼
                  Flask API (needle_engine/api.py)
                                │
                  NeedleAgent (needle_engine/agent.py)
                     ├─ SessionManager
                     ├─ ToolExecutor ── schema validation, timeouts, trace
                     ├─ NativeRuntime ── cactus-needle.Needle (serialized)
                     └─ SimulationRuntime ── explicit only
                                │
                     ToolRegistry (8 safe tools)
                                │
             time · device simulator · extraction · system · filesystem
```

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The audit and verified package findings are in [`docs/IMPLEMENTATION_AUDIT.md`](docs/IMPLEMENTATION_AUDIT.md).

## Quick start

### 1. Install

```bash
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
python -m venv .venv
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Install the real native engine (optional but recommended where supported):

```bash
python -m pip install -r requirements-native.txt
```

### 2. Run

```bash
python app.py
```

The server binds to `127.0.0.1:5000` by default and opens the sandbox at <http://127.0.0.1:5000/>. It writes a PID file, checks the port safely, and never kills an unrelated process.

Without opening a browser:

```bash
NEEDLE_OPEN_BROWSER=0 python app.py
```

```powershell
$env:NEEDLE_OPEN_BROWSER=0; python app.py
```

Explicit simulation (no model download, useful on unsupported platforms):

```bash
NEEDLE_MODE=simulation python app.py
```

```powershell
$env:NEEDLE_MODE=simulation; python app.py
```

### 3. Verify

```bash
curl -s http://127.0.0.1:5000/health
curl -s http://127.0.0.1:5000/ready
```

`/ready` returns `200` only when the engine can process AI requests. `503` means the
server is up but the selected runtime is not ready.

### 4. CLI

```bash
python needle_terminal_client.py
```

The CLI uses the same native runtime, tools and sessions as the web app. It supports
`:help`, `:mode auto|native|simulation`, `:tools`, `:session`, `:history` and `:reset`.
There is no shell command, by design.

## Modes

`NEEDLE_MODE` sets the default; each `POST /chat` may request a mode explicitly.

| Mode | Behavior |
| --- | --- |
| `auto` (default) | Uses native inference when available. If the package or platform is unavailable, requests return `503` with `engine_unavailable`. **No silent simulation.** |
| `native` | Requires the native runtime. Returns `503` if it is not ready. |
| `simulation` | Explicit deterministic demonstration. No model is loaded. `confidence` is `null`, output is marked `simulated`/`mode: "simulation"`. |

The sandbox and classic page expose this choice in the UI. The standalone sandbox
(`file://`) is labeled **Local demo** and never claims to be native.

## Interfaces

### Browser sandbox — `/`

The primary UI. It retains the phone environment, tool editor, presets, JSON/Calls
tabs, activity log and keyboard shortcuts.

- **Backend** mode calls the real `/chat` endpoint. The tool editor shows the live
  server registry and is read-only; browser edits cannot grant server execution.
- **Demo** mode sends `mode: "simulation"` to the backend when served over HTTP.
- Opening `sandbox.html` directly from disk runs the local demo engine; the Backend
  button is disabled.
- Run, Cancel, Copy, Export, Reset, mic input, and `Enter` / `Ctrl`/`Cmd`+`Enter` / `/` / `R`
  shortcuts are supported.
- Failure to reach the backend shows an error; it does not silently switch modes.

### Classic chat — `/classic`

A red/white mobile-first chat with sessions, timestamps, tool cards, mode badge,
Auto/Demo selector, clear, copy and error states. It calls the same backend.

### Terminal — `needle_terminal_client.py`

Native/simulation choice, session history, tool list, and real result output.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Sandbox UI |
| `GET` | `/sandbox` | Sandbox UI alias |
| `GET` | `/classic` | Classic chat UI |
| `GET` | `/health` | App, engine, mode, uptime, tool names |
| `GET` | `/ready` | `200` only when the engine can process requests |
| `GET` | `/api/status` | Safe diagnostics, tools, capabilities, limits |
| `POST` | `/chat` | Run a prompt |
| `POST` | `/chat/reset` | Clear a session |
| `POST` | `/sessions` | Create a session |
| `GET` | `/sessions/<id>` | Session metadata and history |
| `DELETE` | `/sessions/<id>` | Delete a session |
| `GET` | `/tools` | Registered tool schemas |
| `POST` | `/tools/validate` | Validate proposed schemas without registering them |

### `POST /chat`

```bash
curl -s -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What time is it in Kolkata?","mode":"auto"}'
```

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/chat `
  -ContentType "application/json" `
  -Body '{"prompt":"What time is it in Kolkata?","mode":"auto"}'
```

Request fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `prompt` | string | yes | Trimmed; limited by `NEEDLE_MAX_PROMPT_CHARS` |
| `session_id` | string | no | `[A-Za-z0-9_-]{1,64}`; created if absent |
| `mode` | string | no | `auto`, `native`, or `simulation` |
| `tools_enabled` | boolean | no | Default `true`; `false` uses a no-tools native agent (slower) and returns no calls |

Response (abridged):

```json
{
  "success": true,
  "session_id": "05114984195b499bb57d5f0c59c313c0",
  "request_id": "d9dc227f58d44581871f283a111af24f",
  "response": "get_current_time: Current time: 2026-11-03 22:25:22 IST (Asia/Kolkata)",
  "function_calls": [
    { "name": "get_current_time", "arguments": { "timezone": "Kolkata" } }
  ],
  "suppressed_calls": [],
  "results": [
    {
      "name": "get_current_time",
      "arguments": { "timezone": "Kolkata" },
      "ok": true,
      "status": "ok",
      "output": {
        "timezone": "Asia/Kolkata",
        "iso": "2026-11-03T22:25:22+05:30",
        "display": "2026-11-03 22:25:22 IST",
        "epoch": 1793724922
      },
      "error": null,
      "latency_ms": 1.8
    }
  ],
  "reasoning": "Result shows Kolkata is in Kolkata. Respond with that.",
  "confidence": 0.53,
  "mode": "native",
  "simulated": false,
  "tools_enabled": true,
  "latency_ms": 1017.0,
  "error": null,
  "error_code": null,
  "errors": [],
  "model": { "generation": 3, "package_version": "3.2.10", "weights": null },
  "metrics": { "prefill_tps": 392.0, "decode_tps": 164.6, "peak_ram_mb": 127.2 },
  "app_version": "1.0.0"
}
```

Errors use the same envelope with `success: false`, a safe `error`, and `error_code`.
HTTP status codes: `400` invalid request/tool schema, `404` unknown session/route,
`413` body too large, `503` engine unavailable/busy, `504` timeout.

## Tools

| Tool | Purpose | Safety |
| --- | --- | --- |
| `get_current_time` | Current time for local/UTC/IANA timezone | Read-only |
| `control_device` | On/off/toggle/dim/brighten/lock/unlock/set a named device | In-memory simulated store; marked `simulated` |
| `parse_invoice_text` | Merchant, amount, currency, due date | Read-only; validated fields |
| `extract_structured_data` | Emails, amounts, dates, phone numbers; optional fields | Read-only |
| `get_system_info` | OS, Python, CPU count, cwd, PID | Read-only; no env values |
| `get_current_directory` | Process working directory | Read-only |
| `list_directory` | List up to 200 entries under the file root | Confined to `NEEDLE_FILE_ROOT` |
| `search_files` | Search names under the file root, max 50 by default | Confined; skips `.git`, `.venv`, etc. |

There is **no shell tool**. `NEEDLE_ENABLE_SHELL=1` fails startup. The HTTP API is not a
shell endpoint. Browser edits to tool definitions never register server tools.

Add a tool by creating a `ToolSpec` in `needle_engine/tool_registry.py` with a JSON
Schema, a timeout, and a safe implementation, then registering it in
`default_registry()`. Native callables and schemas are generated from the registry.

## Configuration

The app loads `.env` if present, without overriding real environment variables. Copy
[`.env.example`](.env.example).

| Variable | Default | Description |
| --- | --- | --- |
| `FLASK_HOST` | `127.0.0.1` | Bind address. `0.0.0.0` is an explicit LAN choice |
| `FLASK_PORT` / `PORT` | `5000` | Port |
| `NEEDLE_OPEN_BROWSER` | `1` | Open the sandbox on startup |
| `NEEDLE_MODE` | `auto` | `auto`, `native`, or `simulation` |
| `NEEDLE_ALLOW_SIMULATION` | `1` | Permit explicit simulation requests |
| `NEEDLE_MODEL` | unset | Path to a tuned `.cact` file |
| `NEEDLE_GENERATION` | `3` | Native model generation (`2` or `3`) |
| `NEEDLE_TELEMETRY` | `1` | Set `0` to set `NEEDLE_TELEMETRY=0`/`DO_NOT_TRACK=1` for the native package |
| `NEEDLE_MAX_TOOL_CALLS` | `8` | Per-request tool call limit |
| `NEEDLE_REQUEST_TIMEOUT` | `30` | Native/tool request timeout in seconds |
| `NEEDLE_SESSION_TIMEOUT` | `3600` | Session TTL in seconds |
| `NEEDLE_MAX_PROMPT_CHARS` | `4000` | Prompt character limit |
| `NEEDLE_MAX_REQUEST_BYTES` | `65536` | HTTP body limit |
| `NEEDLE_MAX_NEW_TOKENS` | `512` | Native decode limit |
| `NEEDLE_MAX_SESSIONS` | `100` | In-memory session cap |
| `NEEDLE_MAX_HISTORY` | `40` | Messages retained per session |
| `NEEDLE_SESSION_CONTEXT_TURNS` | `0` | Recent turns prepended to the prompt |
| `NEEDLE_FILE_ROOT` | cwd | Filesystem tool sandbox root |
| `NEEDLE_CORS_ORIGINS` | unset | Comma-separated allowed origins; unset = same-origin only |
| `NEEDLE_ENABLE_SHELL` | `0` | Must remain `0`; shell is not supported |
| `NEEDLE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `NEEDLE_DEBUG` | `0` | Return internal errors locally; never enable on a shared host |
| `NEEDLE_PID_FILE` | `.needle3/needle3.pid` | PID file used by start/stop scripts |

## Native engine

Install:

```bash
python -m pip install -r requirements-native.txt
# or: python -m pip install "cactus-needle>=3.2.10,<4"
```

The API used by this project:

```python
import needle

agent = needle.Needle(tools=[...], system="...", stateless=True)
response = agent.run("What time is it in Kolkata?", max_steps=8, max_new_tokens=512)
print(response["function_calls"], response["confidence"], response["results"])
```

The engine and weights are fetched from Hugging Face on first use and cached. Published
engines cover x86_64 and arm64 on Windows, macOS and Linux (glibc/musl). **Android/Bionic
is not supported by the published shared libraries**; the package raises a clear error.
Use simulation, PRoot Ubuntu, or a custom `NEEDLE3_LIB_PATH` build.

The C engine is process-global per generation, so this app serializes native inference.
`tools_enabled: false` creates a temporary no-tools agent, which reinitializes the
engine and is slower; use it only when needed.

## Sessions

- IDs are random 128-bit values; supplied IDs must match `[A-Za-z0-9_-]{1,64}`.
- In-memory, per-session lock, TTL, bounded history, reset and delete.
- No cross-session leakage. No persistence by default.
- `NEEDLE_SESSION_CONTEXT_TURNS=0` by default because Needle is optimized for
  single-turn tool routing. Increase carefully if your prompts benefit from context.

## Security

- Loopback binding by default; LAN exposure is explicit.
- CORS is disabled unless `NEEDLE_CORS_ORIGINS` names origins.
- No arbitrary shell execution. `NEEDLE_ENABLE_SHELL=1` fails startup.
- Filesystem tools are confined to `NEEDLE_FILE_ROOT`; path traversal is rejected.
- JSON Schema validation rejects unknown arguments and wrong types.
- Tool calls, timeouts, prompt length and request body size are bounded.
- Security headers include `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options`, and a Content Security Policy.
- Prompts and request bodies are not logged; request IDs are.
- This is a local personal tool, not a multi-user authenticated service. Put an
  authenticated reverse proxy in front of it before exposing it beyond loopback.

## Start, stop, health

```bash
python app.py                     # managed server, auto-open
python scripts/start.py           # same managed lifecycle
python scripts/stop.py            # stop only the recorded PID
python scripts/healthcheck.py     # check /health and /ready
```

POSIX wrappers: `scripts/start.sh`, `scripts/stop.sh`.

The server writes `.needle3/needle3.pid`, detects live instances, removes stale PID
files, reports a busy port with a best-effort owner, and never kills arbitrary
processes. On Windows, `stop.py` may force the recorded PID if graceful termination is
ignored; on POSIX, `--force` is the explicit opt-in.

## Windows and Android

### Windows

Use Python 3.11/3.12, `python -m pip`, and PowerShell. Native inference is verified on
Windows 11 x86_64. The PID and port checks use `tasklist`/`netstat` read-only.

### Termux / Android

```bash
pkg update && pkg upgrade -y
pkg install python git -y
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
python -m pip install -r requirements.txt
NEEDLE_MODE=simulation python app.py
```

Use `NEEDLE_MODE=simulation` explicitly on Bionic. For native inference, use PRoot
Ubuntu (Python + `cactus-needle`) or a custom Bionic shared library. The browser
sandbox works without native inference.

Pydroid 3: install Flask via Pip, open `app.py`, run it, and use simulation mode.

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

The 54 tests cover API validation and errors, health/readiness, CORS and security
headers, sessions and TTL, tool schemas, argument validation, execution limits,
timeouts, path traversal, native runtime state transitions (with mocked engines), and
native call tracing. The suite does not download the model.

Native smoke test (supported platform, network for first download):

```bash
python -c "import needle; print(needle.__version__)"
NEEDLE_MODE=native NEEDLE_OPEN_BROWSER=0 python app.py
curl -s http://127.0.0.1:5000/ready
```

UI verification: the sandbox was tested with a real native backend (Backend mode), with
explicit backend simulation (Demo mode), and standalone from `file://` (Local demo).
The classic page was tested against the native backend with tool cards, confidence,
latency and session history.

## Project structure

```text
Needle3/
├── app.py                     # WSGI app / managed server entry point
├── sandbox.html               # Backend-connected sandbox + explicit local demo
├── classic.html               # Classic chat UI
├── needle_engine/
│   ├── __init__.py
│   ├── configuration.py       # Settings and .env loading
│   ├── exceptions.py
│   ├── schemas.py             # JSON Schema validation
│   ├── tool_registry.py       # 8 safe tools and native callables
│   ├── tool_executor.py       # Validation, timeouts, trace
│   ├── runtime.py             # Native/simulation runtimes and states
│   ├── sessions.py
│   ├── agent.py               # Request orchestration and envelope
│   ├── api.py                 # Flask app factory and routes
│   └── server.py              # PID, port, browser, signals
├── scripts/
│   ├── start.py / start.sh
│   ├── stop.py / stop.sh
│   └── healthcheck.py
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_engine.py
│   ├── test_tool_registry.py
│   ├── test_tool_execution.py
│   ├── test_sessions.py
│   ├── test_security.py
│   └── test_server.py
├── docs/
│   ├── IMPLEMENTATION_AUDIT.md
│   ├── ARCHITECTURE.md
│   └── TROUBLESHOOTING.md
├── needle_terminal_client.py  # CLI using the same engine
├── needle_tools_registry.py   # Optional @needle.tool samples
├── requirements.txt           # Flask + tzdata
├── requirements-native.txt    # optional native engine
├── requirements-dev.txt       # pytest
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

## Limitations

- Needle is a tool router; there is no general chat prose generation. `response` is a
  rendering of real tool outputs.
- Sessions are in-memory; restarting the server loses history.
- Native inference is serialized; concurrent requests queue.
- `control_device` is a simulator until a real integration is configured.
- Android/Bionic cannot load the published native engine.
- No streaming; no authentication; no persistent storage.
- `confidence` is `null` for simulation and for tuned weights without a confidence head.
- Cancel aborts the browser request; the native C engine cannot be interrupted mid-call, so a cancelled inference may still finish server-side.

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for platform and runtime fixes.

## License

The project metadata declares Apache-2.0, matching the upstream Needle ecosystem. No
`LICENSE` file is currently included in this repository; add one before redistributing.

## Acknowledgements

- [Cactus Compute — Needle](https://cactuscompute.com/needle) for the model, documentation and sandbox inspiration.
- [cactus-compute/needle](https://github.com/cactus-compute/needle) for the reference implementation and tool-design guidance.

# Needle 3 — Mobile Web Interface & Browser Sandbox

A small, dependency-light toolkit for working with **Needle 3**, Cactus Compute's 8–29 MB on-device model for tool calls, structured extraction and embeddings.

This repository contains two independent surfaces:

| Surface | What it is | Runtime |
| --- | --- | --- |
| **Browser sandbox** (`sandbox.html`) | A polished, standalone playground for designing tool schemas and testing Needle-shaped tool calls. Includes a simulated phone environment, preset requests, editable tool JSON, and JSON/Calls result views. | Any modern browser. No server, no build step. |
| **Flask mobile chat** (`app.py`) | A mobile-first chat page served at `/`, plus `/chat` and `/health` endpoints. Uses the native Needle engine when importable, otherwise a clearly marked simulation stub. | Python + Flask. |

The sandbox is a **UI and contract test harness**, not model inference. It reproduces Needle's response shape (`function_calls`, `reasoning`, `confidence`, `results`) with a deterministic rule engine so you can iterate on tool descriptions and UX before wiring a real model.

---

## Contents

- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Browser sandbox](#browser-sandbox)
- [Flask mobile chat](#flask-mobile-chat)
- [API](#api)
- [Configuration](#configuration)
- [Native Needle engine](#native-needle-engine)
- [Android](#android)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Quick start

### 1. Open the sandbox (no install)

Clone the repository and open `sandbox.html` directly:

```bash
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
```

```powershell
# Windows PowerShell
start sandbox.html
```

```bash
# macOS
open sandbox.html

# Linux
xdg-open sandbox.html
```

Or serve the folder and open it from another device:

```bash
python -m http.server 8000
# http://localhost:8000/sandbox.html
```

### 2. Run the Flask chat app

```bash
python -m venv .venv
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. The same page is reachable from a phone on the same network at `http://<your-computer-ip>:5000`.

> `app.py` calls `release_port()` on startup, which **terminates whatever process is listening on the target port**. If something else uses port 5000, choose another port first (see [Configuration](#configuration)) or stop the other process yourself.

### 3. Run the CLI client

```bash
python needle_terminal_client.py
```

Type a prompt and press Enter. `exit` or `quit` closes the client.

---

## Command reference

All commands run from the repository root unless noted.

| Task | Command |
| --- | --- |
| Open the sandbox (Windows) | `start sandbox.html` |
| Open the sandbox (macOS) | `open sandbox.html` |
| Open the sandbox (Linux) | `xdg-open sandbox.html` |
| Serve the repository over HTTP | `python -m http.server 8000` |
| Sandbox URL when served | `http://localhost:8000/sandbox.html` |
| Create a virtual environment | `python -m venv .venv` |
| Activate (Windows PowerShell) | `.\.venv\Scripts\Activate.ps1` |
| Activate (macOS/Linux) | `source .venv/bin/activate` |
| Install Flask | `python -m pip install -r requirements.txt` |
| Run the chat server | `python app.py` |
| Run on another port (bash) | `FLASK_PORT=8080 python app.py` |
| Run on another port (PowerShell) | `$env:FLASK_PORT=8080; python app.py` |
| Run on another port (cmd.exe) | `set FLASK_PORT=8080 && python app.py` |
| Health check (bash) | `curl http://127.0.0.1:5000/health` |
| Health check (PowerShell) | `Invoke-RestMethod http://127.0.0.1:5000/health` |
| Send a chat request (bash) | `curl -X POST http://127.0.0.1:5000/chat -H "Content-Type: application/json" -d '{"prompt":"hostname"}'` |
| Send a chat request (PowerShell) | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/chat -ContentType "application/json" -Body '{"prompt":"hostname"}'` |
| Run the CLI | `python needle_terminal_client.py` |
| Exercise the sample tools | `python -c "import needle_tools_registry as t; print(t.get_current_time('UTC'))"` |
| Install the native engine (optional) | `python -m pip install cactus-needle` |
| Disable Needle telemetry (bash) | `NEEDLE_TELEMETRY=0 DO_NOT_TRACK=1 python app.py` |

---

## Browser sandbox

`sandbox.html` is self-contained: HTML, CSS and JavaScript in one file, with no frameworks, external assets or build step.

### Layout

- **Environment** — a simulated phone. The home screen, dock, quick settings, brightness, volume, now-playing bar, notification banner and per-app sheets all react to the calls the engine returns.
- **Defined tools** — an editable JSON array of tool definitions. Each entry can include `name`, `description`, `parameters` (JSON Schema) and optional `triggers` (regular expressions).
- **Query** — the natural-language request. Press **Run** or **Enter**.
- **Result** — two views:
  - **JSON** — the full response object, syntax-highlighted.
  - **Calls** — one card per call with arguments, executed output, confidence and reasoning.
- **Try** — eight preset requests covering single calls, two- and three-call chains, trigger routing, extraction and an intentional refusal.

### Controls

| Control | Action |
| --- | --- |
| `Enter` in the query box | Run the request |
| `Ctrl` / `Cmd` + `Enter` | Run from anywhere |
| `/` | Focus the query box |
| `R` | Reset the environment and restore the default tools |
| `Reset` | Same as `R` |
| `Format` | Pretty-print and validate the tools JSON |
| `Copy` | Copy the last response JSON |
| Mic button | Dictate a request where the browser supports the Web Speech API |

### What the simulation does

1. The request is normalised and passed through intent handlers.
2. Requests with multiple actions are split on `and`, `then`, commas and semicolons; whole-text intents (messages, extraction, speech) are consumed first so their text is not split.
3. If no handler matches, a schema-keyword fallback scores the defined tools; a request with no plausible tool returns an **empty call list** rather than a guess.
4. Each call is executed against the phone state and the response is assembled in Needle's shape:

```json
{
  "type": "call",
  "success": true,
  "error": null,
  "error_code": null,
  "function_calls": [
    {
      "name": "control_device",
      "arguments": { "device": "bedroom lights", "action": "dim", "value": 30 }
    }
  ],
  "reasoning": "matched a tool-specific rule: control_device(device=\"bedroom lights\", action=\"dim\", value=30).",
  "confidence": 0.92,
  "results": [
    {
      "name": "control_device",
      "arguments": { "device": "bedroom lights", "action": "dim", "value": 30 },
      "output": "bedroom lights → dim (30%)"
    }
  ],
  "mode": "simulation",
  "latency_ms": 8,
  "tools_considered": 19
}
```

Edit the tool JSON and run again to see the match change. Invalid JSON is reported inline and blocks the run. Tools without a specific handler still work through the schema fallback — try adding a `set_thermostat` tool with `room` and `temperature` properties.

### Sandbox presets

| Preset | Demonstrates |
| --- | --- |
| Dim + jazz | Two calls from one sentence |
| Morning run | Three calls: alarm, setting, clock |
| Text Ada | Whole-text message with a recipient and body |
| Find the lease | Trigger-style routing to document search |
| Invoice | Structured extraction with typed fields |
| Off-topic | Empty call list (refusal), not a guess |
| Screen | Brightness change plus screenshot |
| Music + timer | Media control plus timer |

---

## Flask mobile chat

`app.py` is a single-file Flask application:

1. On import, it frees the target port (5000 by default).
2. It tries `import needle`. If the import succeeds, `HAS_NATIVE_NEEDLE` is `True`; otherwise a `_StubNeedle` keeps the app running.
3. `/` renders the inline mobile chat UI (`MOBILE_HTML`).
4. `/chat` accepts `{ "prompt": "..." }` and returns the engine's response.
5. `/health` reports `{ "status": "ok", "native_engine": <bool> }`.

In simulation mode, the stub supports:

```text
exec <command>     run a shell command and return its output
hostname           shortcut for common read-only commands
whoami
uptime
pwd
dir
ls
```

Anything else returns a clearly marked `[Simulation Engine]` message. Simulation is expected on Pydroid 3 and on raw Termux without a container.

> The Flask bridge calls `needle.run(prompt)`. The current `cactus-needle` Python API is agent-based (`needle.Needle(tools=[...]).run(prompt)`), so installing the native wheel may require adapting the bridge. See [Native Needle engine](#native-needle-engine).

---

## API

### `GET /`

Returns the mobile chat HTML page.

### `POST /chat`

Request:

```json
{ "prompt": "dim the bedroom lights" }
```

Response (native mode returns the engine object; simulation returns a `response` string):

```json
{ "response": "[Simulation Engine] Processed prompt: \"dim the bedroom lights\"." }
```

Errors: `400` with `{ "error": "Missing prompt" }` when `prompt` is empty. CORS is open (`Access-Control-Allow-Origin: *`).

### `GET /health`

```json
{ "status": "ok", "native_engine": false }
```

### Example

```bash
curl -s http://127.0.0.1:5000/health
curl -s -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"exec whoami"}'
```

---

## Configuration

`app.py` reads only these variables:

| Variable | Default | Description |
| --- | --- | --- |
| `FLASK_PORT` | `5000` | Port for the Flask server |
| `PORT` | `5000` | Fallback when `FLASK_PORT` is unset |

The server always binds to `0.0.0.0`. `FLASK_HOST` is **not** read by the current code. Telemetry variables apply to the native `cactus-needle` engine, not to Flask:

| Variable | Default | Description |
| --- | --- | --- |
| `NEEDLE_TELEMETRY` | `1` | Set to `0` to disable native-engine telemetry |
| `DO_NOT_TRACK` | unset | Set to `1` to disable native-engine telemetry |

---

## Native Needle engine

Install the package:

```bash
python -m pip install cactus-needle
```

The documented API builds an agent from decorated Python functions:

```python
import needle
from needle_tools_registry import get_current_time, control_device, parse_invoice_text

agent = needle.Needle(tools=[get_current_time, control_device, parse_invoice_text])
response = agent.run("what time is it?")
print(response["function_calls"])
print(response["results"])
```

`needle_tools_registry.py` contains three sample tools decorated with `@needle.tool`:

- `get_current_time(timezone)`
- `control_device(device_name, action)`
- `parse_invoice_text(text)`

It is a standalone example: `app.py` does **not** import it. To use the native agent inside the Flask app, build a `needle.Needle` with those functions at startup and call `agent.run(prompt)` in `/chat` instead of `needle.run(prompt)`.

Native wheels are platform-specific. On Android's Bionic runtime the standard `manylinux` wheel will not load directly; use a Linux container (for example Termux + PRoot Ubuntu) or stay in simulation mode.

---

## Android

### Open the sandbox

Copy `sandbox.html` to the phone and open it in Chrome, Firefox or Samsung Internet. It works offline and needs no Python.

To reach a copy served by your computer:

```bash
python -m http.server 8000
# then open http://<your-computer-ip>:8000/sandbox.html on the phone
```

### Run the Flask app with Pydroid 3

1. Install **Pydroid 3** from the Play Store.
2. Pydroid → Menu → Pip → install `flask`.
3. Copy the repository to storage (for example `Download/Needle3`).
4. Open `app.py` in Pydroid and tap **Run**.
5. Open `http://127.0.0.1:5000` in the phone browser.

Pydroid uses Android's native Python runtime, so the native `cactus-needle` wheel is generally unavailable; the app falls back to simulation.

### Run with Termux

```bash
pkg update && pkg upgrade -y
pkg install python git -y
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
python -m pip install flask
python app.py
```

For the native engine, set up PRoot Ubuntu inside Termux, then install `cactus-needle` there.

---

## Project structure

```text
Needle3/
├── app.py                    # Flask server, inline mobile chat UI, /chat and /health
├── sandbox.html              # Standalone browser sandbox (no dependencies)
├── needle_terminal_client.py # Terminal CLI, simulation-aware
├── needle_tools_registry.py  # Sample @needle.tool functions (not imported by app.py)
├── requirements.txt          # Flask, plus a commented-out cactus-needle line
└── README.md
```

> Earlier versions of this README referenced `termux_needle.py`, `tools.py`, `.gitignore` and `LICENSE`. Those files are not present in the repository. The actual entry points are the five files above.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'flask'`**
Install the dependency in the active environment:

```bash
python -m pip install -r requirements.txt
```

**Port 5000 is already in use**
Pick another port. Remember that `app.py` frees the port by terminating the process that holds it:

```bash
FLASK_PORT=8080 python app.py
```

```powershell
$env:FLASK_PORT=8080; python app.py
```

**The sandbox returns no calls**
That is intentional for requests no tool covers: Needle's contract is an empty call list rather than a guess. Check the query against the tool descriptions/triggers, or add a matching tool to the JSON editor. The **Calls** tab shows the reasoning.

**The sandbox says “Invalid JSON”**
The tools editor must contain a JSON array of objects, each with a `name`. Use **Format** to locate the syntax error; the run is blocked until it parses.

**The sandbox is not the real model**
Correct. It is a deterministic browser simulation with no model download. Install `cactus-needle` and use the Python API (or adapt `app.py`) for real inference.

**Native engine imports but `/chat` fails**
The bridge uses `needle.run(prompt)`, while the documented package exposes `needle.Needle(tools=[...]).run(prompt)`. Build an agent and call that instead. Also verify the wheel matches your platform.

**`release_port()` killed an unrelated process**
The function runs at import time and terminates whatever listens on the selected port. Start the app with a dedicated `FLASK_PORT`, or remove/guard the call in `app.py` if that behaviour is not wanted.

**Android: `cactus-needle` will not install**
Use simulation mode or run inside a Linux container. The standard wheels target desktop Linux, macOS and Windows.

---

## License

No `LICENSE` file is currently included in this repository. Add one before redistributing or publishing the project.

---

## Acknowledgements

- [Cactus Compute — Needle](https://cactuscompute.com/needle) for the model, documentation and the original sandbox that inspired this one.
- [cactus-compute/needle](https://github.com/cactus-compute/needle) for the reference implementation and tool-design guidance.

# Needle3 — Mobile Web Interface

A lightweight, mobile‑first web application that lets you interact with **Needle 3** — Cactus Compute’s 8–29 MB on‑device foundation model for tool calling, structured extraction, and text embedding — directly from a phone browser. The app runs a small Flask server, exposes a responsive chat UI, and includes a **simulation fallback** so the interface works even when the native Needle engine cannot be installed on a particular mobile Python environment.

## Table of Contents

* [Features](#features)
* [How It Works](#how-it-works)
* [Requirements](#requirements)
* [Installation](#installation)
  * [Desktop / Server](#desktop--server)
  * [Android (Pydroid 3 or Termux)](#android-pydroid-3-or-termux)
* [Usage](#usage)
  * [Web UI](#web-ui)
  * [CLI Mode](#cli-mode)
* [Configuration](#configuration)
* [Project Structure](#project-structure)
* [Troubleshooting](#troubleshooting)
* [Contributing](#contributing)
* [License](#license)
* [Acknowledgements](#acknowledgements)

## Features

* **Mobile‑first UI** – A self‑contained, responsive HTML chat page served at `/`; works seamlessly in any modern phone browser.
* **Needle 3 Tool Calling** – Decorate Python functions with `@needle.tool`; the model picks the right tool and populates arguments from natural‑language input.
* **Structured Extraction** – Declare a Pydantic model or JSON schema and extract typed fields from unstructured text.
* **Text Embedding** – Obtain sentence vectors locally for search, matching, or intent routing.
* **Simulation Fallback** – If `cactus-needle` (or its native platform wheel) cannot be imported, a stub module keeps the app running and returns clearly marked simulated responses.
* **Cross‑Platform** – Runs on desktop Linux/macOS/Windows and Android environments (via Pydroid 3 or Termux).
* **Zero External Front‑End Dependencies** – No React, no `npm`; built strictly with Flask and standard library components.

## How It Works

1. `app.py` starts a Flask server on `0.0.0.0:5000`.
2. The root route (`/`) serves a single‑file mobile chat interface (`MOBILE_HTML`).
3. The `/chat` endpoint accepts a JSON payload `{ "prompt": "..." }` and forwards the request to:
   * The native `needle` agent when `cactus-needle` is installed.
   * The simulation stub (`_StubNeedle`) when the native engine is unavailable.
4. Tool functions decorated with `@needle.tool` in `tools.py` are executed gracefully within the runtime setup.

## Requirements

| Component | Minimum | Notes |
| ----- | ----- | ----- |
| Python | 3.9+ | 3.10 or 3.11 recommended |
| Flask | 3.0+ | Installed via `pip` |
| `cactus-needle` | *(optional)* | Provides the real Needle 3 engine; simulation mode is active if absent |
| Mobile Device | Android 8+ | Pydroid 3 or Termux |

> **About the Needle 3 Engine on Android:**
>
> `cactus-needle` is distributed as platform‑specific wheels. On Android’s native Bionic libc runtime, the standard `manylinux` wheel cannot load directly. For full production execution on Android, run inside a Linux container (e.g., Termux + PRoot Ubuntu) or utilize the simulation fallback for UI and API workflow development.

## Installation

### Desktop / Server

```bash
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
python -m venv .venv
source .venv/bin/activate      # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

# Optional: install the native engine
# pip install cactus-needle

python app.py
```

Open `http://127.0.0.1:5000` in your browser.

### Android (Pydroid 3 or Termux)

#### Option A — Pydroid 3 (Simplest)

1. Install **Pydroid 3** from the Google Play Store.
2. Open Pydroid 3 → Menu → Pip → Search & Install `flask`.
3. Copy/extract the repository folder to your storage (e.g., `Download/Needle3`).
4. In Pydroid 3, open `app.py` and tap **Run**.
5. Open your mobile browser and navigate to `http://127.0.0.1:5000`.

*Note: Pydroid 3 uses Android's native Python runtime; `cactus-needle` will automatically default to simulation mode.*

#### Option B — Termux (Recommended for Native Engine)

```bash
pkg update && pkg upgrade -y
pkg install python git -y
git clone https://github.com/DwaipayanDutta/Needle3.git
cd Needle3
pip install flask

# For the native engine, setup PRoot Ubuntu in Termux, then:
# pip install cactus-needle

python app.py
```

## Usage

### Web UI

1. Start the server:
   ```bash
   python app.py
   ```
2. Open `http://127.0.0.1:5000` (or `http://<your-phone-ip>:5000` from another device on the same local network).
3. Type a message and tap **Send**.

### CLI Mode

A terminal client is provided via `termux_needle.py` for direct CLI interaction:

```bash
python termux_needle.py
```

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
| ----- | ----- | ----- |
| `FLASK_PORT` / `PORT` | `5000` | Custom port configuration for the Flask server |
| `FLASK_HOST` | `0.0.0.0` | Host interface IP binding |
| `NEEDLE_TELEMETRY` | `1` | Set to `0` to disable anonymous usage metrics |
| `DO_NOT_TRACK` | – | Alternative flag to disable telemetry (`DO_NOT_TRACK=1`) |

## Project Structure

```
Needle3/
├── app.py              # Flask server, mobile HTML UI, and /chat endpoint
├── termux_needle.py    # Terminal CLI interface (simulation-aware)
├── tools.py            # Custom tool definitions (@needle.tool)
├── requirements.txt    # Base Python dependencies
├── .gitignore          # Version control ignore patterns
├── LICENSE             # Apache-2.0 License
└── README.md           # Project documentation
```

## Troubleshooting

* **App starts but replies with `[Simulation] ...`**
  The native `cactus-needle` engine is not installed in the active environment. This is expected behavior on Pydroid 3 or raw Termux without PRoot.
* **Port 5000 is already in use**
  Launch Flask on another port by passing an environment variable:
  ```bash
  FLASK_PORT=8080 python app.py
  ```

## License

Distributed under the Apache-2.0 License. See `LICENSE` for more information.
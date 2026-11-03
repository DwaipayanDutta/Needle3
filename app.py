# app.py – Needle3 Mobile Interface & Automation Server
import os, sys, json, subprocess, signal, logging, threading, webbrowser
from flask import Flask, request, jsonify, render_template_string, send_from_directory

# --- 1. Logging Setup ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --- 2. Port Conflict Cleanup --------------------------------------------------
def release_port(port=5000):
    """Automatically frees the specified port before starting the server."""
    try:
        current_pid = str(os.getpid())
        if sys.platform.startswith("win"):
            # Windows port cleanup
            cmd = f'netstat -aon | findstr :{port}'
            output = subprocess.check_output(cmd, shell=True).decode()
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if pid != "0" and pid != current_pid:
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stderr=subprocess.DEVNULL)
        else:
            # Linux / Termux / macOS port cleanup
            cmd = f"lsof -t -i:{port}"
            pids = subprocess.check_output(cmd, shell=True).decode().strip().split()
            for pid in pids:
                if pid and pid != current_pid:
                    logging.info(f"Port {port} in use by PID {pid}. Terminating process...")
                    os.kill(int(pid), signal.SIGKILL)
    except Exception:
        pass

# The port is released in the main runner, once the configured port is known.

# --- 3. Needle Import & Execution Engine ---------------------------------------
HAS_NATIVE_NEEDLE = False
try:
    import needle
    HAS_NATIVE_NEEDLE = True
except ImportError:
    class _StubNeedle:
        @staticmethod
        def tool(func):
            return func

        @staticmethod
        def run(prompt: str, **kwargs):
            prompt_clean = prompt.strip()
            
            # Direct System Execution Handling
            if prompt_clean.lower().startswith("exec "):
                cmd = prompt_clean[5:].strip()
                try:
                    res = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=10)
                    return {"response": res.decode('utf-8', errors='replace')}
                except subprocess.TimeoutExpired:
                    return {"response": "Error: Command timed out after 10 seconds."}
                except subprocess.CalledProcessError as e:
                    return {"response": f"Error (Exit {e.returncode}):\n{e.output.decode('utf-8', errors='replace')}"}

            # Pre-configured helper shortcuts
            if prompt_clean.lower() in ["hostname", "whoami", "uptime", "pwd", "dir", "ls"]:
                try:
                    res = subprocess.check_output(prompt_clean, shell=True, stderr=subprocess.STDOUT, timeout=5)
                    return {"response": res.decode('utf-8', errors='replace')}
                except Exception as e:
                    return {"response": f"Execution error: {str(e)}"}

            return {
                "response": f"[Simulation Engine] Processed prompt: \"{prompt}\".\nTip: Type 'exec <command>' (e.g., 'exec ls' or 'exec ipconfig') to run direct terminal commands."
            }

    needle = _StubNeedle()
    logging.warning("cactus-needle native library not found. Falling back to execution simulation.")

# --- 4. Flask Application Setup ------------------------------------------------
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# --- 5. Massive Monster Styled Mobile UI ---------------------------------------
MOBILE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Needle3 Engine</title>
  <style>
    :root {
      --bg-red: #d9232a;
      --card-bg: #ffffff;
      --text-dark: #1a1a1a;
      --accent-black: #0d0d0d;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0; padding: 1rem;
      background-color: var(--bg-red);
      color: var(--text-dark);
      display: flex; flex-direction: column; align-items: center; min-height: 100vh;
    }
    .container {
      width: 100%; max-width: 600px;
      background: var(--card-bg);
      border-radius: 16px;
      padding: 1.25rem;
      box-shadow: 0 10px 25px rgba(0,0,0,0.3);
      display: flex; flex-direction: column; height: 90vh;
    }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      border-bottom: 3px solid var(--bg-red);
      padding-bottom: 0.75rem; margin-bottom: 1rem;
    }
    .brand { display: flex; align-items: center; gap: 0.6rem; }
    .brand svg { width: 36px; height: 36px; fill: var(--bg-red); }
    .brand h1 { margin: 0; font-size: 1.4rem; font-weight: 900; letter-spacing: 1px; color: var(--bg-red); }
    .badge {
      font-size: 0.7rem; font-weight: bold; padding: 4px 8px; border-radius: 12px;
      text-transform: uppercase; letter-spacing: 0.5px;
    }
    .badge-sim { background: #fff0f0; color: var(--bg-red); border: 1px solid var(--bg-red); }
    .badge-native { background: #e6ffed; color: #1a7f37; border: 1px solid #1a7f37; }

    #chat-box {
      flex: 1; overflow-y: auto; background: #f8f9fa;
      border: 2px solid #eee; border-radius: 10px;
      padding: 0.8rem; margin-bottom: 1rem;
      display: flex; flex-direction: column; gap: 0.75rem;
    }
    .msg { max-width: 85%; padding: 0.6rem 0.9rem; border-radius: 8px; font-size: 0.95rem; line-height: 1.4; word-break: break-word; }
    .msg.user { align-self: flex-end; background: var(--bg-red); color: white; border-bottom-right-radius: 2px; }
    .msg.bot { align-self: flex-start; background: #e9ecef; color: #212529; border-bottom-left-radius: 2px; }
    .msg pre { margin: 0; font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; }

    .shortcuts { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; overflow-x: auto; padding-bottom: 4px; }
    .chip {
      background: #f1f3f5; border: 1px solid #ced4da; border-radius: 12px;
      padding: 4px 10px; font-size: 0.75rem; font-weight: 600; cursor: pointer; white-space: nowrap;
    }
    .chip:hover { background: var(--bg-red); color: white; border-color: var(--bg-red); }

    .input-group { display: flex; gap: 0.5rem; }
    input[type="text"] {
      flex: 1; padding: 0.75rem; border: 2px solid #ddd; border-radius: 8px; font-size: 0.95rem; outline: none;
    }
    input[type="text"]:focus { border-color: var(--bg-red); }
    button {
      background: var(--bg-red); color: white; border: none; border-radius: 8px;
      padding: 0.75rem 1.25rem; font-weight: bold; cursor: pointer;
    }
    button:active { transform: scale(0.98); }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="brand">
        <svg viewBox="0 0 100 100">
          <path d="M 50,10 C 30,10 20,25 20,45 C 20,65 30,90 50,90 C 70,90 80,65 80,45 C 80,25 70,10 50,10 Z M 35,35 A 5,5 0 1,1 35,45 A 5,5 0 1,1 35,35 Z M 65,35 A 5,5 0 1,1 65,45 A 5,5 0 1,1 65,35 Z M 35,60 Q 50,75 65,60 Z"/>
        </svg>
        <h1>NEEDLE 3</h1>
      </div>
      <span class="badge {{ 'badge-native' if native else 'badge-sim' }}">
        {{ 'NATIVE ENGINE' if native else 'SIMULATION / EXEC MODE' }}
      </span>
    </div>

    <div id="chat-box">
      <div class="msg bot">Ready to accept commands. Type <code>exec &lt;cmd&gt;</code> to run terminal commands remotely.</div>
    </div>

    <div class="shortcuts">
      <span class="chip" onclick="quickSend('hostname')">hostname</span>
      <span class="chip" onclick="quickSend('whoami')">whoami</span>
      <span class="chip" onclick="quickSend('exec uptime')">uptime</span>
      <span class="chip" onclick="quickSend('exec dir')">dir / ls</span>
    </div>

    <div class="input-group">
      <input id="prompt" type="text" placeholder="Enter prompt or exec command..." autocomplete="off" onkeydown="if(event.key==='Enter') send()">
      <button onclick="send()">Send</button>
    </div>
  </div>

  <script>
    function quickSend(cmd) {
      document.getElementById('prompt').value = cmd;
      send();
    }
    async function send() {
      const input = document.getElementById('prompt');
      const text = input.value.trim();
      if (!text) return;

      append('user', text);
      input.value = '';

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt: text})
        });
        const data = await res.json();
        const responseText = data.response || JSON.stringify(data, null, 2);
        append('bot', responseText);
      } catch (err) {
        append('bot', 'Error communicating with host server: ' + err.message);
      }
    }

    function append(role, text) {
      const box = document.getElementById('chat-box');
      const div = document.createElement('div');
      div.className = 'msg ' + role;
      if (text.includes('\n')) {
        const pre = document.createElement('pre');
        pre.textContent = text;
        div.appendChild(pre);
      } else {
        div.textContent = text;
      }
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
    }
  </script>
</body>
</html>
"""

# --- 6. UI Serving ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_FILE = "sandbox.html"

def serve_sandbox():
    """Serve the standalone sandbox UI; fall back to the classic chat page."""
    sandbox_path = os.path.join(BASE_DIR, SANDBOX_FILE)
    if os.path.isfile(sandbox_path):
        response = send_from_directory(BASE_DIR, SANDBOX_FILE)
        response.headers["Cache-Control"] = "no-store"
        return response

    logging.warning("sandbox.html not found; serving the classic mobile chat UI instead.")
    return render_template_string(MOBILE_HTML, native=HAS_NATIVE_NEEDLE)

def open_browser(port):
    """Open the sandbox in the default browser once the server is up."""
    url = f"http://127.0.0.1:{port}/"
    try:
        logging.info(f"Opening the sandbox UI at {url}")
        if not webbrowser.open(url):
            logging.info("No browser available; open the URL manually.")
    except Exception as exc:
        logging.warning(f"Could not open a browser automatically: {exc}")

# --- 7. Endpoints -------------------------------------------------------------
@app.route("/")
def index():
    return serve_sandbox()

@app.route("/sandbox")
def sandbox():
    return serve_sandbox()

@app.route("/classic")
def classic():
    return render_template_string(MOBILE_HTML, native=HAS_NATIVE_NEEDLE)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"error": "Missing prompt"}), 400

    result = needle.run(prompt)
    if isinstance(result, str):
        return jsonify({"response": result})
    return jsonify(result)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "native_engine": HAS_NATIVE_NEEDLE})

# --- 8. Main Runner -----------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", os.environ.get("PORT", 5000)))
    release_port(port)
    logging.info(f"Starting Needle3 server on 0.0.0.0:{port}...")
    logging.info(f"Sandbox UI:   http://127.0.0.1:{port}/")
    logging.info(f"Classic UI:   http://127.0.0.1:{port}/classic")

    if os.environ.get("NEEDLE_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"}:
        opener = threading.Timer(1.2, open_browser, args=(port,))
        opener.daemon = True
        opener.start()

    app.run(host="0.0.0.0", port=port, debug=False)

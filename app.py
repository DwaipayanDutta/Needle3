import os
import sys
import logging
import subprocess
import platform
import json
from flask import Flask, request, jsonify, render_template_string

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("needle_app")

# --- 1. Robust Needle Engine Import & Local Fallback Execution ---
IS_SIMULATION = False

def execute_system_command(command: str) -> dict:
    """Executes a system command locally and captures stdout/stderr."""
    try:
        # Run command in shell safely returning output
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip(),
            "returncode": res.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command execution timed out after 30 seconds."}
    except Exception as e:
        return {"error": str(e)}

try:
    import needle
    logger.info("Successfully imported native 'needle' module.")
except ImportError:
    IS_SIMULATION = True
    logger.warning("cactus-needle package not found. Activating LOCAL EXECUTION / SIMULATION mode.")

    class _StubNeedle:
        """Fallback engine that actually executes system commands on the host machine."""
        @staticmethod
        def tool(func):
            return func

        @staticmethod
        def run(prompt: str, **kwargs):
            # Parse prefix command triggers for command execution from remote clients
            if prompt.startswith("exec ") or prompt.startswith("run "):
                cmd = prompt.split(" ", 1)[1]
                result = execute_system_command(cmd)
                output = result.get("stdout") or result.get("stderr") or result.get("error") or "Executed successfully (no output)."
                return {
                    "response": f"[Host Output ({platform.system()})]\n{output}",
                    "raw": result,
                    "status": "executed"
                }

            return {
                "response": f"[Simulation] Host system IP listening on network. Received command: '{prompt}'. (Tip: Start prompt with 'exec <cmd>' to execute shell commands remotely)",
                "system_info": {
                    "platform": platform.platform(),
                    "python_version": sys.version.split()[0]
                },
                "status": "simulated"
            }

    needle = _StubNeedle()

# --- 2. Configuration & Flask App Setup ---
app = Flask(__name__)

# Allow cross-origin requests so external web apps / clients can send commands
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

PORT = int(os.environ.get("FLASK_PORT", os.environ.get("PORT", 5000)))
HOST = os.environ.get("FLASK_HOST", "0.0.0.0")  # Listens on all network interfaces
API_KEY = os.environ.get("NEEDLE_API_KEY", None) # Optional authorization key

# Red & White Massive Monster Inspired Mobile & Remote Control HTML Interface
MOBILE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>Needle 3 — Massive Monster Control Console</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap');
    
    body {
      font-family: 'Inter', sans-serif;
      background-color: #0d0d0d;
      color: #f3f4f6;
    }

    .mono {
      font-family: 'JetBrains-Mono', monospace;
    }

    /* Custom Scrollbar for Chat Container */
    #chat::-webkit-scrollbar {
      width: 6px;
    }
    #chat::-webkit-scrollbar-track {
      background: #171717;
    }
    #chat::-webkit-scrollbar-thumb {
      background: #dc2626;
      border-radius: 3px;
    }

    .monster-red {
      background-color: #e51d25;
    }
    .monster-red-dark {
      background-color: #b91c1c;
    }
    .monster-border {
      border-color: #e51d25;
    }
  </style>
</head>
<body class="h-screen flex flex-col justify-between max-w-4xl mx-auto p-2 sm:p-4">

  <!-- Header Banner with Massive Monster Branding -->
  <header class="monster-red rounded-xl p-4 shadow-lg text-white mb-3 flex flex-wrap justify-between items-center gap-3">
    <div class="flex items-center space-x-3">
      <!-- Embedded Massive Monster Style SVG Logo -->
      <div class="bg-white p-2 rounded-lg shadow-md flex items-center justify-center w-12 h-12 flex-shrink-0">
        <svg viewBox="0 0 100 120" class="w-8 h-8 fill-[#e51d25]">
          <path d="M 20 20 L 10 35 L 25 35 Z"/>
          <path d="M 80 20 L 90 35 L 75 35 Z"/>
          <path d="M 20 30 Q 50 15 80 30 Q 90 60 85 90 Q 50 100 15 90 Q 10 60 20 30 Z" />
          <circle cx="35" cy="45" r="5" fill="#e51d25"/>
          <circle cx="65" cy="45" r="5" fill="#e51d25"/>
          <path d="M 30 60 Q 50 75 70 55 Q 55 80 30 60 Z" fill="#e51d25"/>
        </svg>
      </div>
      <div>
        <h1 class="font-extrabold text-lg sm:text-xl tracking-tight leading-none uppercase">Needle 3</h1>
        <p class="text-xs font-semibold text-red-100 uppercase tracking-widest mt-1">Massive Monster Control Console</p>
      </div>
    </div>

    <!-- Status Badge -->
    <div class="flex items-center space-x-2">
      <span class="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-white text-[#e51d25] shadow-sm">
        {{ 'Local Exec Engine' if is_sim else 'Native Engine' }}
      </span>
    </div>
  </header>

  <!-- Network & Quick Commands Tool Bar -->
  <div class="bg-neutral-900 border border-neutral-800 rounded-lg p-2.5 mb-3 flex flex-wrap justify-between items-center text-xs text-neutral-400 gap-2">
    <div class="flex items-center space-x-2">
      <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
      <span>Host: <strong class="text-white mono">{{ request.host }}</strong></span>
    </div>
    <div class="flex items-center space-x-1.5 overflow-x-auto py-1">
      <span class="text-neutral-500 font-semibold mr-1">Shortcuts:</span>
      <button onclick="quickCmd('exec hostname')" class="bg-neutral-800 hover:bg-red-700 hover:text-white px-2 py-1 rounded transition">hostname</button>
      <button onclick="quickCmd('exec uptime')" class="bg-neutral-800 hover:bg-red-700 hover:text-white px-2 py-1 rounded transition">uptime</button>
      <button onclick="quickCmd('exec whoami')" class="bg-neutral-800 hover:bg-red-700 hover:text-white px-2 py-1 rounded transition">whoami</button>
    </div>
  </div>

  <!-- Chat Log Output Window -->
  <main id="chat" class="flex-1 bg-neutral-900 border border-neutral-800 rounded-xl p-4 overflow-y-auto space-y-3 mb-3 shadow-inner">
    <div class="bg-neutral-800/60 border border-neutral-700/50 p-3 rounded-lg text-xs text-neutral-300">
      <strong class="text-red-400">⚡ Console Ready:</strong> Enter natural language queries or execute direct host commands by prefixing with <code class="bg-neutral-900 px-1.5 py-0.5 rounded text-red-300 mono">exec &lt;command&gt;</code>.
    </div>
  </main>

  <!-- Input Form & Controls -->
  <form id="input-area" onsubmit="send(event)" class="flex gap-2">
    <input 
      id="prompt" 
      type="text" 
      placeholder="Type prompt or 'exec <command>' to execute..." 
      autocomplete="off" 
      required
      class="flex-1 bg-neutral-900 border border-neutral-700 focus:border-red-600 focus:ring-1 focus:ring-red-600 rounded-xl px-4 py-3 text-white placeholder-neutral-500 text-sm outline-none transition mono"
    />
    <button 
      id="send-btn" 
      type="submit" 
      class="monster-red hover:bg-red-700 active:bg-red-800 text-white font-bold px-6 py-3 rounded-xl shadow-lg transition flex items-center justify-center gap-2"
    >
      <span>Send</span>
      <svg class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </form>

  <script>
    function quickCmd(cmd) {
      const input = document.getElementById('prompt');
      input.value = cmd;
      send();
    }

    async function send(e) {
      if (e) e.preventDefault();
      const input = document.getElementById('prompt');
      const btn = document.getElementById('send-btn');
      const text = input.value.trim();
      if (!text) return;

      appendMsg('user', text);
      input.value = '';
      input.disabled = true;
      btn.disabled = true;

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt: text})
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Server processing error');
        
        const reply = typeof data.response === 'string' ? data.response : JSON.stringify(data, null, 2);
        appendMsg('bot', reply);
      } catch (err) {
        appendMsg('error', 'Error: ' + err.message);
      } finally {
        input.disabled = false;
        btn.disabled = false;
        input.focus();
      }
    }

    function appendMsg(role, text) {
      const chat = document.getElementById('chat');
      const div = document.createElement('div');
      
      if (role === 'user') {
        div.className = 'ml-auto max-w-[85%] bg-neutral-800 border-l-4 border-red-600 text-white p-3 rounded-r-lg rounded-tl-lg text-sm shadow-md';
      } else if (role === 'bot') {
        div.className = 'mr-auto max-w-[90%] bg-neutral-950 border border-neutral-800 text-neutral-200 p-3 rounded-lg text-sm shadow-md mono whitespace-pre-wrap';
      } else {
        div.className = 'mx-auto max-w-[90%] bg-red-950/80 border border-red-800 text-red-200 p-2.5 rounded-lg text-xs text-center';
      }

      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }
  </script>
</body>
</html>
"""

# --- 3. Endpoints & Control Handlers ---
@app.route("/", methods=["GET"])
def index():
    """Serves the remote command web UI."""
    return render_template_string(MOBILE_HTML, is_sim=IS_SIMULATION)

@app.route("/health", methods=["GET"])
def health():
    """Health check and network status endpoint."""
    return jsonify({
        "status": "online",
        "system": platform.platform(),
        "simulation_mode": IS_SIMULATION,
        "host_ip": request.host
    }), 200

@app.route("/chat", methods=["OPTIONS", "POST"])
def chat():
    """Main remote command & inference entry point."""
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    # Optional API key authorization
    if API_KEY:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.replace("Bearer ", "") != API_KEY:
            return jsonify({"error": "Unauthorized access: invalid API Key"}), 401

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json(silent=True)
    if not data or "prompt" not in data:
        return jsonify({"error": "Missing 'prompt' in request body"}), 400

    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    logger.info(f"Received remote command from {request.remote_addr}: '{prompt}'")

    try:
        result = needle.run(prompt)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to execute: {str(e)}"}), 500

if __name__ == "__main__":
    logger.info(f"Starting Needle Control Server on http://{HOST}:{PORT}")
    logger.info("Access from other systems on your local Wi-Fi / network using the host IP address.")
    app.run(host=HOST, port=PORT, debug=False)
import os
import sys
import logging
from flask import Flask, request, jsonify, render_template_string

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("needle_app")

# --- 1. Robust Needle Engine Import & Fallback ---
IS_SIMULATION = False

try:
    import needle
    logger.info("Successfully imported native 'needle' module.")
except ImportError:
    IS_SIMULATION = True
    logger.warning("cactus-needle package not found. Activating SIMULATION mode.")

    class _StubNeedle:
        """Fallback simulation class mirroring Needle's primary API interface."""
        @staticmethod
        def tool(func):
            """No-op decorator preserving function metadata."""
            return func

        @staticmethod
        def run(prompt: str, **kwargs):
            """Simulates response handling when native binary engine is absent."""
            return {
                "response": f"[Simulation] Processed prompt: '{prompt}'",
                "tool_calls": [],
                "status": "simulated"
            }

    needle = _StubNeedle()

# --- 2. Configuration & Initialization ---
app = Flask(__name__)

PORT = int(os.environ.get("FLASK_PORT", os.environ.get("PORT", 5000)))
HOST = os.environ.get("FLASK_HOST", "0.0.0.0")

# Mobile HTML UI Template
MOBILE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>Needle Mobile</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 1rem; background: #121212; color: #e0e0e0; display: flex; flex-direction: column; height: 100vh; }
    header { margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; }
    h1 { font-size: 1.25rem; margin: 0; font-weight: 600; }
    .status-badge { font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 12px; background: #333; color: #aaa; }
    .status-badge.sim { background: #5a3c00; color: #ffca28; }
    .status-badge.native { background: #0d47a1; color: #90caf9; }
    #chat { flex: 1; border: 1px solid #2a2a2a; border-radius: 8px; padding: 1rem; overflow-y: auto; background: #1e1e1e; display: flex; flex-direction: column; gap: 0.75rem; }
    .msg { padding: 0.6rem 0.8rem; border-radius: 6px; max-width: 85%; word-wrap: break-word; line-height: 1.4; font-size: 0.95rem; }
    .msg.user { align-self: flex-end; background: #005c4b; color: #e9edef; }
    .msg.bot { align-self: flex-start; background: #202c33; color: #e9edef; border: 1px solid #2a3942; }
    .msg.error { align-self: center; background: #421010; color: #ff8a80; font-size: 0.85rem; }
    #input-area { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
    #prompt { flex: 1; padding: 0.75rem; border-radius: 6px; border: 1px solid #333; background: #222; color: #fff; font-size: 1rem; outline: none; }
    #prompt:focus { border-color: #0084ff; }
    button { padding: 0.75rem 1.25rem; border: none; border-radius: 6px; background: #0084ff; color: white; font-weight: 600; font-size: 1rem; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
  </style>
</head>
<body>
  <header>
    <h1>📱 Needle Mobile</h1>
    <span class="status-badge {{ 'sim' if is_sim else 'native' }}">
      {{ 'Simulation Mode' if is_sim else 'Native Engine' }}
    </span>
  </header>
  <div id="chat"></div>
  <form id="input-area" onsubmit="send(event)">
    <input id="prompt" type="text" placeholder="Type a command or query..." autocomplete="off" required />
    <button id="send-btn" type="submit">Send</button>
  </form>
  <script>
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
        
        if (!res.ok) {
          throw new Error(data.error || 'Server error');
        }
        
        const reply = typeof data.response === 'string' ? data.response : JSON.stringify(data.response, null, 2);
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
      div.className = 'msg ' + role;
      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }
  </script>
</body>
</html>
"""

# --- 3. Route Handlers ---
@app.route("/", methods=["GET"])
def index():
    """Renders the mobile frontend."""
    return render_template_string(MOBILE_HTML, is_sim=IS_SIMULATION)

@app.route("/health", methods=["GET"])
def health():
    """Healthcheck endpoint."""
    return jsonify({
        "status": "healthy",
        "simulation_mode": IS_SIMULATION,
        "python_version": sys.version.split()[0]
    }), 200

@app.route("/chat", methods=["POST"])
def chat():
    """Handles incoming chat requests."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json(silent=True)
    if not data or "prompt" not in data:
        return jsonify({"error": "Missing 'prompt' field in payload"}), 400

    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    try:
        result = needle.run(prompt)
        if isinstance(result, str):
            return jsonify({"response": result, "status": "ok"})
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Inference error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to execute prompt: {str(e)}"}), 500

if __name__ == "__main__":
    logger.info(f"Starting Needle Web UI on {HOST}:{PORT} (Simulation Mode: {IS_SIMULATION})")
    app.run(host=HOST, port=PORT, debug=False)
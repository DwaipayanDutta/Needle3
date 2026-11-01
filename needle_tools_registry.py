import datetime
import json

try:
    import needle
except ImportError:
    class _StubNeedle:
        @staticmethod
        def tool(func):
            return func
    needle = _StubNeedle()

@needle.tool
def get_current_time(timezone: str = "UTC") -> str:
    """Returns the current system time."""
    now = datetime.datetime.now()
    return f"Current time ({timezone}): {now.strftime('%Y-%m-%d %H:%M:%S')}"

@needle.tool
def control_device(device_name: str, action: str) -> str:
    """Simulates smart home device control."""
    return f"Device '{device_name}' successfully executed action: '{action}'."

@needle.tool
def parse_invoice_text(text: str) -> str:
    """Extracts summary information from plain text invoice snippets."""
    return json.dumps({
        "status": "extracted",
        "input_length": len(text),
        "note": "Sample extraction result"
    })
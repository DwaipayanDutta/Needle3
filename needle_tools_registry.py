"""Sample tools that use the same safe implementations as the Needle3 backend.

This module is optional: the web app builds its registry from
`needle_engine.tool_registry`. It is kept for scripts and examples that want a
few `@needle.tool` functions to pass to `needle.Needle(tools=[...])`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from needle_engine.configuration import Settings
from needle_engine.tool_registry import default_registry

try:
    from needle import tool
except ImportError:
    def tool(function=None, **kwargs):
        def decorate(func):
            return func

        return decorate(function) if function is not None else decorate


_REGISTRY = default_registry(Settings(mode="simulation", file_root=Path.cwd()))


@tool
def get_current_time(timezone: str = "UTC") -> dict:
    """Return the current time for a timezone.

    Args:
        timezone: local, UTC, or an IANA name such as Asia/Kolkata.
    """
    return _REGISTRY.get("get_current_time").implementation(timezone=timezone)


@tool
def control_device(
    device: str,
    action: str,
    value: Optional[int] = None,
) -> dict:
    """Control a named simulated smart-home device.

    Args:
        device: The device name, for example 'bedroom lights'.
        action: One of on, off, toggle, dim, brighten, lock, unlock, set.
        value: Brightness or target value, when relevant.
    """
    return _REGISTRY.get("control_device").implementation(
        device=device,
        action=action,
        value=value,
    )


@tool
def parse_invoice_text(text: str) -> dict:
    """Extract merchant, amount, currency and due date from invoice text.

    Args:
        text: The source invoice or receipt text.
    """
    return _REGISTRY.get("parse_invoice_text").implementation(text=text)


SAFE_TOOLS = [get_current_time, control_device, parse_invoice_text]

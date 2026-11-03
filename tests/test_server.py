from __future__ import annotations

import socket

from needle_engine.server import _port_available


def test_port_check_detects_a_listening_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert _port_available("127.0.0.1", port) is False
    assert _port_available("127.0.0.1", port) is True

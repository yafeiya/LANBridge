from __future__ import annotations

import json
import socket
import threading
import time

from lanbridge.discovery import DISCOVERY_REQUEST, serve_discovery


def test_receiver_answers_discovery_request() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    stop = threading.Event()
    thread = threading.Thread(
        target=serve_discovery,
        args=(port, 45831, "ubuntu-test", stop, lambda _message: None),
    )
    thread.start()
    try:
        time.sleep(0.05)
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(1)
        client.sendto(DISCOVERY_REQUEST, ("127.0.0.1", port))
        data, _ = client.recvfrom(4096)
        response = json.loads(data)
        assert response["service"] == "lanbridge"
        assert response["name"] == "ubuntu-test"
        assert response["port"] == 45831
        client.close()
    finally:
        stop.set()
        thread.join(timeout=2)

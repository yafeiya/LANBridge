from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable

DISCOVERY_REQUEST = b"LANBRIDGE_DISCOVER_V1"


def serve_discovery(
    port: int,
    tcp_port: int,
    device_name: str,
    stop: threading.Event,
    logger: Callable[[str], None] = print,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    response = json.dumps(
        {"service": "lanbridge", "version": 1, "name": device_name, "port": tcp_port},
        ensure_ascii=False,
    ).encode("utf-8")
    logger(f"局域网发现服务已启动：UDP {port}")
    try:
        while not stop.is_set():
            try:
                data, address = sock.recvfrom(1024)
            except TimeoutError:
                continue
            if data == DISCOVERY_REQUEST:
                sock.sendto(response, address)
    finally:
        sock.close()


def discover(port: int, timeout: float = 2.0) -> list[dict[str, object]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.2)
    sock.sendto(DISCOVERY_REQUEST, ("255.255.255.255", port))
    deadline = time.monotonic() + timeout
    found: dict[tuple[str, int], dict[str, object]] = {}
    while time.monotonic() < deadline:
        try:
            data, address = sock.recvfrom(4096)
        except TimeoutError:
            continue
        try:
            item = json.loads(data.decode("utf-8"))
            if item.get("service") != "lanbridge":
                continue
            item["host"] = address[0]
            found[(address[0], int(item["port"]))] = item
        except (ValueError, KeyError, UnicodeDecodeError):
            continue
    sock.close()
    return list(found.values())

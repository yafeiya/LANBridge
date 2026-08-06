from __future__ import annotations

import secrets
import socket
import threading

import pytest

from lanbridge.crypto import client_handshake, server_handshake


def test_encrypted_channel_is_bidirectional() -> None:
    left, right = socket.socketpair()
    secret = secrets.token_bytes(32)
    result = {}

    def server() -> None:
        channel = server_handshake(right, secret)
        result["request"] = channel.receive()
        channel.send({"type": "reply", "text": "来自 Ubuntu"})

    thread = threading.Thread(target=server)
    thread.start()
    client = client_handshake(left, secret)
    client.send({"type": "hello", "text": "来自 Windows"})
    assert client.receive() == {"type": "reply", "text": "来自 Ubuntu"}
    thread.join(timeout=2)
    assert result["request"] == {"type": "hello", "text": "来自 Windows"}
    left.close()
    right.close()


def test_wrong_pairing_token_is_rejected() -> None:
    left, right = socket.socketpair()
    client_secret = secrets.token_bytes(32)
    server_secret = secrets.token_bytes(32)
    result = {}

    def server() -> None:
        try:
            server_handshake(right, server_secret)
        except PermissionError as exc:
            result["error"] = exc
        finally:
            right.close()

    thread = threading.Thread(target=server)
    thread.start()
    with pytest.raises((ConnectionError, PermissionError)):
        client_handshake(left, client_secret)
    thread.join(timeout=2)
    assert isinstance(result["error"], PermissionError)
    left.close()

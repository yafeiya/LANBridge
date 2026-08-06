from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"LBR1"
MAX_FRAME = 1024 * 1024


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        data = sock.recv(remaining)
        if not data:
            raise ConnectionError("连接已关闭")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _send_plain(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _recv_plain(sock: socket.socket) -> bytes:
    size = struct.unpack("!I", _recv_exact(sock, 4))[0]
    if size > 4096:
        raise ValueError("握手数据过大")
    return _recv_exact(sock, size)


def _proof(secret: bytes, label: bytes, transcript: bytes) -> str:
    return hmac.new(secret, label + transcript, hashlib.sha256).hexdigest()


def _keys(secret: bytes, client_nonce: bytes, server_nonce: bytes) -> tuple[bytes, bytes]:
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=client_nonce + server_nonce,
        info=b"lanbridge-session-v1",
    ).derive(secret)
    return material[:32], material[32:]


@dataclass
class SecureChannel:
    sock: socket.socket
    send_key: bytes
    recv_key: bytes
    send_prefix: bytes
    recv_prefix: bytes
    send_counter: int = 0
    recv_counter: int = 0
    send_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def send(self, message: dict[str, Any]) -> None:
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_FRAME:
            raise ValueError("消息过大")
        with self.send_lock:
            counter = self.send_counter
            self.send_counter += 1
            nonce = self.send_prefix + counter.to_bytes(8, "big")
            aad = MAGIC + counter.to_bytes(8, "big")
            encrypted = ChaCha20Poly1305(self.send_key).encrypt(nonce, raw, aad)
            frame = counter.to_bytes(8, "big") + encrypted
            self.sock.sendall(struct.pack("!I", len(frame)) + frame)

    def receive(self) -> dict[str, Any]:
        size = struct.unpack("!I", _recv_exact(self.sock, 4))[0]
        if size < 24 or size > MAX_FRAME + 64:
            raise ValueError("加密帧长度无效")
        frame = _recv_exact(self.sock, size)
        counter = int.from_bytes(frame[:8], "big")
        if counter != self.recv_counter:
            raise ValueError("消息序号无效")
        self.recv_counter += 1
        nonce = self.recv_prefix + counter.to_bytes(8, "big")
        aad = MAGIC + counter.to_bytes(8, "big")
        raw = ChaCha20Poly1305(self.recv_key).decrypt(nonce, frame[8:], aad)
        message = json.loads(raw.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("消息格式无效")  # noqa: TRY004 - invalid protocol data
        return message

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def client_handshake(sock: socket.socket, secret: bytes) -> SecureChannel:
    client_nonce = secrets.token_bytes(16)
    request = {
        "magic": MAGIC.decode("ascii"),
        "nonce": client_nonce.hex(),
        "proof": _proof(secret, b"client", client_nonce),
    }
    _send_plain(sock, json.dumps(request, separators=(",", ":")).encode("ascii"))
    response = json.loads(_recv_plain(sock).decode("ascii"))
    if response.get("magic") != MAGIC.decode("ascii"):
        raise PermissionError("对端协议不匹配")
    server_nonce = bytes.fromhex(response["nonce"])
    transcript = client_nonce + server_nonce
    expected = _proof(secret, b"server", transcript)
    if not hmac.compare_digest(response.get("proof", ""), expected):
        raise PermissionError("对端身份验证失败")
    client_key, server_key = _keys(secret, client_nonce, server_nonce)
    prefixes = hashlib.sha256(transcript + b"nonce-prefix").digest()
    return SecureChannel(sock, client_key, server_key, prefixes[:4], prefixes[4:8])


def server_handshake(sock: socket.socket, secret: bytes) -> SecureChannel:
    request = json.loads(_recv_plain(sock).decode("ascii"))
    if request.get("magic") != MAGIC.decode("ascii"):
        raise PermissionError("客户端协议不匹配")
    client_nonce = bytes.fromhex(request["nonce"])
    expected = _proof(secret, b"client", client_nonce)
    if not hmac.compare_digest(request.get("proof", ""), expected):
        raise PermissionError("客户端配对令牌错误")
    server_nonce = secrets.token_bytes(16)
    transcript = client_nonce + server_nonce
    response = {
        "magic": MAGIC.decode("ascii"),
        "nonce": server_nonce.hex(),
        "proof": _proof(secret, b"server", transcript),
    }
    _send_plain(sock, json.dumps(response, separators=(",", ":")).encode("ascii"))
    client_key, server_key = _keys(secret, client_nonce, server_nonce)
    prefixes = hashlib.sha256(transcript + b"nonce-prefix").digest()
    return SecureChannel(sock, server_key, client_key, prefixes[4:8], prefixes[:4])

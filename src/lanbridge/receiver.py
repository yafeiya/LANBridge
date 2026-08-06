from __future__ import annotations

import os
import socket
import threading
import traceback

from .clipboard import ClipboardWatcher, make_clipboard
from .config import Config
from .crypto import SecureChannel, server_handshake
from .discovery import serve_discovery
from .input_codes import MOUSE_BUTTONS


def make_input_device():  # type: ignore[no-untyped-def]
    if os.name == "nt":
        from .windows_input import WindowsInputDevice

        return WindowsInputDevice()
    from .linux_uinput import UInputDevice

    return UInputDevice()


class Receiver:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.stop_event = threading.Event()
        self.input = make_input_device()
        self.clipboard = make_clipboard()
        self.channel: SecureChannel | None = None
        self.watcher: ClipboardWatcher | None = None
        self.pressed_keys: set[int] = set()
        self.pressed_buttons: set[int] = set()

    def run(self) -> None:
        discovery_thread = threading.Thread(
            target=serve_discovery,
            args=(
                self.config.discovery_port,
                self.config.tcp_port,
                self.config.device_name,
                self.stop_event,
            ),
            daemon=True,
            name="lanbridge-discovery",
        )
        discovery_thread.start()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", self.config.tcp_port))
        server.listen(2)
        server.settimeout(0.5)
        print(f"接收端已启动：TCP {self.config.tcp_port}，等待 Windows 主机连接…")
        try:
            while not self.stop_event.is_set():
                try:
                    client, address = server.accept()
                except TimeoutError:
                    continue
                print(f"收到来自 {address[0]} 的连接")
                try:
                    client.settimeout(10)
                    channel = server_handshake(client, self.config.token_bytes)
                    client.settimeout(None)
                    self._serve_client(channel)
                except PermissionError as exc:
                    print(f"拒绝连接：{exc}")
                    client.close()
                except (ConnectionError, OSError, ValueError) as exc:
                    print(f"连接结束：{exc}")
                except Exception:  # noqa: BLE001 - keep the receiver alive after a bad client
                    traceback.print_exc()
                finally:
                    self._release_all()
        finally:
            self.stop_event.set()
            server.close()
            self.input.close()

    def _serve_client(self, channel: SecureChannel) -> None:
        self.channel = channel
        hello = channel.receive()
        if hello.get("type") != "hello" or hello.get("role") != "controller":
            raise ValueError("客户端角色无效")
        channel.send(
            {
                "type": "hello",
                "role": "receiver",
                "name": self.config.device_name,
                "version": 1,
            }
        )
        print(f"已加密连接到 {hello.get('name', 'Windows 主机')}")
        self.watcher = ClipboardWatcher(self.clipboard, self._send_clipboard)
        self.watcher.start()
        try:
            while not self.stop_event.is_set():
                message = channel.receive()
                self._handle(message)
        finally:
            if self.watcher:
                self.watcher.close()
                self.watcher = None
            channel.close()
            self.channel = None

    def _send_clipboard(self, text: str) -> None:
        if self.channel:
            try:
                self.channel.send({"type": "clipboard", "text": text})
            except OSError:
                pass

    def _handle(self, message: dict[str, object]) -> None:
        kind = message.get("type")
        if kind == "key":
            code = int(message["code"])
            pressed = bool(message["pressed"])
            self.input.key(code, pressed)
            (self.pressed_keys.add if pressed else self.pressed_keys.discard)(code)
        elif kind == "button":
            code = MOUSE_BUTTONS.get(str(message["button"]))
            if code is not None:
                pressed = bool(message["pressed"])
                self.input.button(code, pressed)
                (self.pressed_buttons.add if pressed else self.pressed_buttons.discard)(code)
        elif kind == "move":
            self.input.move(int(message["dx"]), int(message["dy"]))
        elif kind == "scroll":
            self.input.scroll(int(message["dx"]), int(message["dy"]))
        elif kind == "enter":
            # The controller is directly left of this screen. Wayland does not
            # expose a global pointer position, so align the real pointer with
            # the controller's virtual X coordinate on every transition.
            inset = max(1, min(100, int(message.get("inset", 16))))
            edge = str(message.get("edge", "left"))
            if edge == "right":
                self.input.move(32767, 0)
                self.input.move(-inset, 0)
            else:
                self.input.move(-32767, 0)
                self.input.move(inset, 0)
            if self.channel:
                self.channel.send({"type": "entered", "inset": inset})
        elif kind == "clipboard":
            text = message.get("text")
            if isinstance(text, str) and self.watcher:
                try:
                    self.watcher.note_remote_value(text)
                    if self.channel:
                        self.channel.send({"type": "clipboard_ack", "length": len(text)})
                except RuntimeError as exc:
                    print(f"剪贴板同步失败：{exc}")
                    if self.channel:
                        self.channel.send({"type": "clipboard_error", "message": str(exc)})
        elif kind == "release_all":
            self._release_all()
        elif kind == "ping" and self.channel:
            self.channel.send({"type": "pong"})

    def _release_all(self) -> None:
        for code in tuple(self.pressed_keys):
            self.input.key(code, False)
        for code in tuple(self.pressed_buttons):
            self.input.button(code, False)
        self.pressed_keys.clear()
        self.pressed_buttons.clear()

    def stop(self) -> None:
        self.stop_event.set()
        if self.channel:
            self.channel.close()


def run_receiver(config: Config) -> None:
    receiver = Receiver(config)
    try:
        receiver.run()
    except KeyboardInterrupt:
        receiver.stop()

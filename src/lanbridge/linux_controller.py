from __future__ import annotations

import socket
import threading
from typing import Any

from .clipboard import ClipboardWatcher, make_clipboard
from .config import Config
from .crypto import SecureChannel, client_handshake
from .discovery import discover
from .input_codes import MOUSE_BUTTONS, MouseMotionFilter

SWITCH_KEY = 88  # KEY_F12
CTRL_KEYS = {29, 97}
ALT_KEYS = {56, 100}
BUTTON_NAMES = {code: name for name, code in MOUSE_BUTTONS.items()}


class LinuxController:
    """Wayland-compatible controller using exclusive evdev device grabs."""

    def __init__(self, config: Config, host_override: str | None = None, sensitivity: float | None = None) -> None:
        try:
            from evdev import InputDevice, ecodes, list_devices
        except ImportError as exc:
            raise RuntimeError("缺少 evdev，请重新运行 pip install -e .") from exc
        self.InputDevice = InputDevice
        self.ecodes = ecodes
        self.list_devices = list_devices
        self.config = config
        self.host_override = host_override
        self.sensitivity = 1.0 if sensitivity is None else sensitivity
        self.motion_filter = MouseMotionFilter(self.sensitivity, max_delta=500)
        self.channel: SecureChannel | None = None
        self.connected = threading.Event()
        self.stop_event = threading.Event()
        self.remote_active = False
        self.devices: list[Any] = []
        self.device_threads: list[threading.Thread] = []
        self.grabbed: set[str] = set()
        self.pressed_keys: set[int] = set()
        self.suppress_until_release: set[int] = set()
        self.clipboard = make_clipboard()
        self.watcher = ClipboardWatcher(self.clipboard, self._send_clipboard)
        self.local_release: Any | None = None

    def _resolve_host(self) -> tuple[str, int]:
        host = self.host_override or self.config.peer_host
        if host:
            return host, self.config.tcp_port
        print("正在查找局域网中的接收端…")
        peers = discover(self.config.discovery_port)
        if not peers:
            raise RuntimeError("未发现接收端，请在界面中填写对端 IP")
        peer = peers[0]
        print(f"发现 {peer.get('name', '接收端')}：{peer['host']}")
        return str(peer["host"]), int(peer["port"])

    def _connect(self) -> None:
        host, port = self._resolve_host()
        sock = socket.create_connection((host, port), timeout=8)
        channel = client_handshake(sock, self.config.token_bytes)
        sock.settimeout(None)
        channel.send(
            {
                "type": "hello",
                "role": "controller",
                "name": self.config.device_name,
                "version": 1,
            }
        )
        reply = channel.receive()
        if reply.get("type") != "hello" or reply.get("role") != "receiver":
            channel.close()
            raise RuntimeError("接收端握手响应无效")
        self.channel = channel
        self.connected.set()
        print(f"已加密连接到 {reply.get('name', host)} ({host}:{port})")

    def _open_devices(self) -> None:
        from .linux_uinput import UInputDevice

        for path in self.list_devices():
            try:
                device = self.InputDevice(path)
                if device.name.startswith("LAN Bridge"):
                    device.close()
                    continue
                capabilities = device.capabilities()
                key_codes = set(capabilities.get(self.ecodes.EV_KEY, []))
                is_pointer = self.ecodes.EV_REL in capabilities
                is_keyboard = bool(key_codes & {28, 30, 57, *MOUSE_BUTTONS.values()})
                if not is_pointer and not is_keyboard:
                    device.close()
                    continue
                self.devices.append(device)
            except (OSError, PermissionError):
                continue
        if not self.devices:
            raise PermissionError("未找到可访问的物理键鼠设备；请确认当前用户属于 input 组")
        self.local_release = UInputDevice()
        print(f"已检测到 {len(self.devices)} 个物理输入设备")

    def run(self) -> None:
        self._connect()
        self._open_devices()
        self.watcher.start()
        if self.watcher.last_value is not None:
            self._send_clipboard(self.watcher.last_value)
        threading.Thread(target=self._receive_loop, daemon=True, name="linux-controller-network").start()
        for device in self.devices:
            thread = threading.Thread(
                target=self._device_loop,
                args=(device,),
                daemon=True,
                name=f"linux-input-{device.path}",
            )
            thread.start()
            self.device_threads.append(thread)
        print("主控端已启动。按 Ctrl+Alt+F12 切换 Windows/Ubuntu 控制目标。")
        try:
            while self.connected.is_set() and not self.stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _device_loop(self, device: Any) -> None:
        try:
            for event in device.read_loop():
                if self.stop_event.is_set():
                    break
                self._handle_event(event)
        except OSError:
            pass

    def _handle_event(self, event: Any) -> None:
        if event.type == self.ecodes.EV_KEY:
            pressed = event.value != 0
            if pressed:
                self.pressed_keys.add(event.code)
            else:
                self.pressed_keys.discard(event.code)
                if event.code in self.suppress_until_release:
                    self.suppress_until_release.discard(event.code)
                    return
            has_ctrl = bool(self.pressed_keys & CTRL_KEYS)
            has_alt = bool(self.pressed_keys & ALT_KEYS)
            if event.code == SWITCH_KEY and event.value == 1 and has_ctrl and has_alt:
                self._toggle_remote()
                return
            if not self.remote_active:
                return
            button = BUTTON_NAMES.get(event.code)
            if button:
                self._send({"type": "button", "button": button, "pressed": pressed})
            else:
                self._send({"type": "key", "code": event.code, "pressed": pressed})
        elif self.remote_active and event.type == self.ecodes.EV_REL:
            if event.code in (self.ecodes.REL_X, self.ecodes.REL_Y):
                dx = event.value if event.code == self.ecodes.REL_X else 0
                dy = event.value if event.code == self.ecodes.REL_Y else 0
                dx, dy = self.motion_filter.apply(dx, dy)
                if dx or dy:
                    self._send({"type": "move", "dx": dx, "dy": dy})
            elif event.code == self.ecodes.REL_WHEEL:
                self._send({"type": "scroll", "dx": 0, "dy": event.value})
            elif event.code == self.ecodes.REL_HWHEEL:
                self._send({"type": "scroll", "dx": event.value, "dy": 0})

    def _toggle_remote(self) -> None:
        if self.remote_active:
            self._send({"type": "release_all"})
            self.remote_active = False
            self._ungrab_all()
            print("控制目标：Ubuntu")
            return
        grabbed_now: list[Any] = []
        try:
            for device in self.devices:
                device.grab()
                grabbed_now.append(device)
                self.grabbed.add(device.path)
        except OSError as exc:
            for device in grabbed_now:
                try:
                    device.ungrab()
                except OSError:
                    pass
            self.grabbed.clear()
            print(f"错误：无法独占输入设备：{exc}")
            return
        self.suppress_until_release.update(self.pressed_keys)
        if self.local_release:
            for code in self.pressed_keys:
                self.local_release.key(code, False)
        self.remote_active = True
        self.motion_filter.reset()
        self._send({"type": "enter", "edge": "right", "inset": self.config.remote_entry_inset})
        print("控制目标：Windows")

    def _ungrab_all(self) -> None:
        for device in self.devices:
            if device.path not in self.grabbed:
                continue
            try:
                device.ungrab()
            except OSError:
                pass
        self.grabbed.clear()

    def _send(self, message: dict[str, Any]) -> None:
        if not self.channel or not self.connected.is_set():
            return
        try:
            self.channel.send(message)
        except (ConnectionError, OSError):
            self.connected.clear()

    def _send_clipboard(self, text: str) -> None:
        self._send({"type": "clipboard", "text": text})

    def _receive_loop(self) -> None:
        assert self.channel is not None
        try:
            while not self.stop_event.is_set():
                message = self.channel.receive()
                if message.get("type") == "clipboard" and isinstance(message.get("text"), str):
                    self.watcher.note_remote_value(str(message["text"]))
                elif message.get("type") == "clipboard_error":
                    print(f"对端剪贴板同步失败：{message.get('message', '未知错误')}")
        except (ConnectionError, OSError, ValueError):
            if not self.stop_event.is_set():
                print("与接收端的连接已断开")
        finally:
            self.connected.clear()

    def stop(self) -> None:
        self.stop_event.set()
        if self.remote_active:
            self._send({"type": "release_all"})
        self.remote_active = False
        self._ungrab_all()
        self.watcher.close()
        if self.channel:
            self.channel.close()
        for device in self.devices:
            try:
                device.close()
            except OSError:
                pass
        if self.local_release:
            self.local_release.close()
            self.local_release = None


def run_controller(
    config: Config,
    host: str | None = None,
    sensitivity: float | None = None,
    _debug_mouse: bool = False,
) -> None:
    LinuxController(config, host, sensitivity).run()

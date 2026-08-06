from __future__ import annotations

import ctypes
import os
import socket
import threading
import time
from typing import Any

from .clipboard import ClipboardWatcher, make_clipboard
from .config import Config
from .crypto import SecureChannel, client_handshake
from .discovery import discover
from .input_codes import VK_TO_LINUX, MouseMotionFilter


def enable_per_monitor_dpi_awareness() -> None:
    """Keep Win32 hooks, screen metrics and SetCursorPos in physical pixels."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_bool
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        set_context(ctypes.c_void_p(-4))
        return
    except AttributeError:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_long
        shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


class WindowsController:
    def __init__(
        self,
        config: Config,
        host_override: str | None = None,
        sensitivity: float | None = None,
        debug_mouse: bool = False,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("当前 MVP 的主控端需要运行在 Windows")
        enable_per_monitor_dpi_awareness()
        try:
            from pynput import keyboard, mouse
        except ImportError as exc:
            raise RuntimeError("缺少 pynput，请执行：pip install -e .") from exc
        self.keyboard_module = keyboard
        self.mouse_module = mouse
        self.config = config
        self.host_override = host_override
        self.channel: SecureChannel | None = None
        self.connected = threading.Event()
        self.stop_event = threading.Event()
        self.remote_active = False
        self.edge_armed = True
        self.warping = False
        self.last_switch = 0.0
        self.remote_x = config.remote_entry_inset
        self.width = ctypes.windll.user32.GetSystemMetrics(0)
        self.height = ctypes.windll.user32.GetSystemMetrics(1)
        self.center = (self.width // 2, self.height // 2)
        self.mouse_controller = mouse.Controller()
        self.clipboard = make_clipboard()
        self.watcher = ClipboardWatcher(self.clipboard, self._send_clipboard)
        self.pressed_vks: set[int] = set()
        self.mouse_listener: Any | None = None
        self.keyboard_listener: Any | None = None
        self.debug_mouse = debug_mouse
        self.debug_mouse_samples = 0
        selected_sensitivity = config.mouse_sensitivity if sensitivity is None else sensitivity
        if not 0.05 <= selected_sensitivity <= 2.0:
            raise ValueError("鼠标灵敏度必须在 0.05～2.0 之间")
        self.motion_filter = MouseMotionFilter(selected_sensitivity, config.max_mouse_delta)
        self.selected_sensitivity = selected_sensitivity

    def run(self) -> None:
        self._connect()
        self.watcher.start()
        if self.watcher.last_value is not None:
            self._send_clipboard(self.watcher.last_value)
        receiver_thread = threading.Thread(target=self._receive_loop, daemon=True, name="network-receiver")
        receiver_thread.start()

        self.mouse_listener = self.mouse_module.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            win32_event_filter=self._mouse_filter,
        )
        self.keyboard_listener = self.keyboard_module.Listener(
            on_press=lambda key: self._on_key(key, True),
            on_release=lambda key: self._on_key(key, False),
            win32_event_filter=self._keyboard_filter,
        )
        self.mouse_listener.start()
        self.keyboard_listener.start()
        print("主控端已启动。将鼠标移出主屏幕右边缘即可控制 Ubuntu。")
        print(
            f"Windows 主屏幕（物理像素）：{self.width}x{self.height}；"
            f"鼠标倍率：{self.selected_sensitivity:g}"
        )
        print("远程控制时按 Ctrl+Alt+Esc 可立即返回 Windows；Ctrl+C 退出。")
        try:
            while self.connected.is_set() and not self.stop_event.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self._deactivate_remote()
            self.stop_event.set()
            self.mouse_listener.stop()
            self.keyboard_listener.stop()
            self.watcher.close()
            if self.channel:
                self.channel.close()

    def _resolve_host(self) -> tuple[str, int]:
        host = self.host_override or self.config.peer_host
        if host:
            return host, self.config.tcp_port
        print("正在查找局域网中的 Ubuntu 接收端…")
        peers = discover(self.config.discovery_port)
        if not peers:
            raise RuntimeError("未发现接收端；可使用 --host <Ubuntu-IP> 指定地址")
        peer = peers[0]
        print(f"发现 {peer.get('name', 'Ubuntu')}：{peer['host']}")
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
                "screen": {"width": self.width, "height": self.height},
            }
        )
        reply = channel.receive()
        if reply.get("type") != "hello" or reply.get("role") != "receiver":
            channel.close()
            raise RuntimeError("接收端握手响应无效")
        self.channel = channel
        self.connected.set()
        print(f"已加密连接到 {reply.get('name', host)} ({host}:{port})")

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
                elif message.get("type") == "clipboard_ack":
                    print(f"剪贴板已同步至 Ubuntu（{int(message.get('length', 0))} 个字符）")
                elif message.get("type") == "clipboard_error":
                    print(f"Ubuntu 剪贴板同步失败：{message.get('message', '未知错误')}")
                elif message.get("type") == "entered" and self.debug_mouse:
                    print(f"Ubuntu 指针已对齐左边缘（内缩 {message.get('inset', 0)} 像素）")
        except (ConnectionError, OSError, ValueError):
            if not self.stop_event.is_set():
                print("与 Ubuntu 的连接已断开")
        finally:
            self.connected.clear()

    @staticmethod
    def _is_injected(data: Any) -> bool:
        return bool(getattr(data, "flags", 0) & 0x01)

    def _mouse_filter(self, _msg: int, data: Any) -> bool:
        return not self._is_injected(data)

    def _keyboard_filter(self, _msg: int, data: Any) -> bool:
        return not self._is_injected(data)

    def _set_suppression(self, enabled: bool) -> None:
        # pynput exposes suppression as a read-only property, but the backing
        # flag is intentionally checked for every Windows hook event.
        if self.mouse_listener is not None:
            self.mouse_listener._suppress = enabled
        if self.keyboard_listener is not None:
            self.keyboard_listener._suppress = enabled

    def _activate_remote(self) -> None:
        if self.remote_active or time.monotonic() - self.last_switch < 0.5:
            return
        self.remote_active = True
        self._set_suppression(True)
        self.remote_x = self.config.remote_entry_inset
        self.motion_filter.reset()
        self.last_switch = time.monotonic()
        self._send(
            {
                "type": "enter",
                "edge": "left",
                "inset": self.config.remote_entry_inset,
            }
        )
        self._warp_to_center()
        print("控制目标：Ubuntu")

    def _deactivate_remote(self) -> None:
        if not self.remote_active:
            return
        self._send({"type": "release_all"})
        self.remote_active = False
        self.edge_armed = False
        self.pressed_vks.clear()
        self.motion_filter.reset()
        self.last_switch = time.monotonic()
        self.warping = True
        park_x = max(0, self.width - self.config.edge_rearm_distance - 20)
        self.mouse_controller.position = (park_x, min(self.height - 1, self.center[1]))
        # Let the hook suppress the event that caused the switch-back before
        # local input delivery is restored.
        threading.Timer(0.02, self._set_suppression, args=(False,)).start()
        print("控制目标：Windows")

    def _warp_to_center(self) -> None:
        self.warping = True
        self.mouse_controller.position = self.center

    def _on_move(self, x: int, y: int) -> None:
        if self.warping:
            self.warping = False
            return
        if not self.remote_active:
            if not self.edge_armed:
                if x <= self.width - self.config.edge_rearm_distance:
                    self.edge_armed = True
                return
            if x >= self.width - 1 and time.monotonic() - self.last_switch >= 0.5:
                self._activate_remote()
            return
        dx = int(x - self.center[0])
        dy = int(y - self.center[1])
        if not dx and not dy:
            return
        raw_dx, raw_dy = dx, dy
        dx, dy = self.motion_filter.apply(raw_dx, raw_dy)
        if self.debug_mouse and self.debug_mouse_samples < 20:
            self.debug_mouse_samples += 1
            print(
                f"鼠标样本 {self.debug_mouse_samples}: position=({x},{y}) "
                f"center={self.center} raw=({raw_dx},{raw_dy}) send=({dx},{dy})"
            )
        if not dx and not dy:
            self._warp_to_center()
            return
        self.remote_x += dx
        if self.remote_x <= 0 and time.monotonic() - self.last_switch > 0.25:
            self._deactivate_remote()
            return
        self._send({"type": "move", "dx": dx, "dy": dy})
        self._warp_to_center()

    def _on_click(self, _x: int, _y: int, button: Any, pressed: bool) -> None:
        if not self.remote_active:
            return
        name = getattr(button, "name", str(button).split(".")[-1])
        self._send({"type": "button", "button": name, "pressed": pressed})

    def _on_scroll(self, _x: int, _y: int, dx: int, dy: int) -> None:
        if self.remote_active:
            self._send({"type": "scroll", "dx": int(dx), "dy": int(dy)})

    def _key_vk(self, key: Any) -> int | None:
        vk = getattr(key, "vk", None)
        if vk is None:
            vk = getattr(getattr(key, "value", None), "vk", None)
        return int(vk) if vk is not None else None

    def _on_key(self, key: Any, pressed: bool) -> None:
        if not self.remote_active:
            return
        vk = self._key_vk(key)
        if vk is None:
            return
        if pressed:
            self.pressed_vks.add(vk)
        else:
            self.pressed_vks.discard(vk)
        has_ctrl = bool(self.pressed_vks & {0x11, 0xA2, 0xA3})
        has_alt = bool(self.pressed_vks & {0x12, 0xA4, 0xA5})
        if has_ctrl and has_alt and 0x1B in self.pressed_vks:
            self._deactivate_remote()
            return
        code = VK_TO_LINUX.get(vk)
        if code is not None:
            self._send({"type": "key", "code": code, "pressed": pressed})


def run_controller(
    config: Config,
    host: str | None = None,
    sensitivity: float | None = None,
    debug_mouse: bool = False,
) -> None:
    WindowsController(config, host, sensitivity, debug_mouse).run()

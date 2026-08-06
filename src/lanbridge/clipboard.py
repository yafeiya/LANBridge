from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from ctypes import wintypes


class Clipboard:
    def read(self) -> str | None:
        raise NotImplementedError

    def write(self, text: str) -> None:
        raise NotImplementedError


class WindowsClipboard(Clipboard):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    def __init__(self) -> None:
        # ctypes otherwise assumes a 32-bit integer return value. Clipboard
        # and global-memory handles are pointer-sized on 64-bit Windows, so
        # omitting these signatures truncates the handle and can crash Python.
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self.user32.OpenClipboard.argtypes = [wintypes.HWND]
        self.user32.OpenClipboard.restype = wintypes.BOOL
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = wintypes.BOOL
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = wintypes.BOOL
        self.user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        self.user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        self.user32.GetClipboardData.argtypes = [wintypes.UINT]
        self.user32.GetClipboardData.restype = wintypes.HANDLE
        self.user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        self.user32.SetClipboardData.restype = wintypes.HANDLE

        self.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalLock.restype = wintypes.LPVOID
        self.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalUnlock.restype = wintypes.BOOL
        self.kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalFree.restype = wintypes.HGLOBAL

    def _open(self) -> bool:
        for _ in range(5):
            if self.user32.OpenClipboard(None):
                return True
            time.sleep(0.01)
        return False

    def read(self) -> str | None:
        if not self.user32.IsClipboardFormatAvailable(self.CF_UNICODETEXT):
            return None
        if not self._open():
            return None
        try:
            handle = self.user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return None
            pointer = self.kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                return ctypes.wstring_at(pointer)
            finally:
                self.kernel32.GlobalUnlock(handle)
        finally:
            self.user32.CloseClipboard()

    def write(self, text: str) -> None:
        data = (text + "\0").encode("utf-16-le")
        if not self._open():
            return
        handle = None
        try:
            self.user32.EmptyClipboard()
            handle = self.kernel32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
            if not handle:
                return
            pointer = self.kernel32.GlobalLock(handle)
            if not pointer:
                self.kernel32.GlobalFree(handle)
                handle = None
                return
            ctypes.memmove(pointer, data, len(data))
            self.kernel32.GlobalUnlock(handle)
            if not self.user32.SetClipboardData(self.CF_UNICODETEXT, handle):
                return
            handle = None  # ownership transferred to the system
        finally:
            if handle:
                self.kernel32.GlobalFree(handle)
            self.user32.CloseClipboard()


class LinuxClipboard(Clipboard):
    def __init__(self) -> None:
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste") and shutil.which("wl-copy"):
            self.backend = "wayland"
        elif shutil.which("xclip"):
            self.backend = "x11"
        else:
            raise RuntimeError("缺少剪贴板工具：Wayland 请安装 wl-clipboard，X11 请安装 xclip")

    def read(self) -> str | None:
        if self.backend == "wayland":
            command = ["wl-paste", "--no-newline", "--type", "text"]
        else:
            command = ["xclip", "-selection", "clipboard", "-o"]
        result = subprocess.run(command, capture_output=True, timeout=2, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")

    def write(self, text: str) -> None:
        if self.backend == "wayland":
            command = ["wl-copy", "--type", "text/plain;charset=utf-8"]
        else:
            command = ["xclip", "-selection", "clipboard", "-i"]
        try:
            # xclip and wl-copy fork a background process to retain selection
            # ownership. Captured pipes remain open in that child and make
            # subprocess.run wait forever for EOF, so output must not be piped.
            result = subprocess.run(
                command,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"剪贴板命令启动失败：{exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(f"剪贴板命令执行失败：退出码 {result.returncode}")


def make_clipboard() -> Clipboard:
    return WindowsClipboard() if os.name == "nt" else LinuxClipboard()


class ClipboardWatcher:
    def __init__(self, clipboard: Clipboard, on_change: Callable[[str], None], interval: float = 0.5) -> None:
        self.clipboard = clipboard
        self.on_change = on_change
        self.interval = interval
        self.stop_event = threading.Event()
        self.last_value: str | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.last_value = self.clipboard.read()
        self.thread = threading.Thread(target=self._run, name="clipboard-watcher", daemon=True)
        self.thread.start()

    def note_remote_value(self, text: str) -> None:
        self.last_value = text
        self.clipboard.write(text)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                value = self.clipboard.read()
                if value is not None and value != self.last_value:
                    self.last_value = value
                    self.on_change(value)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                time.sleep(self.interval)

    def close(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

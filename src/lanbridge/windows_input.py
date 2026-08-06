from __future__ import annotations

import ctypes
from ctypes import wintypes

from .input_codes import MOUSE_BUTTONS, VK_TO_LINUX

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]  # noqa: RUF012 - ctypes schema


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", INPUTUNION)]


LINUX_TO_VK = {linux_code: virtual_key for virtual_key, linux_code in VK_TO_LINUX.items()}
EXTENDED_VKS = {
    0x21,
    0x22,
    0x23,
    0x24,
    0x25,
    0x26,
    0x27,
    0x28,
    0x2D,
    0x2E,
    0x5B,
    0x5C,
    0xA3,
    0xA5,
}

BUTTON_FLAGS = {
    MOUSE_BUTTONS["left"]: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    MOUSE_BUTTONS["right"]: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    MOUSE_BUTTONS["middle"]: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    MOUSE_BUTTONS["x1"]: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    MOUSE_BUTTONS["x2"]: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
}


class WindowsInputDevice:
    """Inject keyboard and mouse input through the 64-bit-safe SendInput API."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT
        self.pressed_keys: set[int] = set()
        self.pressed_buttons: set[int] = set()

    def _send(self, event: INPUT) -> None:
        sent = self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError(ctypes.get_last_error(), "SendInput 失败")

    def key(self, code: int, pressed: bool) -> None:
        virtual_key = LINUX_TO_VK.get(code)
        if virtual_key is None:
            return
        flags = KEYEVENTF_EXTENDEDKEY if virtual_key in EXTENDED_VKS else 0
        if not pressed:
            flags |= KEYEVENTF_KEYUP
        event = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(virtual_key, 0, flags, 0, 0))
        self._send(event)
        (self.pressed_keys.add if pressed else self.pressed_keys.discard)(code)

    def button(self, code: int, pressed: bool) -> None:
        mapping = BUTTON_FLAGS.get(code)
        if mapping is None:
            return
        down_flag, up_flag, data = mapping
        event = INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(0, 0, data, down_flag if pressed else up_flag, 0, 0),
        )
        self._send(event)
        (self.pressed_buttons.add if pressed else self.pressed_buttons.discard)(code)

    def move(self, dx: int, dy: int) -> None:
        self._send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)))

    def scroll(self, dx: int, dy: int) -> None:
        if dy:
            data = ctypes.c_uint32(dy * WHEEL_DELTA).value
            self._send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data, MOUSEEVENTF_WHEEL, 0, 0)))
        if dx:
            data = ctypes.c_uint32(dx * WHEEL_DELTA).value
            self._send(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data, MOUSEEVENTF_HWHEEL, 0, 0)))

    def release_all(self) -> None:
        for code in tuple(self.pressed_keys):
            self.key(code, False)
        for code in tuple(self.pressed_buttons):
            self.button(code, False)

    def close(self) -> None:
        self.release_all()

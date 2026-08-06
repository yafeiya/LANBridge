from __future__ import annotations

import fcntl
import os
import struct
import time
from pathlib import Path
from typing import Self

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
SYN_REPORT = 0
REL_X = 0
REL_Y = 1
REL_HWHEEL = 6
REL_WHEEL = 8
BUS_USB = 0x03

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502


class UInputDevice:
    """Small dependency-free wrapper around Linux /dev/uinput."""

    def __init__(self, path: str = "/dev/uinput") -> None:
        if not Path(path).exists():
            raise RuntimeError("未找到 /dev/uinput；请先加载 uinput 内核模块")
        try:
            self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except PermissionError as exc:
            raise PermissionError(
                "无权访问 /dev/uinput；请安装 packaging/99-lanbridge-uinput.rules 后重新登录"
            ) from exc
        try:
            self._configure()
        except Exception:
            os.close(self.fd)
            self.fd = None
            raise

    def _ioctl_int(self, request: int, value: int) -> None:
        # uinput's UI_SET_* ioctls receive the event/code value directly as
        # the third ioctl argument. Passing a packed buffer makes the kernel
        # interpret its address as the value and fail with EINVAL.
        fcntl.ioctl(self.fd, request, value)

    def _configure(self) -> None:
        self._ioctl_int(UI_SET_EVBIT, EV_KEY)
        self._ioctl_int(UI_SET_EVBIT, EV_REL)
        for code in range(1, 249):
            self._ioctl_int(UI_SET_KEYBIT, code)
        for code in range(272, 277):
            self._ioctl_int(UI_SET_KEYBIT, code)
        for code in (REL_X, REL_Y, REL_HWHEEL, REL_WHEEL):
            self._ioctl_int(UI_SET_RELBIT, code)

        # Legacy uinput_user_dev layout: name, input_id, ff_effects_max,
        # and four ABS_CNT arrays. No absolute axes are enabled.
        header = struct.pack("80sHHHHi", b"LAN Bridge Virtual Input", BUS_USB, 0x1209, 0xB001, 1, 0)
        abs_axes = struct.pack("256i", *([0] * 256))
        os.write(self.fd, header + abs_axes)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.2)

    def _event(self, event_type: int, code: int, value: int) -> None:
        os.write(self.fd, struct.pack("@llHHi", 0, 0, event_type, code, value))

    def sync(self) -> None:
        self._event(EV_SYN, SYN_REPORT, 0)

    def key(self, code: int, pressed: bool) -> None:
        self._event(EV_KEY, code, 1 if pressed else 0)
        self.sync()

    def button(self, code: int, pressed: bool) -> None:
        self.key(code, pressed)

    def move(self, dx: int, dy: int) -> None:
        if dx:
            self._event(EV_REL, REL_X, dx)
        if dy:
            self._event(EV_REL, REL_Y, dy)
        self.sync()

    def scroll(self, dx: int, dy: int) -> None:
        if dx:
            self._event(EV_REL, REL_HWHEEL, dx)
        if dy:
            self._event(EV_REL, REL_WHEEL, dy)
        self.sync()

    def release_all(self) -> None:
        for code in range(1, 249):
            self._event(EV_KEY, code, 0)
        for code in range(272, 277):
            self._event(EV_KEY, code, 0)
        self.sync()

    def close(self) -> None:
        if getattr(self, "fd", None) is None:
            return
        try:
            self.release_all()
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
            self.fd = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

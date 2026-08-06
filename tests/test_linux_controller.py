from __future__ import annotations

from types import SimpleNamespace

from lanbridge.input_codes import MouseMotionFilter
from lanbridge.linux_controller import LinuxController


class FakeDevice:
    def __init__(self, path: str) -> None:
        self.path = path
        self.grabbed = False

    def grab(self) -> None:
        self.grabbed = True

    def ungrab(self) -> None:
        self.grabbed = False


class FakeLocalInput:
    def __init__(self) -> None:
        self.released: list[int] = []

    def key(self, code: int, pressed: bool) -> None:
        if not pressed:
            self.released.append(code)


def test_linux_controller_grabs_and_releases_devices_on_hotkey_toggle() -> None:
    controller = object.__new__(LinuxController)
    controller.remote_active = False
    controller.devices = [FakeDevice("/dev/input/event1"), FakeDevice("/dev/input/event2")]
    controller.grabbed = set()
    controller.pressed_keys = {29, 56, 88}
    controller.suppress_until_release = set()
    controller.local_release = FakeLocalInput()
    controller.motion_filter = MouseMotionFilter()
    controller.config = SimpleNamespace(remote_entry_inset=16)
    messages = []
    controller._send = messages.append

    controller._toggle_remote()
    assert controller.remote_active
    assert all(device.grabbed for device in controller.devices)
    assert messages[-1] == {"type": "enter", "edge": "right", "inset": 16}
    assert set(controller.local_release.released) == {29, 56, 88}

    controller._toggle_remote()
    assert not controller.remote_active
    assert all(not device.grabbed for device in controller.devices)
    assert messages[-1] == {"type": "release_all"}

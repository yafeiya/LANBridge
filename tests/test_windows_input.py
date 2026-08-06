from __future__ import annotations

import ctypes

from lanbridge.windows_input import INPUT, INPUT_KEYBOARD, KEYBDINPUT, LINUX_TO_VK


def test_windows_input_structure_matches_platform_pointer_size() -> None:
    expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(INPUT) == expected_size


def test_linux_key_codes_map_back_to_windows_virtual_keys() -> None:
    assert LINUX_TO_VK[30] == 0x41  # A
    assert LINUX_TO_VK[57] == 0x20  # Space
    assert LINUX_TO_VK[28] == 0x0D  # Enter


def test_keyboard_input_union_can_be_constructed() -> None:
    event = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0x41, 0, 0, 0, 0))
    assert event.type == INPUT_KEYBOARD
    assert event.ki.wVk == 0x41

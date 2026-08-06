from __future__ import annotations

from dataclasses import dataclass

# Windows virtual-key to Linux input-event key code. The MVP targets the common
# PC/US physical layout; text clipboard sharing is independent of this mapping.
VK_TO_LINUX: dict[int, int] = {
    0x08: 14, 0x09: 15, 0x0D: 28, 0x10: 42, 0x11: 29, 0x12: 56,
    0x14: 58, 0x1B: 1, 0x20: 57, 0x21: 104, 0x22: 109,
    0x23: 107, 0x24: 102, 0x25: 105, 0x26: 103, 0x27: 106,
    0x28: 108, 0x2C: 99, 0x2D: 110, 0x2E: 111,
    0x30: 11, 0x31: 2, 0x32: 3, 0x33: 4, 0x34: 5,
    0x35: 6, 0x36: 7, 0x37: 8, 0x38: 9, 0x39: 10,
    0x41: 30, 0x42: 48, 0x43: 46, 0x44: 32, 0x45: 18,
    0x46: 33, 0x47: 34, 0x48: 35, 0x49: 23, 0x4A: 36,
    0x4B: 37, 0x4C: 38, 0x4D: 50, 0x4E: 49, 0x4F: 24,
    0x50: 25, 0x51: 16, 0x52: 19, 0x53: 31, 0x54: 20,
    0x55: 22, 0x56: 47, 0x57: 17, 0x58: 45, 0x59: 21,
    0x5A: 44, 0x5B: 125, 0x5C: 126, 0x5D: 127,
    0x60: 82, 0x61: 79, 0x62: 80, 0x63: 81, 0x64: 75,
    0x65: 76, 0x66: 77, 0x67: 71, 0x68: 72, 0x69: 73,
    0x6A: 55, 0x6B: 78, 0x6D: 74, 0x6E: 83, 0x6F: 98,
    0x70: 59, 0x71: 60, 0x72: 61, 0x73: 62, 0x74: 63,
    0x75: 64, 0x76: 65, 0x77: 66, 0x78: 67, 0x79: 68,
    0x7A: 87, 0x7B: 88,
    0x90: 69, 0x91: 70,
    0xA0: 42, 0xA1: 54, 0xA2: 29, 0xA3: 97, 0xA4: 56, 0xA5: 100,
    0xBA: 39, 0xBB: 13, 0xBC: 51, 0xBD: 12, 0xBE: 52,
    0xBF: 53, 0xC0: 41, 0xDB: 26, 0xDC: 43, 0xDD: 27,
    0xDE: 40,
}

MOUSE_BUTTONS = {
    "left": 272,
    "right": 273,
    "middle": 274,
    "x1": 275,
    "x2": 276,
}


@dataclass
class MouseMotionFilter:
    """Scale pointer motion while retaining sub-pixel movement."""

    sensitivity: float = 0.4
    max_delta: int = 250
    remainder_x: float = 0.0
    remainder_y: float = 0.0

    def apply(self, dx: int, dy: int) -> tuple[int, int]:
        # Recentering can leave an old absolute hook event in the queue. Such
        # an event is close to half a screen wide and must not be forwarded.
        if abs(dx) > self.max_delta or abs(dy) > self.max_delta:
            self.remainder_x = 0.0
            self.remainder_y = 0.0
            return 0, 0
        scaled_x = dx * self.sensitivity + self.remainder_x
        scaled_y = dy * self.sensitivity + self.remainder_y
        output_x = int(scaled_x)
        output_y = int(scaled_y)
        self.remainder_x = scaled_x - output_x
        self.remainder_y = scaled_y - output_y
        return output_x, output_y

    def reset(self) -> None:
        self.remainder_x = 0.0
        self.remainder_y = 0.0

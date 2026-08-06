from __future__ import annotations

from lanbridge.input_codes import MouseMotionFilter


def test_mouse_filter_preserves_fractional_motion() -> None:
    motion = MouseMotionFilter(sensitivity=0.4)
    output = [motion.apply(1, 0)[0] for _ in range(10)]
    assert sum(output) == 4


def test_mouse_filter_discards_stale_recentering_jump() -> None:
    motion = MouseMotionFilter(sensitivity=0.4, max_delta=250)
    assert motion.apply(900, -500) == (0, 0)
    assert motion.apply(10, -10) == (4, -4)

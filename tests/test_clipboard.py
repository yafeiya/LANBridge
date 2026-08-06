from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from lanbridge.clipboard import LinuxClipboard


def test_xclip_background_process_does_not_inherit_captured_pipes() -> None:
    clipboard = object.__new__(LinuxClipboard)
    clipboard.backend = "x11"
    with patch("lanbridge.clipboard.subprocess.run", return_value=Mock(returncode=0)) as run:
        clipboard.write("hello")
    kwargs = run.call_args.kwargs
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert "capture_output" not in kwargs


def test_clipboard_timeout_becomes_recoverable_runtime_error() -> None:
    clipboard = object.__new__(LinuxClipboard)
    clipboard.backend = "x11"
    error = subprocess.TimeoutExpired(["xclip"], 2)
    with (
        patch("lanbridge.clipboard.subprocess.run", side_effect=error),
        pytest.raises(RuntimeError, match="剪贴板命令启动失败"),
    ):
        clipboard.write("hello")

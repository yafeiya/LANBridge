from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

import pytest

from lanbridge.gui import BackendProcess, LanBridgeApp, backend_command


def test_receiver_backend_command() -> None:
    config_path = Path("/tmp/config.json")
    command = backend_command("receiver", config_path, executable="python")
    assert command == [
        "python",
        "-u",
        "-m",
        "lanbridge",
        "--config",
        str(config_path),
        "receive",
    ]


def test_controller_backend_command() -> None:
    command = backend_command(
        "controller",
        Path("config.json"),
        host="192.168.5.8",
        sensitivity=0.65,
        executable="python",
    )
    assert command[-5:] == ["control", "--host", "192.168.5.8", "--sensitivity", "0.65"]


def test_controller_requires_host() -> None:
    with pytest.raises(ValueError, match="Ubuntu 地址"):
        backend_command("controller", Path("config.json"), executable="python")


def test_backend_process_collects_output_and_exit_code() -> None:
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    backend = BackendProcess(events)
    backend.start([sys.executable, "-c", "print('中文日志正常')"])
    assert events.get(timeout=3) == ("log", "中文日志正常")
    assert events.get(timeout=3) == ("exit", 0)


@pytest.mark.skipif(os.name != "nt", reason="Windows startup entry")
def test_windows_auto_start_entry_can_be_enabled_and_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = object.__new__(LanBridgeApp)
    app._configure_auto_start(True)
    entry = tmp_path / "Microsoft/Windows/Start Menu/Programs/Startup/LAN Bridge.vbs"
    assert entry.exists()
    assert "--autostart" in entry.read_text(encoding="utf-8-sig")
    app._configure_auto_start(False)
    assert not entry.exists()

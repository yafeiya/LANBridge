from __future__ import annotations

from lanbridge.config import Config, load_config, save_config


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    original = Config.new("test-device")
    original.peer_host = "192.168.1.20"
    save_config(original, path)
    loaded = load_config(path)
    assert loaded == original
    assert len(loaded.token_bytes) == 32


from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "lanbridge"


def default_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / APP_NAME / "config.json"


@dataclass
class Config:
    device_name: str
    token: str
    peer_host: str | None = None
    tcp_port: int = 45831
    discovery_port: int = 45832
    switch_edge: str = "right"
    mouse_sensitivity: float = 0.4
    edge_rearm_distance: int = 140
    max_mouse_delta: int = 250
    remote_entry_inset: int = 16
    preferred_role: str = "auto"
    auto_start: bool = False

    @property
    def token_bytes(self) -> bytes:
        value = base64.urlsafe_b64decode(self.token.encode("ascii"))
        if len(value) != 32:
            raise ValueError("配对令牌长度无效")
        return value

    @classmethod
    def new(cls, device_name: str | None = None) -> Config:
        import socket

        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        return cls(device_name=device_name or socket.gethostname(), token=token)


def load_config(path: Path | None = None, create: bool = False) -> Config:
    path = path or default_config_path()
    if not path.exists():
        if not create:
            raise FileNotFoundError(f"尚未初始化配置：{path}")
        config = Config.new()
        save_config(config, path)
        return config
    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(**data)


def save_config(config: Config, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path

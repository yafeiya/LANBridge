from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from . import __version__
from .config import Config, default_config_path, load_config, save_config
from .discovery import discover


def _config_path(value: str | None) -> Path:
    return Path(value).expanduser() if value else default_config_path()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lanbridge",
        description="在局域网内安全共享 Windows 键鼠和 Windows/Ubuntu 文本剪贴板",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="生成本机配置和配对令牌")
    init_parser.add_argument("--name", help="本机显示名称")
    init_parser.add_argument("--force", action="store_true", help="覆盖现有配置并生成新令牌")

    pair_parser = sub.add_parser("pair", help="在 Windows 上保存 Ubuntu 接收端的配对令牌")
    pair_parser.add_argument("token", help="Ubuntu 上 init 命令输出的令牌")
    pair_parser.add_argument("--host", help="Ubuntu IP；省略则运行时自动发现")

    sub.add_parser("show-token", help="显示当前配对令牌")
    sub.add_parser("discover", help="查找局域网接收端")
    sub.add_parser("receive", help="在 Ubuntu 上启动接收端")

    control_parser = sub.add_parser("control", help="在 Windows 上启动主控端")
    control_parser.add_argument("--host", help="Ubuntu IP，覆盖配置和自动发现")
    control_parser.add_argument(
        "--sensitivity",
        type=float,
        help="Ubuntu 鼠标灵敏度倍率，默认 0.4，建议范围 0.1～1.0",
    )
    control_parser.add_argument(
        "--debug-mouse",
        action="store_true",
        help="输出前 20 个远程鼠标坐标样本，用于诊断显示缩放问题",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = _config_path(args.config)
    try:
        if args.command == "init":
            if path.exists() and not args.force:
                config = load_config(path)
                print(f"配置已存在：{path}")
            else:
                config = Config.new(args.name)
                save_config(config, path)
                print(f"已创建配置：{path}")
            print("配对令牌（请仅复制到你的另一台电脑）：")
            print(config.token)
            return 0

        if args.command == "pair":
            try:
                token_bytes = base64.urlsafe_b64decode(args.token.encode("ascii"))
            except Exception as exc:
                raise ValueError("令牌不是有效的 Base64 字符串") from exc
            if len(token_bytes) != 32:
                raise ValueError("令牌长度无效")
            config = load_config(path, create=True)
            config.token = args.token
            config.peer_host = args.host
            save_config(config, path)
            print(f"配对信息已保存：{path}")
            return 0

        config = load_config(path)
        if args.command == "show-token":
            print(config.token)
        elif args.command == "discover":
            peers = discover(config.discovery_port)
            if not peers:
                print("未发现接收端")
                return 1
            for peer in peers:
                print(f"{peer.get('name', '未知设备')}  {peer['host']}:{peer['port']}")
        elif args.command == "receive":
            from .receiver import run_receiver

            run_receiver(config)
        elif args.command == "control":
            if sys.platform == "win32":
                from .windows_host import run_controller
            else:
                from .linux_controller import run_controller

            run_controller(config, args.host, args.sensitivity, args.debug_mouse)
        return 0
    except (FileNotFoundError, PermissionError, RuntimeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

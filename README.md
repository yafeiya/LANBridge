# LAN Bridge
[English Document](./README.en.md)

LAN Bridge 是面向 Windows 11 + Ubuntu 24.04 LTS 的局域网工具，实现跨设备键鼠无缝共享、双向文本剪贴板同步、局域网文件传输。

## 核心交互逻辑
- Windows / Ubuntu 可自由切换主控端、接收端角色
- Windows 主控：鼠标滑出屏幕右边缘，键鼠自动转发至 Ubuntu
- 返回 Windows：鼠标左滑 Ubuntu 虚拟边缘 或 快捷键 `Ctrl+Alt+Esc`
- 两端剪贴板实时双向同步纯文本
- 网络传输安全：预共享令牌身份校验 + ChaCha20-Poly1305 加密TCP通道
- Ubuntu 使用 `/dev/uinput` 注入输入事件，完美兼容 X11 / Wayland

## 图形界面（0.3.0+ 无需命令行）
- Windows：自动生成桌面快捷方式，支持鼠标速度自定义、自动扫描局域网设备、保存配对令牌、开机自启
- Ubuntu：应用菜单生成启动入口，预装Noto CJK中文字体，原生中文界面
- 界面实时展示本机局域网IP，一键复制配对令牌
- Ubuntu Wayland主控：`Ctrl+Alt+F12` 切换受控设备，独占物理键鼠，退出自动释放设备
- 底层保留命令行工具，用于故障排查

## 1. Ubuntu 24.04 安装部署
```bash
sudo apt update
sudo apt install -y python3-venv build-essential python3-dev
cd lanbridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
chmod +x packaging/install-linux.sh
./packaging/install-linux.sh
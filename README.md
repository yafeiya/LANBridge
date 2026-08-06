# LAN Bridge

LAN Bridge 是一个面向 Windows 11 + Ubuntu 24.04 LTS 的局域网键盘、鼠标和文本剪贴板共享工具。

当前版本采用以下控制方式：

- Windows 和 Ubuntu 均可在主控端、接收端之间切换。
- 鼠标到达 Windows 主屏幕右边缘后，键鼠事件发送给 Ubuntu。
- 将鼠标向左移出 Ubuntu 的虚拟边缘，或按 `Ctrl+Alt+Esc`，返回 Windows。
- 两端文本剪贴板自动双向同步。
- TCP 数据使用预共享令牌认证，并使用 ChaCha20-Poly1305 加密。
- Ubuntu 通过 `/dev/uinput` 注入事件，因此兼容 X11 和 Wayland。

## 图形界面

0.3.0 起不再需要日常使用命令行：

- Windows 安装脚本会在桌面创建 `LAN Bridge` 快捷方式。
- Ubuntu 安装脚本会在应用菜单创建 `LAN Bridge` 入口。
- 两端界面均显示当前设备 IP。
- Windows 界面可切换主控/接收角色、自动发现设备、保存配对令牌、调整鼠标速度并启停连接。
- Ubuntu 接收端使用 `uinput`；Ubuntu Wayland 主控端使用 `evdev` 独占物理设备，并通过 `Ctrl+Alt+F12` 安全切换目标。
- 可选择登录后自动启动，并按上次角色、上次 IP 自动连接。
- Ubuntu 安装脚本会安装 Noto CJK 字体，界面自动选择可显示中文的字体。
- 底层命令行仍然保留，便于故障诊断。

## 1. Ubuntu 24.04 安装

```bash
sudo apt update
sudo apt install -y python3-venv build-essential python3-dev

cd lanbridge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
chmod +x packaging/install-linux.sh
./packaging/install-linux.sh
```

安装权限规则后需要注销 Ubuntu 并重新登录。然后从应用菜单启动 `LAN Bridge`，点击“启动”即可。

Ubuntu 界面会自动生成并显示配对令牌。令牌等同于密码，请只复制到自己的 Windows 电脑。

安装脚本会同时安装 Wayland 的 `wl-clipboard` 和 X11 的 `xclip`。

## 2. Windows 11 安装

在 PowerShell 中运行：

```powershell
cd lanbridge
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\install-windows.ps1
```

安装完成后，双击桌面的 `LAN Bridge` 即可；在界面中填写 Ubuntu 地址和配对令牌，然后点击“启动”。

鼠标速度可直接在 Windows 界面中调整，设置会自动保存。

界面会通过 UDP 广播自动发现 Ubuntu。若广播被路由器或防火墙拦截，可直接在界面填写 Ubuntu IP。

## 防火墙端口

- TCP `45831`：加密的输入和剪贴板通道。
- UDP `45832`：局域网自动发现。

只应在“专用网络/家庭网络”配置中放行这些端口，不要在公共网络中开放。

## 当前限制

- 键位按常见 PC/US 物理键盘映射；中英文输入法组合在 Ubuntu 本机完成。
- 只同步纯文本，不同步图片、文件或富文本。
- 无缝边缘切换当前由 Windows 主控端实现，目标屏幕位于主屏幕右侧。
- Ubuntu Wayland 主控使用 `Ctrl+Alt+F12` 切换目标；应用会独占物理键鼠，退出或断线时自动释放。
- Ubuntu 接收端需要当前桌面会话才能访问 Wayland 剪贴板，不能作为无桌面环境的系统服务启动。
- GNOME Wayland 下虚拟指针通过相对位移驱动；进入时会自动与 Ubuntu 左边缘对齐。

## 开发验证

```bash
python -m pip install pytest
pytest
python -m compileall -q src
```

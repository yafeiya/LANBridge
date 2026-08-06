# README.en.md

# LAN Bridge
[中文文档](./README.md)

LAN Bridge is a local area network tool for Windows 11 and Ubuntu 24.04 LTS, which supports cross-device keyboard & mouse sharing, bidirectional text clipboard synchronization and file transfer.

## Core Features & Control Logic
- Both Windows and Ubuntu can switch between host and receiver mode freely.
- When the mouse reaches the right edge of the main Windows screen, keyboard and mouse events will be sent to Ubuntu.
- Move the mouse left across Ubuntu's virtual edge, or press the shortcut `Ctrl+Alt+Esc` to switch back to Windows.
- Plain text clipboard synchronizes bidirectionally in real time on both ends.
- TCP traffic is authenticated via pre-shared token and encrypted with ChaCha20-Poly1305 algorithm.
- Ubuntu injects input events through `/dev/uinput`, compatible with both X11 and Wayland.

## Graphical User Interface
Command-line operations are no longer required for daily use:
- The Windows installation script creates a `LAN Bridge` shortcut on the desktop.
- The Ubuntu installation script adds a `LAN Bridge` entry to the application menu.
- The local LAN IP address is displayed on the GUI of both systems.
- The Windows panel supports role switching, automatic device discovery, pairing token storage, mouse speed adjustment and connection control.
- Ubuntu receiver relies on `uinput`; Ubuntu Wayland host takes exclusive control of physical input devices via `evdev`, use `Ctrl+Alt+F12` to safely switch target device.
- Support auto-launch after login, and automatically reconnect with last-used role and IP.
- The Ubuntu installer deploys Noto CJK fonts, the UI will automatically pick fonts that support Chinese characters.
- Original command-line tools are preserved for troubleshooting.

## 1. Install on Ubuntu 24.04
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
Log out and re-login Ubuntu after installing permission rules. Launch `LAN Bridge` from the application menu and click Start.
A unique pairing token will be auto-generated on the Ubuntu interface, which acts as a password. Only copy it to your trusted Windows machine.
The installation script will automatically install `wl-clipboard` for Wayland and `xclip` for X11 clipboard support.

## 2. Install on Windows 11
Run the following commands in PowerShell:
```powershell
cd lanbridge
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\install-windows.ps1
```
Double-click the desktop `LAN Bridge` shortcut after installation. Fill in the Ubuntu IP address and pairing token, then click Start.
Mouse speed can be modified directly on Windows GUI, configurations will be saved automatically.
The program discovers Ubuntu devices over UDP broadcast. If broadcast traffic is blocked by router or firewall, fill Ubuntu IP manually.

## Firewall Ports
- TCP `45831`: Encrypted channel for input events and clipboard data
- UDP `45832`: UDP broadcast for LAN automatic device discovery

Only allow these ports under Private / Home network profile. Never open them on public networks.

## Current Limitations
- Ubuntu receiver requires an active desktop session to access Wayland clipboard, cannot run as headless background service.
- GNOME Wayland virtual pointer uses relative displacement and aligns with the left screen edge when entering Ubuntu.
- Keyboard follows standard US PC physical layout; input method switching is handled locally on Ubuntu.
- Only plain text is synchronized; images, rich text and files are not supported in clipboard.


#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "此脚本只能在 Linux 上运行" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"

sudo apt-get update
sudo apt-get install -y build-essential python3-dev python3-tk fonts-noto-cjk wl-clipboard xclip

sudo groupadd --force lanbridge
sudo install -m 0644 "$SCRIPT_DIR/99-lanbridge-uinput.rules" /etc/udev/rules.d/99-lanbridge-uinput.rules
sudo usermod -aG lanbridge,input "$TARGET_USER"
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput

GUI_EXEC="$PROJECT_ROOT/.venv/bin/lanbridge-gui"
if [[ ! -x "$GUI_EXEC" ]]; then
  echo "未找到 $GUI_EXEC，请先在虚拟环境中执行 pip install -e ." >&2
  exit 1
fi

APPLICATION_DIR="$TARGET_HOME/.local/share/applications"
DESKTOP_FILE="$APPLICATION_DIR/lanbridge.desktop"
TEMP_DESKTOP="$(mktemp)"
trap 'rm -f "$TEMP_DESKTOP"' EXIT
sed \
  -e "s|@GUI_EXEC@|$GUI_EXEC|g" \
  -e "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" \
  "$SCRIPT_DIR/lanbridge.desktop.in" > "$TEMP_DESKTOP"
sudo install -d -m 0755 -o "$TARGET_USER" -g "$TARGET_GROUP" "$APPLICATION_DIR"
sudo install -m 0644 -o "$TARGET_USER" -g "$TARGET_GROUP" "$TEMP_DESKTOP" "$DESKTOP_FILE"

echo "uinput 权限和应用菜单入口已配置。"
echo "请注销并重新登录，然后从应用菜单启动 LAN Bridge。"

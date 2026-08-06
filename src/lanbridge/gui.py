from __future__ import annotations

import os
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import (
    BooleanVar,
    DoubleVar,
    StringVar,
    Tk,
    font,
    messagebox,
    scrolledtext,
    ttk,
)
from typing import Any

from . import __version__
from .config import Config, default_config_path, load_config, save_config
from .discovery import discover

APP_TITLE = "LAN Bridge"
BG = "#F4F7FB"
CARD = "#FFFFFF"
TEXT = "#172033"
MUTED = "#697386"
PRIMARY = "#2563EB"
SUCCESS = "#15803D"
WARNING = "#B45309"
DANGER = "#B91C1C"
ROLE_LABELS = {"controller": "主控端", "receiver": "接收端"}
ROLE_VALUES = {label: role for role, label in ROLE_LABELS.items()}


def get_local_ipv4() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "无法检测"
    finally:
        probe.close()


def backend_command(
    role: str,
    config_path: Path,
    host: str | None = None,
    sensitivity: float | None = None,
    executable: str | None = None,
) -> list[str]:
    command = [
        executable or sys.executable,
        "-u",
        "-m",
        "lanbridge",
        "--config",
        str(config_path),
    ]
    if role == "receiver":
        return [*command, "receive"]
    if not host:
        raise ValueError("请填写或自动发现 Ubuntu 地址")
    command.extend(["control", "--host", host])
    if sensitivity is not None:
        command.extend(["--sensitivity", f"{sensitivity:.2f}"])
    return command


def choose_font_families(root: Tk) -> tuple[str, str]:
    available = set(font.families(root))
    default_ui = str(font.nametofont("TkDefaultFont", root).actual("family"))
    default_mono = str(font.nametofont("TkFixedFont", root).actual("family"))
    if os.name == "nt":
        ui_candidates = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
        mono_candidates = ("Microsoft YaHei UI", "Cascadia Mono", "Consolas")
    else:
        ui_candidates = ("Noto Sans CJK SC", "WenQuanYi Micro Hei", "Noto Sans CJK", "DejaVu Sans")
        mono_candidates = ("Noto Sans Mono CJK SC", "Noto Sans CJK SC", "DejaVu Sans Mono")
    ui_family = next((name for name in ui_candidates if name in available), default_ui)
    mono_family = next((name for name in mono_candidates if name in available), default_mono or ui_family)
    return ui_family, mono_family


class BackendProcess:
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        self.events = events
        self.process: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, command: list[str]) -> None:
        if self.running:
            raise RuntimeError("后台服务已经运行")
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            **options,
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True, name="gui-backend-log")
        self.reader.start()

    def _read_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.events.put(("log", line.rstrip("\r\n")))
        code = process.wait()
        self.events.put(("exit", code))

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()


class LanBridgeApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.config_path = default_config_path()
        self.config = load_config(self.config_path, create=True)
        if self.config.preferred_role in ROLE_LABELS:
            self.role = self.config.preferred_role
        else:
            self.role = "controller" if os.name == "nt" else "receiver"
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.backend = BackendProcess(self.events)
        self.closing = False
        self.start_after_discovery = False

        self.status_var = StringVar(value="未运行")
        self.host_var = StringVar(value=self.config.peer_host or "")
        self.token_var = StringVar(value=self.config.token)
        self.show_token_var = BooleanVar(value=False)
        self.sensitivity_var = DoubleVar(value=self.config.mouse_sensitivity)
        self.sensitivity_label_var = StringVar(value=f"{self.config.mouse_sensitivity:.2f}×")
        self.role_var = StringVar(value=ROLE_LABELS[self.role])
        self.local_ip_var = StringVar(value=get_local_ipv4())
        self.auto_start_var = BooleanVar(value=self.config.auto_start)
        self.permission_var = StringVar(value=self._permission_status())

        self._configure_window()
        self.ui_font, self.mono_font = choose_font_families(root)
        self._configure_named_fonts()
        self._configure_styles()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._drain_events)

    def _configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("720x760")
        self.root.minsize(640, 680)
        self.root.configure(background=BG)

    def _configure_named_fonts(self) -> None:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name, self.root).configure(family=self.ui_font)
        font.nametofont("TkFixedFont", self.root).configure(family=self.mono_font)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if os.name == "nt":
            style.theme_use("vista")
        style.configure("Page.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(self.ui_font, 22, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=(self.ui_font, 10))
        style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT, font=(self.ui_font, 12, "bold"))
        style.configure("Body.TLabel", background=CARD, foreground=TEXT, font=(self.ui_font, 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 9))
        style.configure("Status.TLabel", background=CARD, foreground=MUTED, font=(self.ui_font, 10, "bold"))
        style.configure("Primary.TButton", font=(self.ui_font, 10, "bold"), padding=(18, 9))
        style.configure("Secondary.TButton", font=(self.ui_font, 9), padding=(12, 7))
        style.configure("Card.TCheckbutton", background=CARD, foreground=MUTED)

    def _build_ui(self) -> None:
        page = ttk.Frame(self.root, style="Page.TFrame", padding=(30, 24))
        page.pack(fill="both", expand=True)

        header = ttk.Frame(page, style="Page.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        platform_text = "Windows" if os.name == "nt" else "Ubuntu"
        self.role_subtitle = ttk.Label(
            header,
            text=f"{platform_text} {ROLE_LABELS[self.role]}  ·  v{__version__}",
            style="Subtitle.TLabel",
        )
        self.role_subtitle.pack(
            side="left", padx=(14, 0), pady=(9, 0)
        )
        role_box = ttk.Combobox(
            header,
            textvariable=self.role_var,
            values=list(ROLE_VALUES),
            state="readonly",
            width=10,
        )
        role_box.pack(side="right", pady=(7, 0))
        role_box.bind("<<ComboboxSelected>>", self._role_changed)

        status_card = ttk.Frame(page, style="Card.TFrame", padding=(20, 15))
        status_card.pack(fill="x", pady=(0, 12))
        ttk.Label(status_card, text="状态", style="Muted.TLabel").pack(side="left")
        self.status_label = ttk.Label(status_card, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(side="left", padx=(12, 0))
        self.toggle_button = ttk.Button(
            status_card,
            text="启动",
            style="Primary.TButton",
            command=self._toggle_backend,
        )
        self.toggle_button.pack(side="right")
        ip_group = ttk.Frame(status_card, style="Card.TFrame")
        ip_group.pack(side="right", padx=(0, 22))
        ttk.Label(ip_group, text="本机 IP", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        ttk.Label(ip_group, textvariable=self.local_ip_var, style="Body.TLabel").pack(side="left")

        self.settings = ttk.Frame(page, style="Card.TFrame", padding=(20, 18))
        self.settings.pack(fill="x", pady=(0, 12))
        self._render_role_settings()

        log_card = ttk.Frame(page, style="Card.TFrame", padding=(20, 15))
        log_card.pack(fill="both", expand=True)
        ttk.Label(log_card, text="运行日志", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.log_box = scrolledtext.ScrolledText(
            log_card,
            height=10,
            wrap="word",
            borderwidth=0,
            background="#F8FAFC",
            foreground="#334155",
            font=(self.mono_font, 9),
            padx=10,
            pady=8,
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

        footer = ttk.Label(
            page,
            text="连接仅限已配对设备，输入与剪贴板数据经过加密传输",
            style="Subtitle.TLabel",
        )
        footer.pack(pady=(10, 0))

    def _render_role_settings(self) -> None:
        for child in self.settings.winfo_children():
            child.destroy()
        if self.role == "controller":
            self._build_controller_settings(self.settings)
        else:
            self._build_receiver_settings(self.settings)

    def _role_changed(self, _event: Any = None) -> None:
        selected_role = ROLE_VALUES.get(self.role_var.get(), self.role)
        if selected_role == self.role:
            return
        if self.backend.running:
            self.role_var.set(ROLE_LABELS[self.role])
            messagebox.showwarning(APP_TITLE, "请先停止当前服务，再切换角色。")
            return
        self.role = selected_role
        self.config.preferred_role = selected_role
        save_config(self.config, self.config_path)
        self.permission_var.set(self._permission_status())
        platform_text = "Windows" if os.name == "nt" else "Ubuntu"
        self.role_subtitle.configure(text=f"{platform_text} {ROLE_LABELS[self.role]}  ·  v{__version__}")
        self._render_role_settings()
        self._set_status("未运行", MUTED)

    def _build_controller_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="对端设备", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(parent, text="IP 地址", style="Body.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.host_var, width=31).grid(
            row=1, column=1, sticky="ew", padx=(14, 10), pady=4
        )
        self.discover_button = ttk.Button(
            parent,
            text="自动发现",
            style="Secondary.TButton",
            command=self._discover,
        )
        self.discover_button.grid(row=1, column=2, sticky="e")

        ttk.Label(parent, text="配对令牌", style="Body.TLabel").grid(row=2, column=0, sticky="w")
        self.token_entry = ttk.Entry(parent, textvariable=self.token_var, show="•")
        self.token_entry.grid(row=2, column=1, sticky="ew", padx=(14, 10), pady=4)
        ttk.Checkbutton(
            parent,
            text="显示",
            variable=self.show_token_var,
            command=self._toggle_token_visibility,
            style="Card.TCheckbutton",
        ).grid(row=2, column=2, sticky="w")

        ttk.Label(parent, text="鼠标速度", style="Body.TLabel").grid(row=3, column=0, sticky="w")
        scale = ttk.Scale(
            parent,
            from_=0.1,
            to=1.2,
            variable=self.sensitivity_var,
            command=self._sensitivity_changed,
        )
        scale.grid(row=3, column=1, sticky="ew", padx=(14, 10), pady=(8, 4))
        ttk.Label(parent, textvariable=self.sensitivity_label_var, style="Body.TLabel").grid(
            row=3, column=2, sticky="w"
        )
        controller_note = (
            "鼠标移出 Windows 主屏幕右边缘时切换；Ctrl+Alt+Esc 返回。"
            if os.name == "nt"
            else "按 Ctrl+Alt+F12 在 Ubuntu 与 Windows 之间切换控制目标。"
        )
        ttk.Label(parent, text=controller_note, style="Muted.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )
        self._build_auto_start(parent, 5)
        parent.columnconfigure(1, weight=1)

    def _build_receiver_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="本机接收信息", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(parent, text="本机地址", style="Body.TLabel").grid(row=1, column=0, sticky="w")
        address = StringVar(value=f"{get_local_ipv4()}:{self.config.tcp_port}")
        address_entry = ttk.Entry(parent, textvariable=address, state="readonly")
        address_entry.grid(row=1, column=1, sticky="ew", padx=(14, 10), pady=4)
        ttk.Button(
            parent,
            text="复制地址",
            style="Secondary.TButton",
            command=lambda: self._copy_text(get_local_ipv4(), "地址已复制"),
        ).grid(row=1, column=2, sticky="e")

        ttk.Label(parent, text="配对令牌", style="Body.TLabel").grid(row=2, column=0, sticky="w")
        token_entry = ttk.Entry(parent, textvariable=self.token_var, state="readonly")
        token_entry.grid(row=2, column=1, sticky="ew", padx=(14, 10), pady=4)
        ttk.Button(
            parent,
            text="复制令牌",
            style="Secondary.TButton",
            command=lambda: self._copy_text(self.token_var.get(), "配对令牌已复制"),
        ).grid(row=2, column=2, sticky="e")

        ttk.Label(parent, text="输入权限", style="Body.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(parent, textvariable=self.permission_var, style="Muted.TLabel").grid(
            row=3, column=1, sticky="w", padx=(14, 10), pady=6
        )
        ttk.Button(
            parent,
            text="更新令牌",
            style="Secondary.TButton",
            command=self._regenerate_token,
        ).grid(row=3, column=2, sticky="e")
        receiver_note = "等待局域网中的主控端连接并控制本机。"
        ttk.Label(parent, text=receiver_note, style="Muted.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )
        self._build_auto_start(parent, 5)
        parent.columnconfigure(1, weight=1)

    def _build_auto_start(self, parent: ttk.Frame, row: int) -> None:
        ttk.Checkbutton(
            parent,
            text="登录后自动启动，并按上次角色自动连接",
            variable=self.auto_start_var,
            command=self._auto_start_changed,
            style="Card.TCheckbutton",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _toggle_token_visibility(self) -> None:
        self.token_entry.configure(show="" if self.show_token_var.get() else "•")

    def _sensitivity_changed(self, _value: str) -> None:
        self.sensitivity_label_var.set(f"{self.sensitivity_var.get():.2f}×")

    def _permission_status(self) -> str:
        if self.role == "controller":
            return ""
        if os.name == "nt":
            return "Windows 输入注入已就绪"
        path = Path("/dev/uinput")
        if not path.exists():
            return "未找到 /dev/uinput"
        if not os.access(path, os.W_OK):
            return "无写入权限，请重新运行 Linux 安装脚本并登录"
        return "已就绪"

    def _auto_start_changed(self) -> None:
        enabled = self.auto_start_var.get()
        try:
            self._configure_auto_start(enabled)
            self.config.auto_start = enabled
            self.config.preferred_role = self.role
            save_config(self.config, self.config_path)
        except OSError as exc:
            self.auto_start_var.set(not enabled)
            messagebox.showerror(APP_TITLE, f"更新自动启动失败：{exc}")
            return
        self._append_log("已启用登录后自动连接" if enabled else "已关闭登录后自动连接")

    def _configure_auto_start(self, enabled: bool) -> None:
        if os.name == "nt":
            startup_dir = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
            entry = startup_dir / "LAN Bridge.vbs"
            if not enabled:
                entry.unlink(missing_ok=True)
                return
            startup_dir.mkdir(parents=True, exist_ok=True)
            python_path = Path(sys.executable)
            pythonw = python_path.with_name("pythonw.exe")
            if pythonw.exists():
                python_path = pythonw
            command = f'"{python_path}" -m lanbridge.gui --autostart'
            escaped = command.replace('"', '""')
            entry.write_text(
                f'CreateObject("WScript.Shell").Run "{escaped}", 0, False\n',
                encoding="utf-8-sig",
            )
            return
        entry = Path.home() / ".config/autostart/lanbridge.desktop"
        if not enabled:
            entry.unlink(missing_ok=True)
            return
        entry.parent.mkdir(parents=True, exist_ok=True)
        project_root = Path(__file__).resolve().parents[2]
        entry.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=LAN Bridge\n"
            f'Exec="{sys.executable}" -m lanbridge.gui --autostart\n'
            f'Path="{project_root}"\n'
            "Icon=input-keyboard\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )

    def _copy_text(self, value: str, notice: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()
        self._append_log(notice)

    def _regenerate_token(self) -> None:
        if self.backend.running:
            messagebox.showwarning(APP_TITLE, "请先停止接收服务，再更新配对令牌。")
            return
        if not messagebox.askyesno(APP_TITLE, "更新令牌后，Windows 需要重新配对。是否继续？"):
            return
        self.config.token = Config.new(self.config.device_name).token
        save_config(self.config, self.config_path)
        self.token_var.set(self.config.token)
        self._append_log("已生成新的配对令牌")

    def _discover(self, start_after: bool = False) -> None:
        if self.role != "controller" or self.backend.running:
            return
        self.start_after_discovery = start_after
        self.discover_button.configure(state="disabled")
        self._set_status("正在发现设备…", WARNING)
        self._append_log("正在搜索局域网中的 Ubuntu 接收端…")

        def worker() -> None:
            try:
                peers = discover(self.config.discovery_port)
                self.events.put(("discovery", peers))
            except OSError as exc:
                self.events.put(("discovery_error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="gui-discovery").start()

    def _toggle_backend(self) -> None:
        if self.backend.running:
            self._append_log("正在停止后台服务…")
            self._set_status("正在停止…", WARNING)
            self.backend.stop()
        else:
            self._start_backend()

    def _start_backend(self) -> None:
        try:
            if self.role == "controller":
                host = self.host_var.get().strip()
                if not host:
                    self._discover(start_after=True)
                    return
                self.config.peer_host = host
                self.config.token = self.token_var.get().strip()
                self.config.mouse_sensitivity = round(self.sensitivity_var.get(), 2)
                _ = self.config.token_bytes
                save_config(self.config, self.config_path)
                command = backend_command(
                    self.role,
                    self.config_path,
                    host,
                    self.config.mouse_sensitivity,
                )
            else:
                if os.name != "nt" and not os.access("/dev/uinput", os.W_OK):
                    raise PermissionError(self._permission_status())
                self.config.preferred_role = "receiver"
                save_config(self.config, self.config_path)
                command = backend_command(self.role, self.config_path)
            self.backend.start(command)
        except (OSError, PermissionError, RuntimeError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            self._set_status("启动失败", DANGER)
            return
        self.toggle_button.configure(text="停止")
        self._set_status("正在启动…", WARNING)
        self._append_log("后台服务正在启动")

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._handle_log(str(payload))
                elif event == "exit":
                    self._handle_exit(int(payload))
                elif event == "discovery":
                    self._handle_discovery(payload)
                elif event == "discovery_error":
                    self.discover_button.configure(state="normal")
                    self._set_status("发现失败", DANGER)
                    messagebox.showerror(APP_TITLE, f"自动发现失败：{payload}")
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self._drain_events)

    def _handle_log(self, line: str) -> None:
        if not line:
            return
        self._append_log(line)
        if "等待 Windows 主机连接" in line:
            self._set_status("等待 Windows 连接", WARNING)
        elif "已加密连接到" in line:
            self._set_status("已安全连接", SUCCESS)
        elif "主控端已启动" in line:
            self._set_status("已连接 · 当前在 Windows", SUCCESS)
        elif "控制目标：Ubuntu" in line:
            self._set_status("已连接 · 当前在 Ubuntu", SUCCESS)
        elif "控制目标：Windows" in line:
            self._set_status("已连接 · 当前在 Windows", SUCCESS)
        elif line.startswith(("错误：", "Traceback")):
            self._set_status("运行异常", DANGER)

    def _handle_exit(self, code: int) -> None:
        self.toggle_button.configure(text="启动")
        if self.closing:
            return
        if code == 0:
            self._set_status("已停止", MUTED)
        else:
            self._set_status(f"已停止 · 错误码 {code}", DANGER)
            self._append_log(f"后台服务已退出，错误码：{code}")

    def _handle_discovery(self, peers: Any) -> None:
        self.discover_button.configure(state="normal")
        if not peers:
            self.start_after_discovery = False
            self._set_status("未发现设备", WARNING)
            self._append_log("未发现 Ubuntu 接收端，可手动填写 IP 地址")
            return
        peer = peers[0]
        host = str(peer["host"])
        self.host_var.set(host)
        self._set_status("已发现设备", SUCCESS)
        self._append_log(f"发现 {peer.get('name', 'Ubuntu')}：{host}:{peer['port']}")
        if self.start_after_discovery:
            self.start_after_discovery = False
            self._start_backend()

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=color)

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _close(self) -> None:
        self.closing = True
        if self.backend.running:
            self.backend.stop()
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--help" in argv or "-h" in argv:
        print("LAN Bridge 图形界面\n\n用法：lanbridge-gui [--smoke-test]")
        return 0
    smoke_test = "--smoke-test" in argv
    try:
        root = Tk()
    except Exception as exc:  # noqa: BLE001 - tkinter raises platform-specific errors
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        return 2
    if smoke_test:
        root.withdraw()
    app = LanBridgeApp(root)
    if smoke_test:
        root.update_idletasks()
        app._close()
        return 0
    if "--autostart" in argv and app.config.auto_start:
        root.after(1200, app._start_backend)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

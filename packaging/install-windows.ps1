$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue

if ($null -ne $PythonLauncher) {
    & py -m venv (Join-Path $ProjectRoot ".venv")
} else {
    & python -m venv (Join-Path $ProjectRoot ".venv")
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install -e $ProjectRoot

$VenvPythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "LAN Bridge.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $VenvPythonw
$Shortcut.Arguments = "-m lanbridge.gui"
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = "$VenvPythonw,0"
$Shortcut.Description = "LAN Bridge 局域网键鼠与剪贴板共享"
$Shortcut.Save()

Write-Host "LAN Bridge 安装完成。"
Write-Host "桌面快捷方式：$ShortcutPath"
Write-Host "双击 LAN Bridge 即可启动，不再需要命令行。"

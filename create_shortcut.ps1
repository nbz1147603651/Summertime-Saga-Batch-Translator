# ============================================================
#  创建「STS 翻译工具」桌面快捷方式
#  直接双击本脚本运行即可
# ============================================================
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Target     = "powershell.exe"
$Arguments  = "-ExecutionPolicy Bypass -NoProfile -File `"$ScriptDir\run_translator.ps1`""
$ShortcutPath = [System.IO.Path]::Combine(
    [System.Environment]::GetFolderPath("Desktop"),
    "STS 翻译工具.lnk"
)

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $Target
$Shortcut.Arguments        = $Arguments
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description      = "Summertime Saga 批量翻译工具"
$Shortcut.WindowStyle      = 1   # 正常窗口

# 尝试设置图标（游戏 exe 自带图标）
$GameExe = [System.IO.Path]::GetFullPath("$ScriptDir\..\summertimesaga.exe")
if (Test-Path $GameExe) {
    $Shortcut.IconLocation = "$GameExe, 0"
}
$Shortcut.Save()

Write-Host "快捷方式已创建到桌面：$ShortcutPath" -ForegroundColor Green
Start-Sleep -Seconds 2

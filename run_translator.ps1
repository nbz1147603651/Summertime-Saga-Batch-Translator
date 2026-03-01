#Requires -Version 5.0
# ============================================================
#  Summertime Saga 批量翻译工具 — PowerShell 启动脚本
# ============================================================

$Host.UI.RawUI.WindowTitle = "STS 翻译工具启动器"
$ErrorActionPreference = "Stop"

# ── 颜色输出辅助 ────────────────────────────────────────────
function Write-Info  ([string]$msg) { Write-Host "[i] $msg" -ForegroundColor Cyan   }
function Write-OK    ([string]$msg) { Write-Host "[✓] $msg" -ForegroundColor Green  }
function Write-Warn  ([string]$msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err   ([string]$msg) { Write-Host "[✗] $msg" -ForegroundColor Red    }

Clear-Host
Write-Host "=================================================" -ForegroundColor Magenta
Write-Host "   Summertime Saga 批量翻译工具 v1.0" -ForegroundColor White
Write-Host "   基于 Ren'Py Modding API + 大模型翻译" -ForegroundColor Gray
Write-Host "=================================================" -ForegroundColor Magenta
Write-Host ""

# ── 切换到脚本所在目录 ───────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir
Write-Info "工作目录：$ScriptDir"

# ── 确定 Python 解释器 ───────────────────────────────────────
$GamePython = Join-Path $ScriptDir "..\lib\py3-windows-x86_64\python.exe"
$GamePython = [System.IO.Path]::GetFullPath($GamePython)

if (Test-Path $GamePython) {
    $Python = $GamePython
    Write-Info "使用游戏内置 Python：$Python"
} else {
    # 检查系统 Python
    $PyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $PyCmd) {
        $PyCmd = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if ($null -eq $PyCmd) {
        Write-Err "未找到 Python！请先安装 Python 3.8+"
        Write-Host "    下载地址：https://www.python.org/downloads/" -ForegroundColor Yellow
        Read-Host "按 Enter 退出"
        exit 1
    }
    $Python = $PyCmd.Source
    # 检查版本 >= 3.8
    $VerStr = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $Major, $Minor = $VerStr.Split('.') | ForEach-Object { [int]$_ }
    if ($Major -lt 3 -or ($Major -eq 3 -and $Minor -lt 8)) {
        Write-Err "Python 版本过低（$VerStr），需要 3.8 以上"
        Read-Host "按 Enter 退出"
        exit 1
    }
    Write-Info "使用系统 Python $VerStr：$Python"
}

# ── 安装依赖 ─────────────────────────────────────────────────
Write-Info "检查并安装依赖（customtkinter / openai / requests）..."
try {
    & $Python -m pip install customtkinter openai requests --quiet --disable-pip-version-check
    Write-OK "依赖就绪"
} catch {
    Write-Warn "pip 安装时出现警告，尝试继续启动..."
}

# ── 启动主程序 ───────────────────────────────────────────────
Write-Host ""
Write-OK "正在启动翻译工具..."
Write-Host ""

try {
    & $Python "$ScriptDir\translator_app.py"
    $ExitCode = $LASTEXITCODE
} catch {
    Write-Err "启动失败：$_"
    Read-Host "按 Enter 退出"
    exit 1
}

if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Err "程序以错误码 $ExitCode 退出"
    Read-Host "按 Enter 关闭"
}

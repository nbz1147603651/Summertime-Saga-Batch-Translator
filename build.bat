@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

title STS 翻译工具 — PyInstaller 打包
echo ==========================================
echo   STS 翻译工具  打包脚本  (PyInstaller)
echo ==========================================
echo.

:: ── 切换到脚本所在目录 ─────────────────────────────────────
cd /d "%~dp0"

:: ── 检测 Python（优先系统 Python，不用游戏内嵌 Python 打包） ──
where python >nul 2>&1
if errorlevel 1 (
    echo [!] 未找到 Python，请先安装 Python 3.8+
    echo     下载地址：https://www.python.org/downloads/
    pause & exit /b 1
)

:: 验证版本 >= 3.8
for /f "tokens=*" %%v in ('python -c "import sys; ok=sys.version_info>=(3,8); print('ok' if ok else 'old')"') do set PYVER=%%v
if "!PYVER!" neq "ok" (
    echo [!] Python 版本过低，需要 3.8+
    pause & exit /b 1
)

echo [i] 使用 Python：
python --version
echo.

:: ── 安装 / 升级依赖 ───────────────────────────────────────
echo [i] 安装打包所需依赖（customtkinter / openai / requests / pyinstaller）...
python -m pip install --upgrade pip --quiet
python -m pip install customtkinter openai requests pyinstaller --quiet
if errorlevel 1 (
    echo [!] 依赖安装失败，请检查网络或 pip 配置
    pause & exit /b 1
)
echo [✓] 依赖就绪
echo.

:: ── 清理上次构建产物 ──────────────────────────────────────
if exist "dist\STS翻译工具" (
    echo [i] 清理旧的 dist\STS翻译工具 目录 ...
    rmdir /s /q "dist\STS翻译工具"
)
if exist "build" (
    rmdir /s /q "build"
)

:: ── 运行 PyInstaller ──────────────────────────────────────
echo [i] 开始打包，请稍候（首次可能需要 2-5 分钟）...
echo.

python -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "STS翻译工具" ^
    --collect-all customtkinter ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "PIL._tkinter_finder" ^
    translator_app.py

if errorlevel 1 (
    echo.
    echo [!] PyInstaller 打包失败！请查看上方错误信息。
    pause & exit /b 1
)

:: ── 复制运行时所需的外部文件 ──────────────────────────────
echo.
echo [i] 复制运行时文件到发布目录 ...

:: config.json — 用户配置，放在 exe 旁边（可直接编辑）
if exist "config.json" (
    copy /y "config.json" "dist\STS翻译工具\config.json" >nul
    echo [✓] config.json
) else (
    echo [i] 未找到 config.json，跳过（程序首次运行时会自动创建）
)

:: unrpyc-master — .rpyc 反编译工具
if exist "unrpyc-master" (
    xcopy /e /i /q /y "unrpyc-master" "dist\STS翻译工具\unrpyc-master" >nul
    echo [✓] unrpyc-master\
) else (
    echo [i] 未找到 unrpyc-master，跳过（程序运行时可从 GitHub 自动下载）
)

:: ── 创建 README ───────────────────────────────────────────
(
echo STS 翻译工具
echo ============
echo.
echo 使用方法：
echo   1. 双击 STS翻译工具.exe 启动
echo   2. 在设置页填入 API Key 和游戏目录
echo   3. 点击「开始翻译」即可
echo.
echo 重要说明：
echo   - config.json 为配置文件，可直接修改
echo   - _internal 目录为程序内部文件，请勿删除
echo   - logs 目录（运行后自动生成）保存运行日志
) > "dist\STS翻译工具\使用说明.txt"

:: ── 完成 ──────────────────────────────────────────────────
echo.
echo ==========================================
echo   [✓] 打包完成！
echo   输出目录：%~dp0dist\STS翻译工具\
echo ==========================================
echo   直接分发整个 dist\STS翻译工具\ 文件夹即可
echo.
pause

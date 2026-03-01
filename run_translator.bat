@echo off
chcp 65001 >nul
title STS 翻译工具启动器
echo ==========================================
echo   Summertime Saga 批量翻译工具
echo ==========================================
echo.

:: 检查 Python（优先使用游戏内置 Python）
set GAME_PYTHON=..\lib\py3-windows-x86_64\python.exe
set SYS_PYTHON=python

if exist %GAME_PYTHON% (
    echo [i] 使用游戏内置 Python 运行...
    set PYTHON=%GAME_PYTHON%
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [!] 未找到 Python，请先安装 Python 3.8+
        echo     下载地址：https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set PYTHON=%SYS_PYTHON%
)

echo [i] 安装/检查依赖...
%PYTHON% -m pip install customtkinter openai requests -q

echo [i] 启动翻译工具...
echo.
%PYTHON% translator_app.py

if errorlevel 1 (
    echo.
    echo [!] 程序异常退出
    pause
)

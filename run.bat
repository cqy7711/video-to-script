@echo off
chcp 65001 >nul 2>nul
setlocal enabledelayedexpansion

:: ==========================================
::   Video to Script — Windows 启动脚本
::   双击此文件即可启动应用
::   首次使用会自动安装所需依赖
:: ==========================================

echo ==========================================
echo   🎬 Video to Script — 视频转剧本工具
echo ==========================================
echo.

:: ─── 检查 Python3 ───
where python >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
    echo ✅ 检测到 !PY_VER!
    set PYTHON=python
) else (
    where python3 >nul 2>nul
    if %errorlevel% equ 0 (
        for /f "tokens=*" %%i in ('python3 --version 2^>^&1') do set PY_VER=%%i
        echo ✅ 检测到 !PY_VER!
        set PYTHON=python3
    ) else (
        echo ❌ 未检测到 Python，请先安装：
        echo    从 https://www.python.org/downloads/ 下载安装
        echo    ⚠️ 安装时务必勾选「Add Python to PATH」
        echo.
        echo 按任意键退出...
        pause >nul
        exit /b 1
    )
)

:: ─── 检查 Python 版本 >= 3.9 ───
for /f "tokens=2 delims= " %%v in ('!PYTHON! --version 2^>^&1') do set PY_VERSION=%%v
for /f "tokens=1,2 delims=." %%a in ("!PY_VERSION!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if !PY_MAJOR! lss 3 (
    echo ❌ Python 版本过低 ^(!PY_VERSION!^)，需要 3.9+
    echo    请从 https://www.python.org/downloads/ 安装新版 Python
    echo.
    echo 按任意键退出...
    pause >nul
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 9 (
    echo ❌ Python 版本过低 ^(!PY_VERSION!^)，需要 3.9+
    echo    请从 https://www.python.org/downloads/ 安装新版 Python
    echo.
    echo 按任意键退出...
    pause >nul
    exit /b 1
)

:: ─── 检查 ffmpeg（可选但推荐）───
where ffmpeg >nul 2>nul
if %errorlevel% equ 0 (
    echo ✅ 检测到 ffmpeg
) else (
    echo ⚠️  未检测到 ffmpeg（应用会使用内置 ffmpeg，但安装系统版本更快）
    echo    可选安装: 从 https://ffmpeg.org/download.html 下载
)

:: ─── 检查/创建虚拟环境 ───
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "VENV_DIR=%APP_DIR%\.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo 📦 首次运行，正在创建虚拟环境并安装依赖...
    echo    （这可能需要几分钟，请耐心等待）
    echo.
    !PYTHON! -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo ❌ 创建虚拟环境失败，请检查 Python 安装
        echo.
        pause
        exit /b 1
    )
    "%VENV_DIR%\Scripts\pip.exe" install --upgrade pip -q
    "%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%\requirements.txt" -q
    if %errorlevel% neq 0 (
        echo ❌ 依赖安装失败，请检查网络连接
        echo.
        pause
        exit /b 1
    )
    echo.
    echo ✅ 依赖安装完成！
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

:: ─── 检查依赖是否完整 ───
echo.
echo 🔍 检查依赖...
set MISSING=0
for %%p in (PySide6 whisper moviepy scenedetect openai yt_dlp) do (
    "%VENV_PYTHON%" -c "import %%p" >nul 2>nul
    if %errorlevel% neq 0 (
        set MISSING=1
    )
)

if !MISSING! equ 1 (
    echo 📦 补充安装缺失依赖...
    "%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%\requirements.txt" -q
)

echo ✅ 所有依赖就绪
echo.
echo 🎬 启动 Video to Script...
echo.

:: ─── 启动应用 ───
cd /d "%APP_DIR%"
"%VENV_PYTHON%" main.py
if %errorlevel% neq 0 (
    echo.
    echo ❌ 应用运行出错
    pause
)

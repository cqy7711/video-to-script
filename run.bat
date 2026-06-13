@echo off
chcp 65001 >nul 2>nul
setlocal enabledelayedexpansion

:: ==========================================
::   Video to Script - Windows Launcher
::   Double-click to run
::   First run will auto-install dependencies
:: ==========================================

echo ==========================================
echo   Video to Script - Video to Script Tool
echo ==========================================
echo.

:: --- Check Python ---
where python >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
    echo [OK] Found !PY_VER!
    set PYTHON=python
) else (
    where python3 >nul 2>nul
    if %errorlevel% equ 0 (
        for /f "tokens=*" %%i in ('python3 --version 2^>^&1') do set PY_VER=%%i
        echo [OK] Found !PY_VER!
        set PYTHON=python3
    ) else (
        echo [ERROR] Python not found. Please install Python 3.9+
        echo   Download from: https://www.python.org/downloads/
        echo   IMPORTANT: Check "Add Python to PATH" during install
        echo.
        echo Press any key to exit...
        pause >nul
        exit /b 1
    )
)

:: --- Check Python version >= 3.9 ---
for /f "tokens=2 delims= " %%v in ('!PYTHON! --version 2^>^&1') do set PY_VERSION=%%v
for /f "tokens=1,2 delims=." %%a in ("!PY_VERSION!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if !PY_MAJOR! lss 3 (
    echo [ERROR] Python version too old (!PY_VERSION!), need 3.9+
    echo   Download from: https://www.python.org/downloads/
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 9 (
    echo [ERROR] Python version too old (!PY_VERSION!), need 3.9+
    echo   Download from: https://www.python.org/downloads/
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

:: --- Check ffmpeg (optional) ---
where ffmpeg >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] Found ffmpeg
) else (
    echo [WARN] ffmpeg not found (will use built-in ffmpeg)
    echo   Optional: Download from https://ffmpeg.org/download.html
)

:: --- Check / Create virtual environment ---
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "VENV_DIR=%APP_DIR%\.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo [INFO] First run, creating virtual environment...
    echo   (This may take a few minutes, please wait)
    echo.
    !PYTHON! -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment
        echo.
        pause
        exit /b 1
    )
    "%VENV_DIR%\Scripts\pip.exe" install --upgrade pip -q
    "%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%\requirements.txt" -q
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies, check network
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Dependencies installed!
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

:: --- Check dependencies ---
echo.
echo [INFO] Checking dependencies...
set MISSING=0
for %%p in (PySide6 whisper moviepy scenedetect openai yt_dlp) do (
    "%VENV_PYTHON%" -c "import %%p" >nul 2>nul
    if errorlevel 1 (
        set MISSING=1
    )
)

if !MISSING! equ 1 (
    echo [INFO] Installing missing dependencies...
    "%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%\requirements.txt" -q
)

echo [OK] All dependencies ready
echo.
echo [INFO] Starting Video to Script...
echo.

:: --- Launch app ---
cd /d "%APP_DIR%"
"%VENV_PYTHON%" main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application error
    pause
)

@echo off
setlocal
chcp 65001 >nul 2>nul
title username_scanner
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo.
echo  ============================================================
echo   username_scanner  -  Telegram username checker bot
echo  ============================================================
echo.

rem --------------------------------------------------------------- python
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo  [!] Python was not found.
    echo      Install Python 3.12+ and put "python" on PATH,
    echo      or create a virtual environment in .venv
    echo.
    pause
    exit /b 1
)
echo  [i] interpreter: %PY%

rem --------------------------------------------------------------- .env
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo  [!] .env was missing - created it from .env.example.
        echo      Open it and fill in BOT_TOKEN, ADMIN_IDS and REQUIRED_* .
        echo.
        pause
        exit /b 1
    )
    echo  [!] .env is missing and there is no .env.example to copy.
    echo.
    pause
    exit /b 1
)

rem --------------------------------------------------------------- deps
"%PY%" -c "import aiogram, telethon, sqlalchemy, pydantic_settings" >nul 2>nul
if errorlevel 1 (
    echo  [i] Installing dependencies - this happens once...
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [!] Dependency installation failed. See the output above.
        echo.
        pause
        exit /b 1
    )
    echo  [i] Dependencies installed.
)

rem --------------------------------------------------------------- modes
if /i "%~1"=="verify" (
    echo.
    "%PY%" scripts\verify_setup.py
    echo.
    pause
    exit /b 0
)

if /i "%~1"=="check" (
    echo.
    "%PY%" scripts\verify_setup.py
    if errorlevel 1 (
        echo.
        echo  [!] Verification found problems. Fix them, then run start.bat again.
        echo.
        pause
        exit /b 1
    )
    echo.
)

rem --------------------------------------------------------------- run
echo  [i] Starting the bot. Press Ctrl+C to stop.
echo.
"%PY%" -m app.main
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="2" (
    echo  [!] BOT_TOKEN is empty. Fill it in .env.
) else if "%RC%"=="3" (
    echo  [!] Database is unreachable. Check DATABASE_URL in .env.
) else if "%RC%"=="4" (
    echo  [!] Telegram rejected BOT_TOKEN. Get a fresh one from @BotFather.
) else if "%RC%"=="0" (
    echo  [i] Bot stopped.
) else (
    echo  [!] Bot exited with code %RC%. See the log above.
)
echo.
pause
exit /b %RC%

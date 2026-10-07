@echo off
setlocal
chcp 65001 >nul 2>nul
title username_scanner - MTProto login
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo.
echo  ============================================================
echo   MTProto login  -  authorise the checking account
echo  ============================================================
echo.
echo   This authorises a Telegram *user* session for the bot.
echo   It is what makes these work:
echo.
echo     - definitive "this username is free" answers
echo     - collectible username lookup (Fragment data)
echo.
echo   You will need:
echo     - the phone number of the account you want to use
echo     - the login code Telegram sends you inside the app
echo.
echo   Enter the PHONE NUMBER, not a bot token.
echo   The session file stays on this machine and is never uploaded.
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
    echo  [!] Python was not found. Install Python 3.12+ or create a .venv
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo  [!] .env is missing. Copy .env.example to .env and fill it in first.
    echo.
    pause
    exit /b 1
)

rem --------------------------------------------------------------- deps
"%PY%" -c "import telethon" >nul 2>nul
if errorlevel 1 (
    echo  [i] Installing dependencies...
    "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo  [!] Installation failed.
        echo.
        pause
        exit /b 1
    )
)

rem --------------------------------------------------------------- relogin?
rem An existing session makes Telethon skip every prompt, so this is where the
rem user decides: replace it, or keep it and just look at it.
if not exist "username_scanner_session.session" goto dologin

echo  [!] A session already exists:
echo        username_scanner_session.session
echo.
echo      Telegram will NOT ask for a code while it is present.
echo      Logging in again REPLACES it.
echo.
"%PY%" scripts\login_mtproto.py --status
echo.
set /p "RELOGIN=  Re-login with another account now? [y/N] "
if /i "%RELOGIN%"=="y" goto dologin

echo.
echo  [i] Keeping the existing session. Nothing was changed.
echo      Run this file again and answer "y" to replace it.
echo.
pause
exit /b 0

:dologin
echo.
echo  [i] Starting login. Answer the prompts below.
echo.
"%PY%" scripts\login_mtproto.py --force
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo  [ok] Session created. Now start the bot with start.bat
) else if "%RC%"=="2" (
    echo  [!] API_ID / API_HASH are missing in .env.
) else if "%RC%"=="3" (
    echo  [!] Telethon is not installed. Run: pip install -r requirements.txt
) else (
    echo  [!] Login did not complete ^(exit %RC%^). Run this file again to retry.
)
echo.
pause
exit /b %RC%

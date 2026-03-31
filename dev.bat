@echo off
:: dev.bat — HardwareToad v0.7.2 Beta
cd /d "%~dp0"

:: Auto-elevate to admin (required for LHMBridge ring0 access)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

setlocal enabledelayedexpansion

:: ── Clear stale registry settings ────────────────────────────────────────────
reg delete "HKCU\Software\HardwareToad" /f >nul 2>&1

:: ── Find Python ───────────────────────────────────────────────────────────────
set PYTHON=
for %%P in (
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python314\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Program Files\Python314\python.exe"
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python312\python.exe"
    "C:\Program Files\Python311\python.exe"
) do (
    if exist %%P (
        set PYTHON=%%P
        goto :found_python
    )
)
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%i in ('where python') do (
        set PYTHON=%%i
        goto :found_python
    )
)
echo ERROR: Python not found. Install from https://python.org
pause & exit /b 1

:found_python
echo [Dev] Using Python: %PYTHON%

:: ── Always rebuild LHMBridge ─────────────────────────────────────────────────
echo [Dev] Rebuilding LHMBridge...
where dotnet >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: .NET SDK not found. Download from https://aka.ms/dotnet/download
    pause & exit /b 1
)
if not exist dist\LHMBridge mkdir dist\LHMBridge
dotnet publish "%~dp0LHMBridge\LHMBridge.csproj" -c Release -r win-x64 --self-contained true -o "%~dp0dist\LHMBridge" --nologo -v quiet
if errorlevel 1 (
    echo ERROR: LHMBridge build failed
    pause & exit /b 1
)
echo [Dev] LHMBridge built.

:: ── Install dependencies if missing ──────────────────────────────────────────
%PYTHON% -c "import PIL, psutil, wmi" >nul 2>&1
if %errorlevel% neq 0 (
    echo [Dev] Installing dependencies...
    %PYTHON% -m pip install -r "%~dp0requirements.txt" --quiet
)

:: ── Clear pycache ─────────────────────────────────────────────────────────────
for /d /r "%~dp0" %%D in (__pycache__) do @if exist "%%D" rmdir /s /q "%%D" >nul 2>&1

:: ── Kill any existing LHMBridge ───────────────────────────────────────────────
taskkill /f /im LHMBridge.exe >nul 2>&1

:: ── Start LHMBridge in this same window (no separate cmd) ────────────────────
:: /b = background process in same window, output goes to this console
echo [Dev] Starting LHMBridge in DEBUG mode...
start /b dist\LHMBridge\LHMBridge.exe --port=8086 --debug

:: ── Wait for LHMBridge /ready ────────────────────────────────────────────────
echo [Dev] Waiting for LHMBridge...
set READY=0
for /l %%i in (1,1,60) do (
    if !READY!==0 (
        curl -s --max-time 1 -o "%TEMP%\lhm_ready.txt" http://127.0.0.1:8086/ready 2>nul
        if !errorlevel!==0 (
            findstr /c:"true" "%TEMP%\lhm_ready.txt" >nul 2>&1
            if !errorlevel!==0 (
                set READY=1
                echo [Dev] LHMBridge ready ^(%%i s^).
            )
        )
        if !READY!==0 timeout /t 1 /nobreak >nul
    )
)
del "%TEMP%\lhm_ready.txt" >nul 2>&1

if !READY!==0 (
    echo [Dev] WARNING: LHMBridge did not respond after 60s — starting app anyway.
) else (
    echo [Dev] Starting app...
)

echo.
echo [Dev] Debug endpoint: http://127.0.0.1:8086/debug
echo.

:: ── Run the app ───────────────────────────────────────────────────────────────
%PYTHON% main.py

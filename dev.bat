@echo off
:: dev.bat — HWInfo Monitor v0.5.6 Beta
cd /d "%~dp0"

:: Auto-elevate to admin (required for LHMBridge ring0 access)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

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

:: ── Kill any existing LHMBridge and start fresh ───────────────────────────────
taskkill /f /im LHMBridge.exe >nul 2>&1
start "" /b dist\LHMBridge\LHMBridge.exe --port=8086

:: ── Wait for LHMBridge to be ready (poll instead of fixed wait) ───────────────
echo [Dev] Waiting for LHMBridge...
set READY=0
for /l %%i in (1,1,30) do (
    if !READY!==0 (
        curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8086/ready 2>nul | findstr "200" >nul 2>&1
        if !errorlevel!==0 set READY=1
        if !READY!==0 timeout /t 1 /nobreak >nul
    )
)
echo [Dev] LHMBridge ready.

:: ── Run the app ───────────────────────────────────────────────────────────────
%PYTHON% main.py

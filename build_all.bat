@echo off
:: build_all.bat — HWInfo Monitor v0.7.2 Beta
title HWInfo Monitor - Build Script
cd /d "%~dp0"

:: ── Clear stale registry settings ────────────────────────────────────────────
reg delete "HKCU\Software\HWInfoMonitor" /f >nul 2>&1

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
echo [Python] Found: %PYTHON%
for %%i in (%PYTHON%) do set PYTHON_DIR=%%~dpi
set PATH=%PATH%;%PYTHON_DIR%;%PYTHON_DIR%Scripts

:: ── FULL CLEAN ────────────────────────────────────────────────────────────────
echo [0/5] Full clean...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist output rmdir /s /q output
if exist bin rmdir /s /q bin
if exist obj rmdir /s /q obj
if exist LHMBridge\bin rmdir /s /q LHMBridge\bin
if exist LHMBridge\obj rmdir /s /q LHMBridge\obj
if exist .pyinstaller rmdir /s /q .pyinstaller
for /d /r "%~dp0" %%D in (__pycache__) do @if exist "%%D" rmdir /s /q "%%D"
for /r "%~dp0" %%F in (*.pyc) do @if exist "%%F" del /f /q "%%F" >nul 2>&1
for /r "%~dp0" %%F in (*.pyo) do @if exist "%%F" del /f /q "%%F" >nul 2>&1
taskkill /f /im HWInfoMonitor.exe >nul 2>&1
taskkill /f /im LHMBridge.exe >nul 2>&1
echo Done.

echo [1/5] Installing Python dependencies...
%PYTHON% -m pip install -r requirements-build.txt --quiet
echo Done.

:: ── Build LHMBridge (Release — no --debug flag) ───────────────────────────────
where dotnet >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: .NET SDK not found. Download from https://aka.ms/dotnet/download
    pause & exit /b 1
)
echo [2/5] Building LHMBridge (Release)...
mkdir dist\LHMBridge
dotnet publish "%~dp0LHMBridge\LHMBridge.csproj" -c Release -r win-x64 --self-contained true -o "%~dp0dist\LHMBridge" --nologo -v quiet
if errorlevel 1 (
    echo ERROR: LHMBridge build failed
    pause & exit /b 1
)
echo Done.

:: ── Build EXE ────────────────────────────────────────────────────────────────
echo [3/5] Building EXE with PyInstaller...
%PYTHON% -m PyInstaller hwinfo_monitor.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    pause & exit /b 1
)
echo Done.

:: ── Verify version ───────────────────────────────────────────────────────────
echo [4/5] Verifying build...
set "VERSION_FILE=%TEMP%\hwinfo_monitor_version.txt"
%PYTHON% -c "from core.constants import APP_VERSION; print(APP_VERSION)" > "%VERSION_FILE%"
set /p RAW_APP_VERSION=<"%VERSION_FILE%"
del /f /q "%VERSION_FILE%" >nul 2>&1
if not defined RAW_APP_VERSION set "RAW_APP_VERSION=0.0.0"
echo Built version: %RAW_APP_VERSION%
set "INSTALLER_VERSION=%RAW_APP_VERSION:v=%"
set "INSTALLER_VERSION=%INSTALLER_VERSION: Beta=%"
set "INSTALLER_VERSION=%INSTALLER_VERSION: =%"
echo Done.

:: ── Inno Setup ───────────────────────────────────────────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe

if not defined ISCC (
    echo [5/5] Inno Setup not found - skipping installer
    echo.
    echo BUILD COMPLETE - dist\HWInfoMonitor\HWInfoMonitor.exe
    pause & exit /b 0
)

echo [5/5] Building installer...
if not exist output mkdir output
"%ISCC%" /DAppVersion=%INSTALLER_VERSION% installer.iss
echo Done.

echo.
echo BUILD COMPLETE
pause

@echo off
:: build_all.bat — HardwareToad v0.8.0 Beta
title HardwareToad - Build Script
cd /d "%~dp0"

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
taskkill /f /im HardwareToad.exe >nul 2>&1
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

:: ── Build GPUStress (DX12 stress engine) ─────────────────────────────────────
echo [2b/5] Building GPUStress...
set "VCVARS="
for %%V in (18 17 16 15) do if not defined VCVARS (
    for %%E in (Community Professional Enterprise BuildTools) do if not defined VCVARS (
        if exist "C:\Program Files\Microsoft Visual Studio\%%V\%%E\VC\Auxiliary\Build\vcvars64.bat" (
            set "VCVARS=C:\Program Files\Microsoft Visual Studio\%%V\%%E\VC\Auxiliary\Build\vcvars64.bat"
        )
    )
)
if defined VCVARS (
    if not exist "%~dp0GPUStress\build" mkdir "%~dp0GPUStress\build"
    set "GPU_BUILD_SCRIPT=%TEMP%\gpu_build_release.bat"
    echo @echo off > "%TEMP%\gpu_build_release.bat"
    echo call "%VCVARS%" ^>nul 2^>^&1 >> "%TEMP%\gpu_build_release.bat"
    echo cd /d "%~dp0GPUStress\build" >> "%TEMP%\gpu_build_release.bat"
    echo cmake .. -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release --log-level=ERROR ^>nul 2^>^&1 >> "%TEMP%\gpu_build_release.bat"
    echo nmake /nologo ^>nul 2^>^&1 >> "%TEMP%\gpu_build_release.bat"
    call "%TEMP%\gpu_build_release.bat"
    del "%TEMP%\gpu_build_release.bat" >nul 2>&1
)
:: Copy to dist (freshly built or pre-existing)
if exist "%~dp0GPUStress\build\GPUStress.exe" (
    if not exist "%~dp0dist\GPUStress" mkdir "%~dp0dist\GPUStress"
    copy /y "%~dp0GPUStress\build\GPUStress.exe" "%~dp0dist\GPUStress\GPUStress.exe" >nul
    xcopy /e /y /q "%~dp0GPUStress\build\shaders" "%~dp0dist\GPUStress\shaders\" >nul 2>&1
    echo [2b/5] GPUStress ready.
) else (
    echo [WARN] GPUStress.exe not found - GPU stress tests unavailable in this build.
)

:: ── Obfuscate LHMBridge with Obfuscar ───────────────────────────────────────
echo [2c/5] Obfuscating LHMBridge...
where obfuscar.console >nul 2>&1
if %errorlevel% neq 0 (
    :: Try local .NET tool
    if exist "%~dp0.tools\obfuscar\obfuscar.console.exe" (
        set OBFUSCAR="%~dp0.tools\obfuscar\obfuscar.console.exe"
    ) else (
        echo [SKIP] Obfuscar not found. Install with:
        echo        dotnet tool install --tool-path .tools\obfuscar Obfuscar.GlobalTool
        echo        ^(run once, then rebuild^)
        goto :skip_obfuscar
    )
) else (
    set OBFUSCAR=obfuscar.console
)

if not exist "%~dp0obfuscar.xml" (
    echo [SKIP] obfuscar.xml not found in project root — skipping obfuscation.
    goto :skip_obfuscar
)

%OBFUSCAR% "%~dp0obfuscar.xml"
if errorlevel 1 (
    echo WARNING: Obfuscar failed — continuing without obfuscation.
)

:skip_obfuscar
echo Done.
echo [3/5] Building EXE with PyInstaller...
cd /d "%~dp0"
%PYTHON% -m PyInstaller hardware_toad.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    pause & exit /b 1
)
echo Done.

:: ── Verify version ───────────────────────────────────────────────────────────
echo [4/5] Verifying build...
set "VERSION_FILE=%TEMP%\hardwaretoad_version.txt"
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
    echo BUILD COMPLETE - dist\HardwareToad\HardwareToad.exe
    pause & exit /b 0
)

echo [5/5] Building installer...
if not exist output mkdir output
"%ISCC%" /DAppVersion=%INSTALLER_VERSION% installer.iss
echo Done.

echo.
echo BUILD COMPLETE
pause

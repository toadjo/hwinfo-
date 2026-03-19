# HWInfo Monitor

Windows hardware monitor with a Python/Tkinter desktop UI and a self-contained `.NET` bridge built on LibreHardwareMonitor.

## Project Layout

- `main.py`: thin app entry point.
- `core/`: Python UI, formatting, sensor bridge client, and stress-test orchestration.
- `LHMBridge/`: self-contained `.NET` sensor bridge that exposes local HTTP endpoints consumed by the Python app.
- `vendor/`: minimal checked-in third-party artifacts required to build the project from source.
- `build_all.bat`: full clean release build for the bridge, PyInstaller package, and optional Inno Setup installer.
- `dev.bat`: fast local run path for source development. It auto-elevates and republishes `dist\LHMBridge` when the bridge executable or required LibreHardwareMonitor sidecar DLLs are missing.
- `requirements.txt`: Python runtime dependencies.
- `requirements-build.txt`: build-time dependencies used by `build_all.bat`.

## Development Workflow

### Fast local run

Use `dev.bat`.

What it does:
- auto-elevates to Administrator
- republishes `dist\LHMBridge` when the bridge executable or required LibreHardwareMonitor sidecar DLLs are missing
- starts `LHMBridge.exe`
- runs `main.py` with the selected Python interpreter

### Full release build

Use `build_all.bat`.

What it does:
- removes generated build artifacts (`dist`, `output`, `build`, `bin`, `obj`, `__pycache__`, `.pyc`, `.pyo`)
- installs Python build dependencies from `requirements-build.txt`
- publishes `LHMBridge` to `dist\LHMBridge`
- runs PyInstaller using `hwinfo_monitor.spec`
- reads `core.constants.APP_VERSION`
- passes the normalized version into Inno Setup so the installer version stays in sync with the app version

## Requirements

- Windows 10 or newer
- Python 3.11+ recommended
- .NET SDK for building `LHMBridge`
- Inno Setup 6 if you want installer output
- Administrator rights when running the bridge against low-level hardware sensors

## Notes

- `dist/` is generated output and should not be treated as source.
- `vendor/LibreHardwareMonitor/` contains the checked-in LibreHardwareMonitor runtime files used by `LHMBridge.csproj`.
- PyInstaller packages the bridge under `_internal/LHMBridge` inside the final app bundle; the bridge launcher also accepts the older `_internal/dist/LHMBridge` layout for compatibility with older builds.
- The solution file intentionally contains only the real `LHMBridge` project.

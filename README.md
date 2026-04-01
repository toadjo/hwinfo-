# HardwareToad

Windows hardware monitor with a Python/Tkinter UI and a self-contained .NET bridge built on LibreHardwareMonitor. Shows real-time CPU, GPU, RAM, and storage data with live graphs, AVX2/FMA stress testing, and RAM stability testing. Requires Administrator rights for low-level sensor access.

## Project Layout

- `main.py` — app entry point
- `core/` — Python UI, sensor bridge client, formatting, and stress test orchestration
- `LHMBridge/` — self-contained .NET sensor bridge, exposes local HTTP endpoints
- `assets/` — app icon (`logo.ico`) used by PyInstaller
- `vendor/` — checked-in LibreHardwareMonitor runtime files
- `build_all.bat` — full clean release build (bridge → PyInstaller → installer)
- `dev.bat` — fast local run for development (auto-elevates, rebuilds bridge if needed)
- `obfuscar.xml` — Obfuscar config for LHMBridge.dll symbol obfuscation
- `requirements.txt` — Python runtime dependencies
- `requirements-build.txt` — build-time dependencies

## Quick Start

```bat
git clone https://github.com/toadjo/hwinfo-
cd hwinfo-
pip install -r requirements.txt
dev.bat
```

## Development Workflow

### Fast local run — `dev.bat`
- Auto-elevates to Administrator
- Rebuilds `dist\LHMBridge` when the exe or required DLLs are missing
- Starts `LHMBridge.exe` and launches `main.py`

### Full release build — `build_all.bat`
- Cleans all build artifacts
- Installs Python build dependencies
- Publishes LHMBridge (with Obfuscar obfuscation if installed)
- Packages the app with PyInstaller using `hardware_toad.spec`
- Reads `APP_VERSION` from `core/constants.py` and passes it to Inno Setup

## Requirements

- Windows 10 or newer (64-bit)
- Python 3.11+
- .NET SDK (to build LHMBridge from source)
- Inno Setup 6 (optional, for installer output)
- Administrator rights at runtime

## Security

HardwareToad includes several layers of protection for the local sensor bridge:

- **Token auth** — a random 256-bit token is generated at startup and required on every HTTP request to LHMBridge
- **SHA256 integrity check** — LHMBridge.exe is hashed on first run; any modification is detected and blocks startup
- **Obfuscar** — LHMBridge.dll symbols are renamed at build time. Install with:
  ```bat
  dotnet tool install --tool-path .tools\obfuscar Obfuscar.GlobalTool
  ```

## Notes

- `dist/` is generated output — do not treat as source
- `vendor/LibreHardwareMonitor/` contains the runtime files used by `LHMBridge.csproj`
- The app icon is embedded via `assets\logo.ico` — referenced in `hardware_toad.spec`
- Version lives in one place: `core/constants.py` → `APP_VERSION`

# Vendor Dependencies

This folder contains the minimal checked-in third-party artifacts required to build HWInfo Monitor from source.

## LibreHardwareMonitor

- `LibreHardwareMonitor/LibreHardwareMonitorLib.dll`
- `LibreHardwareMonitor/RAMSPDToolkit-NDD.dll`
- `LibreHardwareMonitor/DiskInfoToolkit.dll`
- `LibreHardwareMonitor/HidSharp.dll`
- `LibreHardwareMonitor/BlackSharp.Core.dll`
- Used by `LHMBridge/LHMBridge.csproj`
- These files come from the official `LibreHardwareMonitor.NET.10.zip` release bundle.
- The bridge needs the sidecar DLLs at runtime; stripping them breaks sensor initialization.

import platform
from functools import lru_cache


def _import_wmi():
    import importlib

    return importlib.import_module("wmi")


@lru_cache(maxsize=1)
def _get_wmi_client():
    return _import_wmi().WMI()


def _read_windows_current_version_value(*names):
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        )
        for name in names:
            try:
                return winreg.QueryValueEx(key, name)[0]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def get_cpu_name():
    try:
        return _get_wmi_client().Win32_Processor()[0].Name.strip()
    except Exception:
        return platform.processor() or "Unknown CPU"


def get_ram_info():
    try:
        sticks = _get_wmi_client().Win32_PhysicalMemory()
        smb_map = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5"}
        ddr = smb_map.get(getattr(sticks[0], "SMBIOSMemoryType", 0), "DDR")
        form = {8: "DIMM", 12: "SO-DIMM", 13: "SO-DIMM"}.get(
            getattr(sticks[0], "FormFactor", 8), "DIMM"
        )
        spd = sticks[0].Speed or ""
        return f"{ddr}{f' @ {spd} MHz' if spd else ''}  |  {len(sticks)}x {form}"
    except Exception:
        return ""


def get_all_disks():
    try:
        disks = []
        for d in _get_wmi_client().Win32_DiskDrive():
            model = (d.Model or "Unknown").strip()
            size = round(int(d.Size) / 1024 ** 3) if d.Size else 0
            dtype = (
                "NVMe"
                if any(k in model.lower() for k in ["nvme", "sn770", "sn850", "970", "980"])
                else ("SSD" if "ssd" in model.lower() else "HDD")
            )
            disks.append(
                {
                    "model": model,
                    "type": dtype,
                    "size": size,
                    "index": int(d.Index or 0),
                }
            )
        return disks
    except Exception:
        return []


def get_windows_version():
    try:
        build = int(_read_windows_current_version_value("CurrentBuildNumber"))
        ubr = _read_windows_current_version_value("UBR")
        name = "Windows 11" if build >= 22000 else "Windows 10"
        return f"{name} (Build {build}.{ubr})"
    except Exception:
        return f"{platform.system()} {platform.release()}"


def get_windows_version_name():
    """Get friendly version like 23H2, 24H2, 25H2 etc."""
    return _read_windows_current_version_value("DisplayVersion", "ReleaseId")


def get_windows_build():
    """Get build string like 26200.8037"""
    try:
        build = _read_windows_current_version_value("CurrentBuildNumber")
        ubr = _read_windows_current_version_value("UBR")
        return f"{build}.{ubr}"
    except Exception:
        return ""


def get_gpu_driver_version():
    """Get GPU driver version via WMI."""
    try:
        gpus = _get_wmi_client().Win32_VideoController()
        if gpus:
            drv = gpus[0].DriverVersion or ""
            # Format: 31.0.101.5382 → strip leading zeros per segment
            parts = drv.split(".")
            if len(parts) >= 4:
                # NVIDIA style: last two segments form the version e.g. 537.42
                return f"{parts[-2]}.{parts[-1]}"
            return drv
    except Exception:
        pass
    return "N/A"


def load_static_system_info():
    return {
        "cpu_name": get_cpu_name(),
        "ram_info": get_ram_info(),
        "all_disks": get_all_disks(),
        "windows_version": get_windows_version(),
        "windows_ver_name": get_windows_version_name(),
        "windows_build": get_windows_build(),
        "gpu_driver": get_gpu_driver_version(),
    }

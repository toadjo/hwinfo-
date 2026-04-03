# bridge.py — HWInfo Monitor v0.7.2 Beta
import atexit
import ctypes
import hashlib
import json
import secrets
import threading
import os
import subprocess
import sys
import time
import urllib.request

from .constants import BRIDGE_PORT
from .paths import get_base_path

# ── Shared secret — generated once per app launch ─────────────────────────────
_BRIDGE_TOKEN = secrets.token_hex(32)   # 256-bit random token


def get_bridge_token() -> str:
    """Public accessor so stress_manager and app.py can inject the auth header."""
    return _BRIDGE_TOKEN


def _is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin() -> None:
    """Re-launch the current process elevated via ShellExecute RunAs.

    This triggers the UAC prompt. The original (non-elevated) process exits
    immediately after spawning the elevated one.
    """
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    # Use the Python executable that is running us, or the frozen .exe
    exe = sys.executable
    ctypes.windll.shell32.ShellExecuteW(
        None,           # hwnd
        "runas",        # verb — triggers UAC
        exe,            # file
        f'"{script}" {params}',  # params
        None,           # working dir (inherit)
        1,              # SW_NORMAL
    )
    sys.exit(0)


def ensure_admin() -> None:
    """Call this at app startup. If not admin, re-launch elevated and exit."""
    if not _is_admin():
        _relaunch_as_admin()


class BridgeManager:
    def __init__(self, port=BRIDGE_PORT):
        self.port = port
        self._bridge_proc = None
        self._bridge_data = {}
        self._lock = threading.Lock()
        atexit.register(self.stop)

    # ── Authenticated HTTP helper ──────────────────────────────────────────────
    def _make_request(self, path: str, timeout: float = 2):
        """urlopen with X-HardwareToad-Token header injected."""
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, headers={"X-HardwareToad-Token": _BRIDGE_TOKEN})
        return urllib.request.urlopen(req, timeout=timeout)

    # ── LHMBridge integrity check ─────────────────────────────────────────────
    @staticmethod
    def _verify_bridge_integrity(path: str) -> bool:
        """SHA256-check LHMBridge.exe against a stored hash.

        On first run the hash is recorded. Subsequent runs compare against it.
        Returns True if the binary is unmodified (or first run).
        """
        hash_file = os.path.join(os.path.dirname(path), "LHMBridge.sha256")
        try:
            sha = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            current = sha.hexdigest()

            if not os.path.exists(hash_file):
                # First run — store hash
                with open(hash_file, "w") as f:
                    f.write(current)
                return True

            with open(hash_file, "r") as f:
                stored = f.read().strip()

            if current != stored:
                import tkinter.messagebox as mb
                mb.showerror(
                    "HardwareToad — Security Warning",
                    "LHMBridge.exe has been modified since installation.\n\n"
                    "The application will not start for your safety.\n"
                    "Please reinstall HardwareToad.",
                )
                return False
            return True
        except Exception:
            # Fail closed — if we can't verify, don't trust it
            return False

    @property
    def data(self):
        return self._bridge_data

    def _get_bridge_path(self):
        exe_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        for p in [
            os.path.join(exe_dir, "_internal", "LHMBridge", "LHMBridge.exe"),
            os.path.join(exe_dir, "_internal", "dist", "LHMBridge", "LHMBridge.exe"),
            os.path.join(exe_dir, "LHMBridge", "LHMBridge.exe"),
            os.path.join(get_base_path(), "LHMBridge", "LHMBridge.exe"),
        ]:
            if os.path.exists(p):
                return p
        return None

    def _windows_startup_info(self):
        if not hasattr(subprocess, "STARTUPINFO"):
            return None, 0
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return si, creationflags

    def _launch_bridge_elevated(self, path: str) -> bool:
        """Launch LHMBridge.exe elevated via ShellExecute RunAs.

        Used as fallback when the current process is NOT admin.
        Because ShellExecuteW spawns an independent process we can't hold a
        Popen handle — we just wait for /ready instead.

        The auth token is written to a temp file (not CLI args, which are
        visible to all local processes via WMI). The bridge reads and deletes
        the file on startup.
        Returns True if the bridge becomes reachable within ~15 s.
        """
        # Write token to temp file — bridge reads & deletes it at startup
        import tempfile
        token_file = os.path.join(tempfile.gettempdir(), "hardwaretoad_token.tmp")
        try:
            with open(token_file, "w") as f:
                f.write(_BRIDGE_TOKEN)
        except Exception:
            pass

        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            path,
            f"--port={self.port} --token-file=\"{token_file}\"",
            None,
            0,  # SW_HIDE
        )
        # ShellExecuteW returns >32 on success
        if ret <= 32:
            return False

        # Wait for /ready
        for _ in range(30):
            time.sleep(0.5)
            try:
                r = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/ready", timeout=1
                )
                if r.read().decode() == "true":
                    return True
            except Exception:
                pass
        return False

    def start(self):
        """Start LHMBridge if not already running, then wait for sensor data."""
        # ── Already running? (dev.bat pre-launched it) ────────────────────────
        try:
            r = self._make_request("/ready", timeout=1)
            if r.read().decode() == "true":
                for _ in range(20):
                    time.sleep(0.5)
                    try:
                        r2 = self._make_request("/sensors", timeout=2)
                        data = json.loads(r2.read())
                        if len(data) > 2:
                            with self._lock:
                                self._bridge_data = data
                            return True
                    except Exception:
                        pass
                return True
        except Exception:
            pass

        path = self._get_bridge_path()
        if not path:
            return False

        # ── Integrity check ───────────────────────────────────────────────────
        if not self._verify_bridge_integrity(path):
            return False

        # ── Launch bridge ─────────────────────────────────────────────────────
        # The LHMBridge.exe manifest requests requireAdministrator so Windows
        # will auto-elevate it via UAC when the parent is not admin.
        # However, if the parent IS admin we launch normally (inherits perms).
        # If the parent is NOT admin and ShellExecute fails, we fall back to
        # a direct Popen (bridge will run without ring0 — sensors may be N/A).
        bridge_args = [path, f"--port={self.port}"]
        bridge_env = os.environ.copy()
        bridge_env["HARDWARETOAD_TOKEN"] = _BRIDGE_TOKEN
        launched = False
        try:
            if _is_admin():
                # Parent is admin → child inherits → no UAC prompt needed
                si, creationflags = self._windows_startup_info()
                self._bridge_proc = subprocess.Popen(
                    bridge_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=si,
                    creationflags=creationflags,
                    env=bridge_env,
                )
                launched = True
            else:
                # Parent is NOT admin → use ShellExecute RunAs so UAC fires
                launched = self._launch_bridge_elevated(path)
                if launched:
                    # Bridge is already ready — skip the ready-wait below
                    return self._wait_for_sensor_data()
        except Exception:
            pass

        if not launched:
            # Last resort: plain Popen (ring0 may fail but app stays alive)
            try:
                si, creationflags = self._windows_startup_info()
                self._bridge_proc = subprocess.Popen(
                    bridge_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=si,
                    creationflags=creationflags,
                    env=bridge_env,
                )
            except Exception:
                return False

        # ── Wait for /ready ───────────────────────────────────────────────────
        for _ in range(30):
            time.sleep(0.5)
            try:
                r = self._make_request("/ready", timeout=1)
                if r.read().decode() == "true":
                    break
            except Exception:
                pass

        return self._wait_for_sensor_data()

    def _wait_for_sensor_data(self) -> bool:
        """Poll /sensors until we have CPU temp data or timeout (15 s)."""
        for attempt in range(30):
            time.sleep(0.5)
            try:
                r = self._make_request("/sensors", timeout=2)
                data = json.loads(r.read())
                has_cpu_temps = any(
                    "cpu" in k.lower() and
                    any(s.get("Type", "").lower() == "temperature" for s in v)
                    for k, v in data.items()
                )
                if len(data) > 2 and has_cpu_temps:
                    with self._lock:
                        self._bridge_data = data
                    return True
                elif len(data) > 2 and attempt >= 20:
                    with self._lock:
                        self._bridge_data = data
                    return True
            except Exception:
                pass
        return True

    def stop(self):
        if self._bridge_proc:
            try:
                self._bridge_proc.terminate()
            except Exception:
                pass

    def _fetch_once(self):
        try:
            r = self._make_request("/sensors", timeout=2)
            data = json.loads(r.read())
            with self._lock:
                self._bridge_data = data
            return True
        except Exception:
            return False

    def fetch(self):
        return self._fetch_once()

    def get_data_snapshot(self):
        """Return a thread-safe shallow copy of the full data dict."""
        with self._lock:
            return dict(self._bridge_data)

    def get_sensor_snapshot(self, key):
        """Return a thread-safe copy of the sensor list for key."""
        with self._lock:
            return list(self._bridge_data.get(key, []))

    def find_all_sensors(self, hw_type, name_keyword, sensor_type):
        results = []
        for key, sensors in self.get_data_snapshot().items():
            if hw_type.lower() not in key.lower():
                continue
            for s in sensors:
                if s["Type"].lower() != sensor_type.lower():
                    continue
                if name_keyword.lower() in s["Name"].lower():
                    results.append((s["Name"], s["Value"]))
        return results

    def find_all_fans(self):
        """Search every hardware key for Fan sensors (RPM only).

        Only returns Type=Fan sensors — Control sensors report duty cycle %
        not RPM and must not be mixed in.
        Returns list of (name, rpm_value).
        """
        seen    = set()
        results = []

        for key, sensors in self._bridge_data.items():
            for s in sensors:
                if s["Type"].lower() != "fan":
                    continue
                uid = (key, s["Name"])
                if uid in seen:
                    continue
                seen.add(uid)
                val = s["Value"]
                if val is not None:
                    results.append((s["Name"], val))

        if not results:
            try:
                import psutil
                psutil_fans = psutil.sensors_fans()
                if psutil_fans:
                    fb = []
                    for controller, entries in psutil_fans.items():
                        for entry in entries:
                            if entry.current > 0:
                                label = f"{controller} {entry.label}".strip()
                                fb.append((label, entry.current))
                    if fb:
                        return fb
            except Exception:
                pass

        return results

    def get_gpu_keys(self):
        with self._lock:
            keys = list(self._bridge_data.keys())
        return sorted(
            [k for k in keys if "gpu" in k.lower()],
            key=lambda k: (0 if "intel" in k.lower() else 1),
        )

    @staticmethod
    def sensor_value_in(sensors, name_kws, stype):
        for s in sensors:
            if s["Type"].lower() != stype.lower():
                continue
            for kw in name_kws:
                if kw.lower() in s["Name"].lower():
                    return s["Value"]
        return None

    def get_cpu_temp(self):
        """Fetch CPU temp from LHMBridge /cpu-temp endpoint."""
        try:
            r = self._make_request("/cpu-temp", timeout=1)
            val = r.read().decode().strip()
            if val != "null":
                return float(val)
        except Exception:
            pass
        for key, sensors in self.get_data_snapshot().items():
            if "cpu" not in key.lower():
                continue
            v = self.sensor_value_in(
                sensors,
                ["CPU Package", "Package", "Core Max", "Core Average",
                 "Core #0", "Core #1", "Core"],
                "Temperature",
            )
            if v is not None:
                return v
        return None

    def get_memory_timings(self):
        """Fetch real AMD memory timings from LHMBridge /timings endpoint."""
        try:
            r = self._make_request("/timings", timeout=1)
            data = json.loads(r.read())
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
        return {}

    def get_wmi_memory_info(self):
        """WMI SMBIOS fallback — returns dict with 'speed', 'voltage', and JEDEC timings."""
        try:
            import subprocess
            cmd = (
                'powershell -NoProfile -Command "'
                'Get-CimInstance Win32_PhysicalMemory | Select-Object '
                'ConfiguredClockSpeed,ConfiguredVoltage,Speed,SMBIOSMemoryType '
                '| ConvertTo-Json -Compress"'
            )
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
            if r.returncode != 0:
                return {}
            data = json.loads(r.stdout.strip())
            # Single stick returns dict, multiple returns list
            if isinstance(data, dict):
                data = [data]
            if not data:
                return {}
            stick = data[0]
            result = {}
            v = stick.get("ConfiguredVoltage")
            if v and v > 0:
                result["voltage"] = v / 1000.0  # millivolts → volts
            configured = stick.get("ConfiguredClockSpeed") or 0
            spd_speed  = stick.get("Speed") or 0
            speed = configured or spd_speed
            # SMBIOSMemoryType: 26 = DDR4, 34 = DDR5
            mem_type = stick.get("SMBIOSMemoryType", 0)
            if speed and speed > 0:
                result["spd_speed"] = speed
                timings = self._jedec_timings_for_speed(speed, mem_type)
                if timings:
                    result["jedec_timings"] = timings
            return result
        except Exception:
            return {}

    @staticmethod
    def _jedec_timings_for_speed(mhz, mem_type=0):
        """Return standard JEDEC CL-tRCD-tRP-tRAS for a given speed.

        WMI ConfiguredClockSpeed behaviour varies by system:
          - Some return real clock (e.g. 1333 for DDR4-2666)
          - Some return MT/s directly (e.g. 2666 for DDR4-2666)
        We use SMBIOSMemoryType + voltage + value range to determine
        whether to double or not.
        """
        # JEDEC standard timing tables keyed by MT/s
        # DDR4 — JEDEC SPD standard timings per speed bin
        ddr4 = {
            2133: (15, 15, 15, 33),
            2400: (17, 17, 17, 39),
            2666: (19, 19, 19, 42),
            2933: (21, 21, 21, 47),
            3200: (22, 22, 22, 52),
        }
        # DDR5 — JEDEC SPD standard timings per speed bin
        ddr5 = {
            4800: (40, 40, 40, 77),
            5200: (42, 42, 42, 83),
            5600: (46, 46, 46, 90),
            6000: (50, 50, 50, 97),
            6400: (52, 52, 52, 103),
            6800: (56, 56, 56, 110),
            7200: (58, 58, 58, 116),
            7600: (62, 62, 62, 122),
            8000: (64, 64, 64, 129),
            8400: (68, 68, 68, 135),
            8800: (72, 72, 72, 142),
        }

        # Determine if value is already MT/s or needs doubling
        # SMBIOSMemoryType: 26=DDR4, 34=DDR5
        is_ddr4 = mem_type == 26 or (mem_type == 0 and mhz <= 3200)
        is_ddr5 = mem_type == 34 or (mem_type == 0 and mhz > 3200)

        if is_ddr4:
            # Check if value is already MT/s (>= 2000) or real clock (< 2000)
            if mhz >= 2000:
                mt_s = mhz  # already MT/s
            else:
                mt_s = mhz * 2  # real clock → MT/s
            table = ddr4
        elif is_ddr5:
            if mhz >= 4000:
                mt_s = mhz  # already MT/s
            else:
                mt_s = mhz * 2
            table = ddr5
        else:
            # Unknown type — try both tables
            mt_s = mhz if mhz >= 2000 else mhz * 2
            table = {**ddr4, **ddr5}

        # Exact match
        if mt_s in table:
            cl, rcd, rp, ras = table[mt_s]
            return {"tCL": cl, "tRCD": rcd, "tRP": rp, "tRAS": ras}

        # Closest bin ≤ actual speed
        best = None
        for bin_mt, vals in sorted(table.items()):
            if bin_mt <= mt_s:
                best = vals
        if best:
            cl, rcd, rp, ras = best
            return {"tCL": cl, "tRCD": rcd, "tRP": rp, "tRAS": ras}
        return None

    def diagnose_na(self, sensor_type, hw_hint=""):
        """Return a short reason string for why a sensor shows N/A."""
        data = self.get_data_snapshot()

        if not data:
            try:
                self._make_request("/ready", timeout=1)
                return "Bridge running but no data yet — still initializing"
            except Exception:
                return "LHMBridge not running or not accessible"

        if sensor_type == "cpu_temp":
            cpu_keys = [k for k in data if "cpu" in k.lower()]
            if not cpu_keys:
                return "No CPU hardware detected by LHM (try running as Administrator)"
            for key in cpu_keys:
                temps = [s for s in data[key] if s["Type"].lower() == "temperature"]
                if not temps:
                    return f"CPU found ({key}) but no temperature sensors — driver conflict or insufficient permissions"
                valid = [s for s in temps if s["Value"] and 10 <= s["Value"] <= 105]
                if not valid:
                    return f"CPU temps found but all out of range: {[s['Value'] for s in temps]}"
                return f"Sensor found but not matched — available: {[s['Name'] for s in valid]}"
            return "CPU key exists but empty"

        elif sensor_type == "disk":
            storage_keys = [k for k in data if "storage" in k.lower()]
            if not storage_keys:
                return "No storage hardware detected by LHM (try running as Administrator)"
            return f"Storage detected ({len(storage_keys)} drives) but health/temp sensors missing"

        elif sensor_type == "fan":
            fan_sensors = []
            for sensors in data.values():
                fan_sensors += [s for s in sensors if s["Type"].lower() in ("fan", "control")]
            if not fan_sensors:
                return "No fan sensors found — motherboard may not support fan monitoring"
            return f"{len(fan_sensors)} fan sensors found but all read 0 RPM"

        return "Unknown — check Raw Sensors window for details"

    def get_primary_gpu_temp(self):
        for key in self.get_gpu_keys():
            sensors = self.get_sensor_snapshot(key)
            v = self.sensor_value_in(sensors, ["GPU Core", "Core"], "Temperature")
            if v is not None:
                return v
        return None

    def get_mobo_sensors(self):
        """Fetch motherboard SuperIO sensors from LHMBridge /mobo endpoint."""
        try:
            r = self._make_request("/mobo", timeout=2)
            data = json.loads(r.read())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

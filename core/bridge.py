import atexit
import json
import threading
import os
import subprocess
import sys
import time
import urllib.request

from .constants import BRIDGE_PORT
from .paths import get_base_path


class BridgeManager:
    def __init__(self, port=BRIDGE_PORT):
        self.port = port
        self._bridge_proc = None
        self._bridge_data = {}
        self._lock = threading.Lock()
        atexit.register(self.stop)

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

    def start(self):
        """Start LHMBridge if not already running, then wait for sensor data."""
        # Check if bridge is already running (e.g. started by dev.bat)
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/ready", timeout=1)
            if r.read().decode() == "true":
                # Already running — just wait for sensor data
                for _ in range(20):
                    time.sleep(0.5)
                    try:
                        r2 = urllib.request.urlopen(
                            f"http://127.0.0.1:{self.port}/sensors", timeout=2)
                        data = json.loads(r2.read())
                        if len(data) > 2:
                            with self._lock:
                                self._bridge_data = data
                            return True
                    except Exception:
                        pass
                return True
        except Exception:
            pass  # Not running yet, start it below

        path = self._get_bridge_path()
        if not path:
            return False

        try:
            si, creationflags = self._windows_startup_info()
            self._bridge_proc = subprocess.Popen(
                [path, f"--port={self.port}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=si,
                creationflags=creationflags,
            )
            # Wait for /ready
            for _ in range(30):
                time.sleep(0.5)
                try:
                    r = urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/ready", timeout=1
                    )
                    if r.read().decode() == "true":
                        break
                except Exception:
                    pass

            # Wait for actual sensor data — LHM needs extra time after ready
            # Try up to 15 seconds (30 x 0.5s) — some machines need longer for ring0
            for attempt in range(30):
                time.sleep(0.5)
                try:
                    r = urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/sensors", timeout=2
                    )
                    data = json.loads(r.read())
                    # Check if CPU hardware has temperature sensors specifically
                    has_cpu_temps = any(
                        "cpu" in k.lower() and
                        any(s.get("Type","").lower() == "temperature"
                            for s in v)
                        for k, v in data.items()
                    )
                    if len(data) > 2 and has_cpu_temps:
                        with self._lock:
                            self._bridge_data = data
                        return True
                    elif len(data) > 2 and attempt >= 20:
                        # Give up waiting for temps, use what we have
                        with self._lock:
                            self._bridge_data = data
                        return True
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def stop(self):
        if self._bridge_proc:
            try:
                self._bridge_proc.terminate()
            except Exception:
                pass

    def _fetch_once(self):
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/sensors", timeout=2
            )
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

        # Fallback: psutil if LHM returned nothing
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
        """Fetch CPU temp from LHMBridge /cpu-temp endpoint.
        The C# side uses HardwareType enums — no string guessing needed.
        Falls back to sensor scan if endpoint unavailable.
        """
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/cpu-temp", timeout=1)
            val = r.read().decode().strip()
            if val != "null":
                return float(val)
        except Exception:
            pass
        # Fallback for older LHMBridge versions without /cpu-temp
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
        """Fetch real AMD memory timings from LHMBridge /timings endpoint.
        Returns dict with tCL, tRCDRD, tRP, tRAS, tRFC, CR or empty dict."""
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/timings", timeout=1)
            data = json.loads(r.read())
            return data if isinstance(data, dict) and data else {}
        except Exception:
            return {}

    def diagnose_na(self, sensor_type, hw_hint=""):
        """Return a short reason string for why a sensor shows N/A.

        sensor_type: "cpu_temp" | "gpu_temp" | "disk" | "fan"
        hw_hint: optional hardware key substring for context
        """
        data = self.get_data_snapshot()

        # Check if bridge is even running
        if not data:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/ready", timeout=1)
                return "Bridge running but no data yet — still initializing"
            except Exception:
                return "LHMBridge not running or not accessible"

        if sensor_type == "cpu_temp":
            # Check if CPU hardware key exists
            cpu_keys = [k for k in data if "cpu" in k.lower()]
            if not cpu_keys:
                return "No CPU hardware detected by LHM (try running as Administrator)"
            # Check if it has temperature sensors
            for key in cpu_keys:
                temps = [s for s in data[key] if s["Type"].lower() == "temperature"]
                if not temps:
                    return f"CPU found ({key}) but no temperature sensors — driver conflict or insufficient permissions"
                # Check if all temps are out of range
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
            sensors = self.get_sensor_snapshot(key)   # thread-safe copy via lock
            v = self.sensor_value_in(sensors, ["GPU Core", "Core"], "Temperature")
            if v is not None:
                return v
        return None

    def get_mobo_sensors(self):
        """Fetch motherboard SuperIO sensors from LHMBridge /mobo endpoint.

        Returns dict with keys:
            name        - str  : board name e.g. "ROG CROSSHAIR X670E HERO"
            temperatures - list of {name, value}
            voltages     - list of {name, value}
            fans         - list of {name, value}
        Returns empty dict on failure.
        """
        try:
            r = urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/mobo", timeout=2)
            data = json.loads(r.read())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

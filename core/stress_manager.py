import os
import queue
import subprocess
import sys
import threading
import time


SUPPORTED_PYTHON_VERSIONS = ("3.14", "3.13", "3.12", "3.11", "3.10")


class StressManager:
    def __init__(self, log_queue):
        self.log_queue = log_queue
        self._stress_proc = None
        self._stress_reader = None
        self._log_routing = {}
        self._cached_python = None

    def _get_worker_path(self):
        for p in [
            os.path.join(os.path.dirname(sys.executable), "stress_worker.py"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "stress_worker.py"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "stress_worker.py"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stress_worker.py"),
        ]:
            if os.path.exists(p):
                return p
        return None

    def _find_python(self):
        if self._cached_python:
            return self._cached_python

        if not getattr(sys, "frozen", False):
            self._cached_python = sys.executable
            return self._cached_python

        candidates = []

        def add_candidate(path):
            if path and os.path.exists(path) and path not in candidates:
                candidates.append(path)

        try:
            import winreg

            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                for ver in SUPPORTED_PYTHON_VERSIONS:
                    try:
                        key = winreg.OpenKey(
                            hive, rf"SOFTWARE\Python\PythonCore\{ver}\InstallPath"
                        )
                        path = winreg.QueryValue(key, None)
                        exe = os.path.join(path.strip(), "python.exe")
                        add_candidate(exe)
                    except Exception:
                        pass
        except Exception:
            pass

        for p in [
            r"C:\Program Files\Python314\python.exe",
            r"C:\Program Files\Python313\python.exe",
            r"C:\Program Files\Python312\python.exe",
            r"C:\Program Files\Python311\python.exe",
            r"C:\Program Files\Python310\python.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python314\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python313\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Python\Python310\python.exe"),
        ]:
            add_candidate(p)

        try:
            res = subprocess.run(["where", "python"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.strip().splitlines():
                line = line.strip()
                if line.endswith("python.exe") and os.path.exists(line):
                    add_candidate(line)
        except Exception:
            pass

        for exe in candidates:
            try:
                res = subprocess.run(
                    [exe, "-c", "import numpy; print('ok')"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "ok" in res.stdout:
                    self._cached_python = exe
                    return exe
            except Exception:
                pass

        self._cached_python = candidates[0] if candidates else None
        return self._cached_python

    def _windows_startup_info(self):
        if not hasattr(subprocess, "STARTUPINFO"):
            return None, 0
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return si, creationflags

    def _ensure_stress_proc(self):
        if self._stress_proc and self._stress_proc.poll() is None:
            return True

        worker = self._get_worker_path()
        python = self._find_python()
        if not worker or not python:
            return False

        si, creationflags = self._windows_startup_info()
        self._stress_proc = subprocess.Popen(
            [python, worker],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=si,
            creationflags=creationflags,
            text=True,
            bufsize=1,
        )

        def reader():
            while True:
                try:
                    if not self._stress_proc or self._stress_proc.poll() is not None:
                        break
                    line = self._stress_proc.stdout.readline()
                    if not line:
                        time.sleep(0.05)
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    routed = False
                    line_lower = line.lower()
                    for prefix, card_id in list(self._log_routing.items()):
                        if line_lower.startswith(prefix.lower()):
                            self.log_queue.put((card_id, line))
                            routed = True
                            break
                    if not routed:
                        for prefix, card_id in list(self._log_routing.items()):
                            if prefix.lower() in line_lower:
                                self.log_queue.put((card_id, line))
                                routed = True
                                break
                    if not routed:
                        default = next(iter(self._log_routing.values()), None)
                        if default:
                            self.log_queue.put((default, line))
                except Exception:
                    time.sleep(0.05)

        def stderr_reader():
            while True:
                try:
                    if not self._stress_proc or self._stress_proc.poll() is not None:
                        break
                    line = self._stress_proc.stderr.readline()
                    if not line:
                        time.sleep(0.05)
                        continue
                    line = line.strip()
                    if line:
                        default = next(iter(self._log_routing.values()), None)
                        if default:
                            self.log_queue.put((default, f"[ERR] {line}"))
                except Exception:
                    time.sleep(0.05)

        self._stress_reader = threading.Thread(target=reader, daemon=True)
        self._stress_reader.start()
        threading.Thread(target=stderr_reader, daemon=True).start()
        return True

    def _send_cmd(self, cmd):
        if self._stress_proc and self._stress_proc.poll() is None:
            try:
                self._stress_proc.stdin.write(cmd + "\n")
                self._stress_proc.stdin.flush()
            except Exception:
                pass

    def make_stress_action(self, cmd_prefix, card_id):
        prefix_map = {
            "cpu_single": "cpu single",
            "cpu_multi": "cpu multi",
            "cpu_memory": "cpu memory",
            "cpu_hybrid": "cpu hybrid",
            "gpu_core": "gpu core",
            "gpu_vram": "gpu vram",
            "gpu_combined": "gpu combined",
        }
        route_key = prefix_map.get(cmd_prefix, cmd_prefix.replace("_", " "))
        self._log_routing[route_key] = card_id

        def start(log_cb):
            if not self._ensure_stress_proc():
                log_cb("Error: stress_worker.py or Python not found!")
                return
            self._send_cmd(f"{cmd_prefix}_start")
            log_cb("▶ Starting...")

        def stop(log_cb):
            self._send_cmd(f"{cmd_prefix}_stop")
            log_cb("■ Stop sent...")

        return start, stop

    def drain_logs(self, max_items=20):
        items = []
        count = 0
        while not self.log_queue.empty() and count < max_items:
            try:
                items.append(self.log_queue.get_nowait())
                count += 1
            except queue.Empty:
                break
        return items

import queue
import threading
import time
import urllib.request
import json

from .constants import BRIDGE_PORT


class StressManager:
    """Delegates all stress work to LHMBridge C# engine via HTTP."""

    def __init__(self, log_queue, port=BRIDGE_PORT):
        self.log_queue = log_queue
        self.port = port
        self._base = f"http://127.0.0.1:{port}"
        self._log_routing = {}
        self._stop_events  = {}
        self._poll_threads = {}

    # cmd key → LHMBridge mode string
    _BRIDGE_MODE = {
        "cpu_single": "cpu_single",
        "cpu_multi":  "cpu_multi",
        "memory":     "memory",
        "combined":   "combined",
        "gpu_core":     "fma",
        "gpu_vram":     "vram",
        "gpu_combined": "combined",
    }

    def _get(self, path, timeout=3):
        try:
            with urllib.request.urlopen(f"{self._base}{path}", timeout=timeout) as r:
                return r.read().decode()
        except Exception as e:
            return f'{{"error":"{e}"}}'

    def _bridge_start(self, mode):
        raw = self._get(f"/stress/start?mode={mode}")
        try:    return json.loads(raw)
        except: return {}

    def _bridge_stop(self):
        self._get("/stress/stop")

    def _bridge_status(self):
        raw = self._get("/stress/status")
        try:    return json.loads(raw)
        except: return {}

    def _poll_loop(self, cmd_prefix, stop_ev, log_cb):
        passes = 0
        last_iters = 0
        last_time  = time.perf_counter()

        while not stop_ev.is_set():
            stop_ev.wait(2.0)
            if stop_ev.is_set():
                break

            passes += 1
            d = self._bridge_status()
            threads = d.get("threads", 0)
            iters   = d.get("iters",   0)

            now     = time.perf_counter()
            delta_i = iters - last_iters
            delta_t = now - last_time
            rate    = delta_i / delta_t / 1e9 if delta_t > 0 else 0.0
            last_iters = iters
            last_time  = now

            if "error" in d:
                log_cb(f"Bridge error: {d['error']}")
            else:
                log_cb(f"{threads} cores | {rate:.2f}B iters/s | Pass {passes} | OK")

        self._bridge_stop()
        log_cb("■ Stopped.")

    def make_stress_action(self, cmd_prefix, card_id):
        self._log_routing[cmd_prefix] = card_id

        def start(log_cb):
            existing = self._stop_events.get(cmd_prefix)
            if existing and not existing.is_set():
                existing.set()

            mode = self._BRIDGE_MODE.get(cmd_prefix, "cpu_multi")
            resp = self._bridge_start(mode)

            if "error" in resp:
                log_cb(f"[ERR] Bridge not available: {resp['error']}")
                return

            threads = resp.get("threads", "?")
            log_cb(f"▶ Started {threads} threads | mode={mode}")

            stop_ev = threading.Event()
            self._stop_events[cmd_prefix] = stop_ev
            t = threading.Thread(
                target=self._poll_loop,
                args=(cmd_prefix, stop_ev, log_cb),
                daemon=True,
            )
            self._poll_threads[cmd_prefix] = t
            t.start()

        def stop(log_cb):
            ev = self._stop_events.get(cmd_prefix)
            if ev:
                ev.set()
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

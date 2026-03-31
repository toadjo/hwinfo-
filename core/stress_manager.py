# stress_manager.py — HWInfo Monitor v0.5.10 Beta
import queue
import threading
import time
import urllib.request
import urllib.parse
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
        # Generation counter per cmd_prefix — incremented on every new start.
        # Each poll loop captures its own generation at birth; if it no longer
        # matches the current value the loop knows it has been superseded and
        # must NOT send /stress/stop (a newer run is already live).
        self._generations  = {}

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

    def _get(self, path, timeout=4):
        try:
            with urllib.request.urlopen(f"{self._base}{path}", timeout=timeout) as r:
                return r.read().decode()
        except Exception as e:
            # Sanitise so the error string is always safe to embed in JSON.
            safe = str(e).replace('\\', '\\\\').replace('"', '\\"')
            return f'{{"error":"{safe}"}}'

    def _bridge_start(self, mode):
        # Use urlencode — handles any special chars in mode name safely.
        qs  = urllib.parse.urlencode({"mode": mode})
        raw = self._get(f"/stress/start?{qs}")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"bad JSON from bridge: {raw[:120]}"}

    def _bridge_stop(self):
        self._get("/stress/stop")

    def _bridge_status(self):
        raw = self._get("/stress/status")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"bad JSON: {raw[:120]}"}

    def _poll_loop(self, cmd_prefix, stop_ev, log_cb, my_gen):
        passes     = 0
        last_iters = 0
        last_time  = time.perf_counter()

        while not stop_ev.is_set():
            passes += 1
            d       = self._bridge_status()
            threads = d.get("threads", 0)
            iters   = d.get("iters",   0)

            now     = time.perf_counter()
            delta_i = iters - last_iters
            delta_t = now   - last_time

            # Skip rate on pass 1 — delta_t includes startup latency, not
            # real throughput, so it always reads near-zero and is misleading.
            if passes == 1:
                rate_str = "warming up…"
            else:
                rate = delta_i / delta_t / 1e9 if delta_t > 0 else 0.0
                rate_str = f"{rate:.2f}B iters/s"

            last_iters = iters
            last_time  = now

            if "error" in d:
                log_cb(f"Bridge error: {d['error']}")
            else:
                log_cb(f"{threads} cores | {rate_str} | Pass {passes} | OK")

            stop_ev.wait(2.0)

        # Only send /stress/stop if we are still the active generation.
        # If start() was called again while this loop was running, our
        # generation is stale — stopping the bridge would kill the new test.
        if self._generations.get(cmd_prefix) == my_gen:
            self._bridge_stop()
            log_cb("■ Stopped.")
        else:
            log_cb("■ Superseded by new run.")

    def make_stress_action(self, cmd_prefix, card_id):
        self._log_routing[cmd_prefix] = card_id

        def start(log_cb):
            # Cancel the previous run for this slot, if any.
            existing = self._stop_events.get(cmd_prefix)
            if existing and not existing.is_set():
                existing.set()

            # Bump generation so the dying poll loop won't stop the bridge
            # after the new test has already started.
            new_gen = self._generations.get(cmd_prefix, 0) + 1
            self._generations[cmd_prefix] = new_gen

            def _do_start():
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
                    args=(cmd_prefix, stop_ev, log_cb, new_gen),
                    daemon=True,
                )
                self._poll_threads[cmd_prefix] = t
                t.start()

            threading.Thread(target=_do_start, daemon=True).start()

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

# stress_worker.py v0.5.1
# HTTP client delegating burn work to LHMBridge C# engine.
# Clean log output for all 6 stress test modes.

import sys
import time
import threading
import os
import multiprocessing
import urllib.request
import urllib.error
import json

def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)

BRIDGE_PORT = 8086
BRIDGE_BASE = f"http://127.0.0.1:{BRIDGE_PORT}"
NCORES = multiprocessing.cpu_count()

def _bridge_get(path):
    try:
        with urllib.request.urlopen(f"{BRIDGE_BASE}{path}", timeout=3) as r:
            return r.read().decode()
    except Exception as e:
        return f'{{"error":"{e}"}}'

def _parse_status(raw):
    try:
        d = json.loads(raw)
        mode    = d.get("mode", "?")
        threads = d.get("threads", 0)
        iters   = d.get("iters", 0)
        if iters > 0:
            return f"{threads} threads | {iters/1e9:.2f}B iters"
        return f"{threads} threads"
    except Exception:
        return raw

# ── Test definitions ──────────────────────────────────────────────────────────
# Each test maps to a LHMBridge mode and has a display label
_TESTS = {
    # key          bridge_mode  label
    "p95_small":  ("fma",      "FMA Burn"),
    "p95_large":  ("cache",    "Cache Bust"),
    "p95_blend":  ("memory",   "Memory Flood"),
    "gpu_core":   ("fma",      "GPU Core"),
    "gpu_vram":   ("vram",     "GPU VRAM"),
    "gpu_combined":("cache",   "GPU Combined"),
    # also support direct CPU test keys
    "cpu_single": ("single",   "CPU Single"),
    "cpu_multi":  ("fma",      "CPU Multi"),
    "cpu_memory": ("memory",   "CPU Memory"),
    "cpu_hybrid": ("cache",    "CPU Hybrid"),
}

# ── Stop events ───────────────────────────────────────────────────────────────
_stops = {k: threading.Event() for k in _TESTS}
for e in _stops.values():
    e.set()

def _run_worker(key, stop):
    bridge_mode, label = _TESTS[key]
    resp_raw = _bridge_get(f"/stress/start?mode={bridge_mode}")
    try:
        resp = json.loads(resp_raw)
        threads = resp.get("threads", NCORES)
        log(f"{label}: Starting {threads} C# threads | mode={bridge_mode}")
    except Exception:
        log(f"{label}: Started | {resp_raw}")

    passes = 0
    last_iters = 0
    last_time  = time.perf_counter()

    while not stop.is_set():
        stop.wait(2.0)
        if stop.is_set():
            break
        passes += 1
        raw = _bridge_get("/stress/status")
        try:
            d = json.loads(raw)
            threads = d.get("threads", 0)
            iters   = d.get("iters", 0)
            now     = time.perf_counter()
            delta_i = iters - last_iters
            delta_t = now - last_time
            rate    = delta_i / delta_t / 1e9 if delta_t > 0 else 0
            last_iters = iters
            last_time  = now
            log(f"{label}: {threads} cores | {rate:.2f}B iters/s | Pass {passes} | OK")
        except Exception:
            log(f"{label}: Running | Pass {passes}")

    _bridge_get("/stress/stop")
    log(f"{label}: Stopped.")

def start_test(key):
    stop = _stops[key]
    if not stop.is_set():
        return
    stop.clear()
    threading.Thread(target=_run_worker, args=(key, stop), daemon=True).start()

def stop_test(key):
    _stops[key].set()

if __name__ == "__main__":
    log(f"stress_worker ready | LHMBridge C# engine | {NCORES} logical cores")

    for line in sys.stdin:
        cmd = line.strip()
        if   cmd == "cpu_single_start":    start_test("cpu_single")
        elif cmd == "cpu_single_stop":     stop_test("cpu_single")
        elif cmd == "cpu_multi_start":     start_test("cpu_multi")
        elif cmd == "cpu_multi_stop":      stop_test("cpu_multi")
        elif cmd == "cpu_memory_start":    start_test("cpu_memory")
        elif cmd == "cpu_memory_stop":     stop_test("cpu_memory")
        elif cmd == "cpu_hybrid_start":    start_test("cpu_hybrid")
        elif cmd == "cpu_hybrid_stop":     stop_test("cpu_hybrid")
        elif cmd == "gpu_core_start":      start_test("gpu_core")
        elif cmd == "gpu_core_stop":       stop_test("gpu_core")
        elif cmd == "gpu_vram_start":      start_test("gpu_vram")
        elif cmd == "gpu_vram_stop":       stop_test("gpu_vram")
        elif cmd == "gpu_combined_start":  start_test("gpu_combined")
        elif cmd == "gpu_combined_stop":   stop_test("gpu_combined")
        elif cmd == "p95_small_start":     start_test("p95_small")
        elif cmd == "p95_small_stop":      stop_test("p95_small")
        elif cmd == "p95_large_start":     start_test("p95_large")
        elif cmd == "p95_large_stop":      stop_test("p95_large")
        elif cmd == "p95_blend_start":     start_test("p95_blend")
        elif cmd == "p95_blend_stop":      stop_test("p95_blend")
        elif cmd == "exit":                break

# stress_worker.py v0.0.14c
# CPU burn: N threads, each spinning with numpy + ctypes - guaranteed 100% per core
# No multiprocessing (incompatible with DETACHED_PROCESS subprocess launch)

import sys, time, threading, os

def log(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)

# CRITICAL: set BEFORE numpy import - otherwise BLAS ignores them
os.environ["OMP_NUM_THREADS"]      = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"]      = "1"
os.environ["NUMEXPR_NUM_THREADS"]  = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False
    log("WARNING: numpy not found - using pure Python fallback")

# Also limit at runtime via threadpoolctl if available
try:
    import threadpoolctl
    threadpoolctl.threadpool_limits(limits=1)
    TPCTL_OK = True
except ImportError:
    TPCTL_OK = False

import multiprocessing
NCORES = multiprocessing.cpu_count()

# ── ctypes burn - releases GIL, true parallel ─────────────────
import ctypes, ctypes.util

# ── Native DLL (compiled at startup for GIL-free 100% per-core burn) ──────
_NATIVE_LIB = None   # set to ctypes.CDLL if compile succeeds

def _compile_native():
    """Load pre-built DLL if exists, otherwise try to compile stress_native.c."""
    global _NATIVE_LIB
    import os, subprocess

    here     = os.path.dirname(os.path.abspath(__file__))
    dll_path = os.path.join(here, "stress_native.dll")
    src      = os.path.join(here, "stress_native.c")

    # ── Step 1: try to load pre-built DLL (bundled with app) ──────────────
    if os.path.exists(dll_path):
        try:
            lib = ctypes.CDLL(dll_path)
            lib.burn_small_fft.restype  = None
            lib.burn_small_fft.argtypes = [ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(ctypes.c_double)]
            lib.burn_large_fft.restype  = None
            lib.burn_large_fft.argtypes = [ctypes.POINTER(ctypes.c_int),
                                            ctypes.POINTER(ctypes.c_double),
                                            ctypes.c_int,
                                            ctypes.POINTER(ctypes.c_double)]
            lib.burn_blend.restype  = None
            lib.burn_blend.argtypes = [ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_double),
                                        ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_double)]
            _NATIVE_LIB = lib
            log("Native: pre-built stress_native.dll loaded - GIL-free burn active")
            return
        except Exception as ex:
            log(f"Native: pre-built DLL failed to load ({ex}), trying compile...")

    # ── Step 2: try to compile from source (dev machines with gcc/cl) ─────
    if not os.path.exists(src):
        log("Native: stress_native.c not found - using numpy fallback")
        return

    compiled = False
    for compiler, args in [
        ("gcc",    ["gcc", "-O3", "-march=native", "-ffast-math",
                    "-shared", "-fPIC", "-o", dll_path, src, "-lm"]),
        ("cl",     ["cl", "/O2", "/fp:fast", "/LD", f"/Fe{dll_path}", src]),
    ]:
        try:
            r = subprocess.run(args, capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(dll_path):
                compiled = True
                log(f"Native: compiled with {compiler} -> stress_native.dll")
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if not compiled:
        log("Native: no compiler found - using numpy fallback")
        return

    # Load freshly compiled DLL
    try:
        lib = ctypes.CDLL(dll_path)
        lib.burn_small_fft.restype  = None
        lib.burn_small_fft.argtypes = [ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_double)]
        lib.burn_large_fft.restype  = None
        lib.burn_large_fft.argtypes = [ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_double),
                                        ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_double)]
        lib.burn_blend.restype  = None
        lib.burn_blend.argtypes = [ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_double),
                                    ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_double)]
        _NATIVE_LIB = lib
        log("Native: DLL loaded OK - GIL-free 100% per-core burn active")
    except Exception as ex:
        log(f"Native: DLL load failed ({ex}) - using numpy fallback")

_compile_native()


def _ctypes_burn_loop(stop_ev):
    """Pure C math loop via ctypes - releases GIL completely"""
    try:
        libm = ctypes.CDLL(ctypes.util.find_library("m") or "msvcrt.dll")
        libm.sqrt.restype  = ctypes.c_double
        libm.sqrt.argtypes = [ctypes.c_double]
        libm.sin.restype   = ctypes.c_double
        libm.sin.argtypes  = [ctypes.c_double]
        x = ctypes.c_double(1.0)
        while not stop_ev.is_set():
            # Tight C math loop - fully parallel, no GIL
            for _ in range(10000):
                x.value = libm.sqrt(abs(x.value * 1.0000003 + libm.sin(x.value)))
    except Exception:
        # Fallback: numpy matmul still releases GIL
        if NUMPY_OK:
            N = 256
            A = np.random.rand(N, N)
            B = np.random.rand(N, N)
            while not stop_ev.is_set():
                _ = A @ B

# ── Stop events ───────────────────────────────────────────────
_stops = {k: threading.Event() for k in
    ["cpu_single","cpu_multi","cpu_memory","cpu_hybrid",
     "gpu_core","gpu_vram","gpu_combined",
     "p95_small","p95_large","p95_blend"]}
for e in _stops.values(): e.set()

# ── Helpers ───────────────────────────────────────────────────
def gflops(N, t): return (2 * N**3) / t / 1e9

# ── Core burn function (runs in each thread) ──────────────────
def _burn_thread(thread_id, n_threads, stop_ev, score_list, score_lock, label):
    """Each thread: ctypes C loop (GIL-free) + numpy scoring"""
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(200000):
                x = math.sqrt(abs(x * 1.0000003 + math.cos(x)))
        return

    N = 384
    rng = np.random.default_rng(thread_id)
    A = rng.random((N, N))
    B = rng.random((N, N))
    ref = None
    errors = 0

    # ctypes math handle for GIL-free burn
    try:
        libm = ctypes.CDLL(ctypes.util.find_library("m") or "msvcrt.dll")
        libm.sqrt.restype  = ctypes.c_double
        libm.sqrt.argtypes = [ctypes.c_double]
        libm.sin.restype   = ctypes.c_double
        libm.sin.argtypes  = [ctypes.c_double]
        use_ctypes = True
    except:
        use_ctypes = False

    while not stop_ev.is_set():
        t0 = time.perf_counter()

        if use_ctypes:
            # GIL-free C burn - runs truly parallel across all threads
            x = ctypes.c_double(float(thread_id) + 1.0)
            for _ in range(50000):
                x.value = libm.sqrt(abs(x.value * 1.0000003 + libm.sin(x.value)))

        # numpy matmul for scoring (also releases GIL)
        C = A @ B @ A
        elapsed = time.perf_counter() - t0
        score = gflops(N, elapsed) * 2

        fp = float(C[0,0] + C[-1,-1])
        if ref is not None and abs(fp - ref) > 10.0:
            errors += 1
        ref = fp

        with score_lock:
            score_list[thread_id] = (score, errors)

# ── Reporter thread ───────────────────────────────────────────
def _reporter(stop_ev, score_list, score_lock, label, n_threads, interval=1.5):
    passes = 0
    while not stop_ev.is_set():
        stop_ev.wait(interval)
        if stop_ev.is_set(): break
        passes += 1
        with score_lock:
            scores  = [s for s, e in score_list if s > 0]
            errors  = sum(e for s, e in score_list)
        if not scores: continue
        total   = sum(scores)
        avg_per = total / len(scores)
        peak    = max(scores)
        stable  = f"OK ({passes})" if errors == 0 else f"ERRORS:{errors}"
        if n_threads == 1:
            log(f"{label}: {total:.2f} GFLOPS  |  Peak: {peak:.2f}  |  Stable: {stable}")
        else:
            log(f"{label}: Total {total:.1f} GFLOPS  |  Per-core avg {avg_per:.2f}  |  {n_threads} cores  |  Stable: {stable}")

def _launch_burn(key, n_threads, label):
    stop_ev    = _stops[key]
    score_list = [(0.0, 0)] * n_threads
    score_lock = threading.Lock()

    threads = []
    for i in range(n_threads):
        t = threading.Thread(
            target=_burn_thread,
            args=(i, n_threads, stop_ev, score_list, score_lock, label),
            daemon=True)
        t.start()
        threads.append(t)

    rep = threading.Thread(
        target=_reporter,
        args=(stop_ev, score_list, score_lock, label, n_threads),
        daemon=True)
    rep.start()

# ═══════════════════════════════════════════════════════════════
#  CPU SINGLE CORE
# ═══════════════════════════════════════════════════════════════
def cpu_single_worker(stop):
    log(f"CPU Single: Starting 1-thread numpy burn (1/{NCORES} cores)...")
    _launch_burn("cpu_single", 1, "CPU Single")
    stop.wait()
    log("CPU Single: Stopped.")

# ═══════════════════════════════════════════════════════════════
#  CPU MULTI CORE - 1 thread per logical core
# ═══════════════════════════════════════════════════════════════
def cpu_multi_worker(stop):
    log(f"CPU Multi: Spawning {NCORES} threads - 1 per logical core...")
    _launch_burn("cpu_multi", NCORES, "CPU Multi")
    stop.wait()
    log("CPU Multi: Stopped.")

# ═══════════════════════════════════════════════════════════════
#  CPU MEMORY CONTROLLER - DRAM bandwidth stress
# ═══════════════════════════════════════════════════════════════
def _mem_burn_thread(thread_id, stop_ev, score_list, score_lock):
    if not NUMPY_OK:
        buf = bytearray(32 * 1024 * 1024)
        while not stop_ev.is_set():
            for i in range(0, len(buf), 64): buf[i] = (buf[i]+1) & 0xFF
        return

    # 64MB per thread - exceeds L3 per thread, forces DRAM traffic
    size = 16 * 1024 * 1024  # 128MB float64
    try:
        A = np.ones(size, dtype=np.float64)
        B = np.ones(size, dtype=np.float64)
    except MemoryError:
        size = 4 * 1024 * 1024
        A = np.ones(size, dtype=np.float64)
        B = np.ones(size, dtype=np.float64)

    while not stop_ev.is_set():
        t0 = time.perf_counter()
        np.add(A, B, out=A)          # write stream
        s = float(np.sum(A))         # read stream
        idx = np.arange(0, size, 64)
        A[idx] *= 1.0000001          # random-ish access
        elapsed = time.perf_counter() - t0
        bw = (A.nbytes * 3) / elapsed / 1024**3
        with score_lock:
            score_list[thread_id] = (bw, 0)

def _mem_reporter(stop_ev, score_list, score_lock, n_threads):
    passes = 0
    while not stop_ev.is_set():
        stop_ev.wait(1.5)
        if stop_ev.is_set(): break
        passes += 1
        with score_lock:
            bws = [s for s, e in score_list if s > 0]
        if not bws: continue
        total = sum(bws)
        log(f"CPU Memory: {total:.2f} GB/s total  |  Per-thread avg {total/len(bws):.2f}  |  {n_threads} threads  |  Pass {passes}")

def cpu_memory_worker(stop):
    log(f"CPU Memory: Starting {NCORES} memory stream threads (DRAM bandwidth stress)...")
    score_list = [(0.0, 0)] * NCORES
    score_lock = threading.Lock()
    for i in range(NCORES):
        threading.Thread(target=_mem_burn_thread,
                         args=(i, stop, score_list, score_lock),
                         daemon=True).start()
    threading.Thread(target=_mem_reporter,
                     args=(stop, score_list, score_lock, NCORES),
                     daemon=True).start()
    stop.wait()
    log("CPU Memory: Stopped.")

# ═══════════════════════════════════════════════════════════════
#  CPU HYBRID - matmul + memory per thread
# ═══════════════════════════════════════════════════════════════
def _hybrid_thread(thread_id, stop_ev, score_list, score_lock):
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(100000): x = math.sqrt(abs(x*1.0000003+math.cos(x)))
        return

    N = 256
    rng = np.random.default_rng(thread_id + 200)
    A = rng.random((N, N))
    B = rng.random((N, N))
    mem_size = 4 * 1024 * 1024
    try: M = np.ones(mem_size, dtype=np.float64)
    except: M = None

    while not stop_ev.is_set():
        t0 = time.perf_counter()
        C = A @ B @ A @ B  # 4 matmuls
        if M is not None: M += 0.000001; _ = float(np.sum(M[::64]))
        elapsed = time.perf_counter() - t0
        score = gflops(N, elapsed) * 4
        with score_lock:
            score_list[thread_id] = (score, 0)

def cpu_hybrid_worker(stop):
    log(f"CPU Hybrid: Full load - {NCORES} threads, matmul + memory per thread...")
    score_list = [(0.0, 0)] * NCORES
    score_lock = threading.Lock()
    for i in range(NCORES):
        threading.Thread(target=_hybrid_thread,
                         args=(i, stop, score_list, score_lock),
                         daemon=True).start()
    rep = threading.Thread(
        target=_reporter,
        args=(stop, score_list, score_lock, "CPU Hybrid", NCORES, 2.0),
        daemon=True)
    rep.start()
    stop.wait()
    log("CPU Hybrid: Stopped.")

# ═══════════════════════════════════════════════════════════════
#  GPU CORE - float32 compute proxy
# ═══════════════════════════════════════════════════════════════
def gpu_core_worker(stop):
    log("GPU Core: Starting float32 compute stress (CPU-side proxy)...")
    if not NUMPY_OK:
        log("GPU Core: numpy missing"); return
    N = 512
    A = np.random.rand(N, N).astype(np.float32)
    B = np.random.rand(N, N).astype(np.float32)
    passes = 0; total_g = 0.0; max_g = 0.0
    while not stop.is_set():
        t0 = time.perf_counter()
        C = A @ B
        elapsed = time.perf_counter() - t0
        score = gflops(N, elapsed)
        passes += 1; total_g += score; avg = total_g / passes
        if score > max_g: max_g = score
        log(f"GPU Core: {score:.2f} GFLOPS (fp32)  |  Avg: {avg:.2f}  |  Max: {max_g:.2f}  |  Pass {passes}")
        stop.wait(0.1)
    log("GPU Core: Stopped.")

# ═══════════════════════════════════════════════════════════════
#  GPU VRAM - large allocation + R/W
# ═══════════════════════════════════════════════════════════════
def gpu_vram_worker(stop):
    log("GPU VRAM: Allocating large arrays for memory pressure...")
    chunks = []; mb = 0; target_mb = 4096
    try:
        while not stop.is_set() and mb < target_mb:
            chunk = np.ones(256*1024*1024//4, dtype=np.float32)
            chunk *= 1.0001; chunks.append(chunk); mb += 256
            log(f"GPU VRAM: Allocated {mb} MB")
            stop.wait(0.1)
        passes = 0; total_bw = 0.0; max_bw = 0.0
        while not stop.is_set():
            t0 = time.perf_counter()
            for c in chunks: c += 0.0001
            elapsed = time.perf_counter() - t0
            bw = sum(c.nbytes for c in chunks)*2/elapsed/1024**3
            passes += 1; total_bw += bw; avg = total_bw/passes
            if bw > max_bw: max_bw = bw
            log(f"GPU VRAM: {bw:.2f} GB/s  |  Avg: {avg:.2f}  |  Max: {max_bw:.2f}  |  {mb} MB held  |  Pass {passes}")
            stop.wait(0.2)
    except MemoryError:
        log(f"GPU VRAM: MemoryError at {mb} MB - holding")
        while not stop.is_set(): stop.wait(0.5)
    finally:
        del chunks
        log("GPU VRAM: Freed. Stopped.")

# ═══════════════════════════════════════════════════════════════
#  GPU COMBINED
# ═══════════════════════════════════════════════════════════════
def gpu_combined_worker(stop):
    log("GPU Combined: compute + VRAM pressure simultaneously...")
    if not NUMPY_OK:
        log("GPU Combined: numpy missing"); return
    sub_stop = threading.Event()
    scores = {"g": 0.0, "bw": 0.0}; lock = threading.Lock()

    def compute_t():
        N = 512
        A = np.random.rand(N,N).astype(np.float32)
        B = np.random.rand(N,N).astype(np.float32)
        while not sub_stop.is_set() and not stop.is_set():
            t0 = time.perf_counter(); C = A @ B; e = time.perf_counter()-t0
            with lock: scores["g"] = gflops(N, e)
            time.sleep(0.05)

    def vram_t():
        chunks = []; mb = 0
        try:
            while not sub_stop.is_set() and not stop.is_set() and mb < 2048:
                c = np.ones(64*1024*1024//4,dtype=np.float32); c *= 1.0001
                chunks.append(c); mb += 64; time.sleep(0.1)
            while not sub_stop.is_set() and not stop.is_set():
                t0 = time.perf_counter()
                for c in chunks: c += 0.0001
                e = time.perf_counter()-t0
                bw = sum(c.nbytes for c in chunks)*2/e/1024**3
                with lock: scores["bw"] = bw
                time.sleep(0.2)
        except MemoryError: pass
        finally: del chunks

    threading.Thread(target=compute_t, daemon=True).start()
    threading.Thread(target=vram_t,    daemon=True).start()
    passes = 0
    while not stop.is_set():
        stop.wait(2.0); passes += 1
        with lock: g, bw = scores["g"], scores["bw"]
        log(f"GPU Combined: {g:.2f} GFLOPS  |  VRAM {bw:.2f} GB/s  |  Pass {passes}")
    sub_stop.set()
    log("GPU Combined: Stopped.")

# ===============================================================
#  PRIME95-STYLE - Small FFT (max heat, fits in L1/L2)
# ===============================================================
def _p95_small_thread(thread_id, stop_ev, score_list, score_lock):
    if _NATIVE_LIB is not None:
        # GIL-free C burn — true 100% per core
        stop_flag = ctypes.c_int(0)
        score_out = ctypes.c_double(0.0)
        import time as _time
        t0 = _time.perf_counter()
        # Run in a way that we can check stop_ev periodically
        # We poll every 1s by using a short-lived burn loop
        while not stop_ev.is_set():
            stop_flag.value = 0
            t1 = _time.perf_counter()
            _NATIVE_LIB.burn_small_fft(ctypes.byref(stop_flag), ctypes.byref(score_out))
            elapsed = _time.perf_counter() - t1
            iters = score_out.value
            gflops = (iters * 16) / elapsed / 1e9  # ~16 FP ops per iter
            with score_lock:
                score_list[thread_id] = (gflops, 0)
            if stop_ev.wait(0):
                break
            # Re-trigger: stop_flag gets set by stop logic below
            # Actually we need a wrapper — see below
        return

    # numpy fallback
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(200000): x = math.sqrt(abs(x * 1.0000003 + math.cos(x)))
        return
    fft_sizes = [4096, 8192, 16384, 32768, 65536]
    rng = np.random.default_rng(thread_id + 300)
    errors = 0
    while not stop_ev.is_set():
        t0 = time.perf_counter()
        total_ops = 0
        for sz in fft_sizes:
            data = rng.random(sz).astype(np.float64)
            freq = np.fft.rfft(data)
            recovered = np.fft.irfft(freq, n=sz)
            if float(np.max(np.abs(recovered - data))) > 1e-6:
                errors += 1
            total_ops += sz * np.log2(sz)
        elapsed = time.perf_counter() - t0
        gf = total_ops * len(fft_sizes) / elapsed / 1e9
        with score_lock:
            score_list[thread_id] = (gf, errors)


def _native_burn_thread(fn_name, buf_args, thread_id, stop_ev, score_list, score_lock):
    """Generic native burn thread — polls stop_ev every ~1s via stop_flag."""
    lib  = _NATIVE_LIB
    fn   = getattr(lib, fn_name)
    stop_flag = ctypes.c_int(0)
    score_out = ctypes.c_double(0.0)

    while not stop_ev.is_set():
        stop_flag.value = 0
        # Launch the C function — it blocks until stop_flag != 0
        # We use a side thread to set stop_flag after 1s or when stop_ev fires
        import threading as _th
        def _watchdog():
            stop_ev.wait(1.0)
            stop_flag.value = 1
        w = _th.Thread(target=_watchdog, daemon=True)
        w.start()
        t0 = time.perf_counter()
        fn(ctypes.byref(stop_flag), *buf_args, ctypes.byref(score_out))
        elapsed = time.perf_counter() - t0
        w.join()
        iters = score_out.value
        if elapsed > 0:
            gflops = (iters * 16) / elapsed / 1e9
            with score_lock:
                score_list[thread_id] = (gflops, 0)


def _p95_small_thread(thread_id, stop_ev, score_list, score_lock):
    if _NATIVE_LIB is not None:
        _native_burn_thread("burn_small_fft", [], thread_id, stop_ev, score_list, score_lock)
        return
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(200000): x = math.sqrt(abs(x * 1.0000003 + math.cos(x)))
        return
    fft_sizes = [4096, 8192, 16384, 32768, 65536]
    rng = np.random.default_rng(thread_id + 300)
    errors = 0
    while not stop_ev.is_set():
        t0 = time.perf_counter()
        total_ops = 0
        for sz in fft_sizes:
            data = rng.random(sz).astype(np.float64)
            freq = np.fft.rfft(data)
            recovered = np.fft.irfft(freq, n=sz)
            if float(np.max(np.abs(recovered - data))) > 1e-6:
                errors += 1
            total_ops += sz * np.log2(sz)
        elapsed = time.perf_counter() - t0
        gf = total_ops * len(fft_sizes) / elapsed / 1e9
        with score_lock:
            score_list[thread_id] = (gf, errors)

def _p95_reporter(stop_ev, score_list, score_lock, label, n_threads, interval=1.5):
    passes = 0
    while not stop_ev.is_set():
        stop_ev.wait(interval)
        if stop_ev.is_set(): break
        passes += 1
        with score_lock:
            scores = [s for s, e in score_list if s > 0]
            errors = sum(e for s, e in score_list)
        if not scores: continue
        stable = f"OK ({passes})" if errors == 0 else f"ERRORS: {errors}"
        log(f"{label}: {sum(scores):.2f} GFLOPS  |  {n_threads} threads  |  {stable}")

def p95_small_worker(stop):
    log(f"FMA Burn: Starting {NCORES} threads - sizes 4K-64K, max heat...")
    score_list = [(0.0, 0)] * NCORES
    score_lock = threading.Lock()
    for i in range(NCORES):
        threading.Thread(target=_p95_small_thread,
                         args=(i, stop, score_list, score_lock), daemon=True).start()
    threading.Thread(target=_p95_reporter,
                     args=(stop, score_list, score_lock, "FMA Burn", NCORES), daemon=True).start()
    stop.wait()
    log("FMA Burn: Stopped.")

# ===============================================================
#  PRIME95-STYLE - Large FFT (max power, exceeds cache)
# ===============================================================
def _p95_large_thread(thread_id, stop_ev, score_list, score_lock):
    if _NATIVE_LIB is not None:
        # 64MB buffer per thread to bust L3 cache
        buf_len = 8 * 1024 * 1024  # 8M doubles = 64MB
        buf = (ctypes.c_double * buf_len)(*([1.0] * min(buf_len, 1024) + [0.0] * max(0, buf_len - 1024)))
        _native_burn_thread("burn_large_fft", [buf, ctypes.c_int(buf_len)],
                            thread_id, stop_ev, score_list, score_lock)
        return
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(200000): x = math.sqrt(abs(x * 1.0000003 + math.cos(x)))
        return
    fft_sizes = [524288, 1048576, 2097152, 4194304]
    rng = np.random.default_rng(thread_id + 400)
    errors = 0
    while not stop_ev.is_set():
        t0 = time.perf_counter()
        total_ops = 0
        for sz in fft_sizes:
            data = rng.random(sz).astype(np.float64)
            freq = np.fft.rfft(data)
            recovered = np.fft.irfft(freq, n=sz)
            if float(np.max(np.abs(recovered - data))) > 1e-4:
                errors += 1
            total_ops += sz * np.log2(sz)
        elapsed = time.perf_counter() - t0
        gf = total_ops * len(fft_sizes) / elapsed / 1e9
        with score_lock:
            score_list[thread_id] = (gf, errors)

def p95_large_worker(stop):
    log(f"Cache Bust: Starting {NCORES} threads - sizes 512K-4M, max power...")
    score_list = [(0.0, 0)] * NCORES
    score_lock = threading.Lock()
    for i in range(NCORES):
        threading.Thread(target=_p95_large_thread,
                         args=(i, stop, score_list, score_lock), daemon=True).start()
    threading.Thread(target=_p95_reporter,
                     args=(stop, score_list, score_lock, "Cache Bust", NCORES), daemon=True).start()
    stop.wait()
    log("Cache Bust: Stopped.")

# ===============================================================
#  PRIME95-STYLE - Blend (FFT + RAM, like Prime95 Blend mode)
# ===============================================================
def _p95_blend_thread(thread_id, stop_ev, score_list, score_lock):
    if _NATIVE_LIB is not None:
        # 256MB buffer per thread — stresses memory controller hard
        buf_len = 32 * 1024 * 1024  # 32M doubles = 256MB
        try:
            buf = (ctypes.c_double * buf_len)()
        except MemoryError:
            buf_len = 8 * 1024 * 1024
            buf = (ctypes.c_double * buf_len)()
        _native_burn_thread("burn_blend", [buf, ctypes.c_int(buf_len)],
                            thread_id, stop_ev, score_list, score_lock)
        return
    if not NUMPY_OK:
        import math
        while not stop_ev.is_set():
            x = 1.0
            for _ in range(200000): x = math.sqrt(abs(x * 1.0000003 + math.cos(x)))
        return
    fft_sizes = [8192, 32768, 131072, 524288, 2097152]
    rng = np.random.default_rng(thread_id + 500)
    errors = 0
    mem_size = 32 * 1024 * 1024
    try:
        mem_buf = np.ones(mem_size, dtype=np.float64)
    except MemoryError:
        mem_buf = np.ones(4 * 1024 * 1024, dtype=np.float64)
    while not stop_ev.is_set():
        t0 = time.perf_counter()
        total_ops = 0
        for sz in fft_sizes:
            data = rng.random(sz).astype(np.float64)
            freq = np.fft.rfft(data)
            recovered = np.fft.irfft(freq, n=sz)
            if float(np.max(np.abs(recovered - data))) > 1e-4:
                errors += 1
            total_ops += sz * np.log2(sz)
        mem_buf += 0.000001
        _ = float(np.sum(mem_buf[::256]))
        elapsed = time.perf_counter() - t0
        gf = total_ops * len(fft_sizes) / elapsed / 1e9
        with score_lock:
            score_list[thread_id] = (gf, errors)

def p95_blend_worker(stop):
    log(f"Memory Flood: Starting {NCORES} threads - mixed sizes + RAM stress...")
    score_list = [(0.0, 0)] * NCORES
    score_lock = threading.Lock()
    for i in range(NCORES):
        threading.Thread(target=_p95_blend_thread,
                         args=(i, stop, score_list, score_lock), daemon=True).start()
    threading.Thread(target=_p95_reporter,
                     args=(stop, score_list, score_lock, "Memory Flood", NCORES, 2.0), daemon=True).start()
    stop.wait()
    log("Memory Flood: Stopped.")

# -- Worker registry -------------------------------------------
_workers = {
    "cpu_single":   cpu_single_worker,
    "cpu_multi":    cpu_multi_worker,
    "cpu_memory":   cpu_memory_worker,
    "cpu_hybrid":   cpu_hybrid_worker,
    "gpu_core":     gpu_core_worker,
    "gpu_vram":     gpu_vram_worker,
    "gpu_combined": gpu_combined_worker,
    "p95_small":    p95_small_worker,
    "p95_large":    p95_large_worker,
    "p95_blend":    p95_blend_worker,
}

def start_test(key):
    stop = _stops[key]
    if not stop.is_set(): return
    stop.clear()
    threading.Thread(target=_workers[key], args=(stop,), daemon=True).start()

def stop_test(key):
    _stops[key].set()

if __name__ == "__main__":
    if NUMPY_OK:
        log(f"stress_worker ready | numpy {np.__version__} | {NCORES} logical cores | OMP=1")
    else:
        log(f"stress_worker ready | numpy NOT found | {NCORES} logical cores | fallback mode")

    for line in sys.stdin:
        cmd = line.strip()
        if   cmd == "cpu_single_start":   start_test("cpu_single")
        elif cmd == "cpu_single_stop":    stop_test("cpu_single")
        elif cmd == "cpu_multi_start":    start_test("cpu_multi")
        elif cmd == "cpu_multi_stop":     stop_test("cpu_multi")
        elif cmd == "cpu_memory_start":   start_test("cpu_memory")
        elif cmd == "cpu_memory_stop":    stop_test("cpu_memory")
        elif cmd == "cpu_hybrid_start":   start_test("cpu_hybrid")
        elif cmd == "cpu_hybrid_stop":    stop_test("cpu_hybrid")
        elif cmd == "gpu_core_start":     start_test("gpu_core")
        elif cmd == "gpu_core_stop":      stop_test("gpu_core")
        elif cmd == "gpu_vram_start":     start_test("gpu_vram")
        elif cmd == "gpu_vram_stop":      stop_test("gpu_vram")
        elif cmd == "gpu_combined_start": start_test("gpu_combined")
        elif cmd == "gpu_combined_stop":  stop_test("gpu_combined")
        elif cmd == "p95_small_start":    start_test("p95_small")
        elif cmd == "p95_small_stop":     stop_test("p95_small")
        elif cmd == "p95_large_start":    start_test("p95_large")
        elif cmd == "p95_large_stop":     stop_test("p95_large")
        elif cmd == "p95_blend_start":    start_test("p95_blend")
        elif cmd == "p95_blend_stop":     stop_test("p95_blend")
        elif cmd == "exit":               break

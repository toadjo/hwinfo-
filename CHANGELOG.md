# Changelog

All notable changes to HWInfo Monitor will be documented here.

---

## [v0.6.0 Beta] - 2026-03-24

### Changed
- **FP32 stress engine** — `AvxFmaBurn` switched from `Vector256<double>` (FP64, 12 chains × 4 doubles) to `Vector256<float>` (FP32, 24 chains × 8 floats); FP32 FMA throughput is 2× FP64 on all modern x86 CPUs, producing significantly higher thermal output — equivalent to Prime95 Small FFT
- **Combined mode rewritten** — previously split threads half FMA / half memory, which left half the CPU's FP units idle; now every thread runs `AvxFmaMemBurn`: 8 FMA outer iterations followed by one 64MB sequential memory pass, so all cores simultaneously saturate both FP execution ports and DRAM bandwidth for maximum package power
- **RAM Stability Test size picker** — user can now choose test size before starting: 256 MB, 512 MB, 1 GB, 2 GB, 4 GB, or Auto (70% available); selection is highlighted in the card UI; chosen MB is passed to `/ram/start?mb=N`; Auto caps at 90% available to prevent OOM

### Fixed
- RAM card size buttons no longer accidentally trigger test launch when clicked (size picker excluded from card click binding)
- `/ram/start` now accepts optional `?mb=N` query parameter; `RamTester` parses it and caps at 90% of available RAM with a log message if capped; OOM fallback now logs the reduced size

---

## [v0.5.9 Beta] - 2026-03-24

### Fixed
- **`NameError: threading not defined` on startup** — `threading` module was used inside `update_stress_temps` but never imported at the top of `app.py`
- **`dev.bat` LHMBridge ready-wait loop never worked** — `!READY!` uses delayed expansion but `setlocal enabledelayedexpansion` was missing; the loop always ran all 30 iterations regardless of bridge state

### Changed
- `dev.bat` and `build_all.bat` version comments bumped to v0.5.9 Beta
- **Restart race condition** — starting a new stress test while one was running would sometimes stop the bridge immediately after the new test started; fixed with a generation counter: each poll loop captures its generation at birth and only sends `/stress/stop` on exit if it is still the active generation, otherwise it exits silently
- **`_bridge_stop()` killing new test on restart** — old poll loop's exit path unconditionally called `/stress/stop`; now suppressed when superseded
- **JSON injection in `_get` error strings** — exception messages containing backslashes or quotes were breaking the `{"error":"..."}` JSON envelope, causing `_bridge_start` to silently return `{}` and the poll loop to start against a bridge that never actually received the start command; error strings are now sanitised before embedding
- **`_bridge_start` / `_bridge_status` swallowing bad JSON silently** — now return a proper `{"error": ...}` dict instead of `{}` so callers can log the real problem
- **First-pass rate reading always showed 0.00** — `delta_t` on pass 1 includes startup latency, not real throughput; pass 1 now shows "warming up…" instead of a meaningless rate
- **`update_stress_temps` loop could die silently** — if the fetch thread raised any uncaught exception `_apply` would never fire and the entire temp loop would stop permanently with no indication; `_apply` is now always scheduled, even on exception, via a finally-style path
- **Duplicate `update_stress_temps` loops** — `_apply` was the sole rescheduler but could be called concurrently if a second fetch started before the first `_apply` fired; added `_temp_loop_active` guard flag to prevent two loops running simultaneously
- **`get_primary_gpu_temp()` reading `_bridge_data` without the lock** — direct dict access raced with the background poll thread writing `_bridge_data`; switched to `get_sensor_snapshot()` which acquires `_lock`

### Changed
- CPU and GPU temps now fetched **concurrently** inside `_fetch` (two daemon threads joined with 2s timeout each) — worst-case wait drops from 2s sequential to ~1s parallel
- `process_log_queue` interval 250ms → 100ms
- `update_stress_temps` interval 1000ms → 500ms
- `_get` query string for `/stress/start` now built with `urllib.parse.urlencode` instead of manual string formatting

---

## [v0.5.8 Beta] - 2026-03-24

### Fixed
- Stress test start delayed showing temps and logs — `_poll_loop` was waiting 2s before the first status poll; wait moved to bottom of loop so first log line appears immediately
- `update_stress_temps` was calling `bridge.get_cpu_temp()` / `get_primary_gpu_temp()` on the main thread, stalling the UI every second under bridge load — both calls now run on a daemon thread with result applied back via `root.after(0, ...)`

### Changed
- `process_log_queue` interval reduced 250ms → 100ms
- `update_stress_temps` interval reduced 1000ms → 500ms

---

## [v0.5.7 Beta] - 2026-03-24

### Fixed
- App hang on stress test start — `_bridge_start()` (blocking HTTP call) was running on the Tkinter main thread, freezing the UI for up to 3s on timeout; entire start sequence now runs on a daemon thread

### Changed
- `_get()` timeout reduced 3s → 2s

---

## [v0.5.6 Beta] - 2026-03-23

### Added
- **RAM Stability Test** — 15 pattern tests (Solid 0x00/0xFF, Checkerboard, Walking Ones/Zeros, March C-, Mats+, Address XOR, Byte Rotate, Random Seed, etc.) running on 70% of available RAM; write + verify pass per test; errors reported with exact cell address and expected/actual value
- RAM test integrated into CPU Tests tab as a scrollable card below stress tests; click card → active view with live log, progress header (`Test X of 15 — pattern name`), and Stop button; Back button returns to menu
- `/ram/start`, `/ram/stop`, `/ram/status` HTTP endpoints added to LHMBridge
- GPU Stress tab replaced with "Coming Soon" placeholder — full GPU stress requires OpenGL/Vulkan rendering pipeline

### Fixed
- Back button in RAM active view not working — `_show_page_in_tab` now hides `ram_active` frame before showing menu
- RAM card rendered outside scrollable canvas — now placed inside `cpu_mi` inner frame using `grid` alongside CPU stress cards

---

## [v0.5.5 Beta] - 2026-03-23

### Changed
- **Stress engine overhauled — pure C# native, no subprocess, no Python worker**
  - `stress_manager.py` fully rewritten: no subprocess spawn, no stdin/stdout pipe, no Python stress worker — pure HTTP calls to LHMBridge `/stress/start`, `/stress/stop`, `/stress/status`
  - `stress_worker.py` (both root and `core/`) removed — no longer needed
  - `stress_native.dll` / `stress_native.c` removed — no longer needed
- **Three new CPU stress tests replace previous p95 modes**:
  - **CPU Single Core** (`cpu_single`) — 1 thread, 12 independent AVX2 FMA chains × 4 doubles (48 FMAs/iter), maximises single-core boost clock and single-core heat; `[MethodImpl(NoInlining)]` + `Sink()` prevent JIT dead-code elimination
  - **CPU Multi Core** (`cpu_multi`) — same AVX2 FMA engine on all logical cores, equivalent to Prime95 Small FFT in thermal output
  - **Memory / IMC** (`memory`) — 256MB per thread, 3-pass pattern: AVX2 sequential forward (256-bit stores), stride-127 (2M iterations, defeats prefetcher), AVX2 reverse sequential; forces real DRAM traffic above L3
  - **CPU + Memory** (`combined`) — half threads run pure AVX2 FMA, half run pure memory flood simultaneously; both pressures hit the CPU at the same time for maximum package power
- `ThreadPriority` raised from `BelowNormal` → `Highest` on all stress threads
- Scalar fallback expanded from 8 → 16 independent chains for non-AVX2 CPUs
- Window Size setting added to Settings dialog — preset resolutions (1280×720 → 4K) + Custom W×H input; persisted per launch mode in registry; applied immediately on save without restart

### Fixed
- Stress tests showing duplicate process (Python subprocess + C# bridge) — subprocess removed entirely
- Settings dialog height too small after Window Size row addition — increased 320 → 420px

---

## [v0.5.4 Beta] - 2026-03-23

### Changed
- **Stress engine rewritten — C# backend via LHMBridge** — replaced Python thread/multiprocessing burn engine with a native C# `StressBurner` class embedded in LHMBridge; each test mode runs real OS threads with no GIL, achieving true 100% per-core utilization on all machines without requiring a compiler or any extra tools
- **Three distinct stress modes now run genuinely different workloads**:
  - FMA Burn — 8 independent FP64 chains per thread, stays in L1/L2, maximises heat
  - Cache Bust — 64MB stride-access buffer per thread, forces constant L3 misses
  - Memory Flood — 128MB sequential read+write per thread, stresses IMC and DRAM bandwidth
- `stress_worker.py` simplified to a thin HTTP client calling `/stress/start` and `/stress/stop` on LHMBridge — no numpy, no multiprocessing, no GIL issues
- Stress log output cleaned up — now shows `12 cores | 4.2B iters/s | Pass N | OK` instead of raw JSON
- `dev.bat` updated to always rebuild LHMBridge on every run (previously skipped if DLLs existed), auto-installs Python dependencies, and clears `__pycache__` on startup
- `build_all.bat` cleaned up — removed gcc `stress_native.dll` compile step (no longer needed)

### Fixed
- `stress_native.dll` dependency removed entirely — stress tests now work on any machine without gcc, cl.exe, or MSYS2
- Old `stress_worker.py` being loaded from `core\` or `dist\_internal\` instead of root — duplicate files removed, path resolution clarified
- p95 stress modes (`p95_small`, `p95_large`, `p95_blend`) not routing logs to correct UI card — fixed prefix map in `stress_manager.py`
- Duplicate `_p95_small_thread` definition (first broken version silently overwriting second) — removed
- Watchdog closure in `_native_burn_thread` capturing `stop_flag` by late binding — fixed with default argument

---

## [v0.5.3 Beta] - 2026-03-20

### Added
- **Stress Test UI redesign** — replaced crowded card grid with a clean 2-tab system (CPU Tests / GPU Tests); clicking a test card launches it immediately and switches to an active view with a live log and Stop button
- **Native GIL-free stress engine** — new `stress_native.c` compiled at build time via gcc (`-O3 -march=native -ffast-math`); each thread runs a tight FMA loop in C with no Python GIL contention, achieving true 100% per-core utilization
- **Three new CPU stress tests**: FMA Burn (tight FMA loop, max heat, L1/L2), Cache Bust (64MB buffer, busts L3, max power draw), Memory Flood (256MB buffer per thread, stresses IMC + DRAM)
- **Split view mode** (`Sensors + Stress Test`) — both panels now open side-by-side in a single window with a draggable divider instead of two separate windows
- `stress_native.dll` bundled inside installer — end users require no compiler or additional tools

### Fixed
- `graph_gpu_temps` NameError on startup in Stress Test mode
- `bind_all` MouseWheel on stress canvas hijacking scroll in Sensors window — replaced with scoped bindings
- Info window no longer opens automatically in `Sensors + Stress Test` mode
- Unicode encode error (`✓`/`✗`/em-dash) in stress worker log on Windows cp1252 terminals

### Changed
- Stress test names updated to accurately reflect workload: Small FFT → FMA Burn, Large FFT → Cache Bust, Blend → Memory Flood
- `build_all.bat` and `dev.bat` updated to auto-compile `stress_native.dll` via gcc if available
- `hwinfo_monitor.spec` updated to bundle `stress_native.dll` and `stress_native.c`

---

## [v0.5.2 Beta] - 2026-03-19

### Fixed
- Info window no longer auto-scrolls to top on each sensor update — scroll position is now preserved across refreshes
- Graph value labels no longer overlap when multiple series terminate at similar temperatures — collision avoidance pushes labels apart with a minimum 12 px gap

### Changed
- Graph value labels are now anchored to a fixed right-margin column instead of floating next to the line endpoint
- `pad_r` in `draw_multi_graph` increased 44 → 52 px to accommodate right-margin labels
- GPU graph canvas height increased 170 → 200 px for better readability with 3 series
- Stat label colors overhauled for semantic consistency:
  - **CPU** — Clock: blue (accent) · Power: red `#f87171` · Voltage: cyan `#22d3ee`
  - **GPU** — Core Clock: orange (accent) · VRAM Used: amber `#fbbf24` · Power: red `#f87171` · Hotspot: red `#f87171` · VRAM Temp: soft orange `#fb923c` · Voltage: cyan `#22d3ee`
  - **RAM** — Used: purple (accent) · Available: `#a78bfa` · Speed: `#c4b5fd`
- `GPU_TEMP_COLORS` updated: Core = accent orange · Hotspot = `#f87171` · VRAM = `#fb923c`

---

## [v0.5.1 Beta] - Initial release

- First public beta

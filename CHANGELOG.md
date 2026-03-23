# Changelog

All notable changes to HWInfo Monitor will be documented here.

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

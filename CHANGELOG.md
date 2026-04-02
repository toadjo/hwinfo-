# Changelog

All notable changes to HardwareToad will be documented here.


---

## [v0.8.1 Beta] - 2026-04-02

### Fixed
- CPU temperature now works on previously unsupported CPUs (i7-8700, R5-5800X, others) — upgraded LHM dependencies to match vendor dll v0.9.6
- GPU sensor polling (Temp/Power/Load) now correctly reads from LHMBridge using proper bridge methods

### Changed
- GPU stress shaders massively upgraded — ~10x more compute load per shader invocation
  - Compute: 128 loops of transcendental ops (sin/cos/sqrt/exp/log) instead of simple FMA
  - Pixel: 256 heavy ops/pixel with dependency chains, 4K render target instead of 1080p
  - Rasterizer: 30,000 triangles instead of 3,000
  - VRAM: 4 copy passes per frame instead of 1

---

## [v0.8.0 Beta] - 2026-04-02

### Added
- **GPU Stress Engine** — native DX12 stress testing via `GPUStress.exe`
  - **GPU Core Test** — dispatches 16M FMA compute threads via compute shader
  - **VRAM Test** — continuous 256MB GPU memory transfers to saturate bandwidth
  - **Combined** — Compute + VRAM + Rasterizer simultaneously
  - Rasterizer pipeline: 3000 procedural triangles at 1080p with heavy per-pixel math
  - Universal GPU support: feature level fallback (DX12.1 → DX12.0 → DX11.1 → DX11.0)
  - Live log output with elapsed time + iteration count every 5 seconds
- **GPU Stress UI** — active view (same style as CPU tests) with Back button, Temp/Power/Load status bar, full scrollable log
- GPU stress cards now match CPU card style — red border, badge (GPU/VRAM/ALL), full card click, hover effect
- `build_all.bat` auto-builds GPUStress and packages it in the installer
- GPUStress.exe included in installer — end users get GPU stress with zero setup

### Fixed
- GPU stress log queue stale sentinel bug — second test run no longer terminates immediately
- GPU sensor polling now runs in background thread — no more LHMBridge timeouts during stress

---

## [v0.7.5 Beta] - 2026-04-01

### Added
- **LHMBridge token authentication** — 256-bit random token generated at startup via `secrets.token_hex(32)`; passed to LHMBridge as `--token=<hex>` arg; every HTTP request must include `X-HardwareToad-Token` header or receives HTTP 403; token rotates on every app launch
- **SHA256 integrity check for LHMBridge.exe** — on first launch, binary hash is stored in `LHMBridge.sha256` alongside the exe; on every subsequent launch the hash is recomputed and compared; mismatch shows error dialog and aborts startup to prevent tampered bridge execution
- **Obfuscar integration in build pipeline** — `build_all.bat` step `[2b/5]` runs Obfuscar on `dist\LHMBridge\LHMBridge.dll` after `dotnet publish`; renames internal fields, properties, events, and methods; step is skipped gracefully if Obfuscar is not installed
- **`obfuscar.xml` config** — new project-root file specifying InPath/OutPath, obfuscation options, and skip rules for `Main`, `HandleCommand`, `Ring0`, and `AmdMemoryTimings.Read()`
- **`HardwareToad_Guide.docx`** — full user and developer guide: installation, UI walkthrough, project layout, how to add themes/sensors/stress tests, version bump workflow, security features, and troubleshooting table
- **Restricted CORS in LHMBridge** — removed wildcard `Access-Control-Allow-Origin: *`; bridge now only reflects origin header for requests from `127.0.0.1` or `localhost`
- **Live sensor readings in stress test log** — each poll line now appends real-time sensor data relevant to the active test; CPU tests show `CPU °C  W  V`; Memory test shows `CPU °C  RAM %  used/total GB`; Combined shows `CPU °C  W  RAM %`; data pulled from cached bridge snapshot, no extra HTTP requests
- **Window/taskbar icon** — `root.iconphoto()` set from the same base64-embedded robot toad logo used in the splash screen; provided at 256px (taskbar) and 32px (title bar); no external file dependency

### Changed
- **Token passed via environment variable** — `_BRIDGE_TOKEN` is now set as `HARDWARETOAD_TOKEN` env var on the child process instead of `--token=<hex>` CLI arg; CLI args are visible to any local process via Task Manager / WMI `Win32_Process`, env vars are per-process and not trivially enumerable; elevated (ShellExecute RunAs) launch writes token to a temp file that the bridge reads and deletes on startup (`--token-file=`); `--token=` kept as last-resort fallback for dev mode
- **`bridge.py` integrity check fails closed** — `_verify_bridge_integrity()` now returns `False` on I/O exceptions instead of `True`; a bridge binary that can't be hashed is treated as suspect rather than trusted
- **`stress_manager.py` HTTP calls authenticated** — `_get()` now creates a `urllib.request.Request` with `X-HardwareToad-Token` header on every call; previously stress endpoints (`/stress/start`, `/stress/stop`, `/stress/status`) were called without auth, allowing any local process to trigger CPU stress tests
- **`app.py` inline RAM HTTP calls authenticated** — all `urlopen()` calls to `/ram/start`, `/ram/stop`, `/ram/status` now use `Request()` with auth header via `get_bridge_token()`
- **`LHMBridge.cs` token loading order** — reads `HARDWARETOAD_TOKEN` env var first → `--token-file=` second (reads + deletes) → `--token=` last; `System.IO` added to usings
- **Duplicate `_ram_poll`/`_ram_start`/`_ram_stop` blocks removed** — first block (dead code, shadowed by identical second definition) deleted from `app.py`; ~69 lines of unreachable code removed
- **`bridge.py` HTTP calls unified via `_make_request()`** — all `urlopen()` calls replaced with a single helper that injects `X-HardwareToad-Token` header automatically; affects `/sensors`, `/cpu-temp`, `/timings`, `/mobo`, `/ready`, and `/ram/*` endpoints
- **`ring_pair()` and `single_ring()` anchor** changed from `"center"` to `"w"` so gauge rings align to the left edge consistently across CPU, GPU, and RAM blocks
- **`stat_strip()` anchor** changed from `"center"` to `"w"` so stat labels (CLOCK, POWER, VOLTAGE etc.) align with ring left edge instead of floating center
- **`ram_rings_f` pack anchor** changed from `"center"` to `"w"` for consistent RAM block alignment
- **Installer `[Run]` section rewritten** — replaced `runasoriginaluser` + `runascurrentuser` dual-entry logic with a single `shellexec` flag; fixes `CreateProcess failed; code 740` error that appeared after installation when the app tried to launch without elevation
- **`stress_manager.py` version string** updated from `v0.5.9 Beta` → `v0.7.5 Beta`
- **`__init__.py` description** updated from `"HWInfo Monitor"` → `"HardwareToad"`
- **`AvxFmaBurn` upgraded** — 24 FP32 chains → 16 FP32 + 16 FP64 chains running simultaneously; targets both FP execution ports at once; inner unroll 500→1000; scalar fallback expanded to 16 chains; achieves ~30-40% higher sustained power draw on Zen4/Raptor Lake
- **`MemoryBurn` upgraded** — buffer 256MB→512MB per thread (above 7800X3D 96MB L3); stride pass iterations 2M→4M; new 4th pass: xorshift64 random scatter write with fully unpredictable addresses — defeats prefetcher entirely and reveals IMC/XMP instability that sequential patterns miss
- **`AvxFmaMemBurn` (Combined) upgraded** — memory buffer 64MB→128MB per thread; FMA repetitions per memory pass 8→16; both FP ports now loaded simultaneously matching the upgraded FMA engine
- **`LinpackDgemm` upgraded** — matrix dimension N 2048→3072 (3.4× more FMAs per pass: 17B→58B FP64 ops); tile size 64→96; 3 matrices × 226MB per thread; reveals instability that smaller workloads miss

### Fixed
- **Single-core stress test stressing all cores** — `req.Url?.AbsolutePath` in LHMBridge HTTP handler strips query strings, so `/stress/start?mode=cpu_single` arrived as just `"start"` with no mode param, defaulting to `cpu_multi` (all cores); fixed by using `req.Url?.PathAndQuery` for `/stress/` and `/ram/` route handlers; this also fixes the RAM test `?mb=` size parameter being silently dropped
- **Linpack DGEMM showing 0.00B iters/s** — iteration counter was only updated after a full N×N×N pass (~58B FMAs), which takes longer than the 2s poll interval; moved `Interlocked.Add` from end-of-pass to per-tile-row (every 96 rows), so the poll sees smooth incremental progress; total count per pass unchanged (N/TILE × 2×TILE×N×N = 2×N³)
- **Installer error code 740** — `CreateProcess` failure on post-install launch caused by `runasoriginaluser` trying to spawn an admin-manifest exe as a non-elevated user; `shellexec` flag delegates launch to Windows ShellExecute which respects the `requireAdministrator` manifest correctly
- **Obfuscar XML parse failure** — double-dash sequences (`--`) inside XML comments are illegal per the XML spec and caused `System.Xml.XmlException`; all comments removed from `obfuscar.xml`
- **LHMBridge.cs brace mismatch** — orphaned sink/scalar-fallback code left after `AvxFmaBurn` refactor caused CS1001/CS1519 compile errors; removed stale block and restored correct brace balance
- **Stress test sensor temps not showing** — `sensor_fn` was reading from stale cache when update_sensors was throttled to 5s; now calls `bridge._make_request("/cpu-temp")` and `bridge._make_request("/sensors")` directly for fresh data each poll tick; falls back to cache on failure
- **Live/Offline bridge indicator removed** — `status_label` widget removed from toolbar; users no longer see bridge connectivity state
- **Title bar showing tkinter feather icon** — `iconphoto()` with transparent PNG caused tkinter to fall back to the default feather icon; fixed by compositing the logo onto `#0a0a0a` before passing to `iconphoto()`
- **App and splash screen showing different icons** — `_LOGO_B64` updated to a background-removed (flood-fill) version of the logo; both splash and `iconphoto` now use the same transparent PNG base
- **Splash logo too small** — resize from 52×52 → 96×96px
- **Monitor tab stuttering during stress tests** — `update_sensors()` poll throttled from 2s → 5s when a stress test is active; all PIL ring and graph redraws (`draw_ring`, `draw_multi_graph`, `draw_single_graph`) skipped during stress; `update_stress_temps` poll slowed from 500ms → 2s; text labels continue updating normally
- **Desktop/taskbar icon background** — `logo.ico` rebuilt with flood-fill background removal and stored as RGBA PNG-inside-ICO; Windows composites its own theme color behind the transparent toad

---

## [v0.7.4 Beta] - 2026-03-31

### Fixed
- **UI Event Interference** — Resolved a bug where stress test cards wouldn't launch because hover/press animations were overwriting the click-to-start event bindings.
- **Linpack Mode Integration** — Fixed a missing key in the Stress Manager that caused Linpack tests to default to standard multi-core stress.
- **Syntax Correction** — Fixed a calculation error in the generation counter logic within `stress_manager.py`.
---

## [v0.7.3 Beta] - 2026-03-31

### Added
- **Robot toad logo on splash screen** — base64-embedded image in `app.py`, no external file dependency; splash height increased from 240 → 300 to properly fit logo
- **Multi-threaded RAM tester** — parallelized memory stress execution for improved coverage and throughput

### Changed
- **12-chain register-correct FMA burn** — reduced from 24 chains to eliminate register spills; improves execution efficiency and maintains peak thermal load
- **Brutal 4-pass memory burn** — upgraded to 512MB buffers with randomized access patterns and full stride coverage for maximum DRAM stress
- **Thread scheduling priorities** — stress threads set to `BelowNormal`, HTTP server + polling threads set to `AboveNormal`, and 1 CPU core reserved to maintain UI/system responsiveness
- **HTTP timeout increased** — `stress_manager.py` timeout raised from 2s → 4s for improved reliability under heavy load
- **Branding update** — all references from “HWInfo Monitor” → **HardwareToad** across `README.md` and `CHANGELOG.md`

### Assets
- **Robot toad mascot assets added**
  - `logo.svg` — primary scalable asset (recommended for UI usage, stored in assets folder)
  - `logo_256.png` — 256px raster version suitable for application icon
  - Dark theme styling with red accent to match UI


## [v0.7.2 Beta] - 2026-03-30

### Added
- **Linpack DGEMM stress test** — tiled 2048×2048 FP64 matrix multiply (same workload as Intel Linpack/HPL); real data dependencies prevent JIT dead-code elimination, achieving higher thermal output than Combined; AVX2 inner kernel with FMA where supported; OOM fallback to 256×256 scalar
- **LHMBridge `--debug` flag** — verbose sensor logging in console: admin check on startup, every hardware item found, every sensor with value, exclusion reasons (null / ≤0 / >115°C), SuperIO fallback attempts
- **`/debug` HTTP endpoint** — JSON snapshot at `http://127.0.0.1:8086/debug` with `is_admin`, all hardware, all sensors with `"ok"` / `"excluded: value <= 0"` notes, and last 50 log lines; available before first poll with `lhm_ready` status
- **Splash screen real progress bar** — green animated progress bar (0→100%) replaces fixed 4.5s dot animation; bridge starts in background thread so splash closes exactly when sensor data is ready
- **Stress card hover/press feedback** — cards animate normal `#121212` → hover `#1c1c1c` → press `#252525` with all children updating together
- **Tab button hover** — subtle `#1a1a1a` background on inactive tab hover; guard prevents re-rendering when clicking already-active tab

### Fixed
- **Motherboard section hidden when no sensors** — boards with no SuperIO (e.g. Dell, Lenovo locked BIOS) now hide the entire Motherboard section instead of showing "No temperature sensors" / "No voltage sensors" / "No fan sensors" placeholders
- **LHM admin elevation** — `bridge.py` now uses `ShellExecuteW("runas", ...)` instead of `subprocess.Popen` when parent process is not admin; `Popen` silently inherits non-admin token even when manifest requests `requireAdministrator`
- **`dev.bat` ready-wait loop never fired** — `curl | findstr` pipeline broke `errorlevel` in cmd delayed expansion; replaced with `curl -o tempfile` + `findstr` on file — reliable exit code every time
- **LHM diagnostic warning on startup** — app no longer shows "LHMBridge not running" warning on first poll when bridge data hasn't populated yet; warning only appears if `bridge._bridge_data` is non-empty but CPU temp is missing
- **Ring text scroll artifacts** — value, unit, and label text now baked directly into PIL image alongside arc; eliminates `canvas.create_text` items that lagged behind canvas position during scroll
- **Left panel scroll artifacts** — removed scrollable canvas from left sensor panel entirely; window opens at 1440×960 to fit all blocks without scroll; `minsize(900, 700)` prevents over-shrinking

### Changed
- **Left panel no longer scrolls** — replaced `s_canvas` + scrollbar + `_sync_scrollregion` with a plain `tk.Frame`; eliminates all Canvas-in-Canvas scroll artifacts
- **Default window size** `1440x820` → `1440x960` to accommodate all sensor blocks
- **Splash progress bar color** changed from red `#e63946` to green `#40c057`
- **`dev.bat` LHMBridge** now starts in same cmd window (`start /b`) instead of opening a separate console
- **`dev.bat` ready-wait** extended to 60s with 1s polling; app starts immediately after bridge responds instead of after fixed wait
- **`_sync_scrollregion` interval** reduced from 250ms to 1000ms to lower spurious `<Configure>` event rate

---


## [v0.7.1 Beta] - 2026-03-27

### Added
- **Splash screen on startup** — borderless centered window displays app name, version badge, developer credits (ToadJo, Manos2400) and Est. 2026; stays visible for 4.5 seconds to cover LHM initialization so users never see a blank/unresponsive window
- **Animated "Initializing sensors..." status line** on splash — dots cycle every 400ms to signal the app is loading, not frozen

### Fixed
- **Info panel scroll jumping to top on sensor updates** — root cause was `_set()` calling `row.pack_forget()` / `row.pack()` on every poll cycle; re-packing a widget appends it to the end of the frame instead of its original slot, constantly shifting total content height and dragging the scroll fraction with it; rows now stay packed permanently — missing values display `—` in dim grey instead of disappearing
- **Info panel scroll `<Configure>` bind replaced with polling** — binding `_iw_sync_scrollregion` to `<Configure>` fired mid-layout before sizes settled, causing unreliable scrollregion updates; now uses a stable 500ms poll loop matching the left sensor panel's approach
- **GPU block missing red left accent strip** — GPU card was constructed as a plain `tk.Frame(bg=CARD)`, bypassing the 3px accent outer wrapper that `comp_block()` applies to CPU and RAM; fixed to use the same `outer(bg=ACCENT_CPU)` + `inner(padx=(3,0))` pattern



### Changed
- **Unified single-window UI** — removed the 3-mode startup popup (Sensors / Stress Test / Both); app now launches directly into a single window with MSI Center-style top tabs: **Monitor** and **Stress Test**
- **Info panel integrated** — RAM details, Network, System, Fans, Motherboard, and Storage sections are now in a right-side panel within the Monitor tab instead of a separate floating window
- **Black + Red color scheme** — replaced the blue-grey palette with a pure black base (`#0a0a0a`) and unified red accent (`#e63946`); no more per-component rainbow colors (blue GPU, purple RAM, mint fans, amber network, pink system)
- **Unified accent system** — all section dots, ring arcs, graph lines, progress bars, and card stripes use the same red accent; data values use light grey (`#cccccc`) instead of per-component colors
- **Improved text readability** — all label, subtitle, and value font sizes increased; text brightness boosted across the board for better contrast on dark backgrounds; stat strip labels `8pt bold`, info row values `11pt bold`, component subtitles `9pt`
- **`divider` import renamed** to `fmt_divider` to fix name collision with local widget variables
- **`BORDER` added to imports** from constants
- **Window size registry simplified** — single key instead of per-mode keys
- **`dev.bat` and `build_all.bat`** now clear `HKCU\Software\HWInfoMonitor` registry on startup to prevent stale theme/color overrides from affecting the UI

### Fixed
- **Registry theme override in admin profile** — `dev.bat` runs elevated, so HKCU points to the admin user's registry hive; stale `UITheme` values (e.g. "Dark Blue") persisted there would override the default theme silently; both bat files now delete the key on startup
- **`cpu_diag_lbl` yellow artifact** — diagnostic label was always packed even when empty, creating a visible yellow line; now only packed when a warning message exists, hidden otherwise
- **Alternating row backgrounds** — removed `ROW_A`/`ROW_B` alternation in info panel that created visible striping on some monitors; all rows now use uniform `#111111` background with subtle `#1a1a1a` separator lines
- **GPU ring showing blue arc** — GPU load ring used stored `acc` variable that could be stale; now explicitly uses `ACCENT_CPU` (red) for all ring draws
- **`formatting.py` color leaks** — `clock_color()` returned purple `#9775fa`, `usage_color()` returned blue `#4dabf7`; both now return `#cccccc` (light grey)
- **Progress bar track** too bright — darkened from `#2a2a2a` to `#1a1a1a`

### Removed
- Startup mode selection popup
- Separate Info window (Toplevel)
- Per-mode window size registry keys (`WindowSize_sensors`, `WindowSize_stress`, `WindowSize_both`)
- 3-mode code paths (sensors-only, stress-only, both)

---

## [v0.6.1 Beta] - 2026-03-24

### Added
- **Motherboard sensors section** in the Info panel — shows model name, SuperIO temperatures, and voltages from the motherboard's embedded controller (ITE/Nuvoton/Winbond); updated every sensor poll cycle
- `/mobo` HTTP endpoint in LHMBridge — returns `{name, temperatures[], voltages[], fans[]}` from the Motherboard SubHardware entries

### Fixed
- **CPU temp always N/A on AMD Ryzen (5800X, etc.)** — `GetCpuTempFromHardware` had a hard cap of 105°C which rejected valid Tctl/Tdie readings on hot systems; cap raised to 115°C to cover AMD Tctl offset values
- **CPU temp returning 0°C on first poll** — filter changed from `>= 10` to `> 0` so cold-boot readings are accepted; 0 is still excluded (uninitialized sensor)
- **CPU temp returning null when all sensors out of narrow range** — added two-pass logic: first pass tries `> 0 && <= 115`, second pass tries any non-zero sensor; ensures we never return null due to range rejection alone
- **Priority list now includes `Tctl`, `CPU CCD1`, `CPU CCD2`** — previously only `Tctl/Tdie` was in the list, missing some AMD board reporting variants

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

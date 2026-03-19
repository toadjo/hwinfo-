# Changelog

All notable changes to HWInfo Monitor will be documented here.

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

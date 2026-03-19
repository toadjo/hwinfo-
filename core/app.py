import collections
import ctypes
import queue
import re
import socket
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
#ebraioi

from PIL import Image, ImageDraw, ImageTk
import psutil

from .bridge import BridgeManager
from .constants import (
    ACCENT_CPU, ACCENT_DISK, ACCENT_FAN, ACCENT_GPU,
    ACCENT_NET, ACCENT_RAM, ACCENT_SYS, ACCENT_STRESS,
    APP_VERSION,
    BG,
    CARD,
    COL_CPU,
    COL_GPU,
    GRAPH_BG,
    GRAPH_SECONDS,
    BADGE_LIVE, BADGE_OFF,
)
from .formatting import (
    badge_for_temp, badge_live,
    big_stat,
    clock_color,
    divider,
    fmt_clock,
    fmt_data,
    fmt_speed,
    health_color,
    make_bar, update_bar,
    make_card,
    place,
    set_badge,
    small_stat,
    temp_color,
    usage_color,
)
from .stress_manager import StressManager
from .system_info import load_static_system_info


def main():
    log_queue = queue.Queue()
    bridge = BridgeManager()
    bridge.start()
    stress_manager = StressManager(log_queue)

    # ── Font system ───────────────────────────────────────────────────────────
    _FONT_KEY = r"Software\HWInfoMonitor"
    _DEFAULT_FONT = "Segoe UI"

    def _load_font():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _FONT_KEY)
            val, _ = winreg.QueryValueEx(key, "UIFont")
            winreg.CloseKey(key)
            return val
        except Exception:
            return _DEFAULT_FONT

    def _save_font(name):
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _FONT_KEY)
            winreg.SetValueEx(key, "UIFont", 0, winreg.REG_SZ, name)
            winreg.CloseKey(key)
        except Exception:
            pass

    current_font = [_load_font()]  # mutable ref

    def _resolve_theme(theme_dict):
        """Return a flat namespace of color names from a theme dict.

        No module mutation — callers receive a plain object whose attributes
        shadow the imported constants for the lifetime of this main() call.
        """
        class _Theme:
            pass
        t = _Theme()
        t.BG            = theme_dict["bg"]
        t.CARD          = theme_dict["card"]
        t.BORDER        = theme_dict["border"]
        t.GRAPH_BG      = theme_dict["graph_bg"]
        t.ACCENT_CPU    = theme_dict["accent_cpu"]
        t.ACCENT_GPU    = theme_dict["accent_gpu"]
        t.ACCENT_RAM    = theme_dict["accent_ram"]
        t.ACCENT_FAN    = theme_dict["accent_fan"]
        t.ACCENT_NET    = theme_dict["accent_net"]
        t.ACCENT_SYS    = theme_dict["accent_sys"]
        t.ACCENT_DISK   = theme_dict["accent_disk"]
        t.ACCENT_STRESS = theme_dict["accent_stress"]
        t.COL_CPU       = theme_dict["col_cpu"]
        t.COL_GPU       = theme_dict["col_gpu"]
        return t

    def _get_font_families():
        """Return sorted list of readable monospace+sans fonts."""
        try:
            all_fonts = sorted(set(tkfont.families()))
            # Prioritise common readable fonts at top
            priority = ["Segoe UI", "Calibri", "Arial", "Tahoma", "Verdana",
                        "Consolas", "Cascadia Code", "JetBrains Mono", "Fira Code",
                        "Ubuntu", "Roboto", "Open Sans"]
            top = [f for f in priority if f in all_fonts]
            rest = [f for f in all_fonts if f not in top and not f.startswith("@")]
            return top + rest
        except Exception:
            return [_DEFAULT_FONT]

    # ── Theme definitions ─────────────────────────────────────────────────────
    THEMES = {
        "Dark Blue (Default)": {
            "bg": "#0a0e1a", "card": "#111827", "border": "#1e2a3a",
            "graph_bg": "#0d1220",
            "accent_cpu": "#3b82f6", "accent_gpu": "#f97316",
            "accent_ram": "#a855f7", "accent_fan": "#06b6d4",
            "accent_net": "#eab308", "accent_sys": "#ec4899",
            "accent_disk": "#10b981", "accent_stress": "#ef4444",
            "col_cpu": "#3b82f6", "col_gpu": "#f97316",
        },
        "Midnight Purple": {
            "bg": "#0d0b1a", "card": "#160f2e", "border": "#2a1f4a",
            "graph_bg": "#100d20",
            "accent_cpu": "#a855f7", "accent_gpu": "#ec4899",
            "accent_ram": "#8b5cf6", "accent_fan": "#06b6d4",
            "accent_net": "#f59e0b", "accent_sys": "#f97316",
            "accent_disk": "#10b981", "accent_stress": "#ef4444",
            "col_cpu": "#a855f7", "col_gpu": "#ec4899",
        },
        "Cyberpunk": {
            "bg": "#0a0a0f", "card": "#111118", "border": "#1f1f35",
            "graph_bg": "#0d0d15",
            "accent_cpu": "#00ffff", "accent_gpu": "#ff00aa",
            "accent_ram": "#aaff00", "accent_fan": "#ff6600",
            "accent_net": "#ffff00", "accent_sys": "#ff00ff",
            "accent_disk": "#00ff88", "accent_stress": "#ff0044",
            "col_cpu": "#00ffff", "col_gpu": "#ff00aa",
        },
        "Matrix Green": {
            "bg": "#000d00", "card": "#001a00", "border": "#003300",
            "graph_bg": "#000f00",
            "accent_cpu": "#00ff41", "accent_gpu": "#39ff14",
            "accent_ram": "#00cc33", "accent_fan": "#00ffcc",
            "accent_net": "#ccff00", "accent_sys": "#00ff88",
            "accent_disk": "#00dd55", "accent_stress": "#ff4400",
            "col_cpu": "#00ff41", "col_gpu": "#39ff14",
        },
        "Sunset Orange": {
            "bg": "#150a00", "card": "#1f1000", "border": "#3a2000",
            "graph_bg": "#180c00",
            "accent_cpu": "#f97316", "accent_gpu": "#ef4444",
            "accent_ram": "#fb923c", "accent_fan": "#fbbf24",
            "accent_net": "#facc15", "accent_sys": "#f43f5e",
            "accent_disk": "#10b981", "accent_stress": "#dc2626",
            "col_cpu": "#f97316", "col_gpu": "#ef4444",
        },
        "Arctic Blue": {
            "bg": "#f0f4ff", "card": "#ffffff", "border": "#c7d4f0",
            "graph_bg": "#e8eeff",
            "accent_cpu": "#2563eb", "accent_gpu": "#7c3aed",
            "accent_ram": "#0891b2", "accent_fan": "#0284c7",
            "accent_net": "#d97706", "accent_sys": "#db2777",
            "accent_disk": "#059669", "accent_stress": "#dc2626",
            "col_cpu": "#2563eb", "col_gpu": "#7c3aed",
        },
        "Rose Gold": {
            "bg": "#1a0f12", "card": "#261519", "border": "#3d2028",
            "graph_bg": "#1d1014",
            "accent_cpu": "#fb7185", "accent_gpu": "#f472b6",
            "accent_ram": "#e879f9", "accent_fan": "#a78bfa",
            "accent_net": "#fbbf24", "accent_sys": "#fb923c",
            "accent_disk": "#34d399", "accent_stress": "#f43f5e",
            "col_cpu": "#fb7185", "col_gpu": "#f472b6",
        },
        "Stealth Grey": {
            "bg": "#0c0c0c", "card": "#161616", "border": "#2a2a2a",
            "graph_bg": "#111111",
            "accent_cpu": "#9ca3af", "accent_gpu": "#6b7280",
            "accent_ram": "#d1d5db", "accent_fan": "#4b5563",
            "accent_net": "#d97706", "accent_sys": "#6b7280",
            "accent_disk": "#4b5563", "accent_stress": "#ef4444",
            "col_cpu": "#9ca3af", "col_gpu": "#6b7280",
        },
        "Ocean Teal": {
            "bg": "#011926", "card": "#012233", "border": "#013a4a",
            "graph_bg": "#011c2e",
            "accent_cpu": "#06b6d4", "accent_gpu": "#0ea5e9",
            "accent_ram": "#14b8a6", "accent_fan": "#22d3ee",
            "accent_net": "#f59e0b", "accent_sys": "#38bdf8",
            "accent_disk": "#10b981", "accent_stress": "#ef4444",
            "col_cpu": "#06b6d4", "col_gpu": "#0ea5e9",
        },
        "Blood Red": {
            "bg": "#120000", "card": "#1c0000", "border": "#330000",
            "graph_bg": "#150000",
            "accent_cpu": "#ef4444", "accent_gpu": "#dc2626",
            "accent_ram": "#f87171", "accent_fan": "#fca5a5",
            "accent_net": "#f59e0b", "accent_sys": "#fb923c",
            "accent_disk": "#10b981", "accent_stress": "#ff0000",
            "col_cpu": "#ef4444", "col_gpu": "#dc2626",
        },
    }

    _THEME_KEY = r"Software\HWInfoMonitor"

    def _load_theme_name():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY)
            val, _ = winreg.QueryValueEx(key, "UITheme")
            winreg.CloseKey(key)
            return val if val in THEMES else "Dark Blue (Default)"
        except Exception:
            return "Dark Blue (Default)"

    def _save_theme_name(name):
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _THEME_KEY)
            winreg.SetValueEx(key, "UITheme", 0, winreg.REG_SZ, name)
            winreg.CloseKey(key)
        except Exception:
            pass

    current_theme_name = [_load_theme_name()]

    def open_settings(parent_win):
        sw = tk.Toplevel(parent_win)
        sw.title("Settings")
        sw.configure(bg=BG)
        sw.resizable(False, False)
        sw.geometry("460x320")
        sw.grab_set()

        tk.Label(sw, text="Settings", fg="white", bg=BG,
                 font=("Segoe UI", 14, "bold")).pack(pady=(20, 4))
        tk.Frame(sw, bg="#1e2a3a", height=1).pack(fill="x", padx=20)

        # ── Font selector ─────────────────────────────────────────────────────
        ff = tk.Frame(sw, bg=BG)
        ff.pack(fill="x", padx=24, pady=(14, 6))
        tk.Label(ff, text="UI Font:", fg="#6b7280", bg=BG,
                 font=("Segoe UI", 10)).pack(side="left")
        font_var = tk.StringVar(value=current_font[0])
        families = _get_font_families()
        font_combo = ttk.Combobox(ff, textvariable=font_var, values=families,
                                  width=24, state="readonly")
        font_combo.pack(side="left", padx=(10, 0))

        # ── Theme selector ────────────────────────────────────────────────────
        tf = tk.Frame(sw, bg=BG)
        tf.pack(fill="x", padx=24, pady=(6, 4))
        tk.Label(tf, text="Theme:", fg="#6b7280", bg=BG,
                 font=("Segoe UI", 10)).pack(side="left")
        theme_var = tk.StringVar(value=current_theme_name[0])
        theme_combo = ttk.Combobox(tf, textvariable=theme_var,
                                   values=list(THEMES.keys()),
                                   width=24, state="readonly")
        theme_combo.pack(side="left", padx=(10, 0))

        # ── Preview swatch ────────────────────────────────────────────────────
        swatch_frame = tk.Frame(sw, bg=BG)
        swatch_frame.pack(fill="x", padx=24, pady=(8, 4))

        swatch_boxes = []
        for _ in range(8):
            b = tk.Frame(swatch_frame, width=28, height=28)
            b.pack(side="left", padx=2)
            b.pack_propagate(False)
            swatch_boxes.append(b)

        preview_lbl = tk.Label(sw, text="Preview: AaBbCc 0123",
                               fg="#a0aec0", bg=CARD,
                               font=(current_font[0], 11))
        preview_lbl.pack(fill="x", padx=24, pady=(0, 8))

        def update_preview(e=None):
            f = font_var.get()
            t = THEMES.get(theme_var.get(), THEMES["Dark Blue (Default)"])
            preview_lbl.config(font=(f, 11), bg=t["card"],
                               fg=t["accent_cpu"])
            accents = [t["accent_cpu"], t["accent_gpu"], t["accent_ram"],
                       t["accent_fan"], t["accent_net"], t["accent_sys"],
                       t["accent_disk"], t["accent_stress"]]
            for box, color in zip(swatch_boxes, accents):
                box.config(bg=color)

        font_combo.bind("<<ComboboxSelected>>", update_preview)
        theme_combo.bind("<<ComboboxSelected>>", update_preview)
        update_preview()

        def apply():
            current_font[0] = font_var.get()
            current_theme_name[0] = theme_var.get()
            _save_font(current_font[0])
            _save_theme_name(current_theme_name[0])
            sw.destroy()
            info = tk.Toplevel(parent_win)
            info.configure(bg=BG)
            info.title("")
            info.resizable(False, False)
            info.geometry("320x110")
            tk.Label(info, text="Settings saved!", fg="white", bg=BG,
                     font=("Segoe UI", 12, "bold")).pack(pady=(24, 4))
            tk.Label(info, text="Restart the app to apply changes.", fg="#6b7280", bg=BG,
                     font=("Segoe UI", 9)).pack()
            tk.Button(info, text="OK", bg=ACCENT_CPU, fg="white",
                      font=("Segoe UI", 10, "bold"), relief="flat",
                      padx=20, pady=6, cursor="hand2",
                      command=info.destroy).pack(pady=(12, 0))

        bf = tk.Frame(sw, bg=BG)
        bf.pack(pady=(0, 16))
        tk.Button(bf, text="Apply & Save", bg=ACCENT_CPU, fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=apply).pack(side="left", padx=6)
        tk.Button(bf, text="Cancel", bg="#1e2a3a", fg="#6b7280",
                  font=("Segoe UI", 10), relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=sw.destroy).pack(side="left", padx=6)

    # ── Raw Sensors Window ────────────────────────────────────────────────────
    _raw_win = [None]

    def open_raw_sensors(parent_win):
        if _raw_win[0] and _raw_win[0].winfo_exists():
            _raw_win[0].lift()
            return

        rw = tk.Toplevel(parent_win)
        _raw_win[0] = rw
        rw.title(f"HWInfo Monitor {APP_VERSION} - Raw Sensors")
        rw.geometry("1000x660")
        rw.configure(bg=BG)
        rw.resizable(True, True)

        # ── Unit formatting per sensor type ──────────────────────────────────
        _UNITS = {
            "temperature": "°C",
            "load":        "%",
            "clock":       "MHz",
            "fan":         "RPM",
            "control":     "%",
            "voltage":     "V",
            "power":       "W",
            "current":     "A",
            "data":        "GB",
            "smalldata":   "MB",
            "throughput":  "MB/s",
            "level":       "%",
            "factor":      "×",
            "noise":       "dB",
        }

        # Sanity limits per type — values outside these are sensor garbage
        _SANE = {
            "temperature": (1,     110),   # <1°C or >110°C = garbage
            "load":        (0,     100),
            "clock":       (1,   10000),
            "fan":         (0,   10000),
            "control":     (0,     100),
            "voltage":     (0,      30),
            "power":       (0,     600),
            "current":     (0,     100),
            "level":       (0,     100),
        }

        def _is_sane(val, stype):
            """Return False if value is clearly out of range garbage."""
            if val is None:
                return False
            lo, hi = _SANE.get(stype.lower(), (-1e9, 1e9))
            return lo <= val <= hi

        def _fmt_val(val, stype):
            if val is None:
                return "—"
            unit = _UNITS.get(stype.lower(), "")
            if stype.lower() in ("clock",) and val >= 1000:
                return f"{val/1000:.2f} GHz"
            if stype.lower() in ("data",):
                return f"{val:.1f} GB" if val < 1000 else f"{val/1000:.2f} TB"
            if isinstance(val, float):
                return f"{val:.1f}{' ' + unit if unit else ''}"
            return f"{val}{' ' + unit if unit else ''}"

        def _val_color(val, stype):
            """Return a color tag based on sensor type and value."""
            stype = stype.lower()
            if val is None:
                return "dim"
            if stype == "temperature":
                if val > 85: return "hot"
                if val > 65: return "warm"
                return "ok"
            if stype == "load":
                if val > 85: return "hot"
                if val > 60: return "warm"
                return "normal"
            if stype in ("fan", "clock", "voltage", "power"):
                return "normal"
            return "normal"

        # Header
        hdr = tk.Frame(rw, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(hdr, text="📊  Raw Sensors", fg="#a0aec0", bg=BG,
                 font=(current_font[0], 12, "bold")).pack(side="left")
        raw_count = tk.Label(hdr, text="", fg="#4a5568", bg=BG,
                             font=(current_font[0], 9))
        raw_count.pack(side="left", padx=(12, 0))
        raw_status = tk.Label(hdr, text="Connecting...", fg="#555", bg=BG,
                              font=(current_font[0], 9))
        raw_status.pack(side="right")

        # ttk style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Raw.Treeview",
                        background=CARD, foreground="#a0aec0",
                        fieldbackground=CARD, rowheight=24,
                        font=(current_font[0], 9))
        style.configure("Raw.Treeview.Heading",
                        background="#1e2a3a", foreground="#6b7280",
                        font=(current_font[0], 9, "bold"), relief="flat")
        style.map("Raw.Treeview",
                  background=[("selected", "#1e3a5f")],
                  foreground=[("selected", "white")])

        # Treeview — removed "type" column, added proper widths
        cols = ("sensor", "value", "min", "max")
        tree = ttk.Treeview(rw, columns=cols, show="tree headings",
                            style="Raw.Treeview")
        tree.heading("#0",     text="Hardware",  anchor="w")
        tree.heading("sensor", text="Sensor",    anchor="w")
        tree.heading("value",  text="Value",     anchor="e")
        tree.heading("min",    text="Min",       anchor="e")
        tree.heading("max",    text="Max",       anchor="e")
        tree.column("#0",     width=200, stretch=False)
        tree.column("sensor", width=280, stretch=False)
        tree.column("value",  width=120, stretch=False, anchor="e")
        tree.column("min",    width=100, stretch=False, anchor="e")
        tree.column("max",    width=100, stretch=True,  anchor="e")

        vsb = ttk.Scrollbar(rw, orient="vertical",   command=tree.yview)
        hsb = ttk.Scrollbar(rw, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True, padx=(8, 0), pady=(4, 0))

        # Row & value color tags
        tree.tag_configure("odd",    background="#0f1623")
        tree.tag_configure("even",   background=CARD)
        tree.tag_configure("hw",     background="#0d1e2a", foreground="#3b82f6",
                           font=(current_font[0], 9, "bold"))
        # Value color overrides (foreground only — set via per-row tag combos)
        tree.tag_configure("hot",    foreground="#ef4444")
        tree.tag_configure("warm",   foreground="#f59e0b")
        tree.tag_configure("ok",     foreground="#22c55e")
        tree.tag_configure("normal", foreground="#a0aec0")
        tree.tag_configure("dim",    foreground="#4a5568")

        # Per-sensor min/max — only track sane values
        _sensor_minmax = {}

        def refresh_raw():
            if not rw.winfo_exists():
                return
            data = bridge.get_data_snapshot()
            if not data:
                raw_status.config(text="No data", fg="#555")
                rw.after(2000, refresh_raw)
                return

            raw_status.config(text="● Live", fg="#22c55e")

            # Remember expanded state
            expanded = {iid for iid in tree.get_children()
                        if tree.item(iid, "open")}

            tree.delete(*tree.get_children())
            row_idx = 0
            total_sensors = 0

            for hw_key in sorted(data.keys()):
                sensors = data[hw_key]
                hw_label = hw_key.split("|")[-1] if "|" in hw_key else hw_key
                hw_iid = tree.insert("", "end", iid=hw_key,
                                     text=f"  {hw_label}",
                                     tags=("hw",),
                                     open=(hw_key in expanded or not expanded))

                for s in sensors:
                    uid   = (hw_key, s["Name"])
                    val   = s["Value"]
                    stype = s["Type"]
                    total_sensors += 1

                    # Track min/max — only from sane values, reject outliers
                    # For any sensor type, ignore values that deviate >50% from
                    # the running average (catches LHM TjMax garbage on core temps)
                    if _is_sane(val, stype):
                        if uid in _sensor_minmax:
                            prev_min, prev_max, prev_avg, prev_n = _sensor_minmax[uid]
                            # Outlier check: reject if >3x the running avg (catches 3506°C etc)
                            if prev_avg > 0 and val > prev_avg * 3:
                                # Outlier — keep existing stats unchanged
                                new_min, new_max = prev_min, prev_max
                                new_avg = prev_avg
                                new_n   = prev_n
                            else:
                                new_min = min(prev_min, val)
                                new_max = max(prev_max, val)
                                new_n   = prev_n + 1
                                new_avg = prev_avg + (val - prev_avg) / new_n
                            _sensor_minmax[uid] = (new_min, new_max, new_avg, new_n)
                        else:
                            new_min = new_max = val
                            _sensor_minmax[uid] = (val, val, val, 1)
                        min_str = _fmt_val(new_min, stype)
                        max_str = _fmt_val(new_max, stype)
                    else:
                        if uid in _sensor_minmax:
                            new_min, new_max, _, _ = _sensor_minmax[uid]
                            min_str = _fmt_val(new_min, stype)
                            max_str = _fmt_val(new_max, stype)
                        else:
                            min_str = "—"
                            max_str = "—"

                    color_tag = _val_color(val, stype)
                    row_tag   = "odd" if row_idx % 2 else "even"
                    row_idx  += 1

                    tree.insert(hw_iid, "end",
                                values=(s["Name"],
                                        _fmt_val(val, stype),
                                        min_str,
                                        max_str),
                                tags=(row_tag, color_tag))

            raw_count.config(text=f"{total_sensors} sensors")
            rw.after(2000, refresh_raw)

        refresh_raw()

    static_info = load_static_system_info()
    cpu_name   = static_info["cpu_name"]
    ram_info   = static_info["ram_info"]
    all_disks  = static_info["all_disks"]
    win_ver    = static_info["windows_version"]
    win_ver_name = static_info.get("windows_ver_name", "")
    win_build  = static_info.get("windows_build", "")
    gpu_driver = static_info.get("gpu_driver", "N/A")

    # Build letter→disk_index map once at startup via WMI
    _letter_to_disk = {}
    try:
        import wmi as _wmi
        for disk in _wmi.WMI().Win32_DiskDrive():
            idx = int(disk.Index or 0)
            for part in disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical in part.associators("Win32_LogicalDiskToPartition"):
                    letter = (logical.DeviceID or "").strip().upper()  # "C:"
                    _letter_to_disk[letter] = idx
    except Exception:
        _letter_to_disk = {}

    graph_cpu_temps  = collections.deque(maxlen=GRAPH_SECONDS)
    graph_gpu_series = {}
    # GPU_TEMP_COLORS built after theme resolved (COL_GPU not yet available here)
    GPU_TEMP_COLORS  = {}

    RING_SIZE  = 150
    RING_WIDTH = 11
    RING_TRACK = (37, 37, 53, 255)
    RING_SCALE = 4   # render at 4x, downsample for antialiasing

    def _hex_to_rgba(h):
        h = h.lstrip("#")
        return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255)

    _ring_cache = {}   # canvas_id -> (value, accent) last drawn

    def draw_ring(canvas, value, label, accent, card_bg,
                  size=None, max_val=100, unit="%"):
        """Pillow-rendered antialiased ring gauge — skips redraw if unchanged."""
        cache_key = id(canvas)
        last = _ring_cache.get(cache_key)
        # Round value for comparison to avoid tiny float differences
        rounded = round(value, 0) if value is not None else None
        if last == (rounded, accent, label):
            return  # nothing changed, skip expensive redraw
        _ring_cache[cache_key] = (rounded, accent, label)

        if size is None:
            size = RING_SIZE
        s  = size * RING_SCALE
        rw = RING_WIDTH * RING_SCALE
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        m   = rw + RING_SCALE * 2
        box = [m, m, s - m, s - m]

        # Track
        d.arc(box, start=0, end=359.9, fill=RING_TRACK, width=rw)

        # Value arc
        if value is not None and value > 0:
            frac = min(value / max_val, 1.0)
            col  = _hex_to_rgba(accent) if isinstance(accent, str) else accent
            d.arc(box, start=-90, end=-90 + frac * 359.9, fill=col, width=rw)

        img = img.resize((size, size), Image.LANCZOS)

        # Store on canvas to prevent GC
        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas._ring_photo = photo
        canvas.create_image(size // 2, size // 2, image=photo)

        # Text
        cx = cy = size // 2
        if value is not None:
            canvas.create_text(cx, cy - 12, text=f"{value:.0f}",
                               fill=accent if isinstance(accent, str) else "#888",
                               font=("Segoe UI", 20, "bold"), anchor="center")
            canvas.create_text(cx, cy + 7, text=unit,
                               fill="#555", font=("Segoe UI", 9), anchor="center")
        else:
            canvas.create_text(cx, cy, text="N/A",
                               fill="#555", font=("Segoe UI", 11), anchor="center")
        canvas.create_text(cx, cy + 22, text=label,
                           fill="#4a5568", font=("Segoe UI", 7, "bold"),
                           anchor="center")

    def make_dual_rings(parent, accent_load, accent_temp, card_bg):
        """Two equally-sized ring canvases, centered with even spacing."""
        frame = tk.Frame(parent, bg=card_bg)
        frame.pack(anchor="center", pady=(10, 0))
        c_load = tk.Canvas(frame, width=RING_SIZE, height=RING_SIZE,
                           bg=card_bg, highlightthickness=0)
        c_load.pack(side="left", padx=14)
        c_temp = tk.Canvas(frame, width=RING_SIZE, height=RING_SIZE,
                           bg=card_bg, highlightthickness=0)
        c_temp.pack(side="left", padx=14)
        return c_load, c_temp

    def draw_single_graph(canvas, data, color, height, label=""):
        """Single-series graph wrapper."""
        draw_multi_graph(canvas, [(data, color)], height)

    def draw_multi_graph(canvas, series_list, height):
        """Multi-series temp graph. series_list = [(deque, color), ...]"""
        canvas.update_idletasks()
        canvas.delete("all")
        w = canvas.winfo_width()
        if w < 10: w = 400
        pad_l, pad_r, pad_t, pad_b = 36, 52, 8, 18
        plot_w = w - pad_l - pad_r
        plot_h = height - pad_t - pad_b
        label_x = w - pad_r + 4
        for tv in [0, 25, 50, 75, 100]:
            y = pad_t + plot_h * (1 - tv / 100)
            canvas.create_line(pad_l, y, w-pad_r, y, fill="#1e2a3a", dash=(3,4))
            canvas.create_text(pad_l-4, y, text=f"{tv}°",
                               fill="#4a5568", font=("Segoe UI", 7), anchor="e")
        for i in [0, 30, 60]:
            x = pad_l + plot_w * (i / 60)
            canvas.create_text(x, height-pad_b+8,
                               text=f"-{60-i}s" if i < 60 else "now",
                               fill="#4a5568", font=("Segoe UI", 7))
        label_min_gap = 12
        raw_labels = []
        for data, color in series_list:
            pts = list(data); n = len(pts)
            if n < 2: continue
            valid = [(i, v) for i, v in enumerate(pts) if v is not None]
            if len(valid) < 2: continue
            right_edge = pad_l + plot_w
            coords = []
            for i, v in valid:
                age = n - 1 - i
                x = right_edge - plot_w * (age / (GRAPH_SECONDS - 1))
                x = max(pad_l, min(x, right_edge))
                y = pad_t + plot_h * (1 - min(max(v, 0), 100) / 100)
                coords += [x, y]
            canvas.create_line(coords, fill=color, width=2)
            raw_labels.append((coords[-1], valid[-1][1], color))
        raw_labels.sort(key=lambda e: e[0])
        placed = []
        for ideal_y, val, color in raw_labels:
            y_label = ideal_y
            for prev_y in placed:
                if abs(y_label - prev_y) < label_min_gap:
                    y_label = prev_y + label_min_gap
            y_label = max(pad_t + 4, min(y_label, height - pad_b - 4))
            placed.append(y_label)
            canvas.create_text(label_x, y_label,
                               text=f"{val:.0f}°",
                               fill=color, font=("Segoe UI", 8, "bold"), anchor="w")

    def draw_graph_on(canvas, height):
        """Legacy combined graph — kept for stress test mode."""
        canvas.update_idletasks()
        canvas.delete("all")
        w = canvas.winfo_width()
        if w < 10: w = 1060
        h = height
        pad_l, pad_r, pad_t, pad_b = 44, 56, 12, 22
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        for tv in [0, 25, 50, 75, 100]:
            y = pad_t + plot_h * (1 - tv / 100)
            canvas.create_line(pad_l, y, w-pad_r, y, fill="#2e2e2e", dash=(4,3))
            canvas.create_text(pad_l-6, y, text=f"{tv}°", fill="#666",
                               font=("Segoe UI", 8), anchor="e")
        for i in [0, 15, 30, 45, 60]:
            x = pad_l + plot_w * (i / 60)
            canvas.create_text(x, h-pad_b+9,
                               text=f"-{60-i}s" if i < 60 else "now",
                               fill="#555", font=("Segoe UI", 8))
        def draw_line(data, color):
            pts = list(data); n = len(pts)
            if n < 2: return
            valid = [(i, v) for i, v in enumerate(pts) if v is not None]
            if len(valid) < 2: return
            right_edge = pad_l + plot_w
            coords = []
            for i, v in valid:
                age = n - 1 - i
                x = right_edge - plot_w * (age / (GRAPH_SECONDS - 1))
                x = max(pad_l, min(x, right_edge))
                y = pad_t + plot_h * (1 - min(max(v, 0), 100) / 100)
                coords += [x, y]
            canvas.create_line(coords, fill=color, width=2)
            lx, ly = coords[-2], coords[-1]
            canvas.create_text(min(lx+4, w-4), ly,
                               text=f"{valid[-1][1]:.0f}°",
                               fill=color, font=("Segoe UI", 8, "bold"), anchor="w")
        draw_line(graph_cpu_temps, COL_CPU)
        draw_line(graph_gpu_temps, COL_GPU)

    app_mode = None

    def show_startup_popup():
        nonlocal app_mode
        from . import constants as _sc
        _BG = _sc.BG
        popup = tk.Tk()
        popup.title("HWInfo Monitor")
        popup.configure(bg=_BG)
        popup.resizable(False, False)
        popup.geometry("560x260")
        popup.eval("tk::PlaceWindow . center")

        tk.Label(popup, text="HWInfo Monitor", fg="white", bg=_BG,
                 font=("Segoe UI", 20, "bold")).pack(pady=(32, 4))
        tk.Label(popup, text=APP_VERSION, fg="#555", bg=_BG,
                 font=("Segoe UI", 10)).pack()
        tk.Label(popup, text="Choose mode to launch:", fg="#888", bg=_BG,
                 font=("Segoe UI", 11)).pack(pady=(20, 14))

        btn_frame = tk.Frame(popup, bg=_BG)
        btn_frame.pack()

        def choose(mode):
            nonlocal app_mode
            app_mode = mode
            popup.destroy()

        tk.Button(btn_frame, text="Sensors", bg="#1a3a5c", fg="white",
                  font=("Segoe UI", 12, "bold"), relief="flat",
                  padx=20, pady=12, cursor="hand2", width=13,
                  command=lambda: choose("sensors")).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Stress Test", bg="#5c1a1a", fg="white",
                  font=("Segoe UI", 12, "bold"), relief="flat",
                  padx=20, pady=12, cursor="hand2", width=13,
                  command=lambda: choose("stress")).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Sensors + Stress", bg="#2a1a3a", fg="white",
                  font=("Segoe UI", 12, "bold"), relief="flat",
                  padx=20, pady=12, cursor="hand2", width=20,
                  command=lambda: choose("both")).pack(side="left", padx=8)

        popup.protocol("WM_DELETE_WINDOW", popup.destroy)
        popup.mainloop()

    show_startup_popup()
    if app_mode is None:
        sys.exit(0)

    # Resolve theme into a plain object — no module mutation needed
    _t = _resolve_theme(THEMES[current_theme_name[0]])
    BG            = _t.BG
    CARD          = _t.CARD
    BORDER        = _t.BORDER
    GRAPH_BG      = _t.GRAPH_BG
    ACCENT_CPU    = _t.ACCENT_CPU
    ACCENT_GPU    = _t.ACCENT_GPU
    ACCENT_RAM    = _t.ACCENT_RAM
    ACCENT_FAN    = _t.ACCENT_FAN
    ACCENT_NET    = _t.ACCENT_NET
    ACCENT_SYS    = _t.ACCENT_SYS
    ACCENT_DISK   = _t.ACCENT_DISK
    ACCENT_STRESS = _t.ACCENT_STRESS
    COL_CPU       = _t.COL_CPU
    COL_GPU       = _t.COL_GPU
    GPU_TEMP_COLORS = {"Core": COL_GPU, "Hotspot": "#f87171", "VRAM": "#fb923c"}

    # ── Header builder (replaces three identical copy-paste blocks) ──────────
    def _build_header(win, subtitle, subtitle_color, show_toolbar=True):
        """Pack the title bar into *win*. Returns the status label."""
        hf = tk.Frame(win, bg=BG)
        hf.pack(fill="x", padx=20, pady=(14, 0))
        tk.Label(hf, text="HWInfo Monitor", fg="white", bg=BG,
                 font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(hf, text=APP_VERSION, fg="#555", bg=BG,
                 font=("Segoe UI", 10)).pack(side="left", padx=(8, 0), pady=4)
        tk.Label(hf, text=subtitle, fg=subtitle_color, bg=BG,
                 font=("Segoe UI", 10)).pack(side="left", padx=(12, 0), pady=4)
        sl = tk.Label(hf, text="Connecting...", fg="#888", bg=BG,
                      font=("Segoe UI", 10))
        sl.pack(side="right", pady=4)
        if show_toolbar:
            tk.Button(hf, text="⚙ Settings", bg=BORDER, fg="#6b7280",
                      font=("Segoe UI", 9), relief="flat", padx=10, pady=4,
                      cursor="hand2",
                      command=lambda: open_settings(win)).pack(side="right", padx=(0, 8))
            tk.Button(hf, text="📊 Raw Sensors", bg=BORDER, fg="#6b7280",
                      font=("Segoe UI", 9), relief="flat", padx=10, pady=4,
                      cursor="hand2",
                      command=lambda: open_raw_sensors(win)).pack(side="right", padx=(0, 4))
        return sl

    root = tk.Tk()
    root.configure(bg=BG)
    root.resizable(True, True)

    if app_mode == "sensors":
        root.title(f"HWInfo Monitor {APP_VERSION} - Sensors")
        root.geometry("1100x740")
        status_label = _build_header(root, "Sensors", COL_CPU)
        sensors_root = root
        stress_root = None

    elif app_mode == "stress":
        root.title(f"HWInfo Monitor {APP_VERSION} - Stress Test")
        root.geometry("1100x740")
        status_label = _build_header(root, "Stress Test", "#ff6644")
        sensors_root = None
        stress_root = root

    else:  # both
        root.title(f"HWInfo Monitor {APP_VERSION} - Sensors")
        root.geometry("1100x740")
        root.geometry("+0+0")
        status_label = _build_header(root, "Sensors", COL_CPU)

        stress_win = tk.Toplevel(root)
        stress_win.title(f"HWInfo Monitor {APP_VERSION} - Stress Test")
        stress_win.geometry("1100x740")
        stress_win.geometry("+1110+0")
        stress_win.configure(bg=BG)
        stress_win.resizable(True, True)
        # Stress window has no toolbar (Settings/Raw Sensors belong to the
        # sensors window; stress window gets its own status label only)
        stress_status_label = _build_header(stress_win, "Stress Test",
                                            "#ff6644", show_toolbar=False)

        sensors_root = root
        stress_root = stress_win

    if app_mode in ("sensors", "both"):
        s_canvas = tk.Canvas(sensors_root, bg=BG, highlightthickness=0)
        s_sb = tk.Scrollbar(sensors_root, orient="vertical", command=s_canvas.yview)
        s_canvas.configure(yscrollcommand=s_sb.set)
        s_sb.pack(side="right", fill="y")
        s_canvas.pack(side="left", fill="both", expand=True)

        sf = tk.Frame(s_canvas, bg=BG)
        sf_window = s_canvas.create_window((0, 0), window=sf, anchor="nw")
        # Track scroll position ourselves — never let tkinter reset it
        _user_scrolled = [False]
        _last_bbox     = [None]

        def _sync_scrollregion():
            """Called periodically — only updates scrollregion if bbox changed,
            and always restores the user's scroll position."""
            bbox = s_canvas.bbox("all")
            if bbox and bbox != _last_bbox[0]:
                _last_bbox[0] = bbox
                pos = s_canvas.yview()[0]
                s_canvas.configure(scrollregion=bbox)
                if pos > 0:
                    s_canvas.yview_moveto(pos)
            s_canvas.after(250, _sync_scrollregion)

        sf.bind("<Configure>", lambda e: None)   # disable default
        s_canvas.bind("<Configure>", lambda e: s_canvas.itemconfig(sf_window, width=e.width))
        # Bind scroll only to main window widgets — not global bind_all
        sensors_root.bind("<MouseWheel>", lambda e: s_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        s_canvas.bind("<MouseWheel>", lambda e: s_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        sf.bind("<MouseWheel>", lambda e: s_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        s_canvas.after(500, _sync_scrollregion)

        for c in range(3):
            sf.columnconfigure(c, weight=1)

        sf.columnconfigure(0, weight=1)    # left — rings (full width now)
        sf.columnconfigure(1, weight=0)    # separator — hidden
        sf.columnconfigure(2, weight=0)    # right — moved to separate window
        sf.rowconfigure(0, weight=1)

        RS = 160   # ring canvas size — bigger = more presence
        BLOCK_BG = "#0d1525"   # subtle darker bg for each component block

        # ── Helpers ───────────────────────────────────────────────────────────
        def comp_block(parent):
            """Component block with subtle dark background."""
            outer = tk.Frame(parent, bg=BLOCK_BG)
            outer.pack(fill="x", pady=(0, 2))
            inner = tk.Frame(outer, bg=BLOCK_BG, padx=24, pady=18)
            inner.pack(fill="x")
            return inner

        def comp_title(parent, icon, title, subtitle, accent):
            """Component header inside a block."""
            hf = tk.Frame(parent, bg=BLOCK_BG)
            hf.pack(fill="x", pady=(0, 12))
            tk.Label(hf, text=f"{icon}  {title}", fg=accent, bg=BLOCK_BG,
                     font=("Segoe UI", 12, "bold")).pack(side="left")
            tk.Label(hf, text=subtitle, fg="#4a5568", bg=BLOCK_BG,
                     font=("Segoe UI", 8)).pack(side="left", padx=(10, 0), pady=(3, 0))

        def ring_pair(parent, bg=None):
            """Two side-by-side ring canvases."""
            if bg is None: bg = BLOCK_BG
            f = tk.Frame(parent, bg=bg)
            f.pack(anchor="center", pady=(0, 8))
            cl = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
            cl.pack(side="left", padx=24)
            cr = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
            cr.pack(side="left", padx=24)
            return cl, cr

        def single_ring(parent, bg=None):
            """One centered ring canvas."""
            if bg is None: bg = BLOCK_BG
            f = tk.Frame(parent, bg=bg)
            f.pack(anchor="center", pady=(0, 8))
            c = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
            c.pack(padx=24)
            return c

        def stat_strip(parent, specs, bg=None):
            """Horizontal strip of label+value stats. specs = [(label, accent), ...]
            Returns list of value labels in same order."""
            if bg is None: bg = BLOCK_BG
            f = tk.Frame(parent, bg=bg)
            f.pack(anchor="center", pady=(4, 0))
            labels = []
            for lbl, accent in specs:
                col = tk.Frame(f, bg=bg)
                col.pack(side="left", padx=18)
                tk.Label(col, text=lbl, fg="#4a5568", bg=bg,
                         font=("Segoe UI", 8, "bold")).pack()
                v = tk.Label(col, text="--", fg=accent, bg=bg,
                             font=("Segoe UI", 14, "bold"))
                v.pack()
                labels.append(v)
            return labels

        # ── LEFT PANEL ────────────────────────────────────────────────────────
        left = tk.Frame(sf, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")

        # ·· CPU Block — rings left, graph right ················
        cpu_block = comp_block(left)
        comp_title(cpu_block, "🖥", "CPU", cpu_name, ACCENT_CPU)
        cpu_row = tk.Frame(cpu_block, bg=BLOCK_BG)
        cpu_row.pack(fill="x")

        # Rings side
        cpu_rings_col = tk.Frame(cpu_row, bg=BLOCK_BG)
        cpu_rings_col.pack(side="left")
        cpu_ring_load, cpu_ring_temp = ring_pair(cpu_rings_col)
        cpu_stats_f = tk.Frame(cpu_rings_col, bg=BLOCK_BG)
        cpu_stats_f.pack(anchor="center", pady=(4, 0))
        cpu_clock_lbl, cpu_power_lbl, cpu_voltage_lbl = stat_strip(cpu_stats_f, [
            ("CLOCK",   ACCENT_CPU),
            ("POWER",   "#f87171"),
            ("VOLTAGE", "#22d3ee"),
        ])
        cpu_diag_lbl = tk.Label(cpu_rings_col, text="", fg="#f59e0b", bg=BLOCK_BG,
                                font=("Segoe UI", 8), wraplength=300)
        cpu_diag_lbl.pack(anchor="center", pady=(4, 0))

        # Graph side
        cpu_graph_col = tk.Frame(cpu_row, bg=BLOCK_BG)
        cpu_graph_col.pack(side="left", fill="both", expand=True, padx=(16, 0))
        # CPU graph
        tk.Label(cpu_graph_col, text="● CPU TEMP", fg=COL_CPU, bg=BLOCK_BG,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 2))
        cpu_graph_canvas = tk.Canvas(cpu_graph_col, bg=GRAPH_BG, height=85,
                                     highlightthickness=1, highlightbackground=BORDER)
        cpu_graph_canvas.pack(fill="x", pady=(0, 8))
        cpu_graph_canvas.bind("<Configure>",
                              lambda e: draw_single_graph(cpu_graph_canvas,
                                                          graph_cpu_temps, COL_CPU, 85))


        # ·· GPU Block — primary GPU (dGPU preferred) gets full hero treatment ··
        gpu_block = tk.Frame(left, bg=BG)
        gpu_block.pack(fill="x", pady=(0, 2))
        gpu_frames      = {}
        gpu_secondary   = []   # secondary GPU info for right panel
        _gpu_built      = [False]

        def is_igpu(name):
            return any(k in name.lower() for k in ["intel","uhd","iris","igpu","vega"])

        def make_gpu_cards(gpu_list):
            if _gpu_built[0]:
                return
            _gpu_built[0] = True

            sorted_gpus = sorted(enumerate(gpu_list),
                                 key=lambda x: (0 if not is_igpu(x[1]["name"]) else 1))

            for rank, (orig_i, gpu) in enumerate(sorted_gpus):
                acc = ACCENT_GPU if rank == 0 else "#06b6d4"
                label = "GPU" if len(gpu_list) == 1 else (
                    "GPU (dGPU)" if not is_igpu(gpu["name"]) else "GPU (iGPU)")

                if rank == 0:
                    # Primary GPU — identical structure to CPU block
                    blk = tk.Frame(gpu_block, bg=BLOCK_BG, padx=24, pady=18)
                    blk.pack(fill="x", pady=(0, 2))
                    comp_title(blk, "🎮", label, gpu["name"], acc)

                    gpu_row_f = tk.Frame(blk, bg=BLOCK_BG)
                    gpu_row_f.pack(fill="x")

                    # ── Rings side (left) — same as CPU ──────────────────────
                    gpu_rings_col = tk.Frame(gpu_row_f, bg=BLOCK_BG)
                    gpu_rings_col.pack(side="left")
                    rl, rt = ring_pair(gpu_rings_col)
                    # Stat strip row 1
                    sr1 = tk.Frame(gpu_rings_col, bg=BLOCK_BG)
                    sr1.pack(anchor="center", pady=(8, 0))
                    gs1 = stat_strip(sr1, [
                        ("CORE CLOCK", acc),
                        ("VRAM USED",  "#fbbf24"),
                        ("POWER",      "#f87171"),
                    ])
                    # Stat strip row 2
                    sr2 = tk.Frame(gpu_rings_col, bg=BLOCK_BG)
                    sr2.pack(anchor="center", pady=(4, 0))
                    gs2 = stat_strip(sr2, [
                        ("HOTSPOT",   "#f87171"),
                        ("VRAM TEMP", "#fb923c"),
                        ("VOLTAGE",   "#22d3ee"),
                    ])

                    # ── Graph side (right) — hidden until temp exists ─────────
                    gc = tk.Frame(gpu_row_f, bg=BLOCK_BG)
                    gc.pack(side="left", fill="both", expand=True, padx=(16, 0))
                    g_hdr    = tk.Frame(gc, bg=BLOCK_BG)
                    g_legend = tk.Frame(g_hdr, bg=BLOCK_BG)
                    g_canvas = tk.Canvas(gc, bg=GRAPH_BG, height=170,
                                         highlightthickness=1, highlightbackground=BORDER)
                    g_visible = [False]

                    gpu_frames[orig_i] = {
                        "ring_load": rl, "ring_temp": rt, "acc": acc,
                        "graph_canvas": g_canvas, "graph_hdr": g_hdr,
                        "legend_frame": g_legend, "graph_col": gc,
                        "graph_visible": g_visible,
                        "clock":     gs1[0], "vram":     gs1[1], "power":    gs1[2],
                        "hotspot":   gs2[0], "vram_temp":gs2[1], "voltage":  gs2[2],
                        "primary": True,
                    }
                else:
                    gpu_secondary.append({"orig_i": orig_i, "name": gpu["name"], "acc": acc})
                    gpu_frames[orig_i] = {"primary": False, "acc": acc}

        # ·· RAM Block ·········································
        ram_block = comp_block(left)
        ram0 = psutil.virtual_memory()
        comp_title(ram_block, "💾", "RAM",
                   f"Total {ram0.total/1024**3:.0f} GB  ·  {ram_info}", ACCENT_RAM)

        ram_row = tk.Frame(ram_block, bg=BLOCK_BG)
        ram_row.pack(fill="x")

        # ── Rings side (left) ─────────────────────────────────────────────────
        ram_rings_col = tk.Frame(ram_row, bg=BLOCK_BG)
        ram_rings_col.pack(side="left")

        ram_rings_f = tk.Frame(ram_rings_col, bg=BLOCK_BG)
        ram_rings_f.pack(anchor="center", pady=(0, 8))
        ram_ring_usage = tk.Canvas(ram_rings_f, width=RS, height=RS,
                                   bg=BLOCK_BG, highlightthickness=0)
        ram_ring_usage.pack(side="left", padx=24)
        # RAM temp ring — hidden until sensor found
        ram_ring_temp = tk.Canvas(ram_rings_f, width=RS, height=RS,
                                  bg=BLOCK_BG, highlightthickness=0)
        ram_temp_visible = [False]
        ram_temp_history = collections.deque(maxlen=GRAPH_SECONDS)

        # Stat strip below rings
        ram_stats_f = tk.Frame(ram_rings_col, bg=BLOCK_BG)
        ram_stats_f.pack(anchor="center", pady=(4, 0))
        ram_used_lbl, ram_free_lbl, ram_clock_lbl = stat_strip(ram_stats_f, [
            ("USED",      ACCENT_RAM),
            ("AVAILABLE", "#a78bfa"),
            ("SPEED",     "#c4b5fd"),
        ])
        _, ram_bar = make_bar(ram_rings_col, ACCENT_RAM, BORDER)

        # ── Graph side (right) ────────────────────────────────────────────────
        ram_graph_col = tk.Frame(ram_row, bg=BLOCK_BG)
        ram_graph_col.pack(side="left", fill="both", expand=True, padx=(16, 0))

        ram_temp_graph_hdr = tk.Frame(ram_graph_col, bg=BLOCK_BG)
        ram_temp_graph_canvas = tk.Canvas(ram_graph_col, bg=GRAPH_BG, height=85,
                                          highlightthickness=1, highlightbackground=BORDER)
        ram_graph_visible = [False]

        tk.Frame(left, bg=BG, height=12).pack()

        # ── INFO WINDOW — separate Toplevel ──────────────────────────────────
        info_win = tk.Toplevel()   # no parent → independent window
        info_win.title(f"HWInfo Monitor {APP_VERSION} - Info")
        info_win.configure(bg=BG)
        info_win.resizable(True, True)
        info_win.geometry("340x740+1110+0")

        # Closing info → just destroy info, main keeps running
        info_win.protocol("WM_DELETE_WINDOW", info_win.destroy)

        # Closing main → destroy both
        def _on_main_close():
            try: info_win.destroy()
            except Exception: pass
            sensors_root.destroy()
        sensors_root.protocol("WM_DELETE_WINDOW", _on_main_close)

        iw_canvas = tk.Canvas(info_win, bg=BG, highlightthickness=0)
        iw_sb = tk.Scrollbar(info_win, orient="vertical", command=iw_canvas.yview)
        iw_canvas.configure(yscrollcommand=iw_sb.set)
        iw_sb.pack(side="right", fill="y")
        iw_canvas.pack(side="left", fill="both", expand=True)
        right = tk.Frame(iw_canvas, bg=BG)
        iw_win_id = iw_canvas.create_window((0, 0), window=right, anchor="nw")
        iw_canvas.bind("<Configure>", lambda e: iw_canvas.itemconfig(iw_win_id, width=e.width))
        def _iw_sync_scrollregion(e=None):
            bbox = iw_canvas.bbox("all")
            if not bbox:
                return
            pos = iw_canvas.yview()[0]
            iw_canvas.configure(scrollregion=bbox)
            if pos > 0:
                iw_canvas.yview_moveto(pos)
        right.bind("<Configure>", _iw_sync_scrollregion)
        iw_canvas.bind("<MouseWheel>", lambda e: iw_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        info_win.bind("<MouseWheel>", lambda e: iw_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        right.bind("<MouseWheel>", lambda e: iw_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        def _bind_mousewheel_recursive(widget):
            widget.bind("<MouseWheel>", lambda e: iw_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
            for child in widget.winfo_children():
                _bind_mousewheel_recursive(child)

        # Re-bind after all widgets are created
        info_win.after(500, lambda: _bind_mousewheel_recursive(right))

        ROW_A = "#0d1220"
        ROW_B = BG
        _ri = [0]

        def list_header(icon, title, accent):
            _ri[0] = 0
            f = tk.Frame(right, bg=BG)
            f.pack(fill="x", padx=16, pady=(20, 6))
            tk.Label(f, text="●", fg=accent, bg=BG,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
            tk.Label(f, text=title, fg="white", bg=BG,
                     font=("Segoe UI", 11, "bold")).pack(side="left")

        def list_row(label, val_color="#aaa"):
            bg = ROW_A if _ri[0] % 2 == 0 else ROW_B
            _ri[0] += 1
            f = tk.Frame(right, bg=bg)
            f.pack(fill="x", padx=8)
            tk.Label(f, text=label, fg="#4a5568", bg=bg,
                     font=("Segoe UI", 9), anchor="w").pack(
                         side="left", padx=(12, 0), pady=6, fill="x", expand=True)
            v = tk.Label(f, text="\u2014", fg=val_color, bg=bg,
                         font=("Segoe UI", 10, "bold"), anchor="e")
            v.pack(side="right", padx=(0, 16))
            return v

        # Secondary GPU section
        sec_gpu_section = tk.Frame(right, bg=BG)
        sec_gpu_section.pack(fill="x")
        sec_gpu_visible = [False]
        sec_load_lbl = [None]
        sec_vram_lbl = [None]

        # RAM details
        list_header("\U0001f4be", "RAM", ACCENT_RAM)
        ram_type_lbl    = list_row("Type",        ACCENT_RAM)
        ram_form_lbl    = list_row("Form Factor", ACCENT_RAM)
        ram_sticks_lbl  = list_row("Sticks",      ACCENT_RAM)
        ram_timing_lbl  = list_row("SPD Timings", ACCENT_RAM)
        ram_voltage_lbl = list_row("Voltage",     ACCENT_RAM)

        # Network
        list_header("\U0001f310", "Network", ACCENT_NET)
        net_up_lbl   = list_row("Upload",   ACCENT_NET)
        net_down_lbl = list_row("Download", ACCENT_NET)

        # System
        list_header("\u2699", "System", ACCENT_SYS)
        sys_host_lbl    = list_row("Hostname",   "#e2e8f0")
        sys_os_lbl      = list_row("OS",         "#e2e8f0")
        sys_ver_lbl     = list_row("Version",    "#e2e8f0")
        sys_build_lbl   = list_row("Build",      "#e2e8f0")
        sys_gpu_drv_lbl = list_row("GPU Driver", "#e2e8f0")
        sys_uptime_lbl  = list_row("Uptime",     "#e2e8f0")
        sys_host_lbl.config(text=socket.gethostname())
        sys_os_lbl.config(text=win_ver)
        sys_ver_lbl.config(text=win_ver_name if win_ver_name else "\u2014")
        sys_build_lbl.config(text=win_build if win_build else "\u2014")
        sys_gpu_drv_lbl.config(text=gpu_driver)

        # Fans
        list_header("\U0001f300", "Fans", ACCENT_FAN)
        fan_frame = tk.Frame(right, bg=BG)
        fan_frame.pack(fill="x", padx=8)

        # Storage
        list_header("\U0001f4bf", "Storage", ACCENT_DISK)
        disk_frames = {}
        for i, disk in enumerate(all_disks):
            dh = tk.Frame(right, bg=BG)
            dh.pack(fill="x", padx=20, pady=(8, 2))
            tk.Label(dh, text=f"{disk['model'][:30]}  \u00b7  {disk['type']}  \u00b7  {disk['size']} GB",
                     fg="#4a5568", bg=BG, font=("Segoe UI", 8)).pack(side="left")
            _ri[0] = 0
            h_lbl   = list_row("Health",         "#22c55e")
            t_lbl   = list_row("Temp",           "#f59e0b")
            r_lbl   = list_row("Read",           "#6b7280")
            w_lbl   = list_row("Written",        "#6b7280")
            poh_lbl = list_row("Power-On Hours", "#6b7280")
            pf = tk.Frame(right, bg=BG, padx=20)
            pf.pack(fill="x", pady=(4, 0))
            disk_frames[i] = {
                "health": h_lbl, "temp": t_lbl,
                "read": r_lbl, "write": w_lbl,
                "poh": poh_lbl,
                "parts_frame": pf,
            }

        tk.Frame(right, bg=BG, height=20).pack()

        _last_net = [None]  # stores previous net_io_counters() snapshot

        def update_sensors():
            if not bridge.fetch():
                status_label.config(text="Offline - LHMBridge not running", fg="#ff4444")
                root.after(2000, update_sensors)
                return

            status_label.config(text="Live", fg="#00ff88")



            cpu_temp = bridge.get_cpu_temp()
            cpu_usage = None
            cpu_clock = None
            for key, sensors in bridge.get_data_snapshot().items():
                if "cpu" not in key.lower():
                    continue
                u = bridge.sensor_value_in(sensors, ["CPU Total", "CPU Core Max", "Total"], "Load")
                if u is not None:
                    cpu_usage = u
                clks = [(s["Name"], s["Value"]) for s in sensors
                        if s["Type"].lower() == "clock" and "core" in s["Name"].lower()]
                if clks:
                    cpu_clock = max(v for _, v in clks)

            # Fetch power/voltage per cpu key
            cpu_power = None
            cpu_voltage = None
            for key, sensors in bridge.get_data_snapshot().items():
                if "cpu" not in key.lower():
                    continue
                p = bridge.sensor_value_in(sensors, ["CPU Package", "CPU Cores", "Package"], "Power")
                if p is not None:
                    cpu_power = p
                v = bridge.sensor_value_in(sensors, ["CPU Core", "Core"], "Voltage")
                if v is not None:
                    cpu_voltage = v

            # Dual rings: load (left) + temp (right)
            graph_cpu_temps.append(cpu_temp)
            draw_single_graph(cpu_graph_canvas, graph_cpu_temps, COL_CPU, 85)
            draw_ring(cpu_ring_load, cpu_usage, "LOAD", ACCENT_CPU, BLOCK_BG,
                      max_val=100, unit="%")
            draw_ring(cpu_ring_temp, cpu_temp,  "TEMP", temp_color(cpu_temp), BLOCK_BG,
                      max_val=105, unit="°C")
            if cpu_temp is None:
                reason = bridge.diagnose_na("cpu_temp")
                # Simplify message for end users
                if "permissions" in reason.lower() or "driver" in reason.lower():
                    msg = "⚠  Run as Administrator to enable temperature sensors"
                elif "not running" in reason.lower():
                    msg = "⚠  LHMBridge not running — restart the app"
                elif "sensor" in reason.lower() and "available" in reason.lower():
                    # Extract sensor names from message
                    msg = f"⚠  {reason}"
                else:
                    msg = f"⚠  {reason}"
                cpu_diag_lbl.config(text=msg)
            else:
                cpu_diag_lbl.config(text="")
            cpu_clock_lbl.config(text=fmt_clock(cpu_clock), fg=clock_color(cpu_clock))
            cpu_power_lbl.config(
                text=f"{cpu_power:.1f} W" if cpu_power is not None else "N/A",
                fg="#f87171" if cpu_power is not None else "#4a5568")
            cpu_voltage_lbl.config(
                text=f"{cpu_voltage:.3f} V" if cpu_voltage is not None else "N/A",
                fg="#22d3ee" if cpu_voltage is not None else "#4a5568")

            ram = psutil.virtual_memory()
            ram_clocks = bridge.find_all_sensors("memory", "", "Clock")
            ram_clock = int(ram_clocks[0][1]) if ram_clocks else None
            if not ram_clock:
                m = re.search(r"@ (\d+) MHz", ram_info)
                if m:
                    ram_clock = int(m.group(1))
            # Parse RAM type/form from ram_info string e.g. "DDR4 @ 2666 MHz  |  2x SO-DIMM"
            ram_type_str  = ram_info.split("@")[0].strip() if "@" in ram_info else "DDR"
            ram_form_str  = ram_info.split("|")[-1].strip() if "|" in ram_info else "DIMM"
            # Parse stick count from form factor string e.g. "2x SO-DIMM"
            import re as _re
            sticks_m = _re.search(r"(\d+)x", ram_form_str)
            sticks_str = sticks_m.group(1) if sticks_m else "?"
            form_only  = _re.sub(r"\d+x\s*", "", ram_form_str).strip()

            # RAM temp — check all memory keys
            ram_temp = None
            for key, sensors in bridge.get_data_snapshot().items():
                if "memory" not in key.lower(): continue
                v = bridge.sensor_value_in(sensors,
                    ["Temperature", "Memory Temperature", "DIMM"],
                    "Temperature")
                if v is not None and 10 <= v <= 90:
                    ram_temp = v
                    break

            draw_ring(ram_ring_usage, ram.percent, "USAGE", ACCENT_RAM, BLOCK_BG, max_val=100, unit="%")

            # Show/hide RAM temp ring dynamically
            if ram_temp is not None:
                if not ram_temp_visible[0]:
                    ram_ring_temp.pack(side="left", padx=24)
                    ram_temp_visible[0] = True
                draw_ring(ram_ring_temp, ram_temp, "TEMP", temp_color(ram_temp),
                          BLOCK_BG, max_val=90, unit="°C")
                ram_temp_history.append(ram_temp)
                if not ram_graph_visible[0]:
                    ram_graph_visible[0] = True
                    tk.Label(ram_temp_graph_hdr, text="● RAM TEMP", fg=ACCENT_RAM,
                             bg=BLOCK_BG, font=("Segoe UI", 8, "bold")).pack(anchor="w")
                    ram_temp_graph_hdr.pack(fill="x", pady=(0, 2))
                    ram_temp_graph_canvas.pack(fill="x", pady=(0, 4))
                draw_single_graph(ram_temp_graph_canvas, ram_temp_history, ACCENT_RAM, 85)

            ram_used_lbl.config(text=f"{ram.used/1024**3:.1f} GB")
            ram_free_lbl.config(text=f"{ram.available/1024**3:.1f} GB")
            ram_clock_lbl.config(text=f"{ram_clock} MHz" if ram_clock else "N/A")
            update_bar(ram_bar, ram.percent)
            ram_type_lbl.config(text=ram_type_str)
            ram_form_lbl.config(text=form_only)
            ram_sticks_lbl.config(text=sticks_str)

            # RAM timings — real values from AMD UMC via LHMBridge /timings
            timings = bridge.get_memory_timings()
            if timings and "tCL" in timings:
                cl   = timings.get("tCL", "")
                rcd  = timings.get("tRCDRD", timings.get("tRCD", ""))
                rp   = timings.get("tRP", "")
                ras  = timings.get("tRAS", "")
                parts = [str(int(x)) for x in [cl, rcd, rp, ras] if x != ""]
                ram_timing_str = "-".join(parts) if parts else "—"
                cr = timings.get("CR", "")
                if cr: ram_timing_str += f"  {cr}"
            else:
                # Fallback: SPD data from LHM sensors
                ram_timing_str = "—"
                snap = bridge.get_data_snapshot()
                for key, sensors in snap.items():
                    if "memory" not in key.lower(): continue
                    cl   = bridge.sensor_value_in(sensors, ["tAA"], "Factor")
                    trcd = bridge.sensor_value_in(sensors, ["tRCD"], "Factor")
                    trp  = bridge.sensor_value_in(sensors, ["tRP"],  "Factor")
                    tras = bridge.sensor_value_in(sensors, ["tRAS"], "Factor")
                    if cl is not None:
                        parts = [f"{int(cl)}"]
                        for t in [trcd, trp, tras]:
                            if t is not None: parts.append(f"{int(t)}")
                        ram_timing_str = "-".join(parts) + " (SPD)"
                    break

            # Voltage
            ram_volt_str = "—"
            snap = bridge.get_data_snapshot()
            for key, sensors in snap.items():
                if "memory" not in key.lower(): continue
                v = bridge.sensor_value_in(sensors, ["Voltage","VDD","VDIMM","DIMM"], "Voltage")
                if v is not None and 1.0 <= v <= 2.0:
                    ram_volt_str = f"{v:.3f} V"
                break

            ram_timing_lbl.config(text=ram_timing_str)
            ram_voltage_lbl.config(text=ram_volt_str)

            gpu_keys = bridge.get_gpu_keys()
            if gpu_keys:
                make_gpu_cards([{"name": k.split("|")[1] if "|" in k else k} for k in gpu_keys])
                for i, key in enumerate(gpu_keys):
                    if i not in gpu_frames:
                        continue
                    lbls = gpu_frames[i]
                    sensors = bridge.data.get(key, [])
                    g_temp = bridge.sensor_value_in(sensors, ["GPU Core", "Core", "Temperature"], "Temperature")
                    g_usage = bridge.sensor_value_in(sensors, ["D3D 3D", "GPU Core", "GPU Total", "Core"], "Load")
                    g_clock = bridge.sensor_value_in(sensors, ["GPU Core", "Core"], "Clock")
                    g_vram = (bridge.sensor_value_in(sensors, ["GPU Memory Used", "Memory Used", "D3D Shared Memory Used"], "SmallData") or
                              bridge.sensor_value_in(sensors, ["GPU Memory Used", "Memory Used"], "Data"))
                    g_hotspot = bridge.sensor_value_in(sensors, ["GPU Hotspot", "Hotspot", "Hot Spot"], "Temperature")
                    g_vram_t = bridge.sensor_value_in(sensors, ["GPU Memory", "Memory Temperature", "VRAM Temperature"], "Temperature")

                    g_power   = (
                        bridge.sensor_value_in(sensors, ["GPU Package"], "Power") or
                        bridge.sensor_value_in(sensors, ["GPU Power", "Power"], "Power")
                    )
                    g_voltage = bridge.sensor_value_in(sensors, ["GPU Core", "Core"], "Voltage")
                    acc = lbls["acc"]

                    if lbls.get("primary", False):
                        # Rings
                        draw_ring(lbls["ring_load"], g_usage, "LOAD", acc, BLOCK_BG,
                                  max_val=100, unit="%")
                        draw_ring(lbls["ring_temp"], g_temp, "TEMP", temp_color(g_temp), BLOCK_BG,
                                  max_val=110, unit="°C")
                        # Stat strip labels in block
                        lbls["clock"].config(
                            text=fmt_clock(g_clock) if g_clock is not None else "N/A",
                            fg=acc if g_clock is not None else "#4a5568")
                        lbls["vram"].config(
                            text=f"{g_vram:.0f} MB" if g_vram is not None else "N/A",
                            fg="#fbbf24" if g_vram is not None else "#4a5568")
                        lbls["power"].config(
                            text=f"{g_power:.1f} W" if g_power is not None else "N/A",
                            fg="#f87171" if g_power is not None else "#4a5568")
                        lbls["hotspot"].config(
                            text=f"{g_hotspot:.0f}°C" if g_hotspot is not None else "N/A",
                            fg=temp_color(g_hotspot) if g_hotspot is not None else "#4a5568")
                        lbls["vram_temp"].config(
                            text=f"{g_vram_t:.0f}°C" if g_vram_t is not None else "N/A",
                            fg=temp_color(g_vram_t) if g_vram_t is not None else "#4a5568")
                        lbls["voltage"].config(
                            text=f"{g_voltage:.3f} V" if g_voltage is not None else "N/A",
                            fg="#22d3ee" if g_voltage is not None else "#4a5568")
                        # Graph — only show when at least one temp exists
                        any_temp = any(v is not None for v in [g_temp, g_hotspot, g_vram_t])
                        if any_temp:
                            if not lbls["graph_visible"][0]:
                                lbls["graph_visible"][0] = True
                                hdr = lbls["graph_hdr"]
                                tk.Label(hdr, text="GPU TEMPS", fg="#6b7280", bg=BLOCK_BG,
                                         font=("Segoe UI", 8, "bold")).pack(side="left")
                                lbls["legend_frame"].pack(side="left", padx=(8, 0))
                                hdr.pack(fill="x", pady=(8, 2))
                                lbls["graph_canvas"].pack(fill="both", expand=True, pady=(0, 4))
                            gpu_temp_map = {"Core": g_temp, "Hotspot": g_hotspot, "VRAM": g_vram_t}
                            for name, val in gpu_temp_map.items():
                                if val is not None:
                                    if name not in graph_gpu_series:
                                        graph_gpu_series[name] = collections.deque(maxlen=GRAPH_SECONDS)
                                    graph_gpu_series[name].append(val)
                                elif name in graph_gpu_series:
                                    graph_gpu_series[name].append(None)
                            lf = lbls["legend_frame"]
                            for w in lf.winfo_children():
                                w.destroy()
                            series = [(graph_gpu_series[n], GPU_TEMP_COLORS.get(n, COL_GPU))
                                      for n in ["Core","Hotspot","VRAM"] if n in graph_gpu_series]
                            for name in ["Core","Hotspot","VRAM"]:
                                if name in graph_gpu_series:
                                    c = GPU_TEMP_COLORS.get(name, COL_GPU)
                                    tk.Label(lf, text=f"● {name}", fg=c, bg=BLOCK_BG,
                                             font=("Segoe UI", 7, "bold")).pack(side="left", padx=(0,8))
                            draw_multi_graph(lbls["graph_canvas"], series, 170)
                    # Secondary GPU → right panel compact section
                    if not lbls.get("primary", False):
                        if not sec_gpu_visible[0] and gpu_secondary:
                            sec_gpu_visible[0] = True
                            info = gpu_secondary[0]
                            # Header
                            hf = tk.Frame(sec_gpu_section, bg=BG)
                            hf.pack(fill="x", padx=16, pady=(22, 4))
                            tk.Label(hf, text="●", fg=info["acc"], bg=BG,
                                     font=("Segoe UI", 9)).pack(side="left", padx=(0,8))
                            tk.Label(hf, text="IGPU", fg="white", bg=BG,
                                     font=("Segoe UI", 10, "bold")).pack(side="left")
                            tk.Label(hf, text=info["name"], fg="#4a5568", bg=BG,
                                     font=("Segoe UI", 8)).pack(side="left", padx=(8,0))
                            # Rows
                            def _srow(label, val_color):
                                bg = ROW_A
                                f = tk.Frame(sec_gpu_section, bg=bg)
                                f.pack(fill="x", padx=8)
                                tk.Label(f, text=label, fg="#6b7280", bg=bg,
                                         font=("Segoe UI", 10), anchor="w").pack(
                                             side="left", padx=(14,0), pady=8,
                                             fill="x", expand=True)
                                v = tk.Label(f, text="—", fg=val_color, bg=bg,
                                             font=("Segoe UI", 11, "bold"), anchor="e")
                                v.pack(side="right", padx=(0,18))
                                return v
                            sec_load_lbl[0] = _srow("Load",      info["acc"])
                            sec_vram_lbl[0] = _srow("VRAM Used", "#fbbf24")
                        if sec_load_lbl[0]:
                            sec_load_lbl[0].config(text=f"{g_usage:.0f}%" if g_usage is not None else "N/A")
                            sec_vram_lbl[0].config(text=f"{g_vram:.0f} MB" if g_vram is not None else "N/A")

            for w in fan_frame.winfo_children():
                w.destroy()
            fans = bridge.find_all_fans()
            if fans:
                for fi, (fname, fval) in enumerate(fans):
                    bg = ROW_A if fi % 2 == 0 else ROW_B
                    row = tk.Frame(fan_frame, bg=bg)
                    row.pack(fill="x")
                    # RPM value first (right-anchored) so it's never clipped
                    txt = f"{fval:.0f} RPM" if fval > 0 else "0 RPM"
                    tk.Label(row, text=txt, fg=ACCENT_FAN if fval > 0 else "#4a5568",
                             bg=bg, font=("Segoe UI", 10, "bold"),
                             width=10, anchor="e").pack(side="right", padx=(0,16))
                    # Name — truncate if too long
                    display_name = fname if len(fname) <= 22 else fname[:21] + "…"
                    tk.Label(row, text=display_name, fg="#6b7280", bg=bg,
                             font=("Segoe UI", 9), anchor="w").pack(
                                 side="left", padx=(12,0), pady=6)
            else:
                tk.Label(fan_frame, text="No fan sensors found", fg="#4a5568",
                         bg=BG, font=("Segoe UI", 9), padx=12).pack(anchor="w", pady=6)

            storage_keys = sorted([k for k in bridge.data if "storage" in k.lower()])
            for i in range(len(all_disks)):
                if i not in disk_frames:
                    continue
                lbls = disk_frames[i]
                sensors = bridge.data.get(storage_keys[i], []) if i < len(storage_keys) else []
                health = (
                    bridge.sensor_value_in(sensors, ["Remaining Life"], "Level") or
                    bridge.sensor_value_in(sensors, ["Percentage Used"], "Level") or
                    bridge.sensor_value_in(sensors, ["Health", "Life"], "Level")
                )
                # Convert "Percentage Used" to remaining life
                if health is not None:
                    pu = bridge.sensor_value_in(sensors, ["Percentage Used"], "Level")
                    if pu is not None and health == pu:
                        health = max(0, 100 - pu)
                temp   = bridge.sensor_value_in(sensors, ["Temperature", "Composite"], "Temperature")
                read   = bridge.sensor_value_in(sensors, ["Total Bytes Read", "Data Read"], "Data")
                write  = bridge.sensor_value_in(sensors, ["Total Bytes Written", "Data Written"], "Data")
                poh    = (
                    bridge.sensor_value_in(sensors, ["Power On Hours", "Power-On Hours", "Powered On Hours"], "TimeSpan") or
                    bridge.sensor_value_in(sensors, ["Power On Hours", "Power-On Hours", "Powered On Hours"], "Data") or
                    bridge.sensor_value_in(sensors, ["Power On Hours", "Power-On Hours", "Powered On Hours"], "Factor") or
                    bridge.sensor_value_in(sensors, ["Power On Hours", "Power-On Hours", "Powered On Hours"], "SmallData")
                )

                lbls["health"].config(text=f"{health:.0f}%" if health is not None else "N/A", fg=health_color(health))
                lbls["temp"].config(text=f"{temp:.0f}°C" if temp is not None else "N/A", fg=temp_color(temp))
                lbls["read"].config(text=fmt_data(read), fg="#6b7280")
                lbls["write"].config(text=fmt_data(write), fg="#6b7280")
                if poh is not None:
                    poh_days  = int(poh) // 24
                    poh_hours = int(poh) % 24
                    poh_str   = f"{poh_days}d {poh_hours}h" if poh_days > 0 else f"{poh_hours}h"
                    lbls["poh"].config(text=poh_str, fg="#6b7280")
                else:
                    lbls["poh"].config(text="N/A", fg="#4a5568")

                # Rebuild partition bar rows
                pf = lbls["parts_frame"]
                for w in pf.winfo_children():
                    w.destroy()
                try:
                    disk_idx = all_disks[i]["index"]
                    for part in psutil.disk_partitions():
                        letter = part.device.rstrip("\\").upper()
                        if _letter_to_disk and _letter_to_disk.get(letter, -1) != disk_idx:
                            continue
                        try:
                            u    = psutil.disk_usage(part.mountpoint)
                            pct  = u.percent
                            used = u.used  / 1024**3
                            tot  = u.total / 1024**3
                            bar_col = ("#22c55e" if pct < 70
                                       else "#f59e0b" if pct < 88
                                       else "#ef4444")
                            row = tk.Frame(pf, bg=BG)
                            row.pack(fill="x", pady=(3, 0))
                            tk.Label(row, text=letter, fg="white", bg=BG,
                                     font=("Segoe UI", 10, "bold"),
                                     width=4, anchor="w").pack(side="left")
                            tk.Label(row, text=f"{used:.0f} / {tot:.0f} GB",
                                     fg="#6b7280", bg=BG,
                                     font=("Segoe UI", 9)).pack(side="left", expand=True)
                            tk.Label(row, text=f"{pct:.0f}%",
                                     fg=bar_col, bg=BG,
                                     font=("Segoe UI", 10, "bold"),
                                     width=5, anchor="e").pack(side="right")
                            track = tk.Frame(pf, bg=BORDER, height=3)
                            track.pack(fill="x", pady=(1, 2))
                            track.pack_propagate(False)
                            fill_f = tk.Frame(track, bg=bar_col, height=3)
                            fill_f.place(x=0, y=0, relheight=1.0,
                                       relwidth=max(0.01, min(pct / 100, 1.0)))
                        except Exception:
                            pass
                except Exception:
                    pass

            try:
                n_now = psutil.net_io_counters()
                if _last_net[0] is not None:
                    elapsed = 2.0  # matches root.after(2000) interval
                    net_up   = (n_now.bytes_sent - _last_net[0].bytes_sent) / elapsed / 1024
                    net_down = (n_now.bytes_recv - _last_net[0].bytes_recv) / elapsed / 1024
                else:
                    net_up = net_down = None
                _last_net[0] = n_now
            except Exception:
                net_up = net_down = None

            net_up_lbl.config(text=fmt_speed(net_up), fg=ACCENT_CPU)
            net_down_lbl.config(text=fmt_speed(net_down), fg="#22c55e")

            uptime = int(time.time()) - int(psutil.boot_time())
            h, m = divmod(uptime // 60, 60)
            d, h = divmod(h, 24)
            sys_uptime_lbl.config(text=f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m", fg="#6b7280")

            root.after(2000, update_sensors)

        def _fit_window_once():
            """Resize window once immediately — before any user interaction."""
            root.update_idletasks()
            screen_h = root.winfo_screenheight()
            screen_w = root.winfo_screenwidth()
            content_h = sf.winfo_reqheight() + 80
            content_w = max(sf.winfo_reqwidth() + 20, 1100)
            win_w = min(content_w, screen_w - 40)
            win_h = min(content_h, int(screen_h * 0.92))
            x = (screen_w - win_w) // 2
            y = (screen_h - win_h) // 2
            root.geometry(f"{win_w}x{win_h}+{x}+{y}")
            root.minsize(800, 400)

        # Run once synchronously before mainloop takes over
        root.after_idle(_fit_window_once)
        update_sensors()

    if app_mode != "both":
        stress_status_label = status_label

    if app_mode in ("stress", "both"):
        st_canvas = tk.Canvas(stress_root, bg=BG, highlightthickness=0)
        st_sb = tk.Scrollbar(stress_root, orient="vertical", command=st_canvas.yview)
        st_canvas.configure(yscrollcommand=st_sb.set)
        st_sb.pack(side="right", fill="y")
        st_canvas.pack(side="left", fill="both", expand=True)

        stf = tk.Frame(st_canvas, bg=BG)
        st_canvas.create_window((0, 0), window=stf, anchor="nw")
        stf.bind("<Configure>", lambda e: st_canvas.configure(scrollregion=st_canvas.bbox("all")))
        st_canvas.bind_all("<MouseWheel>", lambda e: st_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        for c in range(2):
            stf.columnconfigure(c, weight=1)

        gc2, gi2, _ = make_card(stf, "Live Temperatures (60s)", "🌡", ACCENT_CPU, CARD, BORDER)
        gc2.grid(row=0, column=0, columnspan=2, padx=8, pady=6, sticky="nsew")

        leg2 = tk.Frame(gi2, bg=CARD)
        leg2.pack(anchor="w", pady=(0, 4))
        tk.Label(leg2, text="CPU", fg=COL_CPU, bg=CARD, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 16))
        tk.Label(leg2, text="GPU", fg=COL_GPU, bg=CARD, font=("Segoe UI", 9, "bold")).pack(side="left")

        g_canvas2 = tk.Canvas(gi2, bg=GRAPH_BG, height=130, highlightthickness=1, highlightbackground="#333")
        g_canvas2.pack(fill="x", expand=True)
        g_canvas2.bind("<Configure>", lambda e: draw_graph_on(g_canvas2, 130))

        stress_log_boxes = {}

        def make_stress_card_ui(parent, title, icon, accent, row, col, cmd_prefix, colspan=1):
            start_fn, stop_fn = stress_manager.make_stress_action(cmd_prefix, cmd_prefix)
            card, inner, _ = make_card(parent, title, icon, accent, CARD, BORDER)
            card.grid(row=row, column=col, columnspan=colspan, padx=8, pady=6, sticky="nsew")

            lb = tk.Text(inner, bg="#111", fg="#bbb", font=("Consolas", 9), height=7, bd=0, relief="flat", state="disabled")
            lb.pack(fill="both", expand=True, pady=(0, 8))
            stress_log_boxes[cmd_prefix] = lb

            def log_cb(msg):
                log_queue.put((cmd_prefix, msg))

            bf = tk.Frame(inner, bg=CARD)
            bf.pack(fill="x", pady=(4, 0))
            tk.Button(
                bf,
                text="Start",
                bg="#006633",
                fg="white",
                font=("Segoe UI", 10, "bold"),
                relief="flat",
                padx=16,
                pady=6,
                cursor="hand2",
                command=lambda: start_fn(log_cb),
            ).pack(side="left", padx=(0, 8))
            tk.Button(
                bf,
                text="Stop",
                bg="#660000",
                fg="white",
                font=("Segoe UI", 10, "bold"),
                relief="flat",
                padx=16,
                pady=6,
                cursor="hand2",
                command=lambda: stop_fn(log_cb),
            ).pack(side="left")

        make_stress_card_ui(stf, "CPU - Single Core",       "🖥", ACCENT_CPU,    1, 0, "cpu_single")
        make_stress_card_ui(stf, "CPU - Multi Core",         "🖥", "#2563eb",     1, 1, "cpu_multi")
        make_stress_card_ui(stf, "CPU - Memory Controller",  "💾", ACCENT_RAM,    2, 0, "cpu_memory")
        make_stress_card_ui(stf, "CPU - Hybrid (Full Load)", "🔥", ACCENT_STRESS, 2, 1, "cpu_hybrid")
        make_stress_card_ui(stf, "GPU - Core",               "🎮", ACCENT_GPU,    3, 0, "gpu_core")
        make_stress_card_ui(stf, "GPU - VRAM",               "🎮", "#ea580c",     3, 1, "gpu_vram")
        make_stress_card_ui(stf, "GPU - Combined",           "🔥", ACCENT_STRESS, 4, 0, "gpu_combined", colspan=2)
        tk.Frame(stf, bg=BG, height=16).grid(row=5, column=0, columnspan=2)

        stress_status = stress_status_label if app_mode == "both" else status_label
        stress_win_alive = [True]

        if app_mode == "both":
            def on_stress_win_close():
                stress_win_alive[0] = False
                stress_win.destroy()

            stress_win.protocol("WM_DELETE_WINDOW", on_stress_win_close)

        def process_log_queue():
            if not stress_win_alive[0]:
                return
            for card_id, msg in stress_manager.drain_logs(max_items=20):
                lb = stress_log_boxes.get(card_id)
                if lb:
                    lb.config(state="normal")
                    lb.insert("end", f"{msg}\n")
                    lb.see("end")
                    lb.config(state="disabled")
            root.after(250, process_log_queue)

        def update_stress_temps():
            if not stress_win_alive[0]:
                return
            try:
                cpu_t = bridge.get_cpu_temp()
                gpu_t = bridge.get_primary_gpu_temp()
                if cpu_t is not None or gpu_t is not None:
                    stress_status.config(text="Live", fg="#00ff88")
                else:
                    stress_status.config(text="Offline - LHMBridge not running", fg="#ff4444")
                graph_cpu_temps.append(cpu_t)
                graph_gpu_temps.append(gpu_t)
                draw_graph_on(g_canvas2, 130)
            except tk.TclError:
                stress_win_alive[0] = False
                return

            root.after(1000, update_stress_temps)

        update_stress_temps()
        process_log_queue()

    root.mainloop()

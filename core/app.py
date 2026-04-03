# app.py — HardwareToad v0.7.4 Beta  (unified tabbed UI)
import collections
import ctypes
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk
import psutil

from .bridge import BridgeManager, get_bridge_token
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
    BORDER,
)
from .formatting import (
    badge_for_temp, badge_live,
    big_stat,
    clock_color,
    divider as fmt_divider,
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
    # bridge.start() is now called inside the splash screen thread
    # so the progress bar reflects real LHM init progress
    stress_manager = StressManager(log_queue)

    # ── Font system ───────────────────────────────────────────────────────────
    _FONT_KEY = r"Software\HardwareToad"
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
        try:
            all_fonts = sorted(set(tkfont.families()))
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
        "MSI Dragon (Default)": {
            "bg": "#0a0a0a", "card": "#121212", "border": "#1e1e1e",
            "graph_bg": "#0e0e0e",
            "accent_cpu": "#e63946", "accent_gpu": "#e63946",
            "accent_ram": "#e63946", "accent_fan": "#e63946",
            "accent_net": "#e63946", "accent_sys": "#e63946",
            "accent_disk": "#e63946", "accent_stress": "#e63946",
            "col_cpu": "#e63946", "col_gpu": "#e63946",
        },
        "Dark Blue": {
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

    _THEME_KEY = r"Software\HardwareToad"

    def _load_theme_name():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY)
            val, _ = winreg.QueryValueEx(key, "UITheme")
            winreg.CloseKey(key)
            return val if val in THEMES else "MSI Dragon (Default)"
        except Exception:
            return "MSI Dragon (Default)"

    def _save_theme_name(name):
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _THEME_KEY)
            winreg.SetValueEx(key, "UITheme", 0, winreg.REG_SZ, name)
            winreg.CloseKey(key)
        except Exception:
            pass

    current_theme_name = [_load_theme_name()]

    # ── Window size registry ──────────────────────────────────────────────────
    _WIN_SIZE_KEY = r"Software\HardwareToad"

    def _load_window_size():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_SIZE_KEY)
            val, _ = winreg.QueryValueEx(key, "WindowSize")
            winreg.CloseKey(key)
            parts = val.lower().split("x")
            if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                return val
        except Exception:
            pass
        return None

    def _save_window_size(size_str):
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _WIN_SIZE_KEY)
            winreg.SetValueEx(key, "WindowSize", 0, winreg.REG_SZ, size_str)
            winreg.CloseKey(key)
        except Exception:
            pass

    # ── Color override registry helpers ───────────────────────────────────────
    _COLOR_KEY = r"Software\HardwareToad\ColorOverrides"

    def _load_color_overrides():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _COLOR_KEY)
            overrides = {}
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                    overrides[name] = val
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
            return overrides
        except Exception:
            return {}

    def _save_color_overrides(overrides):
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _COLOR_KEY)
            try:
                existing_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _COLOR_KEY,
                                              0, winreg.KEY_SET_VALUE | winreg.KEY_READ)
                sub_i = 0
                names_to_delete = []
                while True:
                    try:
                        n, _, _ = winreg.EnumValue(existing_key, sub_i)
                        names_to_delete.append(n)
                        sub_i += 1
                    except OSError:
                        break
                for n in names_to_delete:
                    try:
                        winreg.DeleteValue(existing_key, n)
                    except Exception:
                        pass
                winreg.CloseKey(existing_key)
            except Exception:
                pass
            for k, v in overrides.items():
                winreg.SetValueEx(key, k, 0, winreg.REG_SZ, v)
            winreg.CloseKey(key)
        except Exception:
            pass

    def _clear_color_overrides():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _COLOR_KEY,
                                 0, winreg.KEY_SET_VALUE | winreg.KEY_READ)
            names = []
            i = 0
            while True:
                try:
                    n, _, _ = winreg.EnumValue(key, i)
                    names.append(n)
                    i += 1
                except OSError:
                    break
            for n in names:
                try:
                    winreg.DeleteValue(key, n)
                except Exception:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    _color_overrides = [_load_color_overrides()]

    def _build_effective_theme(theme_name, overrides):
        base = dict(THEMES.get(theme_name, THEMES["MSI Dragon (Default)"]))
        for k, v in overrides.items():
            if k in base:
                base[k] = v
        return base

    def open_settings(parent_win):
        sw = tk.Toplevel(parent_win)
        sw.title("Settings")
        sw.configure(bg=BG)
        sw.resizable(True, True)
        sw.geometry("500x640")
        sw.grab_set()

        body_canvas = tk.Canvas(sw, bg=BG, highlightthickness=0)
        body_sb = tk.Scrollbar(sw, orient="vertical", command=body_canvas.yview)
        body_canvas.configure(yscrollcommand=body_sb.set)

        bf = tk.Frame(sw, bg=BG)
        bf.pack(side="bottom", fill="x", pady=(0, 12))
        tk.Frame(sw, bg="#1e1e1e", height=1).pack(side="bottom", fill="x")

        body_sb.pack(side="right", fill="y")
        body_canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(body_canvas, bg=BG)
        body_win = body_canvas.create_window((0, 0), window=body, anchor="nw")
        body_canvas.bind("<Configure>",
                         lambda e: body_canvas.itemconfig(body_win, width=e.width))
        body.bind("<Configure>",
                  lambda e: body_canvas.configure(scrollregion=body_canvas.bbox("all")))
        sw.bind("<MouseWheel>",
                lambda e: body_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        body.bind("<MouseWheel>",
                  lambda e: body_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        tk.Label(body, text="SETTINGS", fg="white", bg=BG,
                 font=("Segoe UI", 14, "bold")).pack(pady=(20, 4))
        tk.Frame(body, bg="#1e1e1e", height=1).pack(fill="x", padx=20)

        def section_label(text):
            tk.Label(body, text=text, fg="#a0a0a0", bg=BG,
                     font=("Segoe UI", 8, "bold")).pack(
                         anchor="w", padx=28, pady=(14, 2))

        section_label("UI FONT")
        ff = tk.Frame(body, bg=BG)
        ff.pack(fill="x", padx=24, pady=(0, 4))
        font_var = tk.StringVar(value=current_font[0])
        families = _get_font_families()
        font_combo = ttk.Combobox(ff, textvariable=font_var, values=families,
                                  width=28, state="readonly")
        font_combo.pack(side="left")

        section_label("BASE THEME")
        tf = tk.Frame(body, bg=BG)
        tf.pack(fill="x", padx=24, pady=(0, 4))
        theme_var = tk.StringVar(value=current_theme_name[0])
        theme_combo = ttk.Combobox(tf, textvariable=theme_var,
                                   values=list(THEMES.keys()),
                                   width=28, state="readonly")
        theme_combo.pack(side="left")
        tk.Button(tf, text="Reset overrides", bg="#1a1a1a", fg="#888888",
                  font=("Segoe UI", 8), relief="flat", padx=8, pady=2,
                  cursor="hand2",
                  command=lambda: _on_reset_overrides()).pack(side="left", padx=(10, 0))

        section_label("WINDOW SIZE")
        _PRESET_SIZES = ["Default","1280x720","1280x800","1366x768","1440x900",
                         "1600x900","1920x1080","2560x1080","2560x1440","3840x2160","Custom"]

        saved_size = _load_window_size()
        _initial_preset = (saved_size if saved_size in _PRESET_SIZES
                           else ("Custom" if saved_size else "Default"))

        wf = tk.Frame(body, bg=BG)
        wf.pack(fill="x", padx=24, pady=(0, 4))
        size_preset_var = tk.StringVar(value=_initial_preset)
        size_combo = ttk.Combobox(wf, textvariable=size_preset_var,
                                  values=_PRESET_SIZES, width=16, state="readonly")
        size_combo.pack(side="left")

        custom_frame = tk.Frame(body, bg=BG)
        _cw_default, _ch_default = "", ""
        if saved_size and _initial_preset == "Custom":
            _parts = saved_size.lower().split("x")
            if len(_parts) == 2:
                _cw_default, _ch_default = _parts[0].strip(), _parts[1].strip()

        custom_w_var = tk.StringVar(value=_cw_default)
        custom_h_var = tk.StringVar(value=_ch_default)

        def _only_digits(val):
            return val == "" or val.isdigit()
        vcmd = sw.register(_only_digits)

        tk.Label(custom_frame, text="W:", fg="#a0a0a0", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left", padx=(32, 2))
        tk.Entry(custom_frame, textvariable=custom_w_var, width=6,
                 bg="#1a1a1a", fg="white", insertbackground="white",
                 relief="flat", font=("Segoe UI", 10),
                 validate="key", validatecommand=(vcmd, "%P")).pack(side="left")
        tk.Label(custom_frame, text="H:", fg="#a0a0a0", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 2))
        tk.Entry(custom_frame, textvariable=custom_h_var, width=6,
                 bg="#1a1a1a", fg="white", insertbackground="white",
                 relief="flat", font=("Segoe UI", 10),
                 validate="key", validatecommand=(vcmd, "%P")).pack(side="left")
        tk.Label(custom_frame, text="px", fg="#555555", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        def _on_preset_change(e=None):
            if size_preset_var.get() == "Custom":
                custom_frame.pack(fill="x", pady=(2, 4))
            else:
                custom_frame.pack_forget()

        size_combo.bind("<<ComboboxSelected>>", _on_preset_change)
        if _initial_preset == "Custom":
            custom_frame.pack(fill="x", pady=(2, 4))

        section_label("PREVIEW")
        swatch_frame = tk.Frame(body, bg=BG)
        swatch_frame.pack(fill="x", padx=24, pady=(0, 4))

        swatch_boxes = []
        for _ in range(8):
            b = tk.Frame(swatch_frame, width=26, height=26)
            b.pack(side="left", padx=2)
            b.pack_propagate(False)
            swatch_boxes.append(b)

        preview_lbl = tk.Label(body, text="Preview: AaBbCc 0123 — HardwareToad",
                               fg="#a0aec0", bg=CARD, font=(current_font[0], 11))
        preview_lbl.pack(fill="x", padx=24, pady=(0, 8))

        _session_overrides = dict(_color_overrides[0])

        def _effective_theme():
            return _build_effective_theme(theme_var.get(), _session_overrides)

        def update_preview(e=None):
            t = _effective_theme()
            f = font_var.get()
            preview_lbl.config(font=(f, 11), bg=t["card"], fg=t["accent_cpu"])
            accents = [t["accent_cpu"], t["accent_gpu"], t["accent_ram"],
                       t["accent_fan"], t["accent_net"], t["accent_sys"],
                       t["accent_disk"], t["accent_stress"]]
            for box, color in zip(swatch_boxes, accents):
                box.config(bg=color)
            for theme_key, btn in _color_btns.items():
                current_color = t.get(theme_key, "#888888")
                btn.config(bg=current_color,
                           fg=_contrast_fg(current_color))

        font_combo.bind("<<ComboboxSelected>>", update_preview)
        theme_combo.bind("<<ComboboxSelected>>", lambda e: _on_theme_change())

        def _on_theme_change():
            _session_overrides.clear()
            update_preview()

        def _on_reset_overrides():
            _session_overrides.clear()
            update_preview()

        tk.Frame(body, bg="#1e1e1e", height=1).pack(fill="x", padx=20, pady=(4, 0))
        section_label("CUSTOMIZE COLORS  —  click any swatch to change")

        _color_btns = {}

        def _contrast_fg(hex_color):
            try:
                h = hex_color.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                luma = 0.299 * r + 0.587 * g + 0.114 * b
                return "#000000" if luma > 140 else "#ffffff"
            except Exception:
                return "#ffffff"

        def _pick_color(theme_key, btn):
            import tkinter.colorchooser as _cc
            current = _session_overrides.get(
                theme_key,
                THEMES.get(theme_var.get(), THEMES["MSI Dragon (Default)"]).get(theme_key, "#888888")
            )
            result = _cc.askcolor(color=current, title=f"Pick color: {theme_key}",
                                  parent=sw)
            if result and result[1]:
                chosen = result[1].lower()
                _session_overrides[theme_key] = chosen
                update_preview()

        def _color_group(label_text, items):
            gl = tk.Label(body, text=label_text, fg="#555555", bg=BG,
                          font=("Segoe UI", 8, "bold"))
            gl.pack(anchor="w", padx=32, pady=(8, 2))
            gf = tk.Frame(body, bg=BG)
            gf.pack(fill="x", padx=28, pady=(0, 4))
            t = _effective_theme()
            for col_idx, (disp, key) in enumerate(items):
                cell = tk.Frame(gf, bg=BG)
                cell.grid(row=0, column=col_idx, padx=4, pady=2, sticky="w")
                tk.Label(cell, text=disp, fg="#a0a0a0", bg=BG,
                         font=("Segoe UI", 8)).pack(anchor="w")
                color = t.get(key, "#888888")
                btn = tk.Button(cell, text="  ", bg=color, fg=_contrast_fg(color),
                                relief="flat", width=6, height=1,
                                cursor="hand2", font=("Segoe UI", 8))
                btn.config(command=lambda k=key, b=btn: _pick_color(k, b))
                btn.pack()
                _color_btns[key] = btn

        _color_group("ACCENTS", [
            ("CPU",    "accent_cpu"),
            ("GPU",    "accent_gpu"),
            ("RAM",    "accent_ram"),
            ("Fan",    "accent_fan"),
            ("Net",    "accent_net"),
            ("System", "accent_sys"),
            ("Disk",   "accent_disk"),
            ("Stress", "accent_stress"),
        ])
        _color_group("GRAPH LINES", [
            ("CPU line",  "col_cpu"),
            ("GPU line",  "col_gpu"),
        ])
        _color_group("BACKGROUNDS", [
            ("Main BG",   "bg"),
            ("Card",      "card"),
            ("Graph BG",  "graph_bg"),
            ("Border",    "border"),
        ])

        err_lbl = tk.Label(bf, text="", fg="#ef4444", bg=BG, font=("Segoe UI", 9))
        err_lbl.pack(pady=(4, 0))

        def apply():
            current_font[0] = font_var.get()
            current_theme_name[0] = theme_var.get()
            _save_font(current_font[0])
            _save_theme_name(current_theme_name[0])

            _color_overrides[0] = dict(_session_overrides)
            if _session_overrides:
                _save_color_overrides(_session_overrides)
            else:
                _clear_color_overrides()

            preset = size_preset_var.get()
            new_geom = None
            if preset == "Default":
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_SIZE_KEY,
                                        0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, "WindowSize")
                    winreg.CloseKey(key)
                except Exception:
                    pass
            elif preset == "Custom":
                cw = custom_w_var.get().strip()
                ch = custom_h_var.get().strip()
                if cw.isdigit() and ch.isdigit() and int(cw) >= 400 and int(ch) >= 300:
                    size_str = f"{cw}x{ch}"
                    _save_window_size(size_str)
                    new_geom = size_str
                else:
                    err_lbl.config(text="⚠ Custom size invalid (min 400×300)")
                    return
            else:
                _save_window_size(preset)
                new_geom = preset

            if new_geom:
                try:
                    parent_win.geometry(new_geom)
                except Exception:
                    pass

            sw.destroy()
            info = tk.Toplevel(parent_win)
            info.configure(bg=BG)
            info.title("")
            info.resizable(False, False)
            info.geometry("320x110")
            tk.Label(info, text="Settings saved!", fg="white", bg=BG,
                     font=("Segoe UI", 12, "bold")).pack(pady=(24, 4))
            tk.Label(info, text="Restart the app to apply all changes.", fg="#a0a0a0", bg=BG,
                     font=("Segoe UI", 9)).pack()
            tk.Button(info, text="OK", bg=ACCENT_CPU, fg="white",
                      font=("Segoe UI", 10, "bold"), relief="flat",
                      padx=20, pady=6, cursor="hand2",
                      command=info.destroy).pack(pady=(12, 0))

        tk.Button(bf, text="Apply & Save", bg=ACCENT_CPU, fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=apply).pack(side="left", padx=(24, 6))
        tk.Button(bf, text="Cancel", bg="#0f0f0f", fg="#888888",
                  font=("Segoe UI", 10), relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  command=sw.destroy).pack(side="left", padx=6)

        update_preview()

    # ── Raw Sensors Window ────────────────────────────────────────────────────
    _raw_win = [None]

    def open_raw_sensors(parent_win):
        if _raw_win[0] and _raw_win[0].winfo_exists():
            _raw_win[0].lift()
            return

        rw = tk.Toplevel(parent_win)
        _raw_win[0] = rw
        rw.title(f"HardwareToad {APP_VERSION} - Raw Sensors")
        rw.geometry("1000x660")
        rw.configure(bg=BG)
        rw.resizable(True, True)

        _UNITS = {
            "temperature": "°C", "load": "%", "clock": "MHz",
            "fan": "RPM", "control": "%", "voltage": "V",
            "power": "W", "current": "A", "data": "GB",
            "smalldata": "MB", "throughput": "MB/s", "level": "%",
            "factor": "×", "noise": "dB",
        }
        _SANE = {
            "temperature": (1,     110),
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
            return "normal"

        hdr = tk.Frame(rw, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(10, 4))
        tk.Label(hdr, text="◈  Raw Sensors", fg="#a0aec0", bg=BG,
                 font=(current_font[0], 12, "bold")).pack(side="left")
        raw_count = tk.Label(hdr, text="", fg="#555555", bg=BG,
                             font=(current_font[0], 9))
        raw_count.pack(side="left", padx=(12, 0))
        raw_status = tk.Label(hdr, text="Connecting...", fg="#555", bg=BG,
                              font=(current_font[0], 9))
        raw_status.pack(side="right")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Raw.Treeview",
                        background="#111111", foreground="#cccccc",
                        fieldbackground="#111111", rowheight=24,
                        font=(current_font[0], 9))
        style.configure("Raw.Treeview.Heading",
                        background="#1a1a1a", foreground="#aaaaaa",
                        font=(current_font[0], 9, "bold"), relief="flat")
        style.map("Raw.Treeview",
                  background=[("selected", "#1a0a0a")],
                  foreground=[("selected", "white")])

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

        tree.tag_configure("odd",    background="#0e0e0e")
        tree.tag_configure("even",   background=CARD)
        tree.tag_configure("hw",     background="#150a0a", foreground="#e63946",
                           font=(current_font[0], 9, "bold"))
        tree.tag_configure("hot",    foreground="#ef4444")
        tree.tag_configure("warm",   foreground="#f59e0b")
        tree.tag_configure("ok",     foreground="#22c55e")
        tree.tag_configure("normal", foreground="#a0aec0")
        tree.tag_configure("dim",    foreground="#555555")

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

                    if _is_sane(val, stype):
                        if uid in _sensor_minmax:
                            prev_min, prev_max, prev_avg, prev_n = _sensor_minmax[uid]
                            if prev_avg > 0 and val > prev_avg * 3:
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

    # ── Load static system info ───────────────────────────────────────────────
    static_info = load_static_system_info()
    cpu_name   = static_info["cpu_name"]
    ram_info   = static_info["ram_info"]
    all_disks  = static_info["all_disks"]
    win_ver    = static_info["windows_version"]
    win_ver_name = static_info.get("windows_ver_name", "")
    win_build  = static_info.get("windows_build", "")
    gpu_driver = static_info.get("gpu_driver", "N/A")

    _letter_to_disk = {}
    try:
        import wmi as _wmi
        for disk in _wmi.WMI().Win32_DiskDrive():
            idx = int(disk.Index or 0)
            for part in disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical in part.associators("Win32_LogicalDiskToPartition"):
                    letter = (logical.DeviceID or "").strip().upper()
                    _letter_to_disk[letter] = idx
    except Exception:
        _letter_to_disk = {}

    graph_cpu_temps  = collections.deque(maxlen=GRAPH_SECONDS)
    graph_gpu_temps  = collections.deque(maxlen=GRAPH_SECONDS)
    graph_gpu_series = {}
    GPU_TEMP_COLORS  = {}

    RING_SIZE  = 150
    RING_WIDTH = 11
    RING_TRACK = (40, 40, 40, 255)
    RING_SCALE = 4

    def _hex_to_rgba(h):
        h = h.lstrip("#")
        return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255)

    _ring_cache = {}

    def draw_ring(canvas, value, label, accent, card_bg,
                  size=None, max_val=100, unit="%"):
        cache_key = id(canvas)
        last = _ring_cache.get(cache_key)
        rounded = round(value, 0) if value is not None else None
        if last == (rounded, accent, label):
            return
        _ring_cache[cache_key] = (rounded, accent, label)

        if size is None:
            size = RING_SIZE
        s  = size * RING_SCALE
        rw = RING_WIDTH * RING_SCALE
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        m   = rw + RING_SCALE * 2
        box = [m, m, s - m, s - m]

        d.arc(box, start=0, end=359.9, fill=RING_TRACK, width=rw)

        if value is not None and value > 0:
            frac = min(value / max_val, 1.0)
            col  = _hex_to_rgba(accent) if isinstance(accent, str) else accent
            d.arc(box, start=-90, end=-90 + frac * 359.9, fill=col, width=rw)

        img = img.resize((size, size), Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas._ring_photo = photo
        canvas.create_image(size // 2, size // 2, image=photo)

        cx = cy = size // 2
        if value is not None:
            canvas.create_text(cx, cy - 11, text=f"{value:.0f}",
                               fill=accent if isinstance(accent, str) else "#888",
                               font=("Segoe UI", 21, "bold"), anchor="center")
            canvas.create_text(cx, cy + 8, text=unit,
                               fill="#a0a0a0", font=("Segoe UI", 9, "bold"), anchor="center")
        else:
            canvas.create_text(cx, cy, text="N/A",
                               fill="#666666", font=("Segoe UI", 11, "bold"), anchor="center")
        canvas.create_text(cx, cy + 23, text=label,
                           fill="#a0a0a0", font=("Segoe UI", 8, "bold"),
                           anchor="center")

    def make_dual_rings(parent, accent_load, accent_temp, card_bg):
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
        draw_multi_graph(canvas, [(data, color)], height)

    def draw_multi_graph(canvas, series_list, height):
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
            canvas.create_line(pad_l, y, w-pad_r, y, fill="#282828", dash=(3,4))
            canvas.create_text(pad_l-4, y, text=f"{tv}°",
                               fill="#707070", font=("Segoe UI", 7), anchor="e")
        for i in [0, 30, 60]:
            x = pad_l + plot_w * (i / 60)
            canvas.create_text(x, height-pad_b+8,
                               text=f"-{60-i}s" if i < 60 else "now",
                               fill="#707070", font=("Segoe UI", 7))
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

    # ══════════════════════════════════════════════════════════════════════════
    # RESOLVE THEME — apply saved overrides
    # ══════════════════════════════════════════════════════════════════════════
    _startup_theme = _build_effective_theme(current_theme_name[0], _color_overrides[0])
    _t = _resolve_theme(_startup_theme)
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
    GPU_TEMP_COLORS = {"Core": "#e63946", "Hotspot": "#ff6b6b", "VRAM": "#cc2233"}

    BLOCK_BG = CARD
    RS = 150

    # ══════════════════════════════════════════════════════════════════════════
    # SPLASH SCREEN — bridge starts in background thread, progress bar is real
    # ══════════════════════════════════════════════════════════════════════════
    _splash = tk.Tk()
    _splash.overrideredirect(True)
    _splash.configure(bg="#0a0a0a")
    _splash.resizable(False, False)

    _SW, _SH = 420, 300
    _splash.geometry(
        f"{_SW}x{_SH}+"
        f"{(_splash.winfo_screenwidth()  - _SW) // 2}+"
        f"{(_splash.winfo_screenheight() - _SH) // 2}"
    )
    _splash.attributes("-topmost", True)

    # Red top accent line
    tk.Frame(_splash, bg="#e63946", height=3).pack(fill="x")

    # Main body
    _body = tk.Frame(_splash, bg="#0a0a0a")
    _body.pack(fill="both", expand=True, padx=2, pady=(0, 2))

    # ── Robot Toad logo (base64-embedded PNG, no external file needed) ─────
    import base64, io
    _LOGO_B64 = (
        "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"
    )
    try:
        _logo_data = base64.b64decode(_LOGO_B64)
        _logo_pil  = Image.open(io.BytesIO(_logo_data))
        _logo_pil.load()  # force full decode before resize
        _logo_pil  = _logo_pil.convert("RGBA")
        _logo_pil  = _logo_pil.resize((96, 96), Image.LANCZOS)
        _logo_photo = ImageTk.PhotoImage(_logo_pil)
        _logo_lbl = tk.Label(_body, image=_logo_photo, bg="#0a0a0a")
        _logo_lbl.image = _logo_photo  # prevent GC
        _logo_lbl.pack(pady=(12, 4))
    except Exception as _logo_err:
        print(f"[Splash] Logo failed: {_logo_err}")  # debug — shows in console

    # App name row
    _name_row = tk.Frame(_body, bg="#0a0a0a")
    _name_row.pack(expand=True)
    tk.Label(_name_row, text="Hardware", fg="white",   bg="#0a0a0a",
             font=("Segoe UI", 28, "bold")).pack(side="left")
    tk.Label(_name_row, text="Toad", fg="#e63946", bg="#0a0a0a",
             font=("Segoe UI", 28, "bold")).pack(side="left")

    # Version badge
    tk.Label(_body, text=APP_VERSION, fg="#555555", bg="#0a0a0a",
             font=("Segoe UI", 9)).pack()

    # Thin divider
    tk.Frame(_body, bg="#1e1e1e", height=1).pack(fill="x", padx=32, pady=(14, 10))

    # Credits row
    _cred_row = tk.Frame(_body, bg="#0a0a0a")
    _cred_row.pack()
    tk.Label(_cred_row, text="Developers: ", fg="#555555", bg="#0a0a0a",
             font=("Segoe UI", 8)).pack(side="left")
    tk.Label(_cred_row, text="ToadJo", fg="#e63946", bg="#0a0a0a",
             font=("Segoe UI", 8, "bold")).pack(side="left")
    tk.Label(_cred_row, text=",", fg="#555555", bg="#0a0a0a",
             font=("Segoe UI", 8)).pack(side="left")
    tk.Label(_cred_row, text=" Manos2400", fg="#e63946", bg="#0a0a0a",
             font=("Segoe UI", 8, "bold")).pack(side="left")
    tk.Label(_cred_row, text="   ·   Est. 2026", fg="#333333", bg="#0a0a0a",
             font=("Segoe UI", 8)).pack(side="left")

    # Status label
    tk.Frame(_body, bg="#0a0a0a", height=8).pack()
    _status_lbl = tk.Label(_body, text="Starting...", fg="#555555",
                           bg="#0a0a0a", font=("Segoe UI", 8))
    _status_lbl.pack()

    # ── Progress bar ──────────────────────────────────────────────────────────
    tk.Frame(_body, bg="#0a0a0a", height=6).pack()
    _bar_bg = tk.Frame(_body, bg="#1a1a1a", height=4)
    _bar_bg.pack(fill="x", padx=32)
    _bar_bg.update_idletasks()
    _bar_fill = tk.Frame(_bar_bg, bg="#40c057", height=4, width=0)
    _bar_fill.place(x=0, y=0, relheight=1.0, width=0)

    _progress    = [0.0]
    _bar_width   = [_SW - 64]

    def _on_bar_configure(e):
        _bar_width[0] = max(e.width, 1)
    _bar_bg.bind("<Configure>", _on_bar_configure)

    def _set_progress(pct: float, msg: str = ""):
        """Schedule a progress update on the tkinter main thread."""
        _progress[0] = max(_progress[0], min(float(pct), 1.0))
        _p = _progress[0]
        _m = msg
        def _apply():
            try:
                w = int(_bar_width[0] * _p)
                _bar_fill.place(x=0, y=0, relheight=1.0, width=max(w, 0))
                if _m:
                    _status_lbl.config(text=_m)
            except Exception:
                pass
        try:
            _splash.after(0, _apply)
        except Exception:
            pass

    # Thin red bottom accent
    tk.Frame(_splash, bg="#e63946", height=2).pack(fill="x", side="bottom")

    # ── Bridge start runs in a background thread ──────────────────────────────
    # The splash closes itself when the bridge has data (or times out).
    # Progress milestones:
    #   5%  → process launched
    #  20%  → process started, waiting for /ready
    #  50%  → /ready received (LHM initialized ring0 drivers)
    #  90%  → first sensor data arrived
    # 100%  → done, splash closes after 400ms
    import threading as _threading

    def _do_wait_sensors():
        """Poll /sensors until CPU temp data arrives (max 10s). Updates bridge data."""
        for attempt in range(40):
            time.sleep(0.25)
            pct = 0.50 + (attempt / 40) * 0.48
            _set_progress(pct)
            try:
                r = urllib.request.urlopen(
                    f"http://127.0.0.1:{bridge.port}/sensors", timeout=2)
                data = json.loads(r.read())
                has_cpu = any(
                    "cpu" in k.lower() and
                    any(s.get("Type", "").lower() == "temperature" for s in v)
                    for k, v in data.items()
                )
                if has_cpu:
                    # Got real CPU temp data — close immediately
                    with bridge._lock:
                        bridge._bridge_data = data
                    return
                elif len(data) > 2 and attempt >= 28:
                    # Timed out waiting for CPU temps — use whatever we have
                    with bridge._lock:
                        bridge._bridge_data = data
                    return
            except Exception:
                pass

    def _finish_splash():
        _set_progress(1.0, "Ready")
        try:
            _splash.after(400, _splash.destroy)
        except Exception:
            pass

    def _bridge_start_thread():
        try:
            import ctypes as _ct
            import subprocess as _sp

            def _is_admin_local():
                try:
                    return bool(_ct.windll.shell32.IsUserAnAdmin())
                except Exception:
                    return False

            # ── Phase 1: check if bridge is already up (dev.bat pre-launches it) ─
            # dev.bat waits for /ready before starting Python, so in 99% of cases
            # the bridge is already running. Just do a quick multi-attempt check
            # (a few retries in case of tiny timing gap) then move on fast.
            _set_progress(0.05, "Initializing sensors...")
            for i in range(8):             # 8 × 0.25s = 2s max quick check
                time.sleep(0.25)
                _set_progress(0.05 + (i / 8) * 0.45)
                try:
                    r = urllib.request.urlopen(
                        f"http://127.0.0.1:{bridge.port}/ready", timeout=1)
                    if r.read().decode() == "true":
                        _set_progress(0.50, "Loading sensor data...")
                        _do_wait_sensors()
                        _finish_splash()
                        return
                except Exception:
                    pass

            # ── Phase 1b: bridge not up yet — poll for up to 20s more ────────
            # Fallback for when app is launched without dev.bat or bridge is slow.
            for i in range(80):            # 80 × 0.25s = 20s
                time.sleep(0.25)
                _set_progress(0.05 + (i / 80) * 0.45)
                try:
                    r = urllib.request.urlopen(
                        f"http://127.0.0.1:{bridge.port}/ready", timeout=1)
                    if r.read().decode() == "true":
                        _set_progress(0.50, "Loading sensor data...")
                        _do_wait_sensors()
                        _finish_splash()
                        return
                except Exception:
                    pass

            # ── Phase 2: bridge not started by dev.bat — launch it ourselves ─
            _set_progress(0.20, "Launching sensor bridge...")
            path = bridge._get_bridge_path()
            if path:
                if _is_admin_local():
                    si, cf = bridge._windows_startup_info()
                    try:
                        bridge._bridge_proc = _sp.Popen(
                            [path, f"--port={bridge.port}"],
                            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                            startupinfo=si, creationflags=cf,
                        )
                    except Exception:
                        pass
                else:
                    bridge._launch_bridge_elevated(path)

                # Wait for /ready after self-launch (another 15s)
                for i in range(60):
                    time.sleep(0.25)
                    _set_progress(0.20 + (i / 60) * 0.30)
                    try:
                        r = urllib.request.urlopen(
                            f"http://127.0.0.1:{bridge.port}/ready", timeout=1)
                        if r.read().decode() == "true":
                            break
                    except Exception:
                        pass

            _set_progress(0.50, "Loading sensor data...")
            _do_wait_sensors()
            _finish_splash()

        except Exception:
            _finish_splash()

    _t = _threading.Thread(target=_bridge_start_thread, daemon=True)
    _t.start()
    _splash.mainloop()
    # Wait for bridge thread to finish — ensures bridge._bridge_data is populated
    # before the main window's first update_sensors() call runs.
    _t.join(timeout=30)

    # ══════════════════════════════════════════════════════════════════════════
    # MAIN WINDOW — single window, MSI Center style with top tabs
    # ══════════════════════════════════════════════════════════════════════════
    root = tk.Tk()
    root.title(f"HardwareToad {APP_VERSION}")

    # ── Window / taskbar / title bar icon ─────────────────────────────────────
    def _apply_icon():
        try:
            import base64 as _b64, io as _io
            _icon_rgba = Image.open(_io.BytesIO(_b64.b64decode(_LOGO_B64))).convert("RGBA")
            # Crop transparent padding so the toad fills the icon frame
            bbox = _icon_rgba.getbbox()
            if bbox:
                _icon_rgba = _icon_rgba.crop(bbox)
            def _make_icon(pil_img, size):
                fg = pil_img.resize((size, size), Image.LANCZOS)
                return ImageTk.PhotoImage(fg)
            _icon_lg = _make_icon(_icon_rgba, 256)
            _icon_md = _make_icon(_icon_rgba, 48)   # taskbar on standard DPI
            _icon_sm = _make_icon(_icon_rgba, 32)   # title bar
            root.iconphoto(True, _icon_lg, _icon_md, _icon_sm)
            root._icon_lg = _icon_lg
            root._icon_md = _icon_md
            root._icon_sm = _icon_sm
            print("[Icon] iconphoto applied OK")
        except Exception as _icon_err:
            import traceback
            print(f"[Icon] FAILED: {_icon_err}")
            traceback.print_exc()
    root.update_idletasks()
    _apply_icon()
    root.after(200, _apply_icon)

    root.configure(bg=BG)
    root.resizable(True, True)
    root.minsize(900, 700)
    root.geometry(_load_window_size() or "1440x960")

    # ── MSI-style header bar ──────────────────────────────────────────────────
    # Top accent line
    tk.Frame(root, bg=ACCENT_CPU, height=3).pack(fill="x")

    header_bar = tk.Frame(root, bg="#0f0f0f")
    header_bar.pack(fill="x")

    # Left: branding
    brand = tk.Frame(header_bar, bg="#0f0f0f")
    brand.pack(side="left", padx=(16, 0), pady=8)
    tk.Label(brand, text="Hardware", fg="white", bg="#0f0f0f",
             font=("Segoe UI", 15, "bold")).pack(side="left")
    tk.Label(brand, text="Toad", fg=ACCENT_CPU, bg="#0f0f0f",
             font=("Segoe UI", 15, "bold")).pack(side="left")

    # Tab buttons — MSI Center style
    tab_frame = tk.Frame(header_bar, bg="#0f0f0f")
    tab_frame.pack(side="left", padx=(32, 0))

    _main_tab_btns = {}
    _main_tab_pages = {}
    _active_tab = [None]

    def _switch_main_tab(name):
        if _active_tab[0] == name:
            return
        for n, page in _main_tab_pages.items():
            page.pack_forget()
        _main_tab_pages[name].pack(fill="both", expand=True)
        _active_tab[0] = name
        for n, btn in _main_tab_btns.items():
            if n == name:
                btn.config(fg="white", bg="#1a1a1a")
            else:
                btn.config(fg="#b0b0b0", bg="#0f0f0f")

    def _make_main_tab_btn(name, label):
        btn = tk.Button(tab_frame, text=label,
                        bg="#0f0f0f", fg="#888888",
                        font=("Segoe UI", 10, "bold"),
                        relief="flat", bd=0, padx=20, pady=10,
                        cursor="hand2",
                        activebackground="#1a1a1a", activeforeground="white",
                        command=lambda n=name: _switch_main_tab(n))
        btn.pack(side="left")
        def _tab_enter(e, b=btn, n=name):
            if n != _active_tab[0]:
                b.config(fg="white", bg="#1a1a1a")
        def _tab_leave(e, b=btn, n=name):
            if n != _active_tab[0]:
                b.config(fg="#888888", bg="#0f0f0f")
        btn.bind("<Enter>", _tab_enter)
        btn.bind("<Leave>", _tab_leave)
        _main_tab_btns[name] = btn

    _make_main_tab_btn("monitor", "Monitor")
    _make_main_tab_btn("stress", "Stress Test")

    # Right: toolbar + status
    toolbar = tk.Frame(header_bar, bg="#0f0f0f")
    toolbar.pack(side="right", padx=(0, 12))

    def _toolbar_btn(text, cmd):
        b = tk.Button(toolbar, text=text, bg="#0f0f0f", fg="#888888",
                      font=("Segoe UI", 8, "bold"), relief="flat",
                      padx=10, pady=4, cursor="hand2", command=cmd,
                      activebackground="#3a3a3a", activeforeground="white",
                      bd=0, highlightthickness=0)
        b.pack(side="right", padx=(4, 0))
        b.bind("<Enter>", lambda e: b.config(fg="white", bg="#1a1a1a"))
        b.bind("<Leave>", lambda e: b.config(fg="#888888", bg="#0f0f0f"))
        return b

    _toolbar_btn("⚙  Settings",    lambda: open_settings(root))
    _toolbar_btn("◈  Raw Sensors", lambda: open_raw_sensors(root))

    # Bottom separator
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

    # ── Main content area ─────────────────────────────────────────────────────
    # ── Update notification banner (hidden until update found) ──────────────
    _update_bar = tk.Frame(root, bg="#1a3a1a", pady=4)
    _update_lbl = tk.Label(_update_bar, text="", fg="#40c057", bg="#1a3a1a",
                           font=("Segoe UI", 9), cursor="hand2")
    _update_lbl.pack(side="left", padx=12)
    tk.Label(_update_bar, text="✕", fg="#40c057", bg="#1a3a1a",
             font=("Segoe UI", 9), cursor="hand2").pack(side="right", padx=8)
    _update_bar.pack_slaves()  # don't show yet

    def _check_for_updates():
        import threading as _ut
        import json as _uj
        import urllib.request as _ur
        def _fetch():
            try:
                url = "https://raw.githubusercontent.com/toadjo/HardwareToad/main/version.json"
                r = _ur.urlopen(url, timeout=5)
                data = _uj.loads(r.read())
                remote = data.get("version", "")
                local  = APP_VERSION.replace("v","").replace(" Beta","").strip()
                remote_clean = remote.replace("v","").replace(" Beta","").strip()
                def _parse(v):
                    try: return tuple(int(x) for x in v.split("."))
                    except: return (0,)
                if _parse(remote_clean) > _parse(local):
                    dl_url = data.get("download_url", "https://github.com/toadjo/HardwareToad/releases/latest")
                    log    = data.get("changelog", "")
                    def _show():
                        try:
                            msg = f"  ↑  New version v{remote_clean} available"
                            if log: msg += f"  —  {log}"
                            msg += "   Click to download"
                            _update_lbl.config(text=msg)
                            _update_bar.pack(fill="x", before=content_area)
                            def _open(e=None):
                                import webbrowser
                                webbrowser.open(dl_url)
                            _update_lbl.bind("<Button-1>", _open)
                            # ✕ to dismiss
                            for w in _update_bar.winfo_children():
                                if w.cget("text") == "✕":
                                    w.bind("<Button-1>", lambda e: _update_bar.pack_forget())
                        except Exception:
                            pass
                    root.after(0, _show)
            except Exception:
                pass
        _ut.Thread(target=_fetch, daemon=True).start()

    root.after(3000, _check_for_updates)  # check 3s after startup

    content_area = tk.Frame(root, bg=BG)
    content_area.pack(fill="both", expand=True)

    # Create pages for each tab
    monitor_page = tk.Frame(content_area, bg=BG)
    stress_page  = tk.Frame(content_area, bg=BG)
    _main_tab_pages["monitor"] = monitor_page
    _main_tab_pages["stress"]  = stress_page

    # ══════════════════════════════════════════════════════════════════════════
    # MONITOR TAB — sensors left, info right (like MSI Center)
    # ══════════════════════════════════════════════════════════════════════════

    # Split: left (sensors with rings/graphs) | right (info panel)
    monitor_split = tk.Frame(monitor_page, bg=BG)
    monitor_split.pack(fill="both", expand=True)

    # Left pane — scrollable sensors
    left_pane = tk.Frame(monitor_split, bg=BG)
    left_pane.pack(side="left", fill="both", expand=True)

    s_canvas = tk.Canvas(left_pane, bg=BG, highlightthickness=0)
    s_sb = tk.Scrollbar(left_pane, orient="vertical", command=s_canvas.yview)
    s_canvas.configure(yscrollcommand=s_sb.set)
    s_sb.pack(side="right", fill="y")
    s_canvas.pack(side="left", fill="both", expand=True)

    sf = tk.Frame(s_canvas, bg=BG)
    sf_window = s_canvas.create_window((0, 0), window=sf, anchor="nw")
    _last_bbox = [None]

    def _sync_scrollregion():
        bbox = s_canvas.bbox("all")
        if bbox and bbox != _last_bbox[0]:
            _last_bbox[0] = bbox
            pos = s_canvas.yview()[0]
            s_canvas.configure(scrollregion=bbox)
            if pos > 0:
                s_canvas.yview_moveto(pos)
        s_canvas.after(500, _sync_scrollregion)

    sf.bind("<Configure>", lambda e: None)
    s_canvas.bind("<Configure>", lambda e: s_canvas.itemconfig(sf_window, width=e.width))
    def _left_scroll(e):
        s_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    left_pane.bind("<MouseWheel>", _left_scroll)
    s_canvas.bind("<MouseWheel>", _left_scroll)
    sf.bind("<MouseWheel>", _left_scroll)
    s_canvas.after(500, _sync_scrollregion)

    sf.columnconfigure(0, weight=1)
    sf.rowconfigure(0, weight=1)

    # ── Right pane — info panel (scrollable) ──────────────────────────────────
    # Thin separator
    tk.Frame(monitor_split, bg=BORDER, width=1).pack(side="left", fill="y")

    right_pane = tk.Frame(monitor_split, bg=BG, width=340)
    right_pane.pack(side="left", fill="y")
    right_pane.pack_propagate(False)

    iw_canvas = tk.Canvas(right_pane, bg=BG, highlightthickness=0)
    iw_sb = tk.Scrollbar(right_pane, orient="vertical", command=iw_canvas.yview)
    iw_canvas.configure(yscrollcommand=iw_sb.set)
    iw_sb.pack(side="right", fill="y")
    iw_canvas.pack(side="left", fill="both", expand=True)
    right = tk.Frame(iw_canvas, bg=BG)
    iw_win_id = iw_canvas.create_window((0, 0), window=right, anchor="nw")
    iw_canvas.bind("<Configure>", lambda e: iw_canvas.itemconfig(iw_win_id, width=e.width))

    def _iw_sync_scrollregion():
        bbox = iw_canvas.bbox("all")
        if bbox:
            iw_canvas.configure(scrollregion=bbox)
        iw_canvas.after(500, _iw_sync_scrollregion)

    iw_canvas.after(600, _iw_sync_scrollregion)
    def _iw_scroll(e):
        iw_canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        return "break"
    iw_canvas.bind("<MouseWheel>", _iw_scroll)
    right_pane.bind("<MouseWheel>", _iw_scroll)
    right.bind("<MouseWheel>", _iw_scroll)

    def _bind_mousewheel_recursive(widget):
        widget.bind("<MouseWheel>", _iw_scroll)
        for child in widget.winfo_children():
            _bind_mousewheel_recursive(child)

    root.after(500, lambda: _bind_mousewheel_recursive(right))

    # ── Sensor block helpers ──────────────────────────────────────────────────
    left = tk.Frame(sf, bg=BG)
    left.grid(row=0, column=0, sticky="nsew")

    def comp_block(parent):
        outer = tk.Frame(parent, bg=ACCENT_CPU)
        outer.pack(fill="x", pady=(0, 2))
        inner = tk.Frame(outer, bg=BLOCK_BG, padx=24, pady=16)
        inner.pack(fill="x", padx=(3, 0))
        return inner

    def comp_title(parent, icon, title, subtitle, accent=None):
        hf = tk.Frame(parent, bg=BLOCK_BG)
        hf.pack(fill="x", pady=(0, 10))
        tk.Label(hf, text="●", fg=ACCENT_CPU, bg=BLOCK_BG,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        tk.Label(hf, text=title.upper(), fg="white", bg=BLOCK_BG,
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        if subtitle:
            disp = subtitle
            tk.Label(hf, text=f"  {disp}", fg="#b0b0b0", bg=BLOCK_BG,
                     font=("Segoe UI", 9)).pack(side="left", pady=(2, 0))

    def ring_pair(parent, bg=None):
        if bg is None: bg = BLOCK_BG
        f = tk.Frame(parent, bg=bg)
        f.pack(anchor="w", pady=(0, 8))
        cl = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
        cl.pack(side="left", padx=24)
        cr = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
        cr.pack(side="left", padx=24)
        return cl, cr

    def single_ring(parent, bg=None):
        if bg is None: bg = BLOCK_BG
        f = tk.Frame(parent, bg=bg)
        f.pack(anchor="w", pady=(0, 8))
        c = tk.Canvas(f, width=RS, height=RS, bg=bg, highlightthickness=0)
        c.pack(padx=24)
        return c

    def stat_strip(parent, specs, bg=None):
        if bg is None: bg = BLOCK_BG
        f = tk.Frame(parent, bg=bg)
        f.pack(anchor="w", pady=(4, 0))
        labels = []
        for lbl, accent in specs:
            col = tk.Frame(f, bg=bg)
            col.pack(side="left", padx=14)
            tk.Label(col, text=lbl, fg="#a0a0a0", bg=bg,
                     font=("Segoe UI", 8, "bold")).pack()
            v = tk.Label(col, text="--", fg=accent, bg=bg,
                         font=("Segoe UI", 14, "bold"))
            v.pack()
            v._stat_col = col
            labels.append(v)
        return labels

    # ── CPU Block ─────────────────────────────────────────────────────────────
    cpu_block = comp_block(left)
    comp_title(cpu_block, "🖥", "CPU", cpu_name, ACCENT_CPU)
    cpu_row = tk.Frame(cpu_block, bg=BLOCK_BG)
    cpu_row.pack(fill="x")

    cpu_rings_col = tk.Frame(cpu_row, bg=BLOCK_BG)
    cpu_rings_col.pack(side="left")
    cpu_ring_load, cpu_ring_temp = ring_pair(cpu_rings_col)
    cpu_stats_f = tk.Frame(cpu_rings_col, bg=BLOCK_BG)
    cpu_stats_f.pack(anchor="w", pady=(4, 0))
    cpu_clock_lbl, cpu_power_lbl, cpu_voltage_lbl = stat_strip(cpu_stats_f, [
        ("CLOCK",   "#cccccc"),
        ("POWER",   "#cccccc"),
        ("VOLTAGE", "#cccccc"),
    ])
    cpu_diag_lbl = tk.Label(cpu_rings_col, text="", fg="#ff6b6b", bg=BLOCK_BG,
                            font=("Segoe UI", 8), wraplength=300)
    # Don't pack yet — only shown when there's a message

    cpu_graph_col = tk.Frame(cpu_row, bg=BLOCK_BG)
    cpu_graph_col.pack(side="left", fill="both", expand=True, padx=(16, 0))
    tk.Label(cpu_graph_col, text="● CPU TEMP", fg=ACCENT_CPU, bg=BLOCK_BG,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
    cpu_graph_canvas = tk.Canvas(cpu_graph_col, bg=GRAPH_BG, height=85,
                                 highlightthickness=1, highlightbackground=BORDER)
    cpu_graph_canvas.pack(fill="x", pady=(0, 8))
    # No <Configure> bind — graph redraws every 2s via update_sensors
    # Binding <Configure> caused redraw on every scroll event (artifact)

    # ── GPU Block ─────────────────────────────────────────────────────────────
    gpu_block = tk.Frame(left, bg=BG)
    gpu_block.pack(fill="x", pady=(0, 2))
    gpu_frames      = {}
    gpu_secondary   = []
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
            acc = ACCENT_CPU   # unified accent — same as CPU
            label = "GPU" if len(gpu_list) == 1 else (
                "GPU (dGPU)" if not is_igpu(gpu["name"]) else "GPU (iGPU)")

            if rank == 0:
                gpu_outer = tk.Frame(gpu_block, bg=ACCENT_CPU)
                gpu_outer.pack(fill="x", pady=(0, 2))
                blk = tk.Frame(gpu_outer, bg=BLOCK_BG, padx=24, pady=16)
                blk.pack(fill="x", padx=(3, 0))
                comp_title(blk, "🎮", label, gpu["name"], acc)

                gpu_row_f = tk.Frame(blk, bg=BLOCK_BG)
                gpu_row_f.pack(fill="x")

                gpu_rings_col = tk.Frame(gpu_row_f, bg=BLOCK_BG)
                gpu_rings_col.pack(side="left")
                rl, rt = ring_pair(gpu_rings_col)
                sr1 = tk.Frame(gpu_rings_col, bg=BLOCK_BG)
                sr1.pack(anchor="center", pady=(8, 0))
                gs1 = stat_strip(sr1, [
                    ("CORE CLOCK", "#cccccc"),
                    ("VRAM USED",  "#cccccc"),
                    ("POWER",      "#cccccc"),
                ])
                sr2 = tk.Frame(gpu_rings_col, bg=BLOCK_BG)
                sr2.pack(anchor="center", pady=(4, 0))
                gs2 = stat_strip(sr2, [
                    ("HOTSPOT",   "#cccccc"),
                    ("VRAM TEMP", "#cccccc"),
                    ("VOLTAGE",   "#cccccc"),
                ])

                gc = tk.Frame(gpu_row_f, bg=BLOCK_BG)
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

    # ── RAM Block ─────────────────────────────────────────────────────────────
    ram_block = comp_block(left)
    ram0 = psutil.virtual_memory()
    comp_title(ram_block, "💾", "RAM",
               f"Total {ram0.total/1024**3:.0f} GB  ·  {ram_info}", ACCENT_RAM)

    ram_row = tk.Frame(ram_block, bg=BLOCK_BG)
    ram_row.pack(fill="x")

    ram_rings_col = tk.Frame(ram_row, bg=BLOCK_BG)
    ram_rings_col.pack(side="left")

    ram_rings_f = tk.Frame(ram_rings_col, bg=BLOCK_BG)
    ram_rings_f.pack(anchor="w", pady=(0, 8))
    ram_ring_usage = tk.Canvas(ram_rings_f, width=RS, height=RS,
                               bg=BLOCK_BG, highlightthickness=0)
    ram_ring_usage.pack(side="left", padx=24)
    ram_ring_temp = tk.Canvas(ram_rings_f, width=RS, height=RS,
                              bg=BLOCK_BG, highlightthickness=0)
    ram_temp_visible = [False]
    ram_temp_history = collections.deque(maxlen=GRAPH_SECONDS)

    ram_stats_f = tk.Frame(ram_rings_col, bg=BLOCK_BG)
    ram_stats_f.pack(anchor="center", pady=(4, 0))
    ram_used_lbl, ram_free_lbl, ram_clock_lbl = stat_strip(ram_stats_f, [
        ("USED",      "#cccccc"),
        ("AVAILABLE", "#cccccc"),
        ("SPEED",     "#cccccc"),
    ])
    _, ram_bar = make_bar(ram_rings_col, ACCENT_CPU, BORDER)

    ram_graph_col = tk.Frame(ram_row, bg=BLOCK_BG)
    ram_graph_col.pack(side="left", fill="both", expand=True, padx=(16, 0))

    ram_temp_graph_hdr = tk.Frame(ram_graph_col, bg=BLOCK_BG)
    ram_temp_graph_canvas = tk.Canvas(ram_graph_col, bg=GRAPH_BG, height=85,
                                      highlightthickness=1, highlightbackground=BORDER)
    ram_graph_visible = [False]

    tk.Frame(left, bg=BG, height=12).pack()

    # ── RIGHT PANEL — info rows ───────────────────────────────────────────────
    ROW_BG = "#111111"
    _ri = [0]

    def list_header(icon, title, accent=None):
        _ri[0] = 0
        f = tk.Frame(right, bg=BG)
        f.pack(fill="x", padx=16, pady=(20, 6))
        tk.Label(f, text="●", fg=ACCENT_CPU, bg=BG,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        tk.Label(f, text=title, fg="white", bg=BG,
                 font=("Segoe UI", 12, "bold")).pack(side="left")

    def list_row(label, val_color="#cccccc"):
        _ri[0] += 1
        f = tk.Frame(right, bg=ROW_BG)
        f.pack(fill="x", padx=8)
        # Subtle bottom separator
        tk.Frame(f, bg="#1a1a1a", height=1).pack(side="bottom", fill="x")
        tk.Label(f, text=label, fg="#b0b0b0", bg=ROW_BG,
                 font=("Segoe UI", 9), anchor="w").pack(
                     side="left", padx=(12, 0), pady=6, fill="x", expand=True)
        v = tk.Label(f, text="\u2014", fg=val_color, bg=ROW_BG,
                     font=("Segoe UI", 11, "bold"), anchor="e")
        v.pack(side="right", padx=(0, 16))
        v._row_frame = f
        return v

    # Secondary GPU section
    sec_gpu_section = tk.Frame(right, bg=BG)
    sec_gpu_section.pack(fill="x")
    sec_gpu_visible = [False]
    sec_load_lbl = [None]
    sec_vram_lbl = [None]

    # RAM details
    list_header("\U0001f4be", "RAM")
    ram_type_lbl    = list_row("Type",        "#cccccc")
    ram_form_lbl    = list_row("Form Factor", "#cccccc")
    ram_sticks_lbl  = list_row("Sticks",      "#cccccc")
    ram_timing_lbl  = list_row("SPD Timings", "#cccccc")
    ram_voltage_lbl = list_row("Voltage",     "#cccccc")

    # Network
    list_header("\U0001f310", "Network")
    net_up_lbl   = list_row("Upload",   "#cccccc")
    net_down_lbl = list_row("Download", "#cccccc")

    # System
    list_header("\u2699", "System")
    sys_host_lbl    = list_row("Hostname",   "#cccccc")
    sys_os_lbl      = list_row("OS",         "#cccccc")
    sys_ver_lbl     = list_row("Version",    "#cccccc")
    sys_build_lbl   = list_row("Build",      "#cccccc")
    sys_gpu_drv_lbl = list_row("GPU Driver", "#cccccc")
    sys_uptime_lbl  = list_row("Uptime",     "#cccccc")
    sys_host_lbl.config(text=socket.gethostname())
    sys_os_lbl.config(text=win_ver)
    sys_ver_lbl.config(text=win_ver_name if win_ver_name else "\u2014")
    sys_build_lbl.config(text=win_build if win_build else "\u2014")
    sys_gpu_drv_lbl.config(text=gpu_driver)

    # Fans
    list_header("\U0001f300", "Fans")
    fan_frame = tk.Frame(right, bg=BG)
    fan_frame.pack(fill="x", padx=8)

    # Motherboard sensors — entire section hidden when board has no sensors
    mobo_section = tk.Frame(right, bg=BG)
    mobo_section.pack(fill="x")
    _mobo_hdr_f = tk.Frame(mobo_section, bg=BG)
    _mobo_hdr_f.pack(fill="x", padx=16, pady=(20, 6))
    tk.Label(_mobo_hdr_f, text="●", fg=ACCENT_CPU, bg=BG,
             font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
    tk.Label(_mobo_hdr_f, text="Motherboard", fg="white", bg=BG,
             font=("Segoe UI", 12, "bold")).pack(side="left")
    mobo_name_lbl = tk.Label(mobo_section, text="", fg="#b0b0b0", bg=BG,
                             font=("Segoe UI", 9), anchor="w")
    mobo_name_lbl.pack(fill="x", padx=20, pady=(0, 4))
    mobo_temps_frame    = tk.Frame(mobo_section, bg=BG)
    mobo_temps_frame.pack(fill="x", padx=8)
    mobo_voltages_frame = tk.Frame(mobo_section, bg=BG)
    mobo_voltages_frame.pack(fill="x", padx=8)
    mobo_fans_frame     = tk.Frame(mobo_section, bg=BG)
    mobo_fans_frame.pack(fill="x", padx=8)

    # Storage
    list_header("\U0001f4bf", "Storage")
    disk_frames = {}
    for i, disk in enumerate(all_disks):
        dh = tk.Frame(right, bg=BG)
        dh.pack(fill="x", padx=20, pady=(8, 2))
        tk.Label(dh, text=f"{disk['model'][:30]}  ·  {disk['type']}  ·  {disk['size']} GB",
                 fg="#b0b0b0", bg=BG, font=("Segoe UI", 9)).pack(side="left")
        _ri[0] = 0
        h_lbl   = list_row("Health",         "#cccccc")
        t_lbl   = list_row("Temp",           "#cccccc")
        r_lbl   = list_row("Read",           "#cccccc")
        w_lbl   = list_row("Written",        "#cccccc")
        poh_lbl = list_row("Power-On Hours", "#cccccc")
        pf = tk.Frame(right, bg=BG, padx=20)
        pf.pack(fill="x", pady=(4, 0))
        disk_frames[i] = {
            "health": h_lbl, "temp": t_lbl,
            "read": r_lbl, "write": w_lbl,
            "poh": poh_lbl,
            "parts_frame": pf,
        }

    tk.Frame(right, bg=BG, height=20).pack()

    # ── Update sensors loop ───────────────────────────────────────────────────
    _last_net = [None]

    def _set(lbl, text, fg):
        col = getattr(lbl, "_stat_col", None)
        if text is None:
            lbl.config(text="—", fg="#444444")
            if col and col.winfo_ismapped(): col.pack_forget()
        else:
            lbl.config(text=text, fg=fg)
            if col and not col.winfo_ismapped(): col.pack(side="left", padx=18)

    def update_sensors():
        # ── Throttle during stress test — skip heavy graph/ring redraws ───────
        # When a stress test is running, we slow the poll to 5s and skip all
        # PIL image renders (rings + graphs) — only text labels update.
        # This keeps the UI responsive without interfering with the stress engine.
        _stress_active = any(
            ev is not None and not ev.is_set()
            for ev in stress_manager._stop_events.values()
        )
        _poll_interval = 5000 if _stress_active else 2000

        if not bridge.fetch():
            root.after(_poll_interval, update_sensors)
            return

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

        graph_cpu_temps.append(cpu_temp)
        if not _stress_active:
            draw_single_graph(cpu_graph_canvas, graph_cpu_temps, COL_CPU, 85)
            draw_ring(cpu_ring_load, cpu_usage, "LOAD", ACCENT_CPU, BLOCK_BG,
                      max_val=100, unit="%")
            draw_ring(cpu_ring_temp, cpu_temp,  "TEMP", temp_color(cpu_temp), BLOCK_BG,
                      max_val=105, unit="°C")
        if cpu_temp is None:
            # Only show warning if bridge has had time to populate data
            # (empty dict on first poll = still loading, not a real error)
            if bridge.get_data_snapshot():
                reason = bridge.diagnose_na("cpu_temp")
                if "permissions" in reason.lower() or "driver" in reason.lower():
                    msg = "⚠  Run as Administrator to enable temperature sensors"
                elif "not running" in reason.lower():
                    msg = "⚠  LHMBridge not running — restart the app"
                else:
                    msg = f"⚠  {reason}"
                cpu_diag_lbl.config(text=msg)
                if not cpu_diag_lbl.winfo_ismapped():
                    cpu_diag_lbl.pack(anchor="center", pady=(4, 0))
            else:
                # Still loading — hide warning silently
                cpu_diag_lbl.config(text="")
                if cpu_diag_lbl.winfo_ismapped():
                    cpu_diag_lbl.pack_forget()
        else:
            cpu_diag_lbl.config(text="")
            if cpu_diag_lbl.winfo_ismapped():
                cpu_diag_lbl.pack_forget()
        cpu_clock_lbl.config(text=fmt_clock(cpu_clock), fg="#cccccc")
        _set(cpu_power_lbl,   f"{cpu_power:.1f} W"   if cpu_power   is not None else None, "#cccccc")
        _set(cpu_voltage_lbl, f"{cpu_voltage:.3f} V" if cpu_voltage is not None else None, "#cccccc")

        ram = psutil.virtual_memory()
        ram_clocks = bridge.find_all_sensors("memory", "", "Clock")
        ram_clock = int(ram_clocks[0][1]) if ram_clocks else None
        if not ram_clock:
            m = re.search(r"@ (\d+) MHz", ram_info)
            if m:
                ram_clock = int(m.group(1))
        ram_type_str  = ram_info.split("@")[0].strip() if "@" in ram_info else "DDR"
        ram_form_str  = ram_info.split("|")[-1].strip() if "|" in ram_info else "DIMM"
        import re as _re
        sticks_m = _re.search(r"(\d+)x", ram_form_str)
        sticks_str = sticks_m.group(1) if sticks_m else "?"
        form_only  = _re.sub(r"\d+x\s*", "", ram_form_str).strip()

        ram_temp = None
        for key, sensors in bridge.get_data_snapshot().items():
            if "memory" not in key.lower(): continue
            v = bridge.sensor_value_in(sensors,
                ["Temperature", "Memory Temperature", "DIMM"],
                "Temperature")
            if v is not None and 10 <= v <= 90:
                ram_temp = v
                break

        if not _stress_active:
            draw_ring(ram_ring_usage, ram.percent, "USAGE", ACCENT_CPU, BLOCK_BG, max_val=100, unit="%")

        if ram_temp is not None:
            if not ram_temp_visible[0]:
                ram_ring_temp.pack(side="left", padx=24)
                ram_temp_visible[0] = True
            if not _stress_active:
                draw_ring(ram_ring_temp, ram_temp, "TEMP", temp_color(ram_temp),
                          BLOCK_BG, max_val=90, unit="°C")
            ram_temp_history.append(ram_temp)
            if not ram_graph_visible[0]:
                ram_graph_visible[0] = True
                tk.Label(ram_temp_graph_hdr, text="● RAM TEMP", fg=ACCENT_CPU,
                         bg=BLOCK_BG, font=("Segoe UI", 8, "bold")).pack(anchor="w")
                ram_temp_graph_hdr.pack(fill="x", pady=(0, 2))
                ram_temp_graph_canvas.pack(fill="x", pady=(0, 4))
            if not _stress_active:
                draw_single_graph(ram_temp_graph_canvas, ram_temp_history, ACCENT_CPU, 85)

        ram_used_lbl.config(text=f"{ram.used/1024**3:.1f} GB")
        ram_free_lbl.config(text=f"{ram.available/1024**3:.1f} GB")
        _set(ram_clock_lbl, f"{ram_clock} MHz" if ram_clock else None, "#cccccc")
        update_bar(ram_bar, ram.percent)
        ram_type_lbl.config(text=ram_type_str)
        ram_form_lbl.config(text=form_only)
        ram_sticks_lbl.config(text=sticks_str)

        # RAM timings
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

        # WMI JEDEC timing fallback (cached)
        if ram_timing_str == "—":
            if not hasattr(bridge, "_wmi_mem_cache"):
                bridge._wmi_mem_cache = bridge.get_wmi_memory_info()
            wmi = bridge._wmi_mem_cache
            jt = wmi.get("jedec_timings")
            if jt:
                parts = [str(jt["tCL"]), str(jt["tRCD"]),
                         str(jt["tRP"]), str(jt["tRAS"])]
                ram_timing_str = "-".join(parts) + " (JEDEC)"

        ram_volt_str = "—"
        snap = bridge.get_data_snapshot()
        for key, sensors in snap.items():
            if "memory" not in key.lower(): continue
            v = bridge.sensor_value_in(sensors, ["Voltage","VDD","VDIMM","DIMM"], "Voltage")
            if v is not None and 1.0 <= v <= 2.0:
                ram_volt_str = f"{v:.3f} V"
            break

        # Try mobo SuperIO voltages for DRAM voltage
        if ram_volt_str == "—":
            mobo = bridge.get_mobo_sensors()
            for ventry in mobo.get("voltages", []):
                vname = (ventry.get("name") or "").lower()
                vval  = ventry.get("value")
                if vval and any(kw in vname for kw in ["dram", "dimm", "vdd", "memory"]):
                    if 0.8 <= vval <= 2.5:
                        ram_volt_str = f"{vval:.3f} V"
                        break

        # WMI SMBIOS fallback for voltage (runs once, caches result)
        if ram_volt_str == "—":
            if not hasattr(bridge, "_wmi_mem_cache"):
                bridge._wmi_mem_cache = bridge.get_wmi_memory_info()
            wmi = bridge._wmi_mem_cache
            wv = wmi.get("voltage")
            if wv and 0.8 <= wv <= 2.5:
                ram_volt_str = f"{wv:.3f} V"

        ram_timing_lbl.config(text=ram_timing_str)
        ram_voltage_lbl.config(text=ram_volt_str)

        # GPU
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
                    if not _stress_active:
                        draw_ring(lbls["ring_load"], g_usage, "LOAD", ACCENT_CPU, BLOCK_BG,
                                  max_val=100, unit="%")
                    rt = lbls["ring_temp"]
                    if g_temp is not None:
                        if not rt.winfo_ismapped(): rt.pack(side="left", padx=24)
                        if not _stress_active:
                            draw_ring(rt, g_temp, "TEMP", temp_color(g_temp), BLOCK_BG,
                                      max_val=110, unit="°C")
                    else:
                        if rt.winfo_ismapped(): rt.pack_forget()
                    def _stat_update(lbl, value, fmt_fn, color):
                        _set(lbl, fmt_fn(value) if value is not None else None, color)

                    _stat_update(lbls["clock"],    g_clock,   fmt_clock,                    "#cccccc")
                    _stat_update(lbls["vram"],     g_vram,    lambda v: f"{v:.0f} MB",      "#cccccc")
                    _stat_update(lbls["power"],    g_power,   lambda v: f"{v:.1f} W",       "#cccccc")
                    _stat_update(lbls["hotspot"],  g_hotspot, lambda v: f"{v:.0f}°C",       temp_color(g_hotspot) if g_hotspot is not None else "#cccccc")
                    _stat_update(lbls["vram_temp"],g_vram_t,  lambda v: f"{v:.0f}°C",       temp_color(g_vram_t) if g_vram_t is not None else "#cccccc")
                    _stat_update(lbls["voltage"],  g_voltage, lambda v: f"{v:.3f} V",       "#cccccc")
                    any_temp = any(v is not None for v in [g_temp, g_hotspot, g_vram_t])
                    gc = lbls["graph_col"]
                    if any_temp:
                        if not gc.winfo_ismapped():
                            gc.pack(side="left", fill="both", expand=True, padx=(16, 0))
                        if not lbls["graph_visible"][0]:
                            lbls["graph_visible"][0] = True
                            hdr = lbls["graph_hdr"]
                            tk.Label(hdr, text="GPU TEMPS", fg="#888888", bg=BLOCK_BG,
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
                                tk.Label(lf, text=f"◆ {name}", fg=c, bg=BLOCK_BG,
                                         font=("Segoe UI", 7, "bold")).pack(side="left", padx=(0,8))
                        if not _stress_active:
                            draw_multi_graph(lbls["graph_canvas"], series, 170)
                    else:
                        if gc.winfo_ismapped(): gc.pack_forget()
                # Secondary GPU → right panel compact section
                if not lbls.get("primary", False):
                    if not sec_gpu_visible[0] and gpu_secondary:
                        sec_gpu_visible[0] = True
                        info = gpu_secondary[0]
                        hf = tk.Frame(sec_gpu_section, bg=BG)
                        hf.pack(fill="x", padx=16, pady=(22, 4))
                        tk.Label(hf, text="●", fg=ACCENT_CPU, bg=BG,
                                 font=("Segoe UI", 9)).pack(side="left", padx=(0,8))
                        tk.Label(hf, text="IGPU", fg="white", bg=BG,
                                 font=("Segoe UI", 10, "bold")).pack(side="left")
                        tk.Label(hf, text=info["name"], fg="#555555", bg=BG,
                                 font=("Segoe UI", 8)).pack(side="left", padx=(8,0))
                        def _srow(label, val_color):
                            f = tk.Frame(sec_gpu_section, bg=ROW_BG)
                            f.pack(fill="x", padx=8)
                            tk.Label(f, text=label, fg="#b0b0b0", bg=ROW_BG,
                                     font=("Segoe UI", 10), anchor="w").pack(
                                         side="left", padx=(14,0), pady=8,
                                         fill="x", expand=True)
                            v = tk.Label(f, text="—", fg=val_color, bg=ROW_BG,
                                         font=("Segoe UI", 11, "bold"), anchor="e")
                            v.pack(side="right", padx=(0,18))
                            return v
                        sec_load_lbl[0] = _srow("Load",      "#cccccc")
                        sec_vram_lbl[0] = _srow("VRAM Used", "#cccccc")
                    if sec_load_lbl[0]:
                        _set(sec_load_lbl[0], f"{g_usage:.0f}%" if g_usage is not None else None, "#cccccc")
                        _set(sec_vram_lbl[0], f"{g_vram:.0f} MB" if g_vram is not None else None, "#cccccc")

        # Fans
        for w in fan_frame.winfo_children():
            w.destroy()
        fans = bridge.find_all_fans()
        if fans:
            for fi, (fname, fval) in enumerate(fans):
                row = tk.Frame(fan_frame, bg=ROW_BG)
                row.pack(fill="x")
                tk.Frame(row, bg="#1a1a1a", height=1).pack(side="bottom", fill="x")
                txt = f"{fval:.0f} RPM" if fval > 0 else "0 RPM"
                tk.Label(row, text=txt, fg="#cccccc" if fval > 0 else "#555555",
                         bg=ROW_BG, font=("Segoe UI", 10, "bold"),
                         width=10, anchor="e").pack(side="right", padx=(0,16))
                display_name = fname if len(fname) <= 22 else fname[:21] + "…"
                tk.Label(row, text=display_name, fg="#b0b0b0", bg=ROW_BG,
                         font=("Segoe UI", 9), anchor="w").pack(
                             side="left", padx=(12,0), pady=6)
        else:
            tk.Label(fan_frame, text="No fan sensors found", fg="#a0a0a0",
                     bg=BG, font=("Segoe UI", 9), padx=12).pack(anchor="w", pady=6)

        # Motherboard sensors
        mobo = bridge.get_mobo_sensors()
        if mobo:
            board_name = mobo.get("name", "")
            temps     = mobo.get("temperatures", [])
            voltages  = mobo.get("voltages", [])
            fans      = mobo.get("fans", [])
            has_any   = any([temps, voltages, fans])

            if has_any:
                mobo_section.pack(fill="x")
                mobo_name_lbl.config(text=board_name)

                def _rebuild_mobo_frame(frame, entries, unit, accent, empty_msg):
                    for w in frame.winfo_children():
                        w.destroy()
                    valid = [e for e in entries
                             if e.get("value") is not None]
                    if not valid:
                        tk.Label(frame, text=empty_msg, fg="#a0a0a0",
                                 bg=BG, font=("Segoe UI", 9), padx=12
                                 ).pack(anchor="w", pady=2)
                        return
                    for fi, e in enumerate(valid):
                        row = tk.Frame(frame, bg=ROW_BG)
                        row.pack(fill="x")
                        tk.Frame(row, bg="#1a1a1a", height=1).pack(side="bottom", fill="x")
                        val_str = f"{e['value']:.1f}{unit}"
                        if unit == "°C":
                            col = temp_color(e["value"])
                        else:
                            col = "#cccccc"
                        tk.Label(row, text=val_str, fg=col, bg=ROW_BG,
                                 font=("Segoe UI", 10, "bold"),
                                 width=10, anchor="e").pack(side="right", padx=(0, 16))
                        name = e["name"]
                        display = name if len(name) <= 22 else name[:21] + "…"
                        tk.Label(row, text=display, fg="#b0b0b0", bg=ROW_BG,
                                 font=("Segoe UI", 9), anchor="w").pack(
                                     side="left", padx=(12, 0), pady=5)

                _rebuild_mobo_frame(
                    mobo_temps_frame,
                    temps,
                    "°C", "#cccccc",
                    "No temperature sensors",
                )
                _rebuild_mobo_frame(
                    mobo_voltages_frame,
                    voltages,
                    " V", "#cccccc",
                    "No voltage sensors",
                )
                _rebuild_mobo_frame(
                    mobo_fans_frame,
                    fans,
                    " RPM", "#cccccc",
                    "No fan sensors",
                )
            else:
                # Board detected but exposes no sensors (e.g. Dell/Lenovo locked BIOS)
                # Hide the entire section — no point showing an empty card
                mobo_section.pack_forget()
        else:
            mobo_section.pack_forget()

        # Storage
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

            _set(lbls["health"], f"{health:.0f}%" if health is not None else None, health_color(health))
            _set(lbls["temp"],   f"{temp:.0f}°C"  if temp   is not None else None, temp_color(temp))
            _set(lbls["read"],   fmt_data(read)   if read   is not None else None, "#cccccc")
            _set(lbls["write"],  fmt_data(write)  if write  is not None else None, "#cccccc")
            if poh is not None:
                poh_days  = int(poh) // 24
                poh_hours = int(poh) % 24
                poh_str   = f"{poh_days}d {poh_hours}h" if poh_days > 0 else f"{poh_hours}h"
                _set(lbls["poh"], poh_str, "#cccccc")
            else:
                _set(lbls["poh"], None, "#cccccc")

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
                                 fg="#b0b0b0", bg=BG,
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

        # Network
        try:
            n_now = psutil.net_io_counters()
            if _last_net[0] is not None:
                elapsed = 2.0
                net_up   = (n_now.bytes_sent - _last_net[0].bytes_sent) / elapsed / 1024
                net_down = (n_now.bytes_recv - _last_net[0].bytes_recv) / elapsed / 1024
            else:
                net_up = net_down = None
            _last_net[0] = n_now
        except Exception:
            net_up = net_down = None

        net_up_lbl.config(text=fmt_speed(net_up), fg="#cccccc")
        net_down_lbl.config(text=fmt_speed(net_down), fg="#cccccc")

        uptime = int(time.time()) - int(psutil.boot_time())
        h, m = divmod(uptime // 60, 60)
        d, h = divmod(h, 24)
        sys_uptime_lbl.config(text=f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m", fg="#cccccc")

        root.after(_poll_interval, update_sensors)

    # Bridge thread is done before main window opens — run first poll immediately
    root.after(100, update_sensors)

    # ══════════════════════════════════════════════════════════════════════════
    # STRESS TEST TAB — single scrollable page, no sub-tabs
    # ══════════════════════════════════════════════════════════════════════════

    stress_content = tk.Frame(stress_page, bg=BG)
    stress_content.pack(fill="both", expand=True)

    # We still use _tabs internally for the active view (log + stop button)
    _tabs = {}
    _tab_btns = {}

    def _show_tab(tab_name):
        """Show the menu or active page for a tab."""
        for n, d in _tabs.items():
            d["menu"].place_forget()
            d["active"].place_forget()
        page = _tabs[tab_name]["page"][0]
        _tabs[tab_name][page].place(relx=0, rely=0, relwidth=1, relheight=1)

    def _show_page_in_tab(tab_name, page):
        _tabs[tab_name]["page"][0] = page
        _tabs[tab_name]["menu"].place_forget()
        _tabs[tab_name]["active"].place_forget()
        if "ram_active" in _tabs[tab_name]:
            _tabs[tab_name]["ram_active"].place_forget()
        if "gpu_active" in _tabs[tab_name]:
            _tabs[tab_name]["gpu_active"].place_forget()
        _tabs[tab_name][page].place(relx=0, rely=0, relwidth=1, relheight=1)

    # Single "cpu" tab holds everything (menu + active views)
    menu_f   = tk.Frame(stress_content, bg=BG)
    active_f = tk.Frame(stress_content, bg=BG)
    _tabs["cpu"] = {"menu": menu_f, "active": active_f, "page": ["menu"]}

    stress_log_boxes = {}
    _active_state = {}

    def _build_active_view(tab_name):
        af = _tabs[tab_name]["active"]
        af.columnconfigure(0, weight=1)
        af.rowconfigure(1, weight=1)

        hdr = tk.Frame(af, bg="#0f0f0f")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")

        tk.Button(hdr, text="< Back",
                  bg="#0f0f0f", fg="#b0b0b0",
                  font=("Segoe UI", 9), relief="flat", bd=0,
                  padx=12, pady=10, cursor="hand2",
                  command=lambda t=tab_name: _show_page_in_tab(t, "menu")).pack(side="left")

        title_lbl = tk.Label(hdr, text="", bg="#0f0f0f", fg="white",
                             font=("Segoe UI", 12, "bold"))
        title_lbl.pack(side="left", padx=12)

        stop_btn = tk.Button(hdr, text="  Stop  ",
                             bg="#e63946", fg="white",
                             font=("Segoe UI", 10, "bold"),
                             relief="flat", padx=12, pady=6,
                             cursor="hand2")
        stop_btn.pack(side="right", padx=12, pady=6)

        log_w = tk.Text(af, bg="#0a0a0a", fg="#cccccc",
                        font=("Consolas", 10), bd=0, relief="flat",
                        state="disabled", wrap="none")
        log_w.grid(row=1, column=0, sticky="nsew")

        vsb = tk.Scrollbar(af, orient="vertical", command=log_w.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        log_w.configure(yscrollcommand=vsb.set)

        _active_state[tab_name] = {
            "title": title_lbl, "log": log_w, "stop": stop_btn,
            "log_cb": [None], "stop_fn": [None],
        }

    _build_active_view("cpu")

    def _write_log(tab_name, msg):
        try:
            w = _active_state[tab_name]["log"]
            w.config(state="normal")
            w.insert("end", f"{msg}\n")
            w.see("end")
            w.config(state="disabled")
        except tk.TclError:
            pass

    def _launch_test(tab_name, cmd_prefix, title, start_fn, stop_fn):
        st = _active_state[tab_name]
        st["log"].config(state="normal")
        st["log"].delete("1.0", "end")
        st["log"].config(state="disabled")
        st["title"].config(text=title)

        def log_cb(msg):
            log_queue.put((cmd_prefix, msg))

        st["log_cb"][0]  = log_cb
        st["stop_fn"][0] = stop_fn
        st["stop"].config(command=lambda: stop_fn(log_cb))
        stress_log_boxes[cmd_prefix] = tab_name
        start_fn(log_cb)
        _show_page_in_tab(tab_name, "active")

    # ── Build the single scrollable menu ──────────────────────────────────────
    mf  = _tabs["cpu"]["menu"]
    mc  = tk.Canvas(mf, bg=BG, highlightthickness=0)
    msb = tk.Scrollbar(mf, orient="vertical", command=mc.yview)
    mc.configure(yscrollcommand=msb.set)
    msb.pack(side="right", fill="y")
    mc.pack(fill="both", expand=True)
    mi = tk.Frame(mc, bg=BG)
    mc.create_window((0, 0), window=mi, anchor="nw")
    mi.bind("<Configure>", lambda e: mc.configure(scrollregion=mc.bbox("all")))
    mf.bind("<MouseWheel>", lambda e: mc.yview_scroll(int(-1*(e.delta/120)), "units"))
    mc.bind("<MouseWheel>",  lambda e: mc.yview_scroll(int(-1*(e.delta/120)), "units"))
    mi.bind("<MouseWheel>",  lambda e: mc.yview_scroll(int(-1*(e.delta/120)), "units"))

    mi.columnconfigure(0, weight=1)

    import multiprocessing as _mp
    _ncores = _mp.cpu_count()

    ALL_TESTS = [
        {"section": "CPU Stress Tests", "title": "CPU Single Core", "badge": "1T",      "accent": "#e63946", "cmd": "cpu_single",
         "desc": f"1 thread · AVX2 FMA · max boost clock + single-core heat"},
        {"section": "CPU Stress Tests", "title": "CPU Multi Core",  "badge": "AVX2",    "accent": "#e63946", "cmd": "cpu_multi",
         "desc": f"All {_ncores} threads · AVX2 FMA · max all-core load + thermals"},
        {"section": "CPU Stress Tests", "title": "Memory / IMC",    "badge": "RAM",     "accent": "#e63946", "cmd": "memory",
         "desc": "256MB/thread · sequential + stride · saturates DDR5 IMC"},
        {"section": "CPU Stress Tests", "title": "CPU + Memory",    "badge": "ALL",     "accent": "#e63946", "cmd": "combined",
         "desc": f"All {_ncores} threads · FMA + memory flood · max package power"},
        {"section": "CPU Stress Tests", "title": "Linpack DGEMM",   "badge": "LINPACK", "accent": "#ff4500", "cmd": "linpack",
         "desc": f"All {_ncores} threads · 2048×2048 FP64 matrix multiply · hotter than Combined"},
    ]

    from collections import OrderedDict
    sections = OrderedDict()
    for t in ALL_TESTS:
        sections.setdefault(t["section"], []).append(t)

    COLS = 2
    mi.columnconfigure(0, weight=1)
    mi.columnconfigure(1, weight=1)

    grid_row = 0
    for sec_name, items in sections.items():
        tk.Label(mi, text=sec_name, bg=BG, fg="#a0a0a0",
                 font=("Segoe UI", 10, "bold")).grid(
                 row=grid_row, column=0, columnspan=COLS,
                 sticky="w", padx=16, pady=(18, 4))
        grid_row += 1
        for i, t in enumerate(items):
            col = i % COLS
            if i > 0 and col == 0:
                grid_row += 1

            # ── sensor_fn: fetches live data directly from bridge each poll ──
            # Uses bridge._make_request() so it always has fresh data even
            # when update_sensors() is throttled to 5s during stress.
            def _make_sensor_fn(cmd=t["cmd"]):
                import json as _json

                def _fetch_sensors():
                    """Fresh snapshot direct from bridge — bypasses cache."""
                    try:
                        r = bridge._make_request("/sensors", timeout=3)
                        return _json.loads(r.read())
                    except Exception:
                        return bridge.get_data_snapshot()  # fall back to cache

                def _cpu_temp_live():
                    try:
                        r = bridge._make_request("/cpu-temp", timeout=3)
                        val = r.read().decode().strip()
                        return float(val) if val != "null" else None
                    except Exception:
                        return bridge.get_cpu_temp()

                def _cpu_only():
                    parts = []
                    temp = _cpu_temp_live()
                    if temp is not None:
                        parts.append(f"CPU {temp:.0f}°C")
                    snap = _fetch_sensors()
                    for key, sensors in snap.items():
                        if "cpu" not in key.lower(): continue
                        pwr = bridge.sensor_value_in(sensors, ["Package", "CPU Package", "CPU"], "Power")
                        if pwr is not None:
                            parts.append(f"{pwr:.0f}W")
                            break
                    for key, sensors in snap.items():
                        if "cpu" not in key.lower(): continue
                        v = bridge.sensor_value_in(sensors, ["CPU Core", "VCore", "Core"], "Voltage")
                        if v is not None:
                            parts.append(f"{v:.3f}V")
                            break
                    return "  ".join(parts)

                def _mem_only():
                    parts = []
                    temp = _cpu_temp_live()
                    if temp is not None:
                        parts.append(f"CPU {temp:.0f}°C")
                    import psutil as _ps
                    ram = _ps.virtual_memory()
                    parts.append(f"RAM {ram.percent:.0f}%  {ram.used/1024**3:.1f}/{ram.total/1024**3:.1f}GB")
                    return "  ".join(parts)

                def _combined():
                    parts = []
                    temp = _cpu_temp_live()
                    if temp is not None:
                        parts.append(f"CPU {temp:.0f}°C")
                    snap = _fetch_sensors()
                    for key, sensors in snap.items():
                        if "cpu" not in key.lower(): continue
                        pwr = bridge.sensor_value_in(sensors, ["Package", "CPU Package", "CPU"], "Power")
                        if pwr is not None:
                            parts.append(f"{pwr:.0f}W")
                            break
                    import psutil as _ps
                    ram = _ps.virtual_memory()
                    parts.append(f"RAM {ram.percent:.0f}%")
                    return "  ".join(parts)

                _MAP = {
                    "cpu_single": _cpu_only,
                    "cpu_multi":  _cpu_only,
                    "linpack":    _cpu_only,
                    "memory":     _mem_only,
                    "combined":   _combined,
                }
                return _MAP.get(cmd, _cpu_only)

            start_fn, stop_fn = stress_manager.make_stress_action(
                t["cmd"], t["cmd"], sensor_fn=_make_sensor_fn()
            )
            stress_log_boxes[t["cmd"]] = None
            card = tk.Frame(mi, bg="#121212",
                            highlightbackground=t["accent"],
                            highlightthickness=2, cursor="hand2")
            card.grid(row=grid_row, column=col, padx=10, pady=8, sticky="nsew", ipady=6)
            tk.Label(card, text=t["badge"], bg=t["accent"], fg="white",
                     font=("Segoe UI", 8, "bold"), padx=8, pady=3).pack(
                     anchor="nw", padx=10, pady=(10, 4))
            tk.Label(card, text=t["title"], bg="#121212", fg="white",
                     font=("Segoe UI", 10, "bold"),
                     wraplength=280, justify="left").pack(anchor="w", padx=10)
            tk.Label(card, text=t.get("desc", "Click to start"),
                     bg="#121212", fg="#909090",
                     font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(2, 10))

            def on_click(e=None, cmd=t["cmd"],
                         title=t["title"], sf=start_fn, stf=stop_fn):
                _launch_test("cpu", cmd, title, sf, stf)

            card.bind("<Button-1>", on_click)
            for w in card.winfo_children():
                w.bind("<Button-1>", on_click)

           # Hover / press feedback
            _acc = t["accent"]
            def _enter(e, c=card, a=_acc):
                c.config(bg="#1c1c1c")
                for ch in c.winfo_children():
                    try:
                        if ch.cget("bg") in ("#121212", "#0f0f0f"):
                            ch.config(bg="#1c1c1c")
                    except Exception: pass
            def _leave(e, c=card, a=_acc):
                c.config(bg="#121212")
                for ch in c.winfo_children():
                    try:
                        if ch.cget("bg") == "#1c1c1c":
                            ch.config(bg="#121212")
                    except Exception: pass
            def _press(e, c=card):
                c.config(bg="#252525")
                for ch in c.winfo_children():
                    try:
                        if ch.cget("bg") in ("#121212","#1c1c1c"):
                            ch.config(bg="#252525")
                    except Exception: pass
            def _release(e, c=card, a=_acc):
                _enter(e, c, a)

            card.bind("<Enter>",           _enter)
            card.bind("<Leave>",           _leave)
            card.bind("<ButtonPress-1>",   _press, add="+")
            card.bind("<ButtonRelease-1>", _release)
            for w in card.winfo_children():
                w.bind("<Enter>",           lambda e, c=card, a=_acc: _enter(e, c, a))
                w.bind("<Leave>",           lambda e, c=card, a=_acc: _leave(e, c, a))
                w.bind("<ButtonPress-1>",   lambda e, c=card: _press(e, c), add="+")
                w.bind("<ButtonRelease-1>", lambda e, c=card, a=_acc: _release(e, c, a))
        grid_row += 1

    # ── RAM Stability Test — same card style ──────────────────────────────────
    tk.Frame(mi, bg="#1e1e1e", height=1).grid(row=grid_row, column=0, columnspan=COLS, sticky="ew", padx=16, pady=(12, 0))
    grid_row += 1
    tk.Label(mi, text="RAM Stability Test", bg=BG, fg="#a0a0a0",
             font=("Segoe UI", 10, "bold")).grid(
             row=grid_row, column=0, columnspan=COLS, sticky="w", padx=16, pady=(8, 4))
    grid_row += 1

    ram_card = tk.Frame(mi, bg="#121212",
                        highlightbackground="#e63946", highlightthickness=2,
                        cursor="hand2")
    ram_card.grid(row=grid_row, column=0, columnspan=COLS, padx=10, pady=8, sticky="ew", ipady=6)

    tk.Label(ram_card, text="RAM", bg="#e63946", fg="white",
             font=("Segoe UI", 8, "bold"), padx=8, pady=3).pack(
             anchor="nw", padx=10, pady=(10, 4))
    tk.Label(ram_card, text="RAM Stability Test",
             bg="#121212", fg="white",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10)
    tk.Label(ram_card,
             text="15 pattern tests · write + verify · detects XMP/EXPO instability",
             bg="#121212", fg="#909090",
             font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(2, 6))

    # RAM size picker
    ram_size_frame = tk.Frame(ram_card, bg="#121212")
    ram_size_frame.pack(anchor="w", padx=10, pady=(0, 10))

    tk.Label(ram_size_frame, text="Test size:", bg="#121212", fg="#a0a0a0",
             font=("Segoe UI", 8)).pack(side="left")

    _RAM_SIZES = [("256 MB", 256), ("512 MB", 512), ("1 GB", 1024),
                  ("2 GB", 2048), ("4 GB", 4096), ("Auto (70%)", 0)]
    _ram_size_mb = [0]

    def _make_size_btn(label, mb, frame):
        is_auto = (mb == 0)
        btn = tk.Button(
            frame, text=label,
            bg="#1a1a1a" if not is_auto else "#2a0a0a",
            fg="white" if not is_auto else "#e63946",
            font=("Segoe UI", 8), relief="flat",
            padx=6, pady=2, cursor="hand2",
        )
        btn.pack(side="left", padx=(4, 0))
        return btn

    _size_btns = []
    for _lbl, _mb in _RAM_SIZES:
        _b = _make_size_btn(_lbl, _mb, ram_size_frame)
        _size_btns.append((_b, _mb))

    def _select_ram_size(chosen_mb):
        _ram_size_mb[0] = chosen_mb
        for btn, mb in _size_btns:
            active = (mb == chosen_mb)
            btn.config(
                bg="#2a0a0a" if active else "#1a1a1a",
                fg="#e63946" if active else "white",
            )

    for btn, mb in _size_btns:
        btn.config(command=lambda m=mb: _select_ram_size(m))

    _select_ram_size(0)
    grid_row += 1

    # ── GPU Stress Tests ───────────────────────────────────────────────────────
    tk.Frame(mi, bg="#1e1e1e", height=1).grid(row=grid_row, column=0, columnspan=COLS, sticky="ew", padx=16, pady=(12, 0))
    grid_row += 1
    tk.Label(mi, text="GPU Stress Test", bg=BG, fg="#a0a0a0",
             font=("Segoe UI", 10, "bold")).grid(
             row=grid_row, column=0, columnspan=COLS, sticky="w", padx=16, pady=(8, 4))
    grid_row += 1

    _GPU_TESTS = [
        ("GPU Core Test", "compute", "Hammers shader cores with FMA compute ops",      "GPU",  "#e63946"),
        ("VRAM Test",     "vram",    "Saturates VRAM bandwidth with 256MB transfers",  "VRAM", "#e63946"),
        ("Combined",      "all",     "Full GPU stress — compute + VRAM + rasterizer",  "ALL",  "#e63946"),
    ]

    _gpu_proc      = [None]
    _gpu_running   = [False]
    _gpu_test_name = [""]
    _gpu_log_queue = queue.Queue()

    def _gpu_exe_path():
        import os, sys
        # Installed: GPUStress subfolder next to HardwareToad.exe
        if getattr(sys, 'frozen', False):
            return os.path.join(os.path.dirname(sys.executable), "GPUStress", "GPUStress.exe")
        # Dev: repo_root/GPUStress/build/
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "GPUStress", "build", "GPUStress.exe")

    def _gpu_stop():
        if _gpu_proc[0] and _gpu_proc[0].poll() is None:
            try: _gpu_proc[0].terminate()
            except Exception: pass
        _gpu_proc[0]    = None
        _gpu_running[0] = False
        _gpu_refresh_ui()
    def _gpu_refresh_ui():
        running = _gpu_running[0]
        for card, _, _ in _gpu_btn_refs:
            card.config(cursor="hand2" if not running else "arrow",
                        highlightbackground="#e63946" if not running else "#555555")
        gpu_stop_btn.config(state="normal" if running else "disabled")
        if not running:
            gpu_status_lbl.config(text="", fg=ACCENT_GPU)

    def _gpu_start(mode, name):
        if _gpu_running[0]:
            return
        import subprocess, os
        exe = _gpu_exe_path()
        if not os.path.exists(exe):
            gpu_status_lbl.config(text="GPUStress.exe not found!", fg="#ef4444")
            return
        # Clear stale queue items
        try:
            while True: _gpu_log_queue.get_nowait()
        except Exception: pass
        try:
            _gpu_proc[0] = subprocess.Popen(
                [exe, "--mode", mode],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            gpu_status_lbl.config(text=f"Error: {e}", fg="#ef4444")
            return
        _gpu_running[0]   = True
        _gpu_test_name[0] = name
        gpu_status_lbl.config(text=f"Running: {name}", fg=ACCENT_GPU)
        gpu_title_lbl.config(text=f"GPU Stress — {name}")
        _gpu_refresh_ui()
        # Clear log and switch to active view
        gpu_log.config(state="normal")
        gpu_log.delete("1.0", "end")
        gpu_log.config(state="disabled")
        _show_gpu_active()
        _gpu_log_write(f"▶ Started: {name}")
        def _reader(proc):
            try:
                for raw in iter(proc.stdout.readline, b''):
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line: _gpu_log_queue.put(line)
            except Exception: pass
            # Also drain stderr
            try:
                for raw in iter(proc.stderr.readline, b''):
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line: _gpu_log_queue.put(line)
            except Exception: pass
            _gpu_log_queue.put(None)  # sentinel
        threading.Thread(target=_reader, args=(_gpu_proc[0],), daemon=True).start()
        _gpu_drain_log()
        _gpu_poll_sensors()

    def _gpu_log_write(msg):
        gpu_log.config(state="normal")
        gpu_log.insert("end", msg + "\n")
        gpu_log.see("end")
        gpu_log.config(state="disabled")

    def _gpu_drain_log():
        try:
            while True:
                item = _gpu_log_queue.get_nowait()
                if item is None:
                    _gpu_log_write("■ Stress test ended.")
                    _gpu_stop()
                    return
                _gpu_log_write(item)
        except Exception: pass
        if _gpu_running[0]:
            root.after(100, _gpu_drain_log)
    def _gpu_poll_sensors():
        if not _gpu_running[0]:
            return
        def _fetch_and_apply():
            try:
                import json as _json
                temp = power = load = volt = vram = hotspot = None

                # Direct bridge call — bypass cache for fresh data
                try:
                    r = bridge._make_request("/sensors", timeout=3)
                    snap = _json.loads(r.read())
                except Exception:
                    snap = bridge.get_data_snapshot()

                for key, sensors in snap.items():
                    if "gpu" not in key.lower():
                        continue
                    # Skip Intel iGPU if a discrete GPU exists
                    is_igpu = "intel" in key.lower() and "uhd" in key.lower()
                    has_dgpu = any("nvidia" in k.lower() or "amd" in k.lower() or "radeon" in k.lower()
                                   for k in snap if "gpu" in k.lower())
                    if is_igpu and has_dgpu:
                        continue

                    # Temperature — try multiple name patterns
                    if temp is None:
                        temp = bridge.sensor_value_in(sensors,
                            ["GPU Core", "Core", "Temperature", "GPU"],
                            "Temperature")
                    if hotspot is None:
                        hotspot = bridge.sensor_value_in(sensors,
                            ["Hot Spot", "Hotspot", "Junction"],
                            "Temperature")
                    if load is None:
                        load = bridge.sensor_value_in(sensors,
                            ["D3D 3D", "GPU Core", "Core", "GPU Total", "Video Engine"],
                            "Load")
                    if power is None:
                        power = bridge.sensor_value_in(sensors,
                            ["GPU Package", "GPU Chip", "Package", "GPU Power", "GPU"],
                            "Power")
                    if volt is None:
                        volt = bridge.sensor_value_in(sensors,
                            ["GPU Core", "Core", "GPU"],
                            "Voltage")
                    if vram is None:
                        vram = bridge.sensor_value_in(sensors,
                            ["D3D Dedicated", "GPU Memory Used", "Memory Used"],
                            "SmallData")
                    # Once we have at least load or temp from this GPU, use it
                    if load is not None or temp is not None:
                        break

                def _apply():
                    if not _gpu_running[0]: return
                    parts = []
                    if temp    is not None: parts.append(f"Temp: {temp:.0f}°C")
                    if hotspot is not None and hotspot != temp:
                        parts.append(f"Hot: {hotspot:.0f}°C")
                    if load    is not None: parts.append(f"Load: {load:.0f}%")
                    if power   is not None: parts.append(f"Power: {power:.0f}W")
                    if volt    is not None: parts.append(f"Volt: {volt:.3f}V")
                    if vram    is not None: parts.append(f"VRAM: {vram:.0f}MB")
                    if parts:
                        _gpu_log_write("[GPU] " + " | ".join(parts))
                    else:
                        _gpu_log_write("[GPU] Sensors: waiting for data…")
                    root.after(5000, _gpu_poll_sensors)
                root.after(0, _apply)
            except Exception:
                if _gpu_running[0]:
                    root.after(0, lambda: root.after(5000, _gpu_poll_sensors))
        threading.Thread(target=_fetch_and_apply, daemon=True).start()

    # ── GPU test cards (menu) ─────────────────────────────────────────────────
    gpu_cards_frame = tk.Frame(mi, bg=BG)
    gpu_cards_frame.grid(row=grid_row, column=0, columnspan=COLS, padx=10, pady=4, sticky="ew")
    for c in range(3):
        gpu_cards_frame.columnconfigure(c, weight=1)

    _gpu_btn_refs = []
    for col, (name, mode, desc, badge, accent) in enumerate(_GPU_TESTS):
        card = tk.Frame(gpu_cards_frame, bg="#121212",
                        highlightbackground=accent,
                        highlightthickness=2, cursor="hand2")
        card.grid(row=0, column=col, padx=10, pady=8, sticky="nsew", ipady=6)
        tk.Label(card, text=badge, bg=accent, fg="white",
                 font=("Segoe UI", 8, "bold"), padx=8, pady=3).pack(
                 anchor="nw", padx=10, pady=(10, 4))
        tk.Label(card, text=name, bg="#121212", fg="white",
                 font=("Segoe UI", 10, "bold"),
                 wraplength=280, justify="left").pack(anchor="w", padx=10)
        tk.Label(card, text=desc, bg="#121212", fg="#909090",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(2, 10))

        def _on_click(e=None, m=mode, n=name): _gpu_start(m, n)
        card.bind("<Button-1>", _on_click)
        for w in card.winfo_children():
            w.bind("<Button-1>", _on_click)

        # Hover feedback
        def _enter(e, c=card, a=accent):
            c.config(bg="#1c1c1c")
            for ch in c.winfo_children():
                try:
                    if ch.cget("bg") in ("#121212",): ch.config(bg="#1c1c1c")
                except Exception: pass
        def _leave(e, c=card, a=accent):
            c.config(bg="#121212")
            for ch in c.winfo_children():
                try:
                    if ch.cget("bg") in ("#1c1c1c",): ch.config(bg="#121212")
                except Exception: pass
        card.bind("<Enter>", _enter)
        card.bind("<Leave>", _leave)
        for w in card.winfo_children():
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        btn = card  # keep ref for disable/enable
        _gpu_btn_refs.append((btn, mode, name))

    grid_row += 1
    tk.Frame(mi, bg=BG, height=20).grid(row=grid_row, column=0, columnspan=COLS)

    # ── GPU active view ───────────────────────────────────────────────────────
    gpu_active = tk.Frame(stress_content, bg=BG)
    gpu_active.columnconfigure(0, weight=1)
    gpu_active.rowconfigure(1, weight=1)

    gpu_hdr = tk.Frame(gpu_active, bg="#0f0f0f")
    gpu_hdr.grid(row=0, column=0, columnspan=2, sticky="ew")

    tk.Button(gpu_hdr, text="< Back",
              bg="#0f0f0f", fg="#b0b0b0",
              font=("Segoe UI", 9), relief="flat", bd=0,
              padx=12, pady=10, cursor="hand2",
              command=lambda: _show_gpu_menu()).pack(side="left")

    gpu_title_lbl = tk.Label(gpu_hdr, text="GPU Stress Test",
                             bg="#0f0f0f", fg="white",
                             font=("Segoe UI", 12, "bold"))
    gpu_title_lbl.pack(side="left", padx=12)

    gpu_status_lbl = tk.Label(gpu_hdr, text="",
                              bg="#0f0f0f", fg=ACCENT_GPU,
                              font=("Segoe UI", 10))
    gpu_status_lbl.pack(side="left", padx=(0, 12))

    gpu_stop_btn = tk.Button(gpu_hdr, text="  ■ Stop  ",
                             bg="#e63946", fg="white",
                             font=("Segoe UI", 10, "bold"),
                             relief="flat", padx=12, pady=6, cursor="hand2",
                             command=_gpu_stop)
    gpu_stop_btn.pack(side="right", padx=12, pady=6)

    gpu_log = tk.Text(gpu_active, bg="#0a0a0a", fg="#cccccc",
                      font=("Consolas", 10), bd=0, relief="flat",
                      state="disabled", wrap="none")
    gpu_log.grid(row=1, column=0, sticky="nsew")

    gpu_vsb = tk.Scrollbar(gpu_active, orient="vertical", command=gpu_log.yview)
    gpu_vsb.grid(row=1, column=1, sticky="ns")
    gpu_log.configure(yscrollcommand=gpu_vsb.set)

    gpu_log.tag_configure("info", foreground="#888888")
    gpu_log.tag_configure("head", foreground=ACCENT_GPU)

    _tabs["cpu"]["gpu_active"] = gpu_active

    def _show_gpu_active():
        _tabs["cpu"]["menu"].place_forget()
        _tabs["cpu"]["active"].place_forget()
        if "ram_active" in _tabs["cpu"]:
            _tabs["cpu"]["ram_active"].place_forget()
        gpu_active.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _show_gpu_menu():
        _gpu_stop()
        _show_page_in_tab("cpu", "menu")

    grid_row += 1

    # ── RAM active view (log + stop) ──────────────────────────────────────────
    ram_active = tk.Frame(stress_content, bg=BG)
    ram_active.columnconfigure(0, weight=1)
    ram_active.rowconfigure(1, weight=1)

    ram_hdr = tk.Frame(ram_active, bg="#0f0f0f")
    ram_hdr.grid(row=0, column=0, columnspan=2, sticky="ew")

    tk.Button(ram_hdr, text="< Back",
              bg="#0f0f0f", fg="#b0b0b0",
              font=("Segoe UI", 9), relief="flat", bd=0,
              padx=12, pady=10, cursor="hand2",
              command=lambda: _show_page_in_tab("cpu", "menu")).pack(side="left")

    ram_title_lbl = tk.Label(ram_hdr, text="RAM Stability Test",
                             bg="#0f0f0f", fg="white",
                             font=("Segoe UI", 12, "bold"))
    ram_title_lbl.pack(side="left", padx=12)

    ram_progress_lbl = tk.Label(ram_hdr, text="",
                                bg="#0f0f0f", fg="#e63946",
                                font=("Segoe UI", 10))
    ram_progress_lbl.pack(side="left", padx=(0, 12))

    ram_stop_btn = tk.Button(ram_hdr, text="  Stop  ",
                             bg="#e63946", fg="white",
                             font=("Segoe UI", 10, "bold"),
                             relief="flat", padx=12, pady=6, cursor="hand2")
    ram_stop_btn.pack(side="right", padx=12, pady=6)

    ram_log = tk.Text(ram_active, bg="#0a0a0a", fg="#cccccc",
                      font=("Consolas", 10), bd=0, relief="flat",
                      state="disabled", wrap="none")
    ram_log.grid(row=1, column=0, sticky="nsew")

    ram_vsb = tk.Scrollbar(ram_active, orient="vertical", command=ram_log.yview)
    ram_vsb.grid(row=1, column=1, sticky="ns")
    ram_log.configure(yscrollcommand=ram_vsb.set)

    ram_log.tag_configure("pass",  foreground="#22c55e")
    ram_log.tag_configure("fail",  foreground="#ef4444")
    ram_log.tag_configure("error", foreground="#f87171")
    ram_log.tag_configure("info",  foreground="#888888")
    ram_log.tag_configure("head",  foreground="#e63946")

    _tabs["cpu"]["ram_active"] = ram_active

    _ram_running  = [False]
    _ram_log_seen = [0]

    def _ram_write(msg):
        ram_log.config(state="normal")
        tag = "info"
        if "✓ PASS" in msg or "✓ RAM" in msg: tag = "pass"
        elif "✗" in msg:                        tag = "fail"
        elif "ERROR" in msg:                    tag = "error"
        elif msg.startswith("Test "):           tag = "head"
        ram_log.insert("end", msg + "\n", tag)
        ram_log.see("end")
        ram_log.config(state="disabled")

    def _show_ram_active():
        _tabs["cpu"]["menu"].place_forget()
        _tabs["cpu"]["active"].place_forget()
        _tabs["cpu"]["ram_active"].place(relx=0, rely=0, relwidth=1, relheight=1)

    # Show the menu initially
    _tabs["cpu"]["menu"].place(relx=0, rely=0, relwidth=1, relheight=1)

    def _ram_poll():
        if not _ram_running[0]:
            return
        try:
            import urllib.request as _ur, json as _j
            r = _ur.urlopen(_ur.Request(f"http://127.0.0.1:{bridge.port}/ram/status", headers={"X-HardwareToad-Token": get_bridge_token()}), timeout=2)
            d = _j.loads(r.read())
        except Exception:
            root.after(800, _ram_poll)
            return
        phase  = d.get("phase", "idle")
        cur    = d.get("current_test", 0)
        total  = d.get("total_tests", 15)
        name   = d.get("current_name", "")
        errors = d.get("total_errors", 0)
        log    = d.get("log", [])
        for line in log[_ram_log_seen[0]:]:
            _ram_write(line)
        _ram_log_seen[0] = len(log)
        if phase == "running":
            ram_progress_lbl.config(
                text=f"Test {cur} of {total}  —  {name}"
                     + (f"  ·  {errors} errors" if errors else ""))
        elif phase in ("done", "stopped", "idle"):
            result = "✓ No errors" if errors == 0 else f"✗ {errors} errors"
            ram_progress_lbl.config(
                text=f"{'Done' if phase == 'done' else 'Stopped'}  ·  {result}")
            ram_stop_btn.config(state="disabled")
            _ram_running[0] = False
            return
        root.after(800, _ram_poll)

    def _ram_start():
        try:
            import urllib.request as _ur
            mb = _ram_size_mb[0]
            url = f"http://127.0.0.1:{bridge.port}/ram/start"
            if mb > 0:
                url += f"?mb={mb}"
            _ur.urlopen(_ur.Request(url, headers={"X-HardwareToad-Token": get_bridge_token()}), timeout=2)
        except Exception:
            return
        ram_log.config(state="normal")
        ram_log.delete("1.0", "end")
        ram_log.config(state="disabled")
        _ram_log_seen[0] = 0
        _ram_running[0]  = True
        size_label = f"{_ram_size_mb[0]} MB" if _ram_size_mb[0] > 0 else "Auto"
        ram_progress_lbl.config(text=f"Starting… ({size_label})")
        ram_stop_btn.config(state="normal")
        _show_ram_active()
        root.after(800, _ram_poll)

    def _ram_stop():
        try:
            import urllib.request as _ur
            _ur.urlopen(_ur.Request(f"http://127.0.0.1:{bridge.port}/ram/stop", headers={"X-HardwareToad-Token": get_bridge_token()}), timeout=2)
        except Exception:
            pass

    ram_stop_btn.config(command=_ram_stop)

    _ram_click_widgets = [ram_card] + [
        w for w in ram_card.winfo_children()
        if w is not ram_size_frame
    ]
    for w in _ram_click_widgets:
        w.bind("<Button-1>", lambda e: _ram_start())

    _show_tab("cpu")

    # ── Stress test log + temp monitoring ─────────────────────────────────────
    stress_win_alive = [True]

    def process_log_queue():
        if not stress_win_alive[0]:
            return
        for card_id, msg in stress_manager.drain_logs(max_items=20):
            tab_name = stress_log_boxes.get(card_id)
            if tab_name == "cpu":
                _write_log(tab_name, msg)
        root.after(100, process_log_queue)

    _temp_loop_active = [False]

    def update_stress_temps():
        if not stress_win_alive[0]:
            return
        if _temp_loop_active[0]:
            return
        _temp_loop_active[0] = True

        def _fetch():
            cpu_result = [None]
            gpu_result = [None]

            def _get_cpu():
                try:
                    cpu_result[0] = bridge.get_cpu_temp()
                except Exception:
                    pass

            def _get_gpu():
                try:
                    gpu_result[0] = bridge.get_primary_gpu_temp()
                except Exception:
                    pass

            t_cpu = threading.Thread(target=_get_cpu, daemon=True)
            t_gpu = threading.Thread(target=_get_gpu, daemon=True)
            t_cpu.start()
            t_gpu.start()
            t_cpu.join(timeout=2)
            t_gpu.join(timeout=2)

            try:
                root.after(0, lambda: _apply(cpu_result[0], gpu_result[0]))
            except Exception:
                _temp_loop_active[0] = False

        def _apply(cpu_t, gpu_t):
            _temp_loop_active[0] = False
            if not stress_win_alive[0]:
                return
            try:
                if cpu_t is not None or gpu_t is not None:
                    pass  # status already set by update_sensors
                graph_cpu_temps.append(cpu_t)
                graph_gpu_temps.append(gpu_t)
            except tk.TclError:
                stress_win_alive[0] = False
                return
            root.after(2000, update_stress_temps)

        threading.Thread(target=_fetch, daemon=True).start()

    update_stress_temps()
    process_log_queue()

    # ── Switch to Monitor tab initially ───────────────────────────────────────
    _switch_main_tab("monitor")

    root.mainloop()

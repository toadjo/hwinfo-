import tkinter as tk

from .constants import BADGE_HOT, BADGE_LIVE, BADGE_OK, BADGE_WARN, BADGE_OFF


# ── Color helpers ─────────────────────────────────────────────────────────────

def temp_color(v):
    if v is None:
        return "#4a5568"
    return "#ef4444" if v > 80 else ("#f59e0b" if v > 65 else "#22c55e")


def usage_color(v):
    if v is None:
        return "#4a5568"
    return "#ef4444" if v > 85 else ("#f59e0b" if v > 60 else "#3b82f6")


def health_color(v):
    if v is None:
        return "#4a5568"
    return "#ef4444" if v < 50 else ("#f59e0b" if v < 75 else "#22c55e")


def clock_color(v):
    return "#4a5568" if v is None else "#a855f7"


def fmt_clock(mhz):
    if mhz is None:
        return "N/A"
    return f"{mhz / 1000:.2f} GHz" if mhz >= 1000 else f"{mhz:.0f} MHz"


def fmt_data(v):
    if v is None:
        return "N/A"
    return f"{v / 1000:.1f} TB" if v >= 1000 else f"{v:.0f} GB"


def fmt_speed(kb):
    if kb is None:
        return "N/A"
    return f"{kb / 1024:.1f} MB/s" if kb >= 1024 else f"{kb:.0f} KB/s"


def fmt_temp(v):
    """Format a temperature value with the degree symbol."""
    if v is None:
        return "N/A"
    return f"{v:.0f}°C"


def badge_for_temp(v):
    if v is None:
        return "N/A", BADGE_OFF
    if v > 80:
        return "HOT", BADGE_HOT
    if v > 65:
        return "WARM", BADGE_WARN
    return "OK", BADGE_OK


def badge_live(online):
    return ("LIVE", BADGE_LIVE) if online else ("OFF", BADGE_OFF)


# ── Layout helpers ────────────────────────────────────────────────────────────
# All widget builders accept explicit `card_bg` and `border_bg` parameters
# so the active theme colours are used rather than the module-level defaults
# (which are evaluated at import time, before the theme is resolved).

def make_card(parent, title, icon, accent, card_bg, border_bg):
    """Dashboard card: dark bg, 2 px top accent border, header with badge slot."""
    outer = tk.Frame(parent, bg=accent)
    body = tk.Frame(outer, bg=card_bg, padx=14, pady=10)
    body.pack(fill="both", expand=True, pady=(2, 0))

    hdr = tk.Frame(body, bg=card_bg)
    hdr.pack(fill="x", pady=(0, 8))

    tk.Label(
        hdr,
        text=f"{icon}  {title}",
        fg=accent,
        bg=card_bg,
        font=("Segoe UI", 10, "bold"),
    ).pack(side="left")

    badge_lbl = tk.Label(
        hdr,
        text="",
        fg="#555",
        bg=card_bg,
        font=("Segoe UI", 7, "bold"),
        padx=6,
        pady=2,
    )
    badge_lbl.pack(side="right")

    return outer, body, badge_lbl


def set_badge(badge_lbl, text, colors):
    bg, fg = colors
    badge_lbl.config(text=text, bg=bg, fg=fg)


def divider(parent, border_bg):
    tk.Frame(parent, bg=border_bg, height=1).pack(fill="x", pady=5)


def big_stat(parent, label, val, color, card_bg):
    f = tk.Frame(parent, bg=card_bg)
    f.pack(side="left", expand=True)
    tk.Label(f, text=label, fg="#4a5568", bg=card_bg, font=("Segoe UI", 8, "bold")).pack()
    lbl = tk.Label(f, text=val, fg=color, bg=card_bg, font=("Segoe UI", 22, "bold"))
    lbl.pack()
    return lbl


def small_stat(parent, label, val, color, card_bg):
    f = tk.Frame(parent, bg=card_bg)
    f.pack(side="left", expand=True)
    tk.Label(f, text=label, fg="#4a5568", bg=card_bg, font=("Segoe UI", 8, "bold")).pack()
    lbl = tk.Label(f, text=val, fg=color, bg=card_bg, font=("Segoe UI", 13, "bold"))
    lbl.pack()
    return lbl


def make_bar(parent, accent, border_bg, height=3):
    bg = tk.Frame(parent, bg=border_bg, height=height)
    bg.pack(fill="x", pady=(6, 0))
    bg.pack_propagate(False)
    fill = tk.Frame(bg, bg=accent, height=height)
    fill.place(x=0, y=0, relheight=1.0, relwidth=0.0)
    return bg, fill


def update_bar(fill_frame, pct):
    if pct is None:
        pct = 0
    fill_frame.place(relwidth=max(0.0, min(pct / 100, 1.0)))


def place(widget, row, col, colspan=1):
    widget.grid(row=row, column=col, columnspan=colspan, padx=8, pady=6, sticky="nsew")

import tkinter as tk

from .constants import BADGE_HOT, BADGE_LIVE, BADGE_OK, BADGE_WARN, BADGE_OFF


# ── Color helpers ─────────────────────────────────────────────────────────────

def temp_color(v):
    if v is None:
        return "#4a4a4a"
    if v > 90:
        return "#ff4444"      # critical red
    if v > 80:
        return "#ff8c00"      # hot orange — distinct from red gauges
    if v > 65:
        return "#ffd43b"      # warm yellow
    return "#69db7c"          # cool green


def usage_color(v):
    if v is None:
        return "#4a4a4a"
    return "#ff6b6b" if v > 85 else ("#ffd43b" if v > 60 else "#cccccc")


def health_color(v):
    if v is None:
        return "#4a4a4a"
    return "#ff6b6b" if v < 50 else ("#ffd43b" if v < 75 else "#69db7c")


def clock_color(v):
    return "#4a4a4a" if v is None else "#cccccc"


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
    if v is None:
        return "N/A"
    return f"{v:.0f}°C"


def badge_for_temp(v):
    if v is None:
        return "N/A", BADGE_OFF
    if v > 90:
        return "HOT", BADGE_HOT
    if v > 80:
        return "WARM", BADGE_WARN
    if v > 65:
        return "WARM", BADGE_WARN
    return "OK", BADGE_OK


def badge_live(online):
    return ("LIVE", BADGE_LIVE) if online else ("OFF", BADGE_OFF)


# ── Layout helpers ────────────────────────────────────────────────────────────

def make_card(parent, title, icon, accent, card_bg, border_bg):
    """MSI One Center style card: clean dark bg, left accent stripe, white title."""
    # Outer frame — left accent stripe (3px)
    outer = tk.Frame(parent, bg=accent)
    # Inner body
    body = tk.Frame(outer, bg=card_bg, padx=16, pady=12)
    body.pack(fill="both", expand=True, padx=(3, 0), pady=(0, 0))

    # Thin top separator in accent color
    tk.Frame(body, bg=accent, height=1).pack(fill="x", pady=(0, 10))

    hdr = tk.Frame(body, bg=card_bg)
    hdr.pack(fill="x", pady=(0, 8))

    tk.Label(
        hdr,
        text=f"{icon}  {title}",
        fg="white",
        bg=card_bg,
        font=("Segoe UI", 10, "bold"),
    ).pack(side="left")

    badge_lbl = tk.Label(
        hdr,
        text="",
        fg="#888",
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
    tk.Frame(parent, bg=border_bg, height=1).pack(fill="x", pady=6)


def big_stat(parent, label, val, color, card_bg):
    f = tk.Frame(parent, bg=card_bg)
    f.pack(side="left", expand=True)
    tk.Label(
        f, text=label, fg="#808080", bg=card_bg,
        font=("Segoe UI", 8, "bold")
    ).pack()
    lbl = tk.Label(
        f, text=val, fg=color, bg=card_bg,
        font=("Segoe UI", 22, "bold")
    )
    lbl.pack()
    return lbl


def small_stat(parent, label, val, color, card_bg):
    f = tk.Frame(parent, bg=card_bg)
    f.pack(side="left", expand=True)
    tk.Label(
        f, text=label, fg="#808080", bg=card_bg,
        font=("Segoe UI", 8, "bold")
    ).pack()
    lbl = tk.Label(
        f, text=val, fg=color, bg=card_bg,
        font=("Segoe UI", 13, "bold")
    )
    lbl.pack()
    return lbl


def make_bar(parent, accent, border_bg, height=3):
    """Clean progress bar."""
    bg = tk.Frame(parent, bg="#1a1a1a", height=height)
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

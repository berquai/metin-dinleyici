# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Renk temaları.

Renkler stil sayfasıyla değil Qt paletiyle verilir: Windows 11 stilinde geniş kapsamlı stil
sayfaları menü kısayollarını üst üste bindiriyor ve sayaç kutusunu boş gösteriyordu.
Aynı palet tam ekran ve odaklanma modunda da geçerli olduğu için tema her yerde aynı görünür.
"""
from PySide6.QtGui import QColor, QPalette

# Kullanıcının özel temada ayarladığı roller → (Türkçe ad, açıklama)
EDITABLE_ROLES = [
    ("base", "Metin arka planı"),
    ("text", "Yazı rengi"),
    ("win", "Pencere ve paneller"),
    ("btn", "Düğmeler"),
    ("sent_bg", "Okunan cümle arka planı"),
    ("sent_fg", "Okunan cümle yazısı"),
    ("hl", "Seçim ve vurgu"),
]

THEMES = {
    # ── açık temalar ──
    "Kâğıt": dict(win="#f3eee2", text="#302e29", base="#fffaf0", btn="#e7dfcf", hl="#b49a3a",
                  sent_bg="#e8d98d", sent_fg="#201e18"),
    "Sepya": dict(win="#e9dcc3", text="#46351f", base="#f5ead3", btn="#dccaa8", hl="#9c6b30",
                  sent_bg="#e2c27f", sent_fg="#2c1f0e"),
    "Bulut": dict(win="#eceff2", text="#25303a", base="#ffffff", btn="#dde3e9", hl="#4f7cac",
                  sent_bg="#cfe0f3", sent_fg="#14212d"),
    "Krem": dict(win="#f6f0dc", text="#3a3526", base="#fdf8e6", btn="#ebe2c4", hl="#a88a2c",
                 sent_bg="#f3df9a", sent_fg="#2a2410"),
    "Nane": dict(win="#e5efe8", text="#22352a", base="#f4faf5", btn="#d3e3d8", hl="#3f8a5f",
                 sent_bg="#bfe3cb", sent_fg="#0f2618"),
    "Lavanta": dict(win="#ece8f3", text="#2f2a3d", base="#faf8fd", btn="#ddd6ea", hl="#7a62b0",
                    sent_bg="#ddd0f5", sent_fg="#1d1530"),
    "Gül Kurusu": dict(win="#f3e6e6", text="#3d2a2c", base="#fdf6f5", btn="#e8d3d3", hl="#b0606a",
                       sent_bg="#f2cdd1", sent_fg="#2b1417"),
    "Kum": dict(win="#ebe6dd", text="#3b372f", base="#f7f4ee", btn="#ddd6c9", hl="#8f7a52",
                sent_bg="#e3d4b0", sent_fg="#262116"),
    "Deniz Köpüğü": dict(win="#e2eef0", text="#1f3439", base="#f3fafb", btn="#cfe2e5", hl="#2f8597",
                         sent_bg="#bfe4ea", sent_fg="#0d2429"),
    "Açık Kontrast": dict(win="#ffffff", text="#000000", base="#ffffff", btn="#e6e6e6", hl="#0050c8",
                          sent_bg="#ffe100", sent_fg="#000000"),
    # ── koyu temalar ──
    "Gece": dict(win="#202124", text="#eee5d5", base="#292a2d", btn="#383a3e", hl="#8a7a3c",
                 sent_bg="#655b35", sent_fg="#fff7df"),
    "Gece Mavisi": dict(win="#1a2030", text="#e2e7f1", base="#212938", btn="#2e384b", hl="#5a7bbd",
                        sent_bg="#34507f", sent_fg="#ffffff"),
    "Orman": dict(win="#1c231f", text="#dfe6d8", base="#232b26", btn="#313b34", hl="#6c9a5b",
                  sent_bg="#3d5a37", sent_fg="#f4fbec"),
    "Kahve": dict(win="#241c17", text="#eadccb", base="#2d231d", btn="#3d3028", hl="#b0804a",
                  sent_bg="#5e4329", sent_fg="#fff3e3"),
    "Arduvaz": dict(win="#22262b", text="#d9dee4", base="#2a2f35", btn="#3a4048", hl="#7d93ad",
                    sent_bg="#44566b", sent_fg="#ffffff"),
    "Mor Gece": dict(win="#1f1a2a", text="#e6def3", base="#272134", btn="#372f48", hl="#9a7fd1",
                     sent_bg="#4c3d70", sent_fg="#ffffff"),
    "Kehribar": dict(win="#141210", text="#f0c674", base="#1a1714", btn="#2a2520", hl="#d08b2c",
                     sent_bg="#5a3f12", sent_fg="#ffe6b0"),
    "Gece Yeşili": dict(win="#101a18", text="#cfe8df", base="#14211e", btn="#22332f", hl="#3fa58a",
                        sent_bg="#1f5747", sent_fg="#f0fff9"),
    "Yüksek Kontrast": dict(win="#000000", text="#ffffff", base="#000000", btn="#1e1e1e", hl="#ffd400",
                            sent_bg="#ffd400", sent_fg="#000000"),
}
CUSTOM = "Özel"
DEFAULT_THEME = "Kâğıt"


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def is_dark(color):
    return QColor(color).lightnessF() < 0.5


def complete(theme):
    """Temel renklerden diğer palet rollerini türetir (özel temalar için de çalışır)."""
    c = dict(THEMES[DEFAULT_THEME])
    c.update({k: v for k, v in (theme or {}).items() if QColor(v).isValid()})
    dark = is_dark(c["base"])
    c["alt"] = _mix(c["base"], c["win"], 0.5)
    c["mid"] = _mix(c["text"], c["base"], 0.45)
    c["hltext"] = "#000000" if not is_dark(c["hl"]) else "#ffffff"
    c["link"] = QColor(c["hl"]).lighter(140).name() if dark else QColor(c["hl"]).darker(140).name()
    return c


def palette_for(theme):
    c = complete(theme)
    pal = QPalette()
    for role, key in ((QPalette.Window, "win"), (QPalette.WindowText, "text"), (QPalette.Base, "base"),
                      (QPalette.AlternateBase, "alt"), (QPalette.Text, "text"), (QPalette.Button, "btn"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "hl"),
                      (QPalette.HighlightedText, "hltext"), (QPalette.ToolTipBase, "base"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "mid"),
                      (QPalette.Mid, "mid"), (QPalette.Link, "link"), (QPalette.BrightText, "text")):
        pal.setColor(role, QColor(c[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["mid"]))
    return pal, c

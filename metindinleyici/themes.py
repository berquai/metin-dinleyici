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
    "Kâğıt": dict(win="#f3eee2", text="#302e29", base="#fffaf0", btn="#e7dfcf", hl="#b49a3a",
                  sent_bg="#e8d98d", sent_fg="#201e18"),
    "Sepya": dict(win="#e9dcc3", text="#46351f", base="#f5ead3", btn="#dccaa8", hl="#9c6b30",
                  sent_bg="#e2c27f", sent_fg="#2c1f0e"),
    "Bulut": dict(win="#eceff2", text="#25303a", base="#ffffff", btn="#dde3e9", hl="#4f7cac",
                  sent_bg="#cfe0f3", sent_fg="#14212d"),
    "Gece": dict(win="#202124", text="#eee5d5", base="#292a2d", btn="#383a3e", hl="#8a7a3c",
                 sent_bg="#655b35", sent_fg="#fff7df"),
    "Gece Mavisi": dict(win="#1a2030", text="#e2e7f1", base="#212938", btn="#2e384b", hl="#5a7bbd",
                        sent_bg="#34507f", sent_fg="#ffffff"),
    "Orman": dict(win="#1c231f", text="#dfe6d8", base="#232b26", btn="#313b34", hl="#6c9a5b",
                  sent_bg="#3d5a37", sent_fg="#f4fbec"),
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

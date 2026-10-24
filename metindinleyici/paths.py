# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Dosya konumları ve platform bilgisi."""
import os
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def resource_path(name):
    """Hem normal çalıştırmada hem de PyInstaller ile paketlenmiş exe'de proje kökündeki dosyayı bulur."""
    base = getattr(sys, "_MEIPASS", None) or str(Path(__file__).resolve().parent.parent)
    return os.path.join(base, name)


def data_dir():
    """Kullanıcıya ait kalıcı veri klasörü (veritabanı, metin önbelleği)."""
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    except Exception:
        base = ""
    base = base or os.path.join(tempfile.gettempdir(), "MetinDinleyici")
    os.makedirs(base, exist_ok=True)
    return base

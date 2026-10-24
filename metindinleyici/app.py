# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Uygulamanın başlangıç noktası."""
import os
import sys

from PySide6.QtGui import QIcon, QPalette, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOptionMenuItem

from . import APP_NAME, APP_ORG, APP_VERSION
from .paths import IS_WINDOWS, data_dir, resource_path


class AppStyle(QProxyStyle):
    """Fusion stilinin küçük bir düzeltmesi.

    Fusion, açılır listeyi seçili öğe kutunun tam üstüne gelecek biçimde açar (macOS alışkanlığı).
    Seçili öğe listenin sonlarındaysa liste yukarı taşar ve pencerenin tepesinden açılıyormuş gibi
    görünür. SH_ComboBox_Popup ipucunu kapatınca liste, Windows'taki gibi kutunun hemen altından açılır."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def drawControl(self, element, option, painter, widget=None):
        """Menü ayraçlarını yazı renginden türetilmiş bir çizgiyle çizer: Fusion'ın ayracı koyu
        temalarda arka planla neredeyse aynı renkte kalıp görünmez oluyordu."""
        super().drawControl(element, option, painter, widget)
        if element == QStyle.CE_MenuItem and isinstance(option, QStyleOptionMenuItem) \
                and option.menuItemType == QStyleOptionMenuItem.Separator:
            c = option.palette.color(QPalette.Text)
            c.setAlpha(110)
            r = option.rect
            y = r.center().y()
            painter.save()
            painter.setPen(QPen(c, 1))
            painter.drawLine(r.left() + 6, y, r.right() - 6, y)
            painter.restore()


def main():
    if "--self-test" in sys.argv:                      # paketleme sonrası denetim (pencere açmaz)
        from .selftest import run
        i = sys.argv.index("--self-test")
        sys.exit(run(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    if IS_WINDOWS:
        # Görev çubuğunun python.exe simgesini değil bizim simgemizi göstermesi için kendi kimliğimiz
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BerkayCelik.MetinDinleyici")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ORG)
    icon = resource_path("metin_dinleyici.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    # Fusion: renk/stil özelleştirmesine en tutarlı yanıt veren Qt stili.
    app.setStyle(AppStyle("Fusion"))

    from .mainwindow import MainWindow
    w = MainWindow(cache_dir=os.path.join(data_dir(), "metin_onbellek"))
    w.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        w.load_path(sys.argv[1])
    sys.exit(app.exec())

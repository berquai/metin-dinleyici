# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Uygulamanın başlangıç noktası."""
import os
import sys

from PySide6.QtCore import QCoreApplication, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPalette, QPen
from PySide6.QtWidgets import QApplication, QMessageBox, QProxyStyle, QStyle, QStyleOptionMenuItem

from . import APP_NAME, APP_ORG, APP_VERSION, crashlog
from .paths import IS_WINDOWS, data_dir, resource_path

SAFE_FLAGS = ("--guvenli", "--güvenli", "--safe")
SAFE_NOTE = ("Güvenli mod: pencere ve panel yerleşimi varsayılana döner, program çevrimiçi ses moduyla açılır, "
             "kütüphanede kapak ve sayfa bilgisi taraması bu oturumda yapılmaz. Kütüphaneniz, alıntılarınız ve "
             "kaldığınız yerler korunur.")


def decide_safe_mode(info):
    """Güvenli mod: komut satırında --guvenli, açılırken Shift basılı tutulması ya da önceki açılışın
    yarıda kesilmesi (kullanıcıya sorulur)."""
    if any(f in sys.argv for f in SAFE_FLAGS):
        crashlog.write("Güvenli mod: komut satırından istendi.")
        return True
    if QGuiApplication.queryKeyboardModifiers() & Qt.ShiftModifier:
        crashlog.write("Güvenli mod: açılırken Shift basılıydı.")
        return True
    if info.get("previous") != "starting":
        return False
    n = info.get("startup_fails", 1)
    box = QMessageBox(QMessageBox.Warning, APP_NAME,
                      "Program son açılışında, açılırken beklenmedik biçimde kapandı"
                      + (f" (art arda {n}. kez)" if n > 1 else "") + ".\n\n"
                      + SAFE_NOTE + "\n\nGüvenli modda açılsın mı?")
    safe_btn = box.addButton("Güvenli Modda Aç", QMessageBox.AcceptRole)
    box.addButton("Normal Aç", QMessageBox.RejectRole)
    log_btn = box.addButton("Hata Günlüğünü Göster", QMessageBox.HelpRole)
    box.setDefaultButton(safe_btn)
    box.exec()
    if box.clickedButton() is log_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(crashlog.log_dir()))
        crashlog.write("Önceki açılış kesilmiş; günlük klasörü açıldı, güvenli modda devam ediliyor.")
        return True
    safe = box.clickedButton() is safe_btn
    crashlog.write("Önceki açılış kesilmiş; kullanıcı " + ("güvenli modu" if safe else "normal açılışı") + " seçti.")
    return safe


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
    # Ad ve kuruluş, veri klasörünün yolunu belirler: kara kutu açılmadan önce tanımlanmalı.
    QCoreApplication.setOrganizationName(APP_ORG)
    QCoreApplication.setApplicationName(APP_NAME)
    info = crashlog.install(APP_VERSION)
    if IS_WINDOWS:
        # Görev çubuğunun python.exe simgesini değil bizim simgemizi göstermesi için kendi kimliğimiz
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BerkayCelik.MetinDinleyici")
        except Exception:
            pass
    app = QApplication(sys.argv)
    crashlog.install_qt()
    crashlog.stage("QApplication kuruldu · ekranlar: " + crashlog.describe_screens(app))
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ORG)
    icon = resource_path("metin_dinleyici.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    # Fusion: renk/stil özelleştirmesine en tutarlı yanıt veren Qt stili.
    app.setStyle(AppStyle("Fusion"))

    crashlog.SAFE_MODE = decide_safe_mode(info)
    app.lastWindowClosed.connect(lambda: crashlog.write("Son pencere kapandı."))
    app.aboutToQuit.connect(lambda: crashlog.write("Uygulama kapanıyor."))

    crashlog.stage("arayüz modülleri yükleniyor")
    from .mainwindow import MainWindow
    crashlog.stage("ana pencere kuruluyor" + (" (GÜVENLİ MOD)" if crashlog.SAFE_MODE else ""))
    w = MainWindow(cache_dir=os.path.join(data_dir(), "metin_onbellek"))
    crashlog.watch_window(w)
    crashlog.stage("ana pencere kuruldu, gösteriliyor")
    w.show()
    crashlog.stage("pencere gösterildi · " + crashlog.describe_window(w))
    QTimer.singleShot(1500, lambda: crashlog.stage("1,5 sn sonra · " + crashlog.describe_window(w)))
    QTimer.singleShot(crashlog.RUNNING_AFTER_MS, lambda: crashlog.mark("running"))
    if crashlog.SAFE_MODE:
        w.setWindowTitle(f"{APP_NAME} — Güvenli Mod")
        w.statusBar().showMessage(SAFE_NOTE, 20000)
    args = [a for a in sys.argv[1:] if a not in SAFE_FLAGS]
    if args and os.path.exists(args[0]):
        w.load_path(args[0])
    code = app.exec()
    crashlog.mark("closed")
    sys.exit(code)

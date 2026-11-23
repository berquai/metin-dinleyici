# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""İletişim pencereleri: Hakkında, lisans, metin görünümü, özel tema, MP3 aralığı."""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFontComboBox, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout,
)

from . import (APP_NAME, APP_VERSION, APP_YEAR, AUTHOR, AUTHOR_MAIL, LICENSE_NAME, LICENSE_SPDX,
               SOURCE_URL)
from .paths import resource_path
from .themes import EDITABLE_ROLES, complete


class RangeDialog(QDialog):
    def __init__(self, parent, total, current):
        super().__init__(parent)
        self.setWindowTitle("MP3 olarak dışa aktar")
        form = QFormLayout(self)
        self.a = QSpinBox(); self.a.setRange(1, total); self.a.setValue(current)
        self.b = QSpinBox(); self.b.setRange(1, total); self.b.setValue(total)
        form.addRow("Başlangıç cümlesi", self.a)
        form.addRow("Bitiş cümlesi", self.b)
        info = QLabel("Seçili çevrimiçi ses, hız ve cümle arası es kullanılır. Uzun aralıklar birkaç dakika sürebilir.")
        info.setWordWrap(True)
        form.addRow(info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)


# ───────────────────────────── Hakkında ve lisans ─────────────────────────────

ABOUT_HTML = f"""
<h2 style="margin-bottom:0">{APP_NAME}</h2>
<p style="margin-top:2px">Sürüm {APP_VERSION} &nbsp;·&nbsp; {APP_YEAR}</p>
<p>PDF, EPUB, DOCX ve TXT belgeleri için sesli okuma uygulaması.</p>
<p><b>Bu sürümde:</b> salt okuma modu (başka işlerle uğraşırken metni takip etmek için küçük, her zaman üstte
kalabilen pencere), yeni Ayarlar menüsü ve sadeleşen kontrol paneli, 19 renk teması, belge sonunda “baştan aransın
mı?” sorusu, orijinal belgede tek tıkla sığdırma ve fareyle sürükleyerek gezinme.</p>
<p>{APP_NAME}, <b>{AUTHOR}</b> tarafından kişisel bir proje olarak geliştirilmiştir
ve <b>tamamen ücretsiz</b> olarak dağıtılmaktadır.</p>
<p><b>Telif Hakkı © {APP_YEAR} {AUTHOR}.</b><br>
Bu yazılım, <b>{LICENSE_NAME}</b> ({LICENSE_SPDX}) ve NOTICE dosyasındaki ek koşullar
kapsamında dağıtılan açık kaynak bir yazılımdır. Lisansın açıkça tanımadığı tüm haklar saklıdır.</p>
<p><b>Yazar atfı.</b> Lisansın 7(b) ve 7(c) maddeleri uyarınca programın ve ondan türetilen
çalışmaların dağıtılan her kopyasında “{AUTHOR}” yazar bilgisi ve telif bildirimi korunmalıdır.
Değiştirilmiş sürümler özgün sürümden farklı olduklarını açıkça belirtmeli; özgün eser ya da
herhangi bir parçası başka bir kişinin eseriymiş gibi sunulmamalıdır. Bu koşullara aykırı
dağıtım, lisansın sağladığı hakları kendiliğinden sona erdirir.</p>
<p>Bu program <b>HİÇBİR GARANTİ OLMAKSIZIN</b>, “olduğu gibi” sunulmaktadır.</p>
<p>İletişim: <a href="mailto:{AUTHOR_MAIL}">{AUTHOR_MAIL}</a><br>
Kaynak kod: <a href="{SOURCE_URL}">{SOURCE_URL}</a></p>
"""


def _read_resource(name):
    for cand in (resource_path(name), resource_path(name + ".txt"), resource_path(name + ".md")):
        if os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
    return None


class LicenseDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Lisans ve bildirimler")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        mono = QFont("Consolas"); mono.setStyleHint(QFont.Monospace)
        for title, name in (("Ek koşullar (NOTICE)", "NOTICE"), ("Lisans metni (AGPL v3)", "LICENSE"),
                            ("Üçüncü taraf bileşenler", "THIRD_PARTY_NOTICES")):
            view = QTextBrowser()
            view.setOpenExternalLinks(True)
            text = _read_resource(name)
            if text is None:
                view.setHtml(f"<p>{name} dosyası bu kurulumda bulunamadı.</p>"
                             f'<p>Lisans metni: <a href="https://www.gnu.org/licenses/agpl-3.0.html">'
                             f"https://www.gnu.org/licenses/agpl-3.0.html</a></p>")
            else:
                if name == "LICENSE":
                    view.setFont(mono)
                view.setPlainText(text)
            tabs.addTab(view, title)
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject); bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        lay.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, parent, icon=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} hakkında")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        if icon is not None and not icon.isNull():
            pic = QLabel(); pic.setPixmap(icon.pixmap(64, 64)); pic.setAlignment(Qt.AlignTop)
            top.addWidget(pic)
        text = QLabel(ABOUT_HTML)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        top.addWidget(text, 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        lic = QPushButton("Lisans ve Bildirimler…")
        lic.clicked.connect(lambda: LicenseDialog(self).exec())
        close = QPushButton("Kapat"); close.setDefault(True); close.clicked.connect(self.accept)
        row.addWidget(lic); row.addStretch(1); row.addWidget(close)
        lay.addLayout(row)


# ───────────────────────────── Metin görünümü ─────────────────────────────

LINE_SPACINGS = [100, 115, 130, 150, 175, 200, 250]


class TextAppearanceDialog(QDialog):
    """Yazı tipi, boyut, satır aralığı, paragraf aralığı ve kenar boşluğu. Değişiklikler anında görünür."""
    changed = Signal(dict)

    def __init__(self, parent, values):
        super().__init__(parent)
        self.setWindowTitle("Metin görünümü")
        self.original = dict(values)
        form = QFormLayout(self)
        self.family = QFontComboBox(); self.family.setCurrentFont(QFont(values["family"]))
        self.size = QSpinBox(); self.size.setRange(8, 40); self.size.setValue(values["size"]); self.size.setSuffix(" pt")
        self.spacing = QComboBox()
        for v in LINE_SPACINGS:
            self.spacing.addItem(f"{v / 100:.2f}".replace(".", ",").rstrip("0").rstrip(","), v)
        self.spacing.setCurrentIndex(max(0, self.spacing.findData(values["line"])))
        self.para = QSpinBox(); self.para.setRange(0, 60); self.para.setValue(values["para"]); self.para.setSuffix(" px")
        self.margin = QSpinBox(); self.margin.setRange(4, 400); self.margin.setSingleStep(8)
        self.margin.setValue(values["margin"]); self.margin.setSuffix(" px")
        self.margin.setToolTip("Metnin iki yanındaki boşluk. Geniş ekranda satırları kısaltıp okumayı kolaylaştırır.")
        form.addRow("Yazı tipi", self.family)
        form.addRow("Boyut", self.size)
        form.addRow("Satır aralığı", self.spacing)
        form.addRow("Paragraf aralığı", self.para)
        form.addRow("Kenar boşluğu", self.margin)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.button(QDialogButtonBox.RestoreDefaults).setText("Varsayılanlar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.defaults)
        form.addRow(bb)
        for w in (self.size, self.para, self.margin):
            w.valueChanged.connect(self.emit)
        self.family.currentFontChanged.connect(self.emit)
        self.spacing.currentIndexChanged.connect(self.emit)

    def values(self):
        return {"family": self.family.currentFont().family(), "size": self.size.value(),
                "line": self.spacing.currentData(), "para": self.para.value(), "margin": self.margin.value()}

    def emit(self, *_):
        self.changed.emit(self.values())

    def defaults(self):
        self.family.setCurrentFont(QFont("Segoe UI"))
        self.size.setValue(12); self.spacing.setCurrentIndex(LINE_SPACINGS.index(130))
        self.para.setValue(0); self.margin.setValue(16)

    def reject(self):
        self.changed.emit(self.original)     # vazgeçince eski görünüme dön
        super().reject()


# ───────────────────────────── Özel tema ─────────────────────────────

class CustomThemeDialog(QDialog):
    changed = Signal(dict)

    def __init__(self, parent, theme):
        super().__init__(parent)
        self.setWindowTitle("Özel tema")
        self.original = dict(theme)
        self.colors = {k: complete(theme)[k] for k, _ in EDITABLE_ROLES}
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.buttons = {}
        for r, (key, label) in enumerate(EDITABLE_ROLES):
            grid.addWidget(QLabel(label), r, 0)
            b = QPushButton(); b.setFixedSize(84, 26)
            b.clicked.connect(lambda _=False, k=key: self.pick(k))
            self.buttons[key] = b
            grid.addWidget(b, r, 1)
        lay.addLayout(grid)
        self.preview = QLabel()
        self.preview.setWordWrap(True); self.preview.setMinimumHeight(70)
        lay.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        for k, b in self.buttons.items():
            c = QColor(self.colors[k])
            fg = "#000" if c.lightnessF() > 0.5 else "#fff"
            b.setText(c.name())
            b.setStyleSheet(f"background:{c.name()}; color:{fg}; border:1px solid #888")
        c = self.colors
        self.preview.setText(
            f'<div style="background:{c["base"]}; color:{c["text"]}; padding:8px">Önceki cümle burada durur. '
            f'<span style="background:{c["sent_bg"]}; color:{c["sent_fg"]}">Şu an okunan cümle böyle görünür.</span> '
            f'Sonraki cümle de burada.</div>')
        self.changed.emit(dict(c))

    def pick(self, key):
        col = QColorDialog.getColor(QColor(self.colors[key]), self, "Renk seçin")
        if col.isValid():
            self.colors[key] = col.name()
            self.refresh()

    def result_theme(self):
        return dict(self.colors)

    def reject(self):
        self.changed.emit(self.original)
        super().reject()


def show_done(parent, title, text, path):
    """İşlem bitti iletisi; dosyayı ya da bulunduğu klasörü tek tıkla açar."""
    from .library_info import reveal_in_folder
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(text)
    box.setInformativeText(os.path.normpath(path))
    open_btn = box.addButton("Dosyayı Aç", QMessageBox.ActionRole)
    folder_btn = box.addButton("Klasörde Göster", QMessageBox.ActionRole)
    ok = box.addButton("Tamam", QMessageBox.AcceptRole)
    box.setDefaultButton(ok)
    box.exec()
    clicked = box.clickedButton()
    if clicked is open_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    elif clicked is folder_btn:
        reveal_in_folder(path)

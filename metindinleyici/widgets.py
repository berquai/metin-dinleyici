# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Yardımcı arayüz bileşenleri: katlanabilir bölüm, kısalan etiket, tam ekran denetim çubuğu."""
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


class CollapsibleSection(QWidget):
    """Başlığına tıklanınca içeriğini gizleyen/gösteren bölüm."""
    toggled = Signal(bool)

    def __init__(self, title, parent=None, expanded=True):
        super().__init__(parent)
        self.head = QToolButton()
        self.head.setText(title)
        self.head.setCheckable(True)
        self.head.setChecked(expanded)
        self.head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.head.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.head.setAutoRaise(True)
        self.head.setFocusPolicy(Qt.NoFocus)
        self.head.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        f = self.head.font(); f.setBold(True); self.head.setFont(f)
        self.head.toggled.connect(self.set_expanded)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 2, 2, 6)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.head)
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)
        lay.addWidget(self.body)
        self.body.setVisible(expanded)

    def set_expanded(self, on):
        self.head.blockSignals(True); self.head.setChecked(on); self.head.blockSignals(False)
        self.head.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)
        self.toggled.emit(on)

    def is_expanded(self):
        return self.head.isChecked()


class ElidedLabel(QLabel):
    """Yer daraldığında metni sonunu '…' ile kısaltarak gösterir; tam metin ipucunda kalır."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def full_text(self):
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(10, self.width() - 4)))


class AdaptiveBox(QWidget):
    """Genişlik yeterliyse sütunları yan yana, değilse alt alta dizer.
    Panel alta/üste yerleştirilince sütunlar yan yana açılır, yana yerleştirilince alt alta.

    Karar, kutunun kendi genişliğine göre değil, onu gösteren alanın (kaydırma alanının
    görünür kısmı) genişliğine göre verilir. Kendi genişliğine bakarsa yan yana düzenin
    geniş kalıbı alt alta düzene geçince de üzerinde kalır ve panel pencereden taşar."""

    HYSTERESIS = 40      # sınırda kaydırma çubuğu belirip kaybolunca düzen gidip gelmesin
    direction_changed = Signal(bool)     # True: yan yana

    def __init__(self, threshold=820, parent=None):
        super().__init__(parent)
        self.threshold = threshold
        self.box = QBoxLayout(QBoxLayout.TopToBottom, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(10)
        self._cols = []
        self._watched = None

    def add_column(self, w, stretch=0):
        self._cols.append((w, stretch))
        self.box.addWidget(w, 0)

    def watch(self, widget):
        """Genişliği izlenecek alan (ör. QScrollArea.viewport())."""
        self._watched = widget
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self._watched and ev.type() == QEvent.Resize:
            self.update_direction(obj.width())
        return False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._watched is None:
            self.update_direction(self.width())

    def update_direction(self, available):
        wide_now = self.box.direction() == QBoxLayout.LeftToRight
        limit = self.threshold - (self.HYSTERESIS if wide_now else 0)
        wide = available >= limit
        if wide == wide_now:
            return
        self.box.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        for w, st in self._cols:
            self.box.setStretchFactor(w, st if wide else 0)
        self.box.invalidate()
        self.updateGeometry()
        self.direction_changed.emit(wide)

    def is_wide(self):
        return self.box.direction() == QBoxLayout.LeftToRight


class OverlayBar(QFrame):
    """Tam ekran ve odaklanma modunda fare hareket edince beliren denetim çubuğu."""
    prev_clicked = Signal()
    restart_clicked = Signal()
    play_clicked = Signal()
    next_clicked = Signal()
    exit_clicked = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("overlayBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        def btn(text, tip, sig):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
            return b

        self.prev_btn = btn("◀ Önceki", "Önceki cümle (Ctrl+←)", self.prev_clicked)
        self.restart_btn = btn("↺ Tekrar Oku", "Cümleyi baştan oku (Ctrl+R)", self.restart_clicked)
        self.play_btn = btn("▶ Oku", "Oku / Duraklat (Boşluk)", self.play_clicked)
        self.play_btn.setMinimumWidth(120)
        self.next_btn = btn("Sonraki ▶", "Sonraki cümle (Ctrl+→)", self.next_clicked)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep)
        self.exit_btn = btn("⤢ Tam Ekrandan Çık", "Çık (Esc)", self.exit_clicked)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(2500)
        self.hide_timer.timeout.connect(self.maybe_hide)
        self.hide()

    def apply_colors(self, colors):
        bg = QColor(colors["win"]); bg.setAlpha(235)
        border = QColor(colors["mid"])
        self.setStyleSheet(
            f"#overlayBar {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f" border: 1px solid {border.name()}; border-radius: 12px; }}"
            f"#overlayBar QPushButton {{ padding: 7px 14px; }}")

    def set_exit_text(self, text):
        self.exit_btn.setText(text)

    def reposition(self):
        p = self.parentWidget()
        if p is None:
            return
        self.adjustSize()
        w = min(self.sizeHint().width(), p.width() - 20)
        self.resize(w, self.sizeHint().height())
        self.move((p.width() - w) // 2, p.height() - self.height() - 28)

    def poke(self):
        """Fare hareket etti: göster ve gizleme sayacını yeniden başlat."""
        if not self.isVisible():
            self.reposition()
            self.show()
            self.raise_()
        self.hide_timer.start()

    def maybe_hide(self):
        # Fare çubuğun üzerindeyse gizleme; kullanıcı düğmeye uzanıyor olabilir.
        if self.underMouse():
            self.hide_timer.start()
        else:
            self.hide()


class EmptyState(QWidget):
    """Belge açık değilken metin alanının ortasında görünen karşılama ekranı."""
    open_clicked = Signal()
    library_clicked = Signal()
    guide_clicked = Signal()
    recent_clicked = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.addStretch(1)
        self.title = QLabel("Okumaya başlamak için bir belge açın")
        f = self.title.font(); f.setPointSizeF(f.pointSizeF() * 1.6); f.setBold(True); self.title.setFont(f)
        self.sub = QLabel("PDF, EPUB, DOCX ya da TXT dosyasını bu alana sürükleyip bırakın\n"
                          "ya da Ctrl+O ile açın.")
        self.open_btn = QPushButton("Dosya Aç…")
        self.open_btn.setFocusPolicy(Qt.NoFocus)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_clicked.emit)
        self.lib_btn = QPushButton("Kütüphaneyi Aç")
        self.lib_btn.setFocusPolicy(Qt.NoFocus)
        self.lib_btn.setCursor(Qt.PointingHandCursor)
        self.lib_btn.clicked.connect(self.library_clicked.emit)
        self.guide_btn = QPushButton("Kullanım Kılavuzu (F1)")
        self.guide_btn.setFocusPolicy(Qt.NoFocus)
        self.guide_btn.setCursor(Qt.PointingHandCursor)
        self.guide_btn.clicked.connect(self.guide_clicked.emit)
        self.recent_title = QLabel("Son açılanlar")
        fr = self.recent_title.font(); fr.setBold(True); self.recent_title.setFont(fr)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        self.tip = QLabel("İpucu: Bir cümleye çift tıklayınca okuma oradan başlar.")
        for w in (self.title, self.sub, self.recent_title, self.tip):
            w.setAlignment(Qt.AlignCenter)
            w.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(self.open_btn); row.addWidget(self.lib_btn); row.addWidget(self.guide_btn)
        row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(row)
        lay.addSpacing(10)
        lay.addWidget(self.recent_title)
        lay.addLayout(self.recent_box)
        lay.addSpacing(10)
        lay.addWidget(self.tip)
        lay.addStretch(2)
        self._recent_buttons = []
        self.set_recent([])

    def set_recent(self, paths):
        import os
        for b in self._recent_buttons:
            self.recent_box.removeWidget(b)
            b.deleteLater()
        self._recent_buttons = []
        for p in paths[:3]:
            b = QPushButton(os.path.basename(p))
            b.setFlat(True)
            b.setToolTip(p)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, p=p: self.recent_clicked.emit(p))
            row = b
            self.recent_box.addWidget(row, 0, Qt.AlignHCenter)
            self._recent_buttons.append(b)
        self.recent_title.setVisible(bool(self._recent_buttons))
        if getattr(self, "_colors", None):
            self.apply_colors(self._colors)

    def apply_colors(self, colors):
        self.tip.setStyleSheet(f"color: {colors['mid']};")
        self.sub.setStyleSheet(f"color: {colors['text']};")
        for b in self._recent_buttons:
            b.setStyleSheet(f"QPushButton {{ color: {colors['link']}; text-decoration: underline; border: none;"
                            f" padding: 2px 6px; }}")
        self._colors = colors


class ThinProgress(QWidget):
    """Tam ekran ve odaklanma modunda ekranın en altında duran, dikkat çekmeyen ince ilerleme çizgisi."""
    HEIGHT = 3

    def __init__(self, parent):
        super().__init__(parent)
        self.frac = 0.0
        self.track = QColor(128, 128, 128, 40)
        self.fill = QColor(180, 150, 60, 170)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedHeight(self.HEIGHT)
        self.hide()

    def set_colors(self, colors):
        self.track = QColor(colors["mid"]); self.track.setAlpha(45)
        self.fill = QColor(colors["hl"]); self.fill.setAlpha(170)
        self.update()

    def set_fraction(self, f):
        f = max(0.0, min(1.0, f))
        if abs(f - self.frac) > 0.0005:
            self.frac = f
            self.update()

    def reposition(self):
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(0, p.height() - self.HEIGHT, p.width(), self.HEIGHT)
            self.raise_()

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.fillRect(self.rect(), self.track)
        p.fillRect(0, 0, int(self.width() * self.frac), self.height(), self.fill)
        p.end()

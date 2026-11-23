# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Salt okuma modu: başka işlerle uğraşırken metni takip etmek için küçük, çerçevesiz, istenirse her zaman üstte
kalan pencere (Görünüm › Salt Okuma Modu, Ctrl+Shift+R).

Fare pencerenin üzerinde değilken yalnızca metin ve okunan cümlenin vurgusu görünür. Fare üzerine gelince
ilerleme çubuğu, sayfa/yüzde bilgisi ve düğmeler belirir. Kenarından ya da köşesinden sürükleyerek boyutlandırılır,
metnin üzerinden sürükleyerek taşınır. Fare üzerindeyken (pencere etkin olmasa da) ya da pencere etkinken
Boşluk tuşu okumayı duraklatır / sürdürür.
"""
import bisect

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import APP_NAME
from .paths import IS_WINDOWS

EDGE = 7                      # kenardan boyutlandırma payı (piksel)
DEFAULT_SIZE = (240, 380)     # dikey kredi kartı oranı (54 × 86 mm ≈ 1 : 1,59)
HOTKEY_ID = 0x4D44            # Boşluk için geçici genel kısayol kimliği
WM_HOTKEY = 0x0312
VK_SPACE = 0x20


class MiniReader(QWidget):
    play_clicked = Signal()
    prev_clicked = Signal()
    next_clicked = Signal()
    back_clicked = Signal()
    sentence_activated = Signal(int)          # cümleye çift tıklandı: oradan oku

    def __init__(self, settings, icon=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.settings = settings
        self.setWindowTitle(f"{APP_NAME} — Salt Okuma")
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumSize(150, 150)
        self.setMouseTracking(True)
        self.sentences = []
        self.starts = []
        self.index = 0
        self.colors = {}
        self._press = None                    # (global nokta, kenarlar) — taşıma / boyutlandırma başlangıcı
        self._hotkey = False
        self.on_top = settings.value("mini_on_top", True, type=bool)
        self._apply_flags()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.text = QTextBrowser()
        self.text.setFrameShape(QFrame.NoFrame)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text.setFocusPolicy(Qt.NoFocus)
        self.text.document().setUndoRedoEnabled(False)
        self.text.viewport().setMouseTracking(True)
        self.text.viewport().installEventFilter(self)
        lay.addWidget(self.text)

        # ── fare üzerindeyken beliren üst şerit: ilerleme ──
        self.top = QFrame(self)
        self.top.setObjectName("miniBar")
        tl = QVBoxLayout(self.top)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(3)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 1000)
        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignCenter)
        tl.addWidget(self.bar)
        tl.addWidget(self.info)

        # ── alt şerit: düğmeler ──
        self.bottom = QFrame(self)
        self.bottom.setObjectName("miniBar")
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(6, 6, 6, 6)
        bl.setSpacing(4)
        r1 = QHBoxLayout()
        r1.setSpacing(4)

        def btn(text, tip, sig):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(sig.emit)
            return b
        self.prev_btn = btn("◀", "Önceki cümle (←)", self.prev_clicked)
        self.play_btn = btn("▶", "Oku / Duraklat (Boşluk)", self.play_clicked)
        self.next_btn = btn("▶▶", "Sonraki cümle (→)", self.next_clicked)
        f = self.play_btn.font(); f.setBold(True); self.play_btn.setFont(f)
        r1.addWidget(self.prev_btn); r1.addWidget(self.play_btn, 1); r1.addWidget(self.next_btn)
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.top_check = QCheckBox("Her zaman üstte")
        self.top_check.setFocusPolicy(Qt.NoFocus)
        self.top_check.setChecked(self.on_top)
        self.top_check.toggled.connect(self.set_on_top)
        self.back_btn = btn("⤢", "Ana görünüme dön (Esc)", self.back_clicked)
        r2.addWidget(self.top_check, 1); r2.addWidget(self.back_btn)
        bl.addLayout(r1)
        bl.addLayout(r2)
        for w in (self.top, self.bottom):
            w.setMouseTracking(True)
            w.hide()

        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.setInterval(350)
        self.leave_timer.timeout.connect(self._check_hover)

        geo = settings.value("mini_geometry")
        if geo is None or not self.restoreGeometry(geo):
            self.resize(*DEFAULT_SIZE)
            scr = QApplication.primaryScreen()
            if scr is not None:
                a = scr.availableGeometry()
                self.move(a.right() - DEFAULT_SIZE[0] - 24, a.bottom() - DEFAULT_SIZE[1] - 24)

    # ── pencere bayrakları ──
    def _apply_flags(self):
        flags = Qt.Window | Qt.FramelessWindowHint
        if self.on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def set_on_top(self, on):
        self.on_top = bool(on)
        self.settings.setValue("mini_on_top", self.on_top)
        visible = self.isVisible()
        geo = self.saveGeometry()
        self._apply_flags()                   # bayrak değişince Qt pencereyi gizler: konumu koruyup yeniden göster
        self.restoreGeometry(geo)
        if visible:
            self.show()

    def save_state(self, settings):
        settings.setValue("mini_geometry", self.saveGeometry())
        settings.setValue("mini_on_top", self.on_top)

    # ── içerik ──
    def set_document(self, display, sentences, appearance):
        self.sentences = sentences
        self.starts = [s.start for s in sentences]
        f = QFont(appearance.get("family", "Segoe UI"))
        size = self.settings.value("mini_font_size", None)
        try:
            size = int(size) if size is not None else int(appearance.get("size", 12))
        except (TypeError, ValueError):
            size = int(appearance.get("size", 12))
        f.setPointSize(max(7, size))
        self.text.setFont(f)
        doc = self.text.document()
        doc.setDefaultFont(f)
        doc.setDocumentMargin(10)
        self.text.setPlainText(display)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(float(appearance.get("line", 130)), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        fmt.setBottomMargin(float(appearance.get("para", 0)))
        cur = QTextCursor(doc)
        cur.select(QTextCursor.Document)
        cur.mergeBlockFormat(fmt)

    def apply_colors(self, colors):
        self.colors = dict(colors)
        bg = QColor(colors["win"])
        self.setStyleSheet(
            f"#miniBar {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},238); border: 1px solid {colors['mid']};"
            f" border-radius: 8px; }}"
            f"#miniBar QPushButton {{ padding: 4px 6px; }}"
            f"#miniBar QLabel {{ color: {colors['text']}; }}")
        if self.sentences:
            self.set_current(self.index, scroll=False)

    def set_current(self, i, scroll=True):
        if not self.sentences:
            return
        self.index = max(0, min(len(self.sentences) - 1, i))
        s = self.sentences[self.index]
        cur = QTextCursor(self.text.document())
        cur.setPosition(s.start)
        cur.setPosition(s.end, QTextCursor.KeepAnchor)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cur
        sel.format.setBackground(QColor(self.colors.get("sent_bg", "#e8d98d")))
        sel.format.setForeground(QColor(self.colors.get("sent_fg", "#201e18")))
        self.text.setExtraSelections([sel])
        if scroll:
            self.scroll_to_current()

    def scroll_to_current(self):
        if not self.sentences:
            return
        s = self.sentences[self.index]
        c = QTextCursor(self.text.document())
        c.setPosition(s.start)
        top = self.text.cursorRect(c).top()
        c.setPosition(s.end)
        bottom = self.text.cursorRect(c).bottom()
        vp = self.text.viewport().height()
        sb = self.text.verticalScrollBar()
        # Okunan cümle pencerenin üst üçte birinde dursun; çok uzunsa başı görünsün.
        lead = int(vp * 0.3) if bottom - top < vp * 0.6 else 6
        sb.setValue(sb.value() + top - lead)

    def set_progress(self, frac, text):
        self.bar.setValue(int(round(max(0.0, min(1.0, frac)) * 1000)))
        self.info.setText(text)

    def set_playing(self, state):
        self.play_btn.setText({"playing": "⏸", "paused": "▶", "loading": "⏳", "idle": "▶"}.get(state, "▶"))
        self.play_btn.setToolTip("Duraklat (Boşluk)" if state == "playing" else "Oku (Boşluk)")

    # ── üzerine gelince denetimler ──
    def _layout_bars(self):
        w = self.width()
        m = 6
        self.top.adjustSize()
        self.top.setGeometry(m, m, w - 2 * m, self.top.sizeHint().height())
        h = self.bottom.sizeHint().height()
        self.bottom.setGeometry(m, self.height() - h - m, w - 2 * m, h)

    def show_controls(self, on):
        if on:
            self._layout_bars()
            for b in (self.top, self.bottom):
                b.show(); b.raise_()
        else:
            for b in (self.top, self.bottom):
                b.hide()

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hovered()

    def _hovered(self):
        self.leave_timer.stop()
        self.show_controls(True)
        self._grab_space(True)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.leave_timer.start()

    def _check_hover(self):
        # Alt pencerelere (düğmeler, ipuçları) geçerken yanlışlıkla gizlenmesin
        if self.geometry().contains(self.cursor().pos()) or self._press is not None:
            return
        self.show_controls(False)
        self._grab_space(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.top.isVisible():
            self._layout_bars()
        QTimer.singleShot(0, self.scroll_to_current)

    def hideEvent(self, e):
        self._grab_space(False)
        super().hideEvent(e)

    # ── Boşluk: fare üzerindeyken pencere etkin olmasa da çalışsın ──
    def _grab_space(self, on):
        """Windows'ta fare pencerenin üzerindeyken Boşluk tuşunu geçici olarak bu pencereye ayırır; fare
        ayrılınca bırakılır. Pencere etkinken tuş zaten keyPressEvent'e gelir."""
        if not IS_WINDOWS or on == self._hotkey:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            if on:
                self._hotkey = bool(user32.RegisterHotKey(hwnd, HOTKEY_ID, 0x4000, VK_SPACE))  # MOD_NOREPEAT
            else:
                user32.UnregisterHotKey(hwnd, HOTKEY_ID)
                self._hotkey = False
        except Exception:
            self._hotkey = False

    def nativeEvent(self, event_type, message):
        if IS_WINDOWS and self._hotkey:
            try:
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.play_clicked.emit()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space:
            self.play_clicked.emit()
        elif k == Qt.Key_Left:
            self.prev_clicked.emit()
        elif k == Qt.Key_Right:
            self.next_clicked.emit()
        elif k == Qt.Key_Escape:
            self.back_clicked.emit()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        # Alt+F4 ya da görev çubuğundan kapatma: ana görünüme dön (program kapanmasın)
        e.ignore()
        self.back_clicked.emit()

    # ── çerçevesiz pencereyi taşıma ve boyutlandırma ──
    def _edges(self, p):
        r = self.rect()
        e = Qt.Edge(0)
        if p.x() <= EDGE:
            e |= Qt.LeftEdge
        elif p.x() >= r.width() - EDGE:
            e |= Qt.RightEdge
        if p.y() <= EDGE:
            e |= Qt.TopEdge
        elif p.y() >= r.height() - EDGE:
            e |= Qt.BottomEdge
        return e

    def _cursor_for(self, e):
        if e in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if e in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if e & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if e & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return None

    def eventFilter(self, obj, ev):
        if obj is self.text.viewport():
            t = ev.type()
            if t == QEvent.Wheel and ev.modifiers() & Qt.ControlModifier:
                # Ctrl+tekerlek: bu penceredeki yazıyı büyüt / küçült (ana pencereyi etkilemez)
                f = self.text.font()
                f.setPointSize(max(7, min(40, f.pointSize() + (1 if ev.angleDelta().y() > 0 else -1))))
                self.text.setFont(f)
                self.text.document().setDefaultFont(f)
                self.settings.setValue("mini_font_size", f.pointSize())
                QTimer.singleShot(0, self.scroll_to_current)
                return True
            if t in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                     QEvent.MouseButtonDblClick):
                p = self.mapFromGlobal(ev.globalPosition().toPoint())
                if t == QEvent.MouseMove:
                    if self._press is not None and ev.buttons() & Qt.LeftButton:
                        start, edges = self._press
                        if (ev.globalPosition().toPoint() - start).manhattanLength() > 4:
                            self._press = None
                            wh = self.windowHandle()
                            if wh is not None:
                                if edges:
                                    wh.startSystemResize(edges)
                                else:
                                    wh.startSystemMove()
                        return True
                    c = self._cursor_for(self._edges(p))
                    if c is None:
                        obj.setCursor(Qt.SizeAllCursor if self.top.isVisible() else Qt.ArrowCursor)
                    else:
                        obj.setCursor(c)
                    if not self.top.isVisible():
                        self._hovered()
                    return False
                if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                    self._press = (ev.globalPosition().toPoint(), self._edges(p))
                    self.activateWindow()
                    return True
                if t == QEvent.MouseButtonRelease:
                    self._press = None
                    return True
                if t == QEvent.MouseButtonDblClick and self.sentences:
                    pos = self.text.cursorForPosition(ev.position().toPoint()).position()
                    self.sentence_activated.emit(max(0, bisect.bisect_right(self.starts, pos) - 1))
                    return True
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, e):
        # Kenar payı denetim şeritlerinin dışında kalan yerlerde de çalışsın
        if e.button() == Qt.LeftButton:
            edges = self._edges(e.position().toPoint())
            wh = self.windowHandle()
            if wh is not None:
                if edges:
                    wh.startSystemResize(edges)
                else:
                    wh.startSystemMove()
        super().mousePressEvent(e)

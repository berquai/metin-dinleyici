# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Orijinal belge paneli: PDF ve EPUB sayfalarını görüntüler, gezinme, yakınlaştırma, resim kaydetme.

Sayfalar alt alta dizilir ve serbestçe kaydırılır (sayfa sonunda takılma yok); yalnızca görünür alana düşen
sayfalar ve hemen komşuları çizilip bellekte tutulur.

Sayfalar ayrı ve tek bir iş parçacığında çizilir; PDF motoru programın başka yerlerinde de (metin çıkarma,
kütüphane kapakları) arka planda çalıştığı için her çağrı ortak kilitle korunur (bkz. pdflock.py). Dosya diske kilitlenmesin diye belleğe okunarak açılır: Windows açık dosyaları
yeniden adlandırmaya ve silmeye izin vermez.
"""
import os
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRect, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget, QAbstractSpinBox,
)

from .pdflock import FITZ_LOCK   # PDF motoruna aynı anda tek iş parçacığı (bkz. pdflock.py)

ZOOMS = [("Genişliğe sığdır", "width"), ("Sayfaya sığdır", "page"), ("%50", 0.5), ("%75", 0.75), ("%100", 1.0),
         ("%125", 1.25), ("%150", 1.5), ("%200", 2.0), ("%300", 3.0)]
VIEWABLE = (".pdf", ".epub")


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz


class _Worker:
    """Belgeyi açık tutan ve sayfaları çizen tek iş parçacıklı yardımcı."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.doc = None
        self.path = None

    def _open(self, path):
        with FITZ_LOCK:
            return self._open_locked(path)

    def _open_locked(self, path):
        if self.path != path:
            self._close()
            fitz = _fitz()
            with open(path, "rb") as f:
                data = f.read()
            self.doc = fitz.open(stream=data, filetype=os.path.splitext(path)[1].lstrip(".").lower())
            self.path = path
        return self.doc

    def _close(self):
        with FITZ_LOCK:
            self._close_locked()

    def _close_locked(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc, self.path = None, None

    def info(self, path):
        with FITZ_LOCK:
            return self._info(path)

    def _info(self, path):
        doc = self._open(path)
        if doc.needs_pass:
            raise RuntimeError("Belge parola korumalı.")
        labels, sizes = [], []
        for i, page in enumerate(doc):
            try:
                labels.append(page.get_label() or str(i + 1))
            except Exception:
                labels.append(str(i + 1))
            sizes.append((page.rect.width, page.rect.height))
        return {"count": len(doc), "labels": labels, "sizes": sizes}

    def render(self, path, index, zoom, rotate):
        with FITZ_LOCK:
            return self._render(path, index, zoom, rotate)

    def _render(self, path, index, zoom, rotate):
        fitz = _fitz()
        doc = self._open(path)
        page = doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(rotate), alpha=False)
        return pix.width, pix.height, pix.stride, bytes(pix.samples)

    def save(self, path, index, dpi, out, rotate):
        with FITZ_LOCK:
            return self._save(path, index, dpi, out, rotate)

    def _save(self, path, index, dpi, out, rotate):
        fitz = _fitz()
        doc = self._open(path)
        z = dpi / 72
        pix = doc[index].get_pixmap(matrix=fitz.Matrix(z, z).prerotate(rotate), alpha=False)
        if out.lower().endswith((".jpg", ".jpeg")):
            pix.save(out, jpg_quality=92)
        else:
            pix.save(out)
        return out

    def submit(self, fn, *args):
        return self.pool.submit(fn, *args)

    def shutdown(self):
        self.pool.submit(self._close)
        self.pool.shutdown(wait=False, cancel_futures=True)


class _Signals(QObject):
    info_ready = Signal(object)
    page_ready = Signal(object)
    saved = Signal(object)


class _Pages(QWidget):
    """Sayfaları alt alta dizen tuval. Yalnızca boyanan alana düşen sayfalar çizilir; görüntüsü henüz hazır
    olmayan sayfanın yerinde boş bir sayfa durur. Yakınlaştırma değişince eski görüntü yenisi gelene dek ölçeklenir."""
    GAP = 10

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.rects = []
        self.tops = []

    def set_rects(self, rects, width, height):
        self.rects = rects
        self.tops = [r.top() for r in rects]
        self.resize(width, height)
        self.update()

    def page_at(self, y):
        k = bisect_right(self.tops, y) - 1
        return max(0, min(len(self.rects) - 1, k))

    def paintEvent(self, e):
        p = QPainter(self)
        clip = e.rect()
        p.fillRect(clip, self.palette().color(QPalette.Window).darker(112))
        if self.rects:
            labels = self.view.labels
            for k in range(self.page_at(clip.top()), self.page_at(clip.bottom()) + 1):
                r = self.rects[k]
                if not r.intersects(clip):
                    continue
                p.fillRect(r.translated(2, 2), QColor(0, 0, 0, 50))          # hafif gölge
                c = self.view.cache.get(k)
                if c is not None:
                    p.drawImage(r, c[0])
                else:
                    p.fillRect(r, Qt.white)
                    p.setPen(QColor(160, 160, 160))
                    p.drawText(r, Qt.AlignCenter, labels[k] if k < len(labels) else str(k + 1))
        p.end()


class DocView(QWidget):
    offset_changed = Signal(int)          # kullanıcı sayfa kaymasını ayarladı (belgeye özel saklanır)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.offset = 0                   # sayfa kayması: okunan sayfa ile gösterilen sayfa arasındaki fark
        self._last_base = None
        self.worker = _Worker()
        self.sig = _Signals(self)
        self.sig.info_ready.connect(self.on_info)
        self.sig.page_ready.connect(self.on_page)
        self.sig.saved.connect(self.on_saved)
        self.path = None
        self.count = 0
        self.labels, self.sizes = [], []
        self.index = 0
        self.rotate = 0
        self.gen = 0                      # çizim kuşağı: yakınlaştırma/döndürme değişince artar
        self.cache = {}                   # sayfa sırası → (QImage, kuşak)
        self._pending = set()             # (sayfa, kuşak) çiziliyor
        self._wanted = set()              # şu an görünür olan ve komşu sayfalar (iş parçacığı da okur)
        self._render_key = None
        self._jumping = False             # programla kaydırılırken geçerli sayfa yeniden hesaplanmasın
        self.reading_index = None
        self.reading_label = None
        self.setMinimumWidth(320)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(2)

        def tb(text, tip, slot):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b
        self.first_btn = tb("⏮", "İlk sayfa (Home)", lambda: self.show_page(0))
        self.prev_btn = tb("◀", "Önceki sayfa (PageUp)", lambda: self.show_page(self.index - 1))
        self.page_spin = QSpinBox()
        self.page_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setMinimumWidth(56)
        self.page_spin.setRange(0, 0)
        self.page_spin.valueChanged.connect(lambda v: self.show_page(v - 1) if v > 0 else None)
        bar.addWidget(self.page_spin)
        self.count_label = QLabel("/ 0")
        bar.addWidget(self.count_label)
        self.next_btn = tb("▶", "Sonraki sayfa (PageDown)", lambda: self.show_page(self.index + 1))
        self.last_btn = tb("⏭", "Son sayfa (End)", lambda: self.show_page(self.count - 1))
        bar.addSpacing(6)
        tb("−", "Uzaklaştır (Ctrl+tekerlek)", lambda: self.step_zoom(-1))
        self.zoom = QComboBox()
        for label, val in ZOOMS:
            self.zoom.addItem(label, val)
        self.zoom.setFocusPolicy(Qt.NoFocus)
        saved = self.settings.value("doc_zoom", "width")
        idx = next((k for k, (_, v) in enumerate(ZOOMS) if str(v) == str(saved)), 0)
        self.zoom.setCurrentIndex(idx)
        self.zoom.activated.connect(lambda _: self.on_zoom_changed())
        bar.addWidget(self.zoom)
        tb("+", "Yakınlaştır (Ctrl+tekerlek)", lambda: self.step_zoom(1))
        # Tek tıkla sığdırma (açılır listeyi açmadan)
        self.fit_width_btn = tb("↔", "Genişliğe sığdır", lambda: self.set_zoom_mode("width"))
        self.fit_page_btn = tb("↕", "Sayfaya sığdır (sayfanın tamamı görünür)", lambda: self.set_zoom_mode("page"))
        bar.addStretch(1)
        self.reading_btn = tb("⌖", "Okunan cümlenin sayfasına git", self.goto_reading)
        self.calib_btn = tb("⇆ Eşle", "Sayfa kalibrasyonu: panel yanlış sayfayı gösteriyorsa okunan metnin bulunduğu "
                                      "sayfayı açın (◀ ▶ ile) ve bu düğmeye basın. Aradaki fark bu belge için "
                                      "hatırlanır ve sonraki tüm sayfalara uygulanır.", self.calibrate_here)
        self.offset_label = QLabel()
        self.offset_label.setToolTip("Bu belgeye uygulanan sayfa kayması. Sıfırlamak için ⋯ menüsü.")
        self.offset_label.hide()
        bar.addWidget(self.offset_label)
        self.follow = QCheckBox("İzle")
        self.follow.setToolTip("Okuma ilerledikçe okunan cümlenin sayfasını kendiliğinden göster")
        self.follow.setFocusPolicy(Qt.NoFocus)
        self.follow.setChecked(self.settings.value("doc_follow", False, type=bool))
        self.follow.toggled.connect(self.on_follow_toggled)
        bar.addWidget(self.follow)
        more = QToolButton()
        more.setText("⋯")
        more.setToolTip("Sayfa işlemleri")
        more.setAutoRaise(True)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setFocusPolicy(Qt.NoFocus)
        menu = QMenu(more)
        menu.addAction("Sayfayı Resim Olarak Kaydet…", self.save_image)
        menu.addAction("Sayfayı Panoya Kopyala", self.copy_image)
        menu.addSeparator()
        menu.addAction("Saat Yönünde Döndür", lambda: self.set_rotate(self.rotate + 90))
        menu.addAction("Döndürmeyi Sıfırla", lambda: self.set_rotate(0))
        menu.addSeparator()
        menu.addAction("Gösterilen Sayfayı Okunan Sayfa Olarak Eşle", self.calibrate_here)
        menu.addAction("Sayfa Kaymasını Elle Ayarla…", self.ask_offset)
        menu.addAction("Sayfa Kaymasını Sıfırla", lambda: self.change_offset(0))
        menu.addSeparator()
        menu.addAction("Belgeyi Varsayılan Uygulamada Aç", self.open_external)
        more.setMenu(menu)
        bar.addWidget(more)
        lay.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        # Çubuk hep görünür: sığdırma kipinde çubuk açılıp kapandıkça genişliğin zıplaması önlenir.
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.canvas = _Pages(self)
        self.scroll.setWidget(self.canvas)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.setFocusPolicy(Qt.StrongFocus)
        self._drag = None                 # fareyle tutup sürükleme: (başlangıç noktası, yatay, dikey kaydırma)
        self.canvas.setAttribute(Qt.WA_TransparentForMouseEvents)   # fare olayları görünüm alanına gitsin
        self.scroll.verticalScrollBar().valueChanged.connect(self.on_scrolled)
        # Tekerlekle yumuşak kaydırma: her çentik hedefi ilerletir, çubuk oraya kısa bir canlandırmayla kayar.
        self._smooth = QVariantAnimation(self)
        self._smooth.setDuration(160)
        self._smooth.setEasingCurve(QEasingCurve.OutCubic)
        self._smooth.valueChanged.connect(lambda v: self.scroll.verticalScrollBar().setValue(round(v)))
        self._smooth_target = 0
        self.want_timer = QTimer(self)
        self.want_timer.setSingleShot(True)
        self.want_timer.setInterval(30)
        self.want_timer.timeout.connect(self.request_visible)
        lay.addWidget(self.scroll, 1)
        self.info = QLabel("Belge açık değil.")
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.info)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(150)
        self.resize_timer.timeout.connect(self.relayout)
        for key, fn in ((Qt.Key_PageDown, lambda: self.show_page(self.index + 1)),
                        (Qt.Key_PageUp, lambda: self.show_page(self.index - 1)),
                        (Qt.Key_Home, lambda: self.show_page(0)),
                        (Qt.Key_End, lambda: self.show_page(self.count - 1))):
            QShortcut(QKeySequence(key), self, fn, context=Qt.WidgetWithChildrenShortcut)
        self.update_controls()

    # ── belge ──
    def open(self, path):
        if path and os.path.normcase(path) == os.path.normcase(self.path or "") and self.count:
            return
        self.clear()
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in VIEWABLE:
            self.info.setText("Orijinal görünüm yalnızca PDF ve EPUB belgelerinde var. "
                              "DOCX ve TXT dosyalarının metni zaten okuma alanında olduğu gibi görünüyor.")
            self.info.show()
            return
        self.path = path
        self.gen += 1
        g = self.gen
        self.info.setText("Belge açılıyor…")
        self.info.show()

        def done(f):
            try:
                r = {"gen": g, "info": f.result()}
            except Exception as e:
                r = {"gen": g, "error": str(e)}
            self._emit(self.sig.info_ready, r)
        self.worker.submit(self.worker.info, path).add_done_callback(done)

    def clear(self):
        self.gen += 1
        self.path, self.count, self.labels, self.sizes = None, 0, [], []
        self.index, self.reading_index, self.reading_label = 0, None, None
        self._last_base = None
        self.cache.clear(); self._pending.clear(); self._wanted = set()
        self._render_key = None
        self._smooth.stop()
        self.canvas.set_rects([], 0, 0)
        self.info.setText("Belge açık değil.")
        self.info.show()
        self.update_controls()

    def on_info(self, r):
        if r["gen"] != self.gen:
            return
        if "error" in r:
            self.info.setText(f"Belge görüntülenemedi: {r['error']}")
            return
        i = r["info"]
        self.count, self.labels, self.sizes = i["count"], i["labels"], i["sizes"]
        self.info.hide()
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, max(1, self.count))
        self.page_spin.blockSignals(False)
        self.count_label.setText(f"/ {self.count}")
        # Belge açılınca okunan cümlenin sayfasından başla
        self.reading_index = self.page_for_label(self.reading_label) if self.reading_label else None
        start = self.reading_index if self.reading_index is not None else 0
        self.index = start
        self.relayout()
        self.show_page(start)

    def base_page_for_label(self, label):
        """Okuma alanındaki bölüm etiketinden ('Sayfa 45') sayfa sırasını bulur (kayma uygulanmadan).
        Aynı etiket birden çok sayfada varsa (ör. her bölümde yeniden 1'den başlayan numaralar) bir önceki
        okunan sayfaya en yakın olanı seçilir; ilk eşleşmeye atlamak panelin yanlış sayfayı izlemesine yol açıyordu."""
        lab = label[6:] if label.startswith("Sayfa ") else label
        hits = [k for k, l in enumerate(self.labels) if l == lab]
        if not hits:
            if lab.isdigit() and 0 < int(lab) <= self.count:
                return int(lab) - 1
            return None
        if len(hits) == 1:
            return hits[0]
        ref = self._last_base if self._last_base is not None else self.index
        return min(hits, key=lambda k: abs(k - ref))

    def page_for_label(self, label):
        """Sayfa kayması (kalibrasyon) uygulanmış sayfa sırası."""
        base = self.base_page_for_label(label)
        if base is None:
            return None
        self._last_base = base
        return max(0, min(self.count - 1, base + self.offset))

    # ── sayfa kalibrasyonu ──
    def set_offset(self, n):
        """Belge açılırken kaydedilmiş kaymayı uygular (sinyal göndermez)."""
        self.offset = int(n or 0)
        self._last_base = None
        self.update_offset_label()
        if self.count and self.reading_label:
            self.reading_index = self.page_for_label(self.reading_label)
            self.update_controls()

    def change_offset(self, n):
        n = int(n)
        if n == self.offset:
            return
        self.offset = n
        self.update_offset_label()
        if self.count and self.reading_label:
            self.reading_index = self.page_for_label(self.reading_label)
            self.update_controls()
            if self.reading_index is not None:
                self.show_page(self.reading_index)
        self.offset_changed.emit(n)

    def calibrate_here(self):
        """Şu an gösterilen sayfa = okunan cümlenin sayfası: aradaki farkı kayma olarak kaydeder."""
        if not self.count or not self.reading_label:
            QMessageBox.information(self, "Sayfa kalibrasyonu",
                                    "Önce bir PDF açıp okumaya başlayın; ardından okunan metnin bulunduğu sayfayı "
                                    "◀ ▶ ile açıp “Eşle”ye basın.")
            return
        base = self.base_page_for_label(self.reading_label)
        if base is None:
            QMessageBox.information(self, "Sayfa kalibrasyonu",
                                    "Okunan cümlenin sayfa bilgisi belgede bulunamadı; kayma “⋯ › Sayfa Kaymasını "
                                    "Elle Ayarla” ile girilebilir.")
            return
        self.change_offset(self.index - base)

    def ask_offset(self):
        n, ok = QInputDialog.getInt(
            self, "Sayfa kayması",
            "Okunan sayfaya göre kaç sayfa ileri (+) ya da geri (−) gidilsin?\n"
            "Ör. panel hep 2 sayfa geriden geliyorsa 2 yazın.", self.offset, -9999, 9999)
        if ok:
            self.change_offset(n)

    def update_offset_label(self):
        self.offset_label.setText(f"kayma {self.offset:+d}")
        self.offset_label.setVisible(bool(self.offset))

    # ── gösterim ──
    def show_page(self, i):
        """i. sayfanın başını görünür alanın üstüne getirir."""
        if not self.count:
            return
        i = max(0, min(self.count - 1, i))
        self.index = i
        self._smooth.stop()
        if i < len(self.canvas.rects):
            self._jumping = True
            try:
                self.scroll.verticalScrollBar().setValue(self.canvas.rects[i].top() - _Pages.GAP)
            finally:
                self._jumping = False
        self.update_controls()
        self.want_timer.start()

    def _page_pts(self, k):
        pw, ph = self.sizes[k] if k < len(self.sizes) else (595, 842)
        if self.rotate % 180:
            pw, ph = ph, pw
        return max(1.0, pw), max(1.0, ph)

    def page_scale(self, k):
        """k. sayfanın ekran pikseli / PDF noktası oranı."""
        val = self.zoom.currentData()
        pw, ph = self._page_pts(k)
        vw = max(50, self.scroll.viewport().width() - 2 * _Pages.GAP)
        vh = max(50, self.scroll.viewport().height() - 2 * _Pages.GAP)
        if val == "width":
            return vw / pw
        if val == "page":
            return min(vw / pw, vh / ph)
        return float(val) * 96 / 72                      # %100 = ekranda gerçek boyut (96 dpi)

    def zoom_factor(self):
        return self.page_scale(self.index) if self.sizes else 1.0

    def relayout(self):
        """Sayfaların yerini ve boyutunu yeniden hesaplar; okunan konum (sayfa ve sayfa içindeki oran) korunur."""
        if not self.count:
            return
        G = _Pages.GAP
        anchor = None
        old = self.canvas.rects
        if self.index < len(old) and old[self.index].height() > 0:
            r = old[self.index]
            anchor = (self.index, (self.scroll.verticalScrollBar().value() + G - r.top()) / r.height())
        vp = self.scroll.viewport()
        val = self.zoom.currentData()
        dpr = self.devicePixelRatioF()
        key = (str(val), self.rotate, dpr, vp.width() if val in ("width", "page") else None,
               vp.height() if val == "page" else None)
        if key != self._render_key:
            self._render_key = key
            self.gen += 1                              # eski görüntüler yenisi gelene dek ölçeklenerek kalır
            self._pending.clear()
        dims = []
        for k in range(self.count):
            s = self.page_scale(k)
            pw, ph = self._page_pts(k)
            dims.append((max(1, round(pw * s)), max(1, round(ph * s))))
        width = max(vp.width(), max(w for w, _ in dims) + 2 * G)
        rects, y = [], G
        for w, h in dims:
            rects.append(QRect((width - w) // 2, y, w, h))
            y += h + G
        height = max(vp.height(), y)
        self.canvas.set_rects(rects, width, height)
        # Kaydırma çubuklarının aralığı QScrollArea'nın gecikmeli güncellemesini beklemeden ayarlanır; yoksa hemen
        # ardından yapılan konumlandırma (show_page, konum koruma) eski aralığa kırpılır.
        self._jumping = True
        try:
            self.scroll.verticalScrollBar().setRange(0, max(0, height - vp.height()))
            self.scroll.horizontalScrollBar().setRange(0, max(0, width - vp.width()))
        finally:
            self._jumping = False
        if anchor is not None:
            k, frac = anchor
            self._jumping = True
            try:
                self.scroll.verticalScrollBar().setValue(round(rects[k].top() - G + frac * rects[k].height()))
            finally:
                self._jumping = False
        self.want_timer.start()
        QTimer.singleShot(0, self.update_pan_cursor)

    def visible_range(self):
        if not self.canvas.rects:
            return 0, -1
        y0 = self.scroll.verticalScrollBar().value()
        return self.canvas.page_at(y0), self.canvas.page_at(y0 + self.scroll.viewport().height())

    def on_scrolled(self, _v):
        if self._jumping or not self.canvas.rects:
            return
        a, b = self.visible_range()
        y0 = self.scroll.verticalScrollBar().value()
        y1 = y0 + self.scroll.viewport().height()
        rects = self.canvas.rects
        # Görünür alanın en büyük kısmını kaplayan sayfa "geçerli sayfa" sayılır.
        k = max(range(a, b + 1), key=lambda j: min(y1, rects[j].bottom()) - max(y0, rects[j].top()))
        if k != self.index:
            self.index = k
            self.update_controls()
        self.want_timer.start()

    def render(self):
        """Sayfa düzenini yeniler ve görünür sayfaları yeniden çizdirir."""
        self.relayout()

    def request_visible(self):
        if not self.count or not self.path or not self.canvas.rects:
            return
        a, b = self.visible_range()
        want = set(range(max(0, a - 1), min(self.count, b + 2)))
        self._wanted = want
        keep = range(a - 3, b + 4)
        for k in [k for k in self.cache if k not in keep]:
            del self.cache[k]                          # uzaktaki sayfaların görüntüsü bellekte tutulmaz
        dpr = self.devicePixelRatioF()
        for k in sorted(want, key=lambda j: (j < a or j > b, abs(j - self.index))):
            c = self.cache.get(k)
            if (c is not None and c[1] == self.gen) or (k, self.gen) in self._pending:
                continue
            self._pending.add((k, self.gen))
            g = self.gen

            def done(f, k=k, g=g):
                try:
                    r = {"gen": g, "index": k, "img": f.result(), "dpr": dpr}
                except Exception as e:
                    r = {"gen": g, "index": k, "error": str(e)}
                self._emit(self.sig.page_ready, r)
            self.worker.submit(self._render_job, self.path, k, self.page_scale(k) * dpr, self.rotate, g
                               ).add_done_callback(done)

    def _render_job(self, path, k, zoom, rotate, gen):
        # Hızlı kaydırmada sıraya giren ama artık görünmeyen sayfalar boşuna çizilmesin.
        if gen != self.gen or k not in self._wanted:
            return None
        return self.worker.render(path, k, zoom, rotate)

    def on_page(self, r):
        self._pending.discard((r["index"], r["gen"]))
        if r["gen"] != self.gen:
            return                                    # daha yeni bir istek var
        if "error" in r:
            self.info.setText(f"Sayfa çizilemedi: {r['error']}")
            self.info.show()
            return
        if r["img"] is None:                          # atlandı; yeniden görünür olduysa yine istensin
            if r["index"] in self._wanted:
                self.want_timer.start()
            return
        w, h, stride, data = r["img"]
        img = QImage(data, w, h, stride, QImage.Format_RGB888).copy()
        img.setDevicePixelRatio(r["dpr"])
        k = r["index"]
        self.cache[k] = (img, r["gen"])
        if k < len(self.canvas.rects):
            self.canvas.update(self.canvas.rects[k].adjusted(0, 0, 3, 3))

    def update_controls(self):
        has = self.count > 0
        for b in (self.first_btn, self.prev_btn):
            b.setEnabled(has and self.index > 0)
        for b in (self.next_btn, self.last_btn):
            b.setEnabled(has and self.index < self.count - 1)
        self.page_spin.setEnabled(has)
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.index + 1 if has else 0)
        self.page_spin.blockSignals(False)
        lab = self.labels[self.index] if has and self.index < len(self.labels) else ""
        self.page_spin.setToolTip(f"Belgedeki sayfa etiketi: {lab}" if lab and lab != str(self.index + 1) else "")
        self.reading_btn.setEnabled(has and self.reading_index is not None)
        self.calib_btn.setEnabled(has and bool(self.reading_label))

    def set_zoom_mode(self, mode):
        k = next((i for i, (_, v) in enumerate(ZOOMS) if v == mode), None)
        if k is not None:
            self.zoom.setCurrentIndex(k)
            self.on_zoom_changed()

    def can_pan(self):
        h, v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        return h.maximum() > h.minimum() or v.maximum() > v.minimum()

    def update_pan_cursor(self):
        vp = self.scroll.viewport()
        if self._drag is not None:
            vp.setCursor(Qt.ClosedHandCursor)
        elif self.can_pan():
            vp.setCursor(Qt.OpenHandCursor)
        else:
            vp.unsetCursor()

    def on_zoom_changed(self):
        self.settings.setValue("doc_zoom", str(self.zoom.currentData()))
        self.relayout()

    def step_zoom(self, d):
        cur = self.zoom_factor() * 72 / 96
        fixed = [v for _, v in ZOOMS if isinstance(v, float)]
        if d > 0:
            nxt = next((v for v in fixed if v > cur + 0.01), fixed[-1])
        else:
            nxt = next((v for v in reversed(fixed) if v < cur - 0.01), fixed[0])
        self.zoom.setCurrentIndex(next(k for k, (_, v) in enumerate(ZOOMS) if v == nxt))
        self.on_zoom_changed()

    def set_rotate(self, deg):
        self.rotate = deg % 360
        self.relayout()

    WHEEL_PX = 120                                     # bir tekerlek çentiğinde kaydırılan piksel

    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport():
            t = ev.type()
            # Sayfayı fareyle tutup sürükleyerek gezdirme (kaydırma çubuklarına gerek kalmadan)
            if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton and self.can_pan():
                self._smooth.stop()
                h, v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
                self._drag = (ev.position().toPoint(), h.value(), v.value())
                self.update_pan_cursor()
                return True
            if t == QEvent.MouseMove and self._drag is not None:
                start, hv, vv = self._drag
                d = ev.position().toPoint() - start
                self.scroll.horizontalScrollBar().setValue(hv - d.x())
                self.scroll.verticalScrollBar().setValue(vv - d.y())
                return True
            if t == QEvent.MouseButtonRelease and self._drag is not None:
                self._drag = None
                self.update_pan_cursor()
                return True
            if t == QEvent.Resize:
                self.resize_timer.start()             # sığdırma ve ortalama yeni boyuta göre yenilensin
                QTimer.singleShot(0, self.update_pan_cursor)
            if t == QEvent.Wheel:
                dy = ev.angleDelta().y()
                if ev.modifiers() & Qt.ControlModifier:
                    if dy:
                        self.step_zoom(1 if dy > 0 else -1)
                    return True
                # Dokunmatik yüzey (piksel kaydırma) ve yatay kaydırma Qt'nin kendi davranışında kalır.
                if dy == 0 or not ev.pixelDelta().isNull() or ev.modifiers() & Qt.ShiftModifier:
                    return False
                sb = self.scroll.verticalScrollBar()
                running = self._smooth.state() == QVariantAnimation.Running
                base = self._smooth_target if running else sb.value()
                target = max(sb.minimum(), min(sb.maximum(), base - dy * self.WHEEL_PX / 120))
                self._smooth_target = target
                self._smooth.stop()
                self._smooth.setStartValue(float(sb.value()))
                self._smooth.setEndValue(float(target))
                self._smooth.start()
                return True
        return super().eventFilter(obj, ev)

    # ── okuma ile bağ ──
    def set_reading_label(self, label):
        """Okunan cümlenin bölüm etiketi değişti; 'İzle' açıksa o sayfaya geç."""
        self.reading_label = label
        if not self.count:
            return                                    # sayfa listesi hazır olunca on_info uygular
        k = self.page_for_label(label)
        self.reading_index = k
        self.update_controls()
        if k is not None and self.follow.isChecked() and k != self.index:
            self.show_page(k)

    def goto_reading(self):
        if self.reading_index is not None:
            self.show_page(self.reading_index)

    def on_follow_toggled(self, on):
        self.settings.setValue("doc_follow", on)
        if on:
            self.goto_reading()

    # ── sayfa işlemleri ──
    def save_image(self):
        if not self.count:
            return
        items = ["150 dpi — ekranda okumak için", "300 dpi — baskı ve tez eki için", "600 dpi — çok ayrıntılı"]
        choice, ok = QInputDialog.getItem(self, "Sayfayı resim olarak kaydet", "Çözünürlük:", items,
                                          self.settings.value("doc_dpi_idx", 1, type=int), False)
        if not ok:
            return
        k = items.index(choice)
        self.settings.setValue("doc_dpi_idx", k)
        dpi = (150, 300, 600)[k]
        stem = os.path.splitext(os.path.basename(self.path))[0]
        lab = self.labels[self.index] if self.index < len(self.labels) else str(self.index + 1)
        start = os.path.join(self.settings.value("doc_img_dir", os.path.dirname(self.path)),
                             f"{stem} - sayfa {lab}.png")
        out, _ = QFileDialog.getSaveFileName(self, "Sayfayı kaydet", start, "PNG (*.png);;JPEG (*.jpg)")
        if not out:
            return
        if not out.lower().endswith((".png", ".jpg", ".jpeg")):
            out += ".png"
        self.settings.setValue("doc_img_dir", os.path.dirname(out))

        def done(f):
            try:
                r = {"path": f.result()}
            except Exception as e:
                r = {"error": str(e)}
            self._emit(self.sig.saved, r)
        self.worker.submit(self.worker.save, self.path, self.index, dpi, out, self.rotate).add_done_callback(done)

    def on_saved(self, r):
        if "error" in r:
            QMessageBox.warning(self, "Kaydedilemedi", r["error"])
            return
        from .dialogs import show_done
        show_done(self, "Sayfa kaydedildi", "Sayfa resim olarak kaydedildi.", r["path"])

    def copy_image(self):
        c = self.cache.get(self.index)
        if c is not None:
            QApplication.clipboard().setImage(c[0])

    def open_external(self):
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def _emit(self, signal, payload):
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def shutdown(self):
        self.worker.shutdown()

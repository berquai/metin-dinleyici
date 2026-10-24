# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Orijinal belge paneli: PDF ve EPUB sayfalarını görüntüler, gezinme, yakınlaştırma, resim kaydetme.

Sayfalar ayrı ve tek bir iş parçacığında çizilir (PyMuPDF belge nesneleri iş parçacığı güvenli
değildir). Dosya diske kilitlenmesin diye belleğe okunarak açılır: Windows açık dosyaları
yeniden adlandırmaya ve silmeye izin vermez.
"""
import os
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget, QAbstractSpinBox,
)

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
        if self.path != path:
            self._close()
            fitz = _fitz()
            with open(path, "rb") as f:
                data = f.read()
            self.doc = fitz.open(stream=data, filetype=os.path.splitext(path)[1].lstrip(".").lower())
            self.path = path
        return self.doc

    def _close(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc, self.path = None, None

    def info(self, path):
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
        fitz = _fitz()
        doc = self._open(path)
        page = doc[index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(rotate), alpha=False)
        return pix.width, pix.height, pix.stride, bytes(pix.samples)

    def save(self, path, index, dpi, out, rotate):
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


class DocView(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
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
        self.gen = 0
        self.image = None
        self.reading_index = None
        self.reading_label = None
        self.wheel_acc = 0
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
        bar.addStretch(1)
        self.reading_btn = tb("⌖", "Okunan cümlenin sayfasına git", self.goto_reading)
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
        menu.addAction("Belgeyi Varsayılan Uygulamada Aç", self.open_external)
        more.setMenu(menu)
        bar.addWidget(more)
        lay.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.scroll.setWidgetResizable(False)
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.page_label)
        self.scroll.viewport().installEventFilter(self)
        self.scroll.setFocusPolicy(Qt.StrongFocus)
        lay.addWidget(self.scroll, 1)
        self.info = QLabel("Belge açık değil.")
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.info)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(150)
        self.resize_timer.timeout.connect(self.render)
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
        self.index, self.image, self.reading_index, self.reading_label = 0, None, None, None
        self.page_label.clear()
        self.page_label.resize(0, 0)
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
        self.index = -1
        self.show_page(start)

    def page_for_label(self, label):
        """Okuma alanındaki bölüm etiketinden ('Sayfa 45') sayfa sırasını bulur."""
        lab = label[6:] if label.startswith("Sayfa ") else label
        try:
            return self.labels.index(lab)
        except ValueError:
            return None

    # ── gösterim ──
    def show_page(self, i):
        if not self.count:
            return
        i = max(0, min(self.count - 1, i))
        if i == self.index and self.image is not None:
            self.update_controls()
            return
        self.index = i
        self.update_controls()
        self.render()

    def zoom_factor(self):
        val = self.zoom.currentData()
        if not self.sizes:
            return 1.0
        pw, ph = self.sizes[self.index]
        if self.rotate % 180:
            pw, ph = ph, pw
        vw = max(50, self.scroll.viewport().width() - 12)
        vh = max(50, self.scroll.viewport().height() - 12)
        if val == "width":
            return vw / pw
        if val == "page":
            return min(vw / pw, vh / ph)
        return float(val) * 96 / 72                      # %100 = ekranda gerçek boyut (96 dpi)

    def render(self):
        if not self.count or not self.path:
            return
        self.gen += 1
        g, i = self.gen, self.index
        dpr = self.devicePixelRatioF()
        zoom = self.zoom_factor()

        def done(f):
            try:
                r = {"gen": g, "index": i, "img": f.result(), "dpr": dpr}
            except Exception as e:
                r = {"gen": g, "error": str(e)}
            self._emit(self.sig.page_ready, r)
        self.worker.submit(self.worker.render, self.path, i, zoom * dpr, self.rotate).add_done_callback(done)

    def on_page(self, r):
        if r["gen"] != self.gen:
            return                                    # daha yeni bir istek var
        if "error" in r:
            self.info.setText(f"Sayfa çizilemedi: {r['error']}")
            self.info.show()
            return
        w, h, stride, data = r["img"]
        img = QImage(data, w, h, stride, QImage.Format_RGB888).copy()
        img.setDevicePixelRatio(r["dpr"])
        self.image = img
        self.page_label.setPixmap(QPixmap.fromImage(img))
        self.page_label.resize(int(w / r["dpr"]), int(h / r["dpr"]))
        self.info.hide()

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

    def on_zoom_changed(self):
        self.settings.setValue("doc_zoom", str(self.zoom.currentData()))
        self.render()

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
        self.render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.zoom.currentData() in ("width", "page"):
            self.resize_timer.start()

    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport() and ev.type() == QEvent.Wheel:
            dy = ev.angleDelta().y()
            if ev.modifiers() & Qt.ControlModifier:
                self.step_zoom(1 if dy > 0 else -1)
                return True
            sb = self.scroll.verticalScrollBar()
            # Sayfanın sonunda aşağı (başında yukarı) kaydırmaya devam edince sayfa değişir.
            if (dy < 0 and sb.value() >= sb.maximum()) or (dy > 0 and sb.value() <= sb.minimum()):
                self.wheel_acc += dy
                if abs(self.wheel_acc) >= 240:
                    forward = self.wheel_acc < 0
                    self.wheel_acc = 0
                    if (forward and self.index < self.count - 1) or (not forward and self.index > 0):
                        self.show_page(self.index + (1 if forward else -1))
                        QTimer.singleShot(0, lambda: sb.setValue(sb.minimum() if forward else sb.maximum()))
                return True
            self.wheel_acc = 0
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
        if self.image is not None:
            QApplication.clipboard().setImage(self.image)

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

# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Kütüphane: kapak ve liste görünümü, arama, sıralama, belge yönetimi."""
import os
from datetime import datetime

from PySide6.QtCore import QCollator, QLocale, QObject, QSize, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListView, QMenu, QMessageBox, QSpinBox, QStackedWidget, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from . import crashlog
from .extract import SUPPORTED
from .library_info import document_info, human_size, move_to_trash, reveal_in_folder, scan_paths, validate_name

ROLE_ID = Qt.UserRole + 1
ROLE_SORT = Qt.UserRole + 2
ROLE_PATH = Qt.UserRole + 3

COLUMNS = ["Ad", "Yazar", "Tür", "Sayfa", "Boyut", "İlerleme", "Son açılma", "Eklenme", "Klasör"]
COL = {name: i for i, name in enumerate(COLUMNS)}
SORTS = [("Ada göre", "Ad"), ("Yazara göre", "Yazar"), ("Son açılmaya göre", "Son açılma"),
         ("Eklenme tarihine göre", "Eklenme"), ("Boyuta göre", "Boyut"), ("Sayfa sayısına göre", "Sayfa"),
         ("İlerlemeye göre", "İlerleme"), ("Türe göre", "Tür")]
ICON_W, ICON_H = 132, 180
TYPE_COLORS = {".pdf": "#a94442", ".epub": "#3c7a4a", ".docx": "#2f5d9a", ".txt": "#6b6b6b"}


def display_name(row):
    return row["custom_title"] or row["title"] or os.path.splitext(os.path.basename(row["path"]))[0]


def placeholder_cover(ext, title, w=ICON_W, h=ICON_H):
    """Kapağı olmayan belgeler (DOCX, TXT, korumalı PDF) için türüne göre renkli kapak çizer."""
    pm = QPixmap(w, h)
    pm.fill(QColor(TYPE_COLORS.get(ext, "#666666")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(255, 255, 255, 60))
    p.drawRect(6, 6, w - 13, h - 13)
    p.setPen(QColor("#ffffff"))
    f = QFont(); f.setBold(True); f.setPointSize(16); p.setFont(f)
    p.drawText(0, 18, w, 40, Qt.AlignHCenter, ext.lstrip(".").upper())
    f.setBold(False); f.setPointSize(9); p.setFont(f)
    p.drawText(12, 64, w - 24, h - 76, Qt.TextWordWrap | Qt.AlignHCenter, title[:90])
    p.end()
    return pm


def fit_cover(pm, w=ICON_W, h=ICON_H):
    """Kapağı sabit bir çerçeveye ortalar ki ızgara düzgün dursun."""
    scaled = pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap((w - scaled.width()) // 2, h - scaled.height(), scaled)
    p.setPen(QColor(0, 0, 0, 70))
    p.drawRect((w - scaled.width()) // 2, h - scaled.height(), scaled.width() - 1, scaled.height() - 1)
    p.end()
    return out


class LibraryModel(QStandardItemModel):
    """Kitap sürüklenince dosya bağlantısı taşır: okuma alanına bırakınca açılır,
    Windows Gezgini'ne bırakınca dosyanın bir kopyası oluşur."""

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        from PySide6.QtCore import QMimeData, QUrl
        paths = []
        for idx in indexes:
            p = idx.data(ROLE_PATH)
            if p and p not in paths and os.path.exists(p):
                paths.append(p)
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return md

    def supportedDragActions(self):
        return Qt.CopyAction


class LibraryProxy(QSortFilterProxyModel):
    """Ada göre sıralamada Türkçe alfabe (ç, ğ, ı, ö, ş, ü doğru yerinde); diğerlerinde sayısal anahtar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.collator = QCollator(QLocale(QLocale.Turkish, QLocale.Turkey))
        self.collator.setNumericMode(True)              # "Cilt 2" "Cilt 10"dan önce gelsin
        self.collator.setCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)

    def lessThan(self, a, b):
        ka, kb = a.data(ROLE_SORT), b.data(ROLE_SORT)
        if isinstance(ka, str) and isinstance(kb, str):
            return self.collator.compare(ka, kb) < 0
        if ka is None or kb is None:
            return kb is not None and ka is None
        return ka < kb


class DetailsDialog(QDialog):
    """Görünen ad ve künye bilgileri (alıntıları dışa aktarırken kullanılır)."""

    def __init__(self, parent, row):
        super().__init__(parent)
        self.setWindowTitle("Belge bilgileri")
        form = QFormLayout(self)
        self.title = QLineEdit(row["custom_title"] or "")
        self.title.setPlaceholderText(row["title"] or "")
        self.author = QLineEdit(row["author"] or "")
        self.author.setPlaceholderText("Ad Soyad; birden çok yazar için noktalı virgülle ayırın")
        self.year = QLineEdit(row["year"] or "")
        self.year.setMaximumWidth(90)
        self.publisher = QLineEdit(row["publisher"] or "")
        self.city = QLineEdit(row["city"] or "")
        self.offset = QSpinBox()
        self.offset.setRange(-2000, 2000)
        self.offset.setValue(int(row["page_offset"] or 0))
        self.offset.setToolTip("Basılı sayfa = belgedeki sayfa + fark.\n"
                               "Örnek: kitabın 1. sayfası PDF'in 15. sayfasıysa fark −14'tür.\n"
                               "PDF'te sayfa etiketleri doğru tanımlıysa fark 0 kalabilir.")
        form.addRow("Görünen ad (eser adı)", self.title)
        form.addRow("Yazar", self.author)
        form.addRow("Yıl", self.year)
        form.addRow("Yayınevi", self.publisher)
        form.addRow("Şehir", self.city)
        form.addRow("Sayfa farkı", self.offset)
        if row["meta_title"]:
            form.addRow("Belgedeki başlık", QLabel(row["meta_title"]))
        p = QLabel(row["path"]); p.setWordWrap(True); p.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Dosya", p)
        hint = QLabel("Bu bilgiler alıntıları dışa aktarırken künyede kullanılır; dosyanın kendisi değişmez. "
                      "Dosyayı yeniden adlandırmak için kütüphanede sağ tık › Yeniden Adlandır.")
        hint.setWordWrap(True)
        form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet"); bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.resize(560, 0)

    def save(self, store, doc_id):
        store.set_details(doc_id, self.title.text(), self.author.text(), self.year.text(), self.publisher.text(),
                          self.city.text(), self.offset.value())


class _Signals(QObject):
    scanned = Signal(object)
    info_ready = Signal(object)
    relinked = Signal(object)


class LibraryView(QWidget):
    open_requested = Signal(str)          # dosya yolu
    renamed = Signal(str, str)            # belge kimliği, yeni yol
    about_to_remove = Signal(list)        # belge kimlikleri (açık belge kapatılsın)
    expand_toggled = Signal(bool)         # kütüphaneyi tam ekran göster / geri al

    def __init__(self, store, pool, settings, cover_dir, parent=None):
        super().__init__(parent)
        self.store, self.pool, self.settings, self.cover_dir = store, pool, settings, cover_dir
        self.sig = _Signals(self)
        self.sig.scanned.connect(self.on_scanned)
        self.sig.info_ready.connect(self.on_info)
        self.sig.relinked.connect(self.on_relinked)
        self.pending_info = set()
        self.current_doc = None
        self.cover_cache = {}
        self.setAcceptDrops(True)
        # Kapaklar tek tek hazırlandıkça ızgarayı her seferinde baştan kurmamak için kısa bir bekleme
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(600)
        self.refresh_timer.timeout.connect(self.refresh)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self.setMinimumWidth(300)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Kütüphanede ara: ad, yazar, klasör…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.on_search)
        self.sort_combo = QComboBox()
        for label, _ in SORTS:
            self.sort_combo.addItem(label)
        self.sort_combo.activated.connect(lambda _: self.apply_sort())
        self.order_btn = QToolButton()
        self.order_btn.setCheckable(True)
        self.order_btn.setToolTip("Sıralama yönü")
        self.order_btn.toggled.connect(lambda _: self.apply_sort())
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Kapak", "Liste"])
        self.view_combo.setToolTip("Kapak ya da liste görünümü")
        self.view_combo.activated.connect(self.set_view)
        add_btn = QToolButton()
        add_btn.setText("＋ Ekle")
        add_btn.setToolTip("Kütüphaneye belge ya da klasör ekle")
        add_btn.setPopupMode(QToolButton.InstantPopup)
        add_menu = QMenu(add_btn)
        add_menu.addAction("Belge Ekle…", self.add_files)
        add_menu.addAction("Klasör Ekle (alt klasörler dahil)…", self.add_folder)
        add_menu.addSeparator()
        add_menu.addAction("Eksik Dosyaları Bul (klasör tara)…", self.relink_missing)
        add_btn.setMenu(add_menu)
        self.expand_btn = QToolButton()
        self.expand_btn.setText("⛶")
        self.expand_btn.setCheckable(True)
        self.expand_btn.setToolTip("Kütüphaneyi tam ekran göster (liste görünümünde tüm sütunlar sığar). Çıkış: Esc")
        self.expand_btn.toggled.connect(self.expand_toggled.emit)
        for w in (self.sort_combo, self.order_btn, self.view_combo, add_btn, self.expand_btn):
            w.setFocusPolicy(Qt.NoFocus)
        # Panel dar da olabilir: arama bir satırda, sıralama ve görünüm ikinci satırda.
        row1 = QHBoxLayout()
        row1.addWidget(self.search, 1)
        row1.addWidget(add_btn)
        row2 = QHBoxLayout()
        row2.addWidget(self.sort_combo, 1)
        row2.addWidget(self.order_btn)
        row2.addWidget(self.view_combo)
        row2.addWidget(self.expand_btn)
        lay.addLayout(row1)
        lay.addLayout(row2)

        self.model = LibraryModel(0, len(COLUMNS), self)
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = LibraryProxy(self)
        self.proxy.setSourceModel(self.model)

        self.grid = QListView()
        self.grid.setModel(self.proxy)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(ICON_W, ICON_H))
        self.grid.setGridSize(QSize(ICON_W + 34, ICON_H + 58))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideRight)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setSpacing(6)
        # Kitabın üzerinden sürükleyince kitap taşınır; boşluktan sürükleyince seçim kutusu çizilir.
        self.grid.setDragEnabled(True)
        self.grid.setDragDropMode(QAbstractItemView.DragOnly)
        self.grid.setDefaultDropAction(Qt.CopyAction)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragOnly)
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(22, 30))
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.sortIndicatorChanged.connect(self.on_header_sort)
        for c, w in ((COL["Ad"], 320), (COL["Yazar"], 160), (COL["Tür"], 56), (COL["Sayfa"], 64),
                     (COL["Boyut"], 80), (COL["İlerleme"], 72), (COL["Son açılma"], 130), (COL["Eklenme"], 130)):
            self.table.setColumnWidth(c, w)

        for v in (self.grid, self.table):
            v.setContextMenuPolicy(Qt.CustomContextMenu)
            v.customContextMenuRequested.connect(lambda pos, v=v: self.show_menu(v, pos))
            v.activated.connect(self.on_activated)
            v.doubleClicked.connect(self.on_activated)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        sort = self.settings.value("lib_sort", 2, type=int)
        self.sort_combo.setCurrentIndex(sort if 0 <= sort < len(SORTS) else 2)
        self.order_btn.setChecked(self.settings.value("lib_desc", True, type=bool))
        view = self.settings.value("lib_view", 0, type=int)
        self.view_combo.setCurrentIndex(view)
        self.set_view(view)

    # ── görünüm ──
    def set_view(self, i):
        self.stack.setCurrentIndex(i)
        self.settings.setValue("lib_view", i)

    def views(self):
        return (self.grid, self.table)

    def apply_sort(self):
        col = COL[SORTS[self.sort_combo.currentIndex()][1]]
        desc = self.order_btn.isChecked()
        self.order_btn.setText("↓ Azalan" if desc else "↑ Artan")
        order = Qt.DescendingOrder if desc else Qt.AscendingOrder
        hh = self.table.horizontalHeader()
        hh.blockSignals(True)
        hh.setSortIndicator(col, order)
        hh.blockSignals(False)
        self.proxy.sort(col, order)
        self.settings.setValue("lib_sort", self.sort_combo.currentIndex())
        self.settings.setValue("lib_desc", desc)

    def on_header_sort(self, col, order):
        names = [c for _, c in SORTS]
        if COLUMNS[col] in names:
            self.sort_combo.setCurrentIndex(names.index(COLUMNS[col]))
        self.order_btn.blockSignals(True)
        self.order_btn.setChecked(order == Qt.DescendingOrder)
        self.order_btn.blockSignals(False)
        self.order_btn.setText("↓ Azalan" if order == Qt.DescendingOrder else "↑ Artan")
        self.settings.setValue("lib_sort", self.sort_combo.currentIndex())
        self.settings.setValue("lib_desc", order == Qt.DescendingOrder)

    def on_search(self, text):
        self.proxy.setFilterFixedString(text.strip())
        self.update_status()

    # ── veri ──
    def cover_path(self, doc_id):
        return os.path.join(self.cover_dir, f"{doc_id}.png")

    def cover_icon(self, row):
        key = (row["id"], row["info_done"])
        if key in self.cover_cache:
            return self.cover_cache[key]
        cp = self.cover_path(row["id"])
        pm = QPixmap(cp) if os.path.exists(cp) else QPixmap()
        pm = fit_cover(pm) if not pm.isNull() else placeholder_cover(row["ext"] or "", display_name(row))
        icon = QIcon(pm)
        self.cover_cache[key] = icon
        return icon

    def refresh(self):
        """Modeli veritabanından baştan kurar (kütüphane birkaç bin belgeyi geçmez; en sade yol)."""
        selected = set(self.selected_ids())
        rows = self.store.library()
        self.model.removeRows(0, self.model.rowCount())
        missing_color = self.palette().color(self.foregroundRole())
        missing_color.setAlpha(110)
        need_info = []
        for r in rows:
            exists = os.path.exists(r["path"])
            name = display_name(r)
            pages = r["pages"]
            prog = None
            if r["sentence_count"]:
                prog = round(100 * min(r["position"] or 0, r["sentence_count"] - 1) / max(1, r["sentence_count"] - 1))
            vals = {
                "Ad": (name, name),
                "Yazar": (r["author"] or "", r["author"] or ""),
                "Tür": ((r["ext"] or "").lstrip(".").upper(), r["ext"] or ""),
                "Sayfa": ((("≈ " if r["pages_approx"] else "") + str(pages)) if pages else "", pages),
                "Boyut": (human_size(r["size"]), r["size"]),
                "İlerleme": (f"%{prog}" if prog is not None else "", prog),
                "Son açılma": (self.fmt_time(r["last_opened"]), r["last_opened"]),
                "Eklenme": (self.fmt_time(r["added_at"]), r["added_at"]),
                "Klasör": (os.path.dirname(r["path"]), os.path.dirname(r["path"])),
            }
            items = []
            for c in COLUMNS:
                text, key = vals[c]
                it = QStandardItem(text)
                it.setData(key, ROLE_SORT)
                it.setData(r["id"], ROLE_ID)
                it.setData(r["path"], ROLE_PATH)
                it.setEditable(False)
                if not exists:
                    it.setForeground(missing_color)
                items.append(it)
            first = items[0]
            first.setIcon(self.cover_icon(r))
            tip = [name]
            if r["author"]:
                tip.append(r["author"])
            tip.append(r["path"])
            if not exists:
                tip.append("⚠ Dosya bu konumda bulunamadı. Sağ tık › Dosyayı Bul…")
            first.setToolTip("\n".join(tip))
            if r["id"] == self.current_doc:
                f = first.font(); f.setBold(True); first.setFont(f)
            self.model.appendRow(items)
            if exists and not r["info_done"]:
                need_info.append((r["id"], r["path"]))
        self.apply_sort()
        self.select_ids(selected)
        self.update_status()
        if crashlog.SAFE_MODE:               # güvenli modda arka plan kapak taraması yapılmaz
            need_info = []
        for doc_id, path in need_info:
            self.request_info(doc_id, path)

    @staticmethod
    def fmt_time(t):
        if not t:
            return ""
        return datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M")

    def update_status(self):
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        txt = f"{total} belge" if shown == total else f"{shown} / {total} belge"
        if self.pending_info:
            txt += f" · {len(self.pending_info)} belgenin bilgileri hazırlanıyor…"
        if not total:
            txt = "Kütüphane boş. Belge Ekle ya da Klasör Ekle ile başlayın; açtığınız belgeler de buraya eklenir."
        self.status.setText(txt)

    def request_info(self, doc_id, path):
        if doc_id in self.pending_info:
            return
        self.pending_info.add(doc_id)
        cover = self.cover_path(doc_id)

        def job():
            try:
                return {"id": doc_id, "info": document_info(path, cover)}
            except Exception as e:
                return {"id": doc_id, "info": {}, "error": str(e)}
        self.pool.submit(job).add_done_callback(lambda f: self._emit(self.sig.info_ready, f.result()))

    def _emit(self, signal, payload):
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def on_info(self, r):
        self.pending_info.discard(r["id"])
        self.store.set_info(r["id"], r.get("info") or {})
        self.cover_cache = {k: v for k, v in self.cover_cache.items() if k[0] != r["id"]}
        self.update_status()
        self.refresh_timer.start()

    # ── ekleme ──
    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Kütüphaneye belge ekle", "",
                                                "Okunabilir dosyalar (*.pdf *.epub *.docx *.txt)")
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Kütüphaneye klasör ekle (alt klasörler dahil)")
        if d:
            self.add_paths([d])

    def add_paths(self, paths):
        self.status.setText("Belgeler taranıyor…")
        self.pool.submit(scan_paths, paths).add_done_callback(
            lambda f: self._emit(self.sig.scanned, f.result() if not f.exception() else []))

    def on_scanned(self, found):
        counts = {"new": 0, "restored": 0, "moved": 0, "exists": 0}
        for path, doc_id in found:
            counts[self.store.add_to_library(doc_id, path)] += 1
        self.refresh()
        parts = []
        if counts["new"]:
            parts.append(f"{counts['new']} belge eklendi")
        if counts["restored"]:
            parts.append(f"{counts['restored']} belge geri getirildi")
        if counts["moved"]:
            parts.append(f"{counts['moved']} belgenin yeni konumu kaydedildi")
        if counts["exists"]:
            parts.append(f"{counts['exists']} belge zaten kütüphanedeydi")
        self.status.setText(" · ".join(parts) if parts else "Desteklenen belge bulunamadı.")

    def relink_missing(self, folder=None):
        """Yeri değişmiş ya da başka bilgisayardan gelen belgeleri bir klasörde içeriğine göre arar.
        Dosya adı değişmiş olsa da bulur: eşleştirme dosya adına değil içerik kimliğine göre yapılır."""
        missing = {r["id"] for r in self.store.missing_in_library()}
        if not missing:
            QMessageBox.information(self, "Eksik dosya yok", "Kütüphanedeki bütün belgelerin dosyası yerinde.")
            return
        folder = folder or QFileDialog.getExistingDirectory(
            self, f"{len(missing)} eksik belge için aranacak klasör (alt klasörler dahil)")
        if not folder:
            return
        self.status.setText(f"{len(missing)} eksik belge aranıyor… (büyük klasörlerde biraz sürebilir)")

        def job():
            found = {}
            for path, doc_id in scan_paths([folder]):
                if doc_id in missing and doc_id not in found:
                    found[doc_id] = path
            return {"found": found, "missing": len(missing)}
        self.pool.submit(job).add_done_callback(
            lambda f: self._emit(self.sig.relinked, f.result() if not f.exception() else {"found": {}, "missing": 0}))

    def on_relinked(self, r):
        for doc_id, path in r["found"].items():
            self.store.set_path(doc_id, path)
        self.refresh()
        left = r["missing"] - len(r["found"])
        self.status.setText(f"{len(r['found'])} belgenin yeni yeri bulundu" +
                            (f"; {left} belge hâlâ eksik." if left else "; eksik belge kalmadı."))

    def dragEnterEvent(self, e):
        if e.source() in (self.grid, self.table):
            e.ignore()                                  # kütüphanenin kendi sürüklemesi: yeniden ekleme
            return
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.isdir(p) or p.lower().endswith(SUPPORTED)]
        if paths:
            e.acceptProposedAction()
            self.add_paths(paths)

    # ── seçim ──
    def active_view(self):
        return self.stack.currentWidget()

    def selected_ids(self):
        ids = []
        for idx in self.active_view().selectionModel().selectedIndexes():
            d = idx.data(ROLE_ID)
            if d and d not in ids:
                ids.append(d)
        return ids

    def select_ids(self, ids):
        if not ids:
            return
        sm = self.active_view().selectionModel()
        for r in range(self.proxy.rowCount()):
            idx = self.proxy.index(r, 0)
            if idx.data(ROLE_ID) in ids:
                sm.select(idx, sm.SelectionFlag.Select | sm.SelectionFlag.Rows)

    def row_for(self, doc_id):
        return self.store.get_document(doc_id)

    # ── işlemler ──
    def on_activated(self, idx):
        self.open_doc(idx.data(ROLE_ID))

    def open_doc(self, doc_id):
        row = self.row_for(doc_id)
        if row is None:
            return
        if not os.path.exists(row["path"]):
            if QMessageBox.question(self, "Dosya bulunamadı",
                                    f"Bu belge artık şu konumda değil:\n{row['path']}\n\nDosyayı bulmak ister misiniz?"
                                    ) == QMessageBox.Yes:
                self.locate(doc_id)
            return
        self.open_requested.emit(row["path"])

    def show_menu(self, view, pos):
        idx = view.indexAt(pos)
        ids = self.selected_ids()
        if idx.isValid() and idx.data(ROLE_ID) not in ids:
            view.selectionModel().clearSelection()
            view.selectionModel().select(idx, view.selectionModel().SelectionFlag.Select
                                         | view.selectionModel().SelectionFlag.Rows)
            ids = [idx.data(ROLE_ID)]
        menu = QMenu(self)
        if not ids:
            menu.addAction("Belge Ekle…", self.add_files)
            menu.addAction("Klasör Ekle…", self.add_folder)
            menu.exec(view.viewport().mapToGlobal(pos))
            return
        one = len(ids) == 1
        row = self.row_for(ids[0]) if one else None
        exists = bool(row) and os.path.exists(row["path"])
        if one:
            menu.addAction("Aç", lambda: self.open_doc(ids[0])).setEnabled(True)
            if exists:
                menu.addAction("Klasörde Göster", lambda: reveal_in_folder(row["path"]))
            else:
                menu.addAction("Dosyayı Bul…", lambda: self.locate(ids[0]))
            menu.addSeparator()
            a = menu.addAction("Yeniden Adlandır…", lambda: self.rename(ids[0]))
            a.setEnabled(exists)
            menu.addAction("Bilgileri Düzenle…", lambda: self.edit_details(ids[0]))
            a = menu.addAction("Kapağı ve Bilgileri Yenile", lambda: self.reload_info(ids))
            a.setEnabled(exists)
        else:
            menu.addAction(f"{len(ids)} belge seçili").setEnabled(False)
            menu.addAction("Kapakları ve Bilgileri Yenile", lambda: self.reload_info(ids))
        menu.addSeparator()
        menu.addAction("Kütüphaneden Kaldır (dosya silinmez)", lambda: self.remove(ids))
        menu.addAction("Diskten Sil (Geri Dönüşüm Kutusu'na)…", lambda: self.trash(ids))
        menu.exec(view.viewport().mapToGlobal(pos))

    def rename(self, doc_id):
        row = self.row_for(doc_id)
        if not row or not os.path.exists(row["path"]):
            return
        folder, fname = os.path.split(row["path"])
        stem, ext = os.path.splitext(fname)
        while True:
            new, ok = QInputDialog.getText(self, "Yeniden adlandır", f"Yeni dosya adı ({ext} uzantısı korunur):",
                                           QLineEdit.Normal, stem)
            if not ok or new.strip() == stem:
                return
            err = validate_name(new)
            target = os.path.join(folder, new.strip() + ext)
            if not err and os.path.exists(target) and os.path.normcase(target) != os.path.normcase(row["path"]):
                err = "Bu klasörde aynı adlı bir dosya zaten var."
            if not err:
                break
            QMessageBox.warning(self, "Geçersiz ad", err)
            stem = new
        try:
            os.rename(row["path"], target)
        except OSError as e:
            QMessageBox.warning(self, "Yeniden adlandırılamadı",
                                f"{e.strerror or e}\n\nDosya başka bir programda açık olabilir.")
            return
        self.store.set_path(doc_id, target)
        self.renamed.emit(doc_id, target)
        self.refresh()

    def edit_details(self, doc_id):
        row = self.row_for(doc_id)
        if not row:
            return
        dlg = DetailsDialog(self, row)
        if dlg.exec() == QDialog.Accepted:
            dlg.save(self.store, doc_id)
            self.cover_cache = {k: v for k, v in self.cover_cache.items() if k[0] != doc_id}
            self.refresh()

    def reload_info(self, ids):
        for doc_id in ids:
            row = self.row_for(doc_id)
            if row and os.path.exists(row["path"]):
                self.cover_cache = {k: v for k, v in self.cover_cache.items() if k[0] != doc_id}
                self.request_info(doc_id, row["path"])
        self.update_status()

    def locate(self, doc_id):
        row = self.row_for(doc_id)
        if not row:
            return
        start = os.path.dirname(row["path"]) if os.path.isdir(os.path.dirname(row["path"])) else ""
        path, _ = QFileDialog.getOpenFileName(self, "Dosyayı bul", start,
                                              f"Belge (*{row['ext'] or '.pdf'});;Okunabilir dosyalar (*.pdf *.epub *.docx *.txt)")
        if not path:
            return
        from .extract import document_id
        try:
            new_id = document_id(path)
        except OSError as e:
            QMessageBox.warning(self, "Dosya okunamadı", str(e))
            return
        if new_id != doc_id:
            r = QMessageBox.question(
                self, "Farklı belge",
                "Seçtiğiniz dosyanın içeriği kayıttaki belgeyle aynı değil (dosya değiştirilmiş olabilir).\n\n"
                "Yine de bu dosya bu kaydın yerine geçsin mi? Kaldığınız yer ve düzeltmeler yeni dosyaya taşınmaz; "
                "dosya kütüphaneye ayrı bir belge olarak eklenir.")
            if r != QMessageBox.Yes:
                return
            self.store.remove_from_library(doc_id)
            self.store.add_to_library(new_id, path)
        else:
            self.store.set_path(doc_id, path)
        self.refresh()

    def remove(self, ids):
        self.about_to_remove.emit(list(ids))
        for doc_id in ids:
            self.store.remove_from_library(doc_id)
        self.refresh()
        self.status.setText(f"{len(ids)} belge kütüphaneden kaldırıldı. Dosyalar diskte duruyor; "
                            "yeniden açtığınızda kaldığınız yer korunur.")

    def trash(self, ids):
        rows = [self.row_for(i) for i in ids]
        rows = [r for r in rows if r]
        existing = [r for r in rows if os.path.exists(r["path"])]
        names = "\n".join(f"• {os.path.basename(r['path'])}" for r in existing[:8])
        more = f"\n… ve {len(existing) - 8} dosya daha" if len(existing) > 8 else ""
        if not existing:
            self.remove(ids)
            return
        if QMessageBox.warning(
                self, "Diskten sil",
                f"Şu dosyalar Geri Dönüşüm Kutusu'na gönderilecek ve kütüphaneden kaldırılacak:\n\n{names}{more}\n\n"
                "Gerekirse Geri Dönüşüm Kutusu'ndan geri alabilirsiniz.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self.about_to_remove.emit(list(ids))
        failed = []
        for r in rows:
            if os.path.exists(r["path"]) and not move_to_trash(r["path"]):
                failed.append(os.path.basename(r["path"]))
                continue
            self.store.remove_from_library(r["id"])
        self.refresh()
        if failed:
            QMessageBox.warning(self, "Bazı dosyalar silinemedi",
                                "Şu dosyalar Geri Dönüşüm Kutusu'na gönderilemedi (başka bir programda açık "
                                "olabilir):\n\n" + "\n".join(failed))
        else:
            self.status.setText(f"{len(rows)} dosya Geri Dönüşüm Kutusu'na gönderildi.")

    COLUMNS_DEFAULT = 4

    def columns_width(self, n=COLUMNS_DEFAULT):
        """Kapak görünümünde yan yana tam n kapağın sığdığı panel genişliği."""
        g = self.grid.gridSize().width() + self.grid.spacing()
        scroll = self.grid.style().pixelMetric(self.grid.style().PixelMetric.PM_ScrollBarExtent)
        m = self.layout().contentsMargins()
        return n * g + self.grid.spacing() + scroll + 2 * self.grid.frameWidth() + m.left() + m.right() + 6

    def set_current(self, doc_id):
        self.current_doc = doc_id

    def touch(self):
        """Kütüphane görünür olduğunda çağrılır."""
        self.refresh()
        self.search.setFocus()

# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Ana pencere."""
import bisect
import hashlib
from datetime import datetime
import html
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QFontMetrics, QKeySequence, QPalette, QShortcut,
                           QTextBlockFormat, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (
    QToolTip,
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QProgressDialog, QPushButton,
    QScrollArea, QSlider, QSpinBox, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from . import APP_NAME, APP_ORG, APP_YEAR, AUTHOR, AUTHOR_MAIL
from .dialogs import AboutDialog, CustomThemeDialog, TextAppearanceDialog, show_done
from .pron_dialog import PronunciationDialog, RuleDialog
from .pronounce import STARTER_RULES, Pronouncer, Rule
from .extract import SUPPORTED, Cancelled, cleanup_stale_temp_dirs, load_document
from .paths import IS_WINDOWS, data_dir
from .store import Store
from .textproc import anchor_of, build_document, locate_anchor, parse_display, resolve_anchor, word_count
from .themes import CUSTOM, DEFAULT_THEME, THEMES, palette_for
from .power import set_awake
from .annotations import KIND_HIGHLIGHT, KIND_NOTE, KIND_QUOTE
from .docview import DocView
from .library import LibraryView
from .library_info import human_size
from .quotes import AnnotationDialog, QuotesView
from .widgets import AdaptiveBox, CollapsibleSection, ElidedLabel, EmptyState, OverlayBar, ThinProgress
from .tts import (EDGE_VOICES, kill_all_processes, list_sapi_voices, safe_remove, sapi_rate,
                  synth_edge_chunk, synth_sapi)

PREFETCH_CHUNKS = 2               # çalan parçadan sonra kaç parça önceden hazırlansın
CHUNK_SENTENCES = 8               # bir parçadaki en fazla cümle
CHUNK_CHARS = 900                 # bir parçadaki en fazla karakter
LOOKAHEAD = 40                    # önbellekte tutulacak ileri cümle penceresi
MAX_RECENT = 10                   # "Son Açılanlar" listesindeki en fazla dosya
NARROW_WIDTH = 760                # dar pencere sınırının alt değeri (asıl sınır içeriğe göre hesaplanır)
READING_COLUMN = 78               # tam ekran/odaklanmada satır başına yaklaşık karakter
PLACEHOLDER_LABEL = ""


@dataclass
class Chunk:
    cfg: tuple
    a: int              # ilk cümle
    b: int              # son cümleden bir sonraki
    path: str
    times: list         # her cümle için (başlangıç_ms, bitiş_ms)


class Bridge(QObject):
    """Arka plan iş parçacıklarından ana arayüze güvenli sinyal köprüsü."""
    synth_done = Signal(object)
    load_done = Signal(object)
    load_progress = Signal(object)       # (yüzde, ileti)
    voices_done = Signal(object)
    export_progress = Signal(int)
    export_done = Signal(object)
    preview_done = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, cache_dir):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)
        self.cache_dir = cache_dir
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.store = Store(os.path.join(data_dir(), "metin_dinleyici.db"))
        if self.store.meta("pron_seeded") is None:
            # İlk açılışta akademik metinler için başlangıç kuralları; hepsi düzenlenebilir ve silinebilir.
            if not self.store.load_rules():
                self.store.save_rules(STARTER_RULES)
            self.store.set_meta("pron_seeded", 1)
        self.rules = self.store.load_rules()
        self.pron = Pronouncer(self.rules, None)
        self.pron_version = 0
        # elle düzeltme
        self.doc_sections = []               # ekrandaki metnin bölümleri (düzeltilmiş olabilir)
        self.extracted_sections = []         # dosyadan çıkarılan özgün bölümler
        self.doc_opts = {}
        self.has_edits = False
        self.edit_undo = []
        self.editing = False
        self.preview_path = None
        # alıntılar
        self.ann_rows = []                   # açık belgedeki alıntı/not/vurgular
        self.ann_marks = []                  # metindeki işaretler (ExtraSelection)
        self.ann_by_sentence = {}            # cümle numarası → kayıtlar (üzerine gelince ipucu)
        self.pending_goto = None
        self.last_annotation = None
        cleanup_stale_temp_dirs()
        self.tmpdir = tempfile.mkdtemp(prefix="metin_dinleyici_")
        self.synth_pool = ThreadPoolExecutor(max_workers=3)
        self.work_pool = ThreadPoolExecutor(max_workers=2)
        self.bridge = Bridge(self)
        self.bridge.synth_done.connect(self.on_synth_done)
        self.bridge.load_done.connect(self.on_loaded)
        self.bridge.load_progress.connect(self.on_load_progress)
        self.bridge.voices_done.connect(self.on_voices)
        self.bridge.export_done.connect(self.on_export_done)
        self.bridge.preview_done.connect(self.on_preview_done)

        self.sentences, self.starts, self.toc, self.combo_first = [], [], [], []
        self.current_index = 0
        self.state = "idle"                  # idle | loading | playing | paused
        self.waiting_index = None
        self.chunks = {}                     # ilk cümle → Chunk
        self.inflight = set()                # (a, b, cfg)
        self.playing = None                  # oynatıcıdaki Chunk
        self.current_path = None
        self.pending_seek = None
        self.seek_guard = 0.0
        self.doc_path = self.doc_id = None
        self.doc_gen = 0
        self.loading = False
        self.load_cancel = None
        self.sapi_voices = None
        self.closing = False
        self.theme_name = DEFAULT_THEME
        self.custom_theme = {}
        self.colors = {}
        self.appearance = {"family": "Segoe UI", "size": 12, "line": 130, "para": 0, "margin": 16}
        self.wpm = {}                        # "motor|ses" → (hız %100'e göre kelime/dk, ölçülen kelime)
        # tam ekran / odaklanma
        self.is_fullscreen = False
        self.focus_mode = False
        self.peek = False                    # tam ekrandayken Enter ile menü ve panel geçici olarak açıldı mı
        self._imm_applied = False
        self._docks_visible = {}            # tam ekrana girerken hangi paneller açıktı
        self._was_maximized = False
        # panel konumu: kullanıcının seçtiği kenar; dar pencerede geçici olarak alta iner
        self.user_dock_area = Qt.RightDockWidgetArea
        self._auto_moved = False
        self._auto_moving = False
        self.scroll_anim = None
        # Kontrol paneli pencere genişliğiyle orantılı büyüyüp küçülür; oranı kullanıcı sürükleyerek belirler.
        self.dock_ratio = None
        self._last_width = None
        self._ratio_applying = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.player.errorOccurred.connect(self.on_player_error)
        self.tick = QTimer(self)
        self.tick.setInterval(40)
        self.tick.timeout.connect(self.on_tick)
        # Kaldığınız yer her cümlede değil, kısa bir beklemeden sonra diske yazılır.
        self.pos_timer = QTimer(self)
        self.pos_timer.setSingleShot(True)
        self.pos_timer.setInterval(1500)
        self.pos_timer.timeout.connect(self.flush_position)

        self.build_ui()
        self.build_extras()
        self.fit_panel_width()
        self.restore_settings()
        self.apply_theme()
        self.setAcceptDrops(True)
        self.text.viewport().installEventFilter(self)
        self.text.installEventFilter(self)
        self.reader.installEventFilter(self)

    # ───────────────────────── arayüz kurulumu ─────────────────────────
    def build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 4)
        self.root_layout = root

        # ── üst çubuk ──
        self.top_bar = QWidget()
        self.top_bar.setObjectName("topBar")
        top = QHBoxLayout(self.top_bar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.open_btn = QPushButton("Dosya Aç")
        self.open_btn.clicked.connect(self.open_file)
        self.close_doc_btn = QPushButton("Kapat")
        self.close_doc_btn.setToolTip("Belgeyi kapat (Ctrl+W)")
        self.close_doc_btn.clicked.connect(self.close_document)
        self.close_doc_btn.setEnabled(False)
        self.edit_btn = QPushButton("✎ Düzenle")
        self.edit_btn.setToolTip("Metni elle düzelt (Ctrl+Shift+E)\nTek bir cümleyi ya da tekrar eden bir artığı silmek için "
                                 "metne sağ tıklayıp “Metni Düzelt”i de kullanabilirsiniz.")
        self.edit_btn.clicked.connect(lambda: self.enter_edit_mode())
        self.edit_btn.setEnabled(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setToolTip("Yüklemeyi iptal et")
        self.cancel_btn.clicked.connect(self.cancel_load)
        self.cancel_btn.hide()
        self.file_label = ElidedLabel(PLACEHOLDER_LABEL)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Metinde ara (Enter: sonraki)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(70)
        self.search.setMaximumWidth(260)
        self.search.returnPressed.connect(self.find_next)
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("Renk teması")
        self.theme_combo.addItems(list(THEMES) + [CUSTOM])
        self.theme_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.theme_combo.setMinimumContentsLength(4)
        self.theme_combo.activated.connect(lambda i: self.set_theme(self.theme_combo.itemText(i)))
        top.addWidget(self.open_btn); top.addWidget(self.close_doc_btn); top.addWidget(self.edit_btn)
        top.addWidget(self.file_label, 1)
        top.addWidget(self.search, 1); top.addWidget(self.theme_combo)
        root.addWidget(self.top_bar)

        # ── okuma alanı (tam ekran ve odaklanma modunda ortalanmış sütun olur) ──
        self.reader = QWidget()
        self.reader.setBackgroundRole(QPalette.Base)
        self.reader.setMouseTracking(True)
        rl = QVBoxLayout(self.reader)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.reader_layout = rl
        self.text = QTextBrowser()
        self.text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self.show_text_menu)
        self.text.document().setUndoRedoEnabled(False)
        self.text.verticalScrollBar().actionTriggered.connect(self.on_user_scroll)
        self.text.viewport().setMouseTracking(True)
        rl.addWidget(self.text, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1); self.progress.setValue(0)
        self.progress.setFormat("")
        self.progress.setTextVisible(True)
        self.progress.setAlignment(Qt.AlignCenter)
        pb = QHBoxLayout()
        pb.setSpacing(6)
        pb.addWidget(self.progress, 1)
        self.stop_load_btn = QPushButton("■ Yüklemeyi Durdur")
        self.stop_load_btn.setToolTip("Yüklemeyi ya da OCR taramasını durdurur (Esc). Belge açılmaz; "
                                      "taranmış sayfalarını okumak istemiyorsanız “Taranmış sayfalar için OCR” "
                                      "seçeneğini kapatıp yeniden açın.")
        self.stop_load_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_load_btn.clicked.connect(self.cancel_load)
        self.stop_load_btn.hide()
        pb.addWidget(self.stop_load_btn)
        self.progress_row = QWidget()
        self.progress_row.setLayout(pb)
        pb.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.progress_row)
        root.addWidget(self.reader, 1)
        self.setCentralWidget(central)

        self.overlay = OverlayBar(self.reader)
        self.overlay.prev_clicked.connect(lambda: self.jump_to(self.current_index - 1))
        self.overlay.restart_clicked.connect(self.restart_sentence)
        self.overlay.play_clicked.connect(self.toggle_play)
        self.overlay.next_clicked.connect(lambda: self.jump_to(self.current_index + 1))
        self.overlay.exit_clicked.connect(self.exit_immersive)
        self.toast = QLabel(self.reader)
        self.toast.setObjectName("toast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast.hide)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.setSingleShot(True)
        self.cursor_timer.setInterval(2600)
        self.cursor_timer.timeout.connect(self.hide_cursor)

        # ── kontrol paneli: dört kenara taşınabilir, ayrı pencereye alınabilir ──
        # 1. sütun: okuma sırasında hep gereken denetimler
        reading = QWidget()
        g = QVBoxLayout(reading)
        g.setContentsMargins(0, 0, 0, 0)
        # Oku/Duraklat alt satırda geniş düğme; Cümleyi Baştan Oku üst satırda ortada.
        r = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Önceki")
        self.restart_btn = QPushButton("↺ Cümleyi Baştan Oku")
        self.next_btn = QPushButton("Sonraki ▶")
        r.addWidget(self.prev_btn); r.addWidget(self.restart_btn, 1); r.addWidget(self.next_btn); g.addLayout(r)
        r = QHBoxLayout()
        self.read_btn = QPushButton("▶ Oku"); self.stop_btn = QPushButton("■ Durdur")
        r.addWidget(self.read_btn, 1); r.addWidget(self.stop_btn); g.addLayout(r)
        # Sağ panelde yer var: okuma düğmeleri iri ve kolay tıklanır olsun.
        big = self.prev_btn.font()
        big.setPointSizeF(big.pointSizeF() * 1.2)
        for b in (self.prev_btn, self.restart_btn, self.next_btn, self.stop_btn):
            b.setFont(big)
            b.setMinimumHeight(44)
        bigger = QFont(big)
        bigger.setPointSizeF(big.pointSizeF() * 1.15)
        bigger.setBold(True)
        self.read_btn.setFont(bigger)
        self.read_btn.setMinimumHeight(54)
        self.prev_btn.clicked.connect(lambda: self.jump_to(self.current_index - 1))
        self.next_btn.clicked.connect(lambda: self.jump_to(self.current_index + 1))
        self.read_btn.clicked.connect(self.toggle_play)
        self.restart_btn.clicked.connect(self.restart_sentence)
        self.stop_btn.clicked.connect(self.stop_playback)

        form2 = QFormLayout()
        ir = QHBoxLayout()
        self.index = QSpinBox()
        self.index.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.index.setKeyboardTracking(False)      # her tuşta değil, Enter'da atlasın
        self.index.setAlignment(Qt.AlignCenter)
        self.index.setRange(0, 0); self.index.setMinimumSize(80, 28)
        self.index.valueChanged.connect(lambda v: self.jump_to(v - 1, reveal=True) if v > 0 else None)
        self.total = QLabel("/ 0")
        ir.addWidget(self.index); ir.addWidget(self.total); ir.addStretch(1)
        form2.addRow("Cümle", ir)
        self.section_combo = QComboBox()
        self.section_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.section_combo.setMinimumContentsLength(8)
        self.section_combo.activated.connect(
            lambda i: self.jump_to(self.combo_first[i], reveal=True) if 0 <= i < len(self.combo_first) else None)
        form2.addRow("Git", self.section_combo)
        g.addLayout(form2)
        self.where = QLabel("")
        self.where.setStyleSheet("font-weight:600")
        g.addWidget(self.where)
        self.current = QLabel("Okunacak cümle burada görünecek.")
        self.current.setWordWrap(True); self.current.setMinimumHeight(90); self.current.setAlignment(Qt.AlignTop)
        self.current.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(self.current, 1)
        cr = QHBoxLayout(); cr.addStretch(1)
        self.copy_btn = QPushButton("Kopyala")
        self.copy_btn.setToolTip("Okunan cümleyi panoya kopyalar (C)")
        self.copy_btn.clicked.connect(self.copy_sentence)
        cr.addWidget(self.copy_btn)
        g.addLayout(cr)

        # 2. sütun: ses ayarları (katlanabilir)
        self.sec_voice = CollapsibleSection("Ses ve Hız")
        v = self.sec_voice.body_layout
        r = QHBoxLayout(); r.addWidget(QLabel("Ses modu"))
        self.mode = QComboBox()
        self.mode.addItems(["Çevrimiçi (Edge sinir ağı sesleri)", "Çevrimdışı (Windows sesleri)"])
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(10)
        if not IS_WINDOWS:
            self.mode.model().item(1).setEnabled(False)
        r.addWidget(self.mode, 1); v.addLayout(r)
        r = QHBoxLayout(); r.addWidget(QLabel("Ses"))
        self.voice = QComboBox()
        self.voice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.voice.setMinimumContentsLength(10)
        r.addWidget(self.voice, 1); v.addLayout(r)
        self.voice_note = QLabel()
        self.voice_note.setWordWrap(True)
        v.addWidget(self.voice_note)
        form = QFormLayout()
        self.rate = QSlider(Qt.Horizontal)
        self.rate.setRange(50, 200); self.rate.setSingleStep(5); self.rate.setPageStep(10); self.rate.setValue(100)
        self.rate_label = QLabel("%100"); self.rate_label.setFixedWidth(52)
        rr = QHBoxLayout(); rr.addWidget(self.rate, 1); rr.addWidget(self.rate_label)
        form.addRow("Hız", rr)
        self.wpm_label = QLabel("")
        self.wpm_label.setToolTip("Seçili sesin bu hızda dakikada okuduğu kelime sayısı.\n"
                                  "Tahmin değil ölçümdür: okunan parçalardan hesaplanır ve okudukça netleşir.\n"
                                  "Cümle arası esler de dahildir, yani kulağınıza ulaşan gerçek tempodur.")
        form.addRow("", self.wpm_label)
        self.pause = QSlider(Qt.Horizontal)
        self.pause.setRange(10, 120); self.pause.setSingleStep(5); self.pause.setPageStep(10); self.pause.setValue(45)
        self.pause.setToolTip("Cümleler arasındaki sessizlik (yalnızca çevrimiçi seslerde)")
        self.pause_label = QLabel("0,45 sn"); self.pause_label.setFixedWidth(52)
        pr = QHBoxLayout(); pr.addWidget(self.pause, 1); pr.addWidget(self.pause_label)
        form.addRow("Cümle arası es", pr)
        v.addLayout(form)
        self.auto_check = QCheckBox("Cümle bitince otomatik devam et")
        self.auto_check.setChecked(True)
        v.addWidget(self.auto_check)
        fr = QHBoxLayout()
        self.follow_check = QCheckBox("Okunan metni takip et")
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip("Açıkken metin, okunan cümleyi görünür tutacak şekilde kayar.\n"
                                     "Okuma sırasında metni elle kaydırırsanız takip kendiliğinden kapanır;\n"
                                     "kutuyu yeniden işaretlediğinizde okunan yere dönülür.")
        self.follow_check.toggled.connect(self.on_follow_toggled)
        self.goto_current_btn = QPushButton("Okunan yere git")
        self.goto_current_btn.clicked.connect(lambda: self.reveal_current())
        fr.addWidget(self.follow_check); fr.addStretch(1); fr.addWidget(self.goto_current_btn)
        v.addLayout(fr)

        # 3. sütun: belge seçenekleri (katlanabilir)
        self.sec_doc = CollapsibleSection("Belge Seçenekleri")
        o = self.sec_doc.body_layout
        self.ocr = QCheckBox("Taranmış sayfalar için OCR")
        self.skip_notes = QCheckBox("Dipnotları ve dipnot numaralarını atla")
        self.strip_headers = QCheckBox("Üst/alt bilgi ve sayfa numaralarını temizle")
        for c in (self.ocr, self.skip_notes, self.strip_headers):
            c.setChecked(True); o.addWidget(c)
        hint = QLabel("Seçenek değişikliği için belgeyi yeniden yükleyin (F5).")
        hint.setWordWrap(True); o.addWidget(hint)

        settings_col = QWidget()
        sc = QVBoxLayout(settings_col)
        sc.setContentsMargins(0, 0, 0, 0)
        sc.addWidget(self.sec_voice)
        sc.addWidget(self.sec_doc)
        sc.addStretch(1)

        self.panel_box = AdaptiveBox(threshold=820)
        self.panel_box.add_column(reading, 3)
        self.panel_box.add_column(settings_col, 2)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 6, 10, 6)
        pl.addWidget(self.panel_box)
        pl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(280)
        self.panel_box.watch(scroll.viewport())
        self.panel_scroll = scroll
        self.panel_box.direction_changed.connect(lambda _: QTimer.singleShot(0, self.fit_panel_width))
        self.dock = QDockWidget("Kontrol Paneli", self)
        self.dock.setObjectName("control_panel")      # saveState/restoreState için zorunlu
        self.dock.setWidget(scroll)
        self.dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                              | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.dockLocationChanged.connect(self.on_dock_moved)
        self.dock.installEventFilter(self)
        self.dock.topLevelChanged.connect(self.on_dock_float_changed)

        for b in (self.prev_btn, self.read_btn, self.next_btn, self.restart_btn, self.stop_btn, self.copy_btn,
                  self.open_btn, self.close_doc_btn, self.edit_btn, self.cancel_btn, self.goto_current_btn):
            b.setFocusPolicy(Qt.NoFocus)          # Boşluk tuşu odaklı düğmeye değil, Oku/Duraklat'a gitsin
        self.theme_combo.setFocusPolicy(Qt.NoFocus)

        credit = QLabel(f'© {APP_YEAR} {AUTHOR} · <a href="mailto:{AUTHOR_MAIL}">{AUTHOR_MAIL}</a>')
        credit.setOpenExternalLinks(True)
        credit.setStyleSheet("padding:0 8px; color:palette(mid)")
        self.statusBar().addPermanentWidget(credit)

        self.mode.currentIndexChanged.connect(self.on_mode_changed)
        self.voice.currentIndexChanged.connect(self.on_voice_changed)
        self.rate.valueChanged.connect(self.on_rate_changed)
        self.pause.valueChanged.connect(self.on_pause_changed)

        # Tam ekranda menü ve panel gizliyken Enter onları geri getirir.
        self.enter_shortcuts = [QShortcut(QKeySequence(k), self, self.toggle_peek) for k in (Qt.Key_Return, Qt.Key_Enter)]
        for sc_ in self.enter_shortcuts:
            sc_.setEnabled(False)
        self.build_menus()

    def build_menus(self):
        def act(menu, text, slot, shortcut=None, checkable=False, tip=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            if tip:
                a.setToolTip(tip)
                a.setStatusTip(tip)
            a.triggered.connect(slot)
            menu.addAction(a)
            self.addAction(a)       # menü çubuğu gizliyken (tam ekran) de kısayollar çalışsın
            return a

        # Menüler ayraçlarla gruplanır: aynı işe ait komutlar bir arada, en sık kullanılanlar üstte.
        m = self.menuBar().addMenu("Dosya")
        m.setToolTipsVisible(True)
        act(m, "Dosya Aç…", self.open_file, "Ctrl+O")
        self.recent_menu = m.addMenu("Son Açılanlar")
        self.close_doc_act = act(m, "Belgeyi Kapat", self.close_document, "Ctrl+W")
        self.close_doc_act.setEnabled(False)
        m.addSeparator()
        act(m, "Kütüphaneye Belge Ekle…", lambda: self.library.add_files())
        act(m, "Kütüphaneye Klasör Ekle…", lambda: self.library.add_folder())
        m.addSeparator()
        act(m, "Ses Olarak Dışa Aktar (MP3)…", self.export_audio, "Ctrl+E",
            tip="Belgenin tamamını ya da bir bölümünü bir veya birden çok ses dosyasına dönüştürür")
        act(m, "Alıntıları Dışa Aktar…", lambda: self.export_quotes(), "Ctrl+Shift+X")
        act(m, "Belge Bilgileri (künye)…", lambda: self.edit_document_details(), "Ctrl+I")
        m.addSeparator()
        act(m, "Yedekle…", lambda: self.make_backup(),
            tip="Kütüphane, alıntılar, sözlük, düzeltmeler ve ayarlar tek bir zip dosyasına")
        act(m, "Yedekten Geri Yükle…", lambda: self.restore_from_backup())
        m.addSeparator()
        act(m, "Seçeneklerle Yeniden Yükle", self.reload, "F5")
        act(m, "Temizlik ve Sıfırlama…", lambda: self.open_cleanup(),
            tip="Önbelleği, geçici dosyaları ve deneme kayıtlarını temizler; kütüphanedeki belgeler korunur")
        m.addSeparator()
        act(m, "Çıkış", self.close, "Ctrl+Q")

        m = self.menuBar().addMenu("Okuma")
        m.setToolTipsVisible(True)
        act(m, "Oku / Duraklat", self.toggle_play, "Space")
        act(m, "Durdur  ·  tam ekranda: Çık", self.on_escape, "Esc")
        m.addSeparator()
        act(m, "Önceki Cümle", lambda: self.jump_to(self.current_index - 1), "Ctrl+Left")
        act(m, "Sonraki Cümle", lambda: self.jump_to(self.current_index + 1), "Ctrl+Right")
        act(m, "Cümleyi Baştan Oku", self.restart_sentence, "Ctrl+R")
        m.addSeparator()
        act(m, "Okunan Yere Git", self.reveal_current, "Ctrl+J")
        self.follow_act = act(m, "Okunan Metni Takip Et", lambda on: self.follow_check.setChecked(on),
                              "Ctrl+Shift+F", checkable=True)
        act(m, "Metinde Ara", lambda: (self.search.setFocus(), self.search.selectAll()), "Ctrl+F")
        m.addSeparator()
        self.awake_act = act(m, "Okurken Uyku Modunu Engelle", lambda _: self.update_power(), checkable=True,
                             tip="Sesli okuma sürerken bilgisayar uyku moduna geçmez.")
        self.awake_act.setChecked(True)

        m = self.menuBar().addMenu("Alıntılar")
        m.setToolTipsVisible(True)
        act(m, "Okunan Cümleyi Kopyala", self.copy_sentence, "C")
        m.addSeparator()
        act(m, "Okunan Cümleyi Alıntıla", lambda: self.quote_current(), "M",
            tip="Okunan cümleyi alıntılar listesine ekler (M: marked)")
        act(m, "Okunan Cümleye Not Ekle…", lambda: self.note_current(), "N")
        act(m, "Okunan Cümleyi Vurgula", lambda: self.highlight_current(), "V",
            tip="Cümleyi metinde kalıcı olarak renklendirir; yeniden basınca vurgu kalkar")
        act(m, "Son Kaydı Düzenle (not, etiket)…", lambda: self.edit_last_annotation(), "Shift+M")
        m.addSeparator()
        act(m, "Alıntılar Paneli", lambda: self.toggle_quotes(), "F8")
        act(m, "Alıntıları Dışa Aktar…", lambda: self.export_quotes())
        act(m, "Belge Bilgileri (künye)…", lambda: self.edit_document_details())

        m = self.menuBar().addMenu("Düzen")
        m.setToolTipsVisible(True)
        self.edit_act = act(m, "Metni Düzenle…", self.enter_edit_mode, "Ctrl+Shift+E")
        self.save_edit_act = act(m, "Düzenlemeyi Kaydet", self.save_edit_mode, "Ctrl+S")
        m.addSeparator()
        self.undo_edit_act = act(m, "Son Düzeltmeyi Geri Al", self.undo_edit, "Ctrl+Z")
        self.remove_edits_act = act(m, "Elle Yapılan Tüm Düzeltmeleri Kaldır…", self.remove_all_edits)
        m.addSeparator()
        act(m, "Telaffuz Sözlüğü…", self.open_pron_dialog, "Ctrl+Shift+L")

        m = self.menuBar().addMenu("Görünüm")
        m.setToolTipsVisible(True)
        self.fullscreen_act = act(m, "Tam Ekran", lambda on: self.set_fullscreen(on), "F11", checkable=True)
        self.focus_act = act(m, "Odaklanma Modu", lambda on: self.set_focus_mode(on), "F12", checkable=True)
        m.addSeparator()
        self.lib_act = act(m, "Kütüphane Paneli", lambda on: self.show_library(on), "Ctrl+L", checkable=True)
        self.quotes_act = act(m, "Alıntılar Paneli", lambda on: self.toggle_quotes(on), checkable=True)
        self.doc_act = act(m, "Orijinal Belge Paneli", lambda on: self.show_docview(on), "F7", checkable=True)
        self.quotes_act.setShortcut(QKeySequence())          # F8 Alıntılar menüsünde
        pa = self.dock.toggleViewAction()
        pa.setText("Kontrol Paneli")
        pa.setShortcut(QKeySequence("F9"))
        m.addAction(pa); self.addAction(pa)
        pm = m.addMenu("Kontrol Panelinin Konumu")
        for text, area in (("Sağda", Qt.RightDockWidgetArea), ("Solda", Qt.LeftDockWidgetArea),
                           ("Üstte", Qt.TopDockWidgetArea), ("Altta", Qt.BottomDockWidgetArea)):
            act(pm, text, lambda _=False, a=area: self.place_dock(a))
        pm.addSeparator()
        act(pm, "Ayrı Pencerede", lambda: self.place_dock(None))
        self.thin_act = act(m, "Tam Ekranda İnce İlerleme Çizgisi", lambda _: self.update_thin_progress(),
                            checkable=True, tip="Tam ekran ve odaklanma modunda ekranın altında ince bir ilerleme çizgisi")
        self.thin_act.setChecked(True)
        m.addSeparator()
        act(m, "Metin Görünümü…", self.edit_appearance, "Ctrl+Shift+T")
        act(m, "Yazıyı Büyüt", lambda: self.change_font(1), "Ctrl++")
        act(m, "Yazıyı Küçült", lambda: self.change_font(-1), "Ctrl+-")
        m.addSeparator()
        tm = m.addMenu("Tema")
        self.theme_group = QActionGroup(self)
        self.theme_actions = {}
        for name in list(THEMES) + [CUSTOM]:
            a = act(tm, name, lambda _=False, n=name: self.set_theme(n), checkable=True)
            self.theme_group.addAction(a)
            self.theme_actions[name] = a
        tm.addSeparator()
        act(tm, "Özel Temayı Düzenle…", self.edit_custom_theme)
        act(m, "Sonraki Tema", self.next_theme, "Ctrl+T")
        m.addSeparator()
        self.on_top_act = act(m, "Her Zaman Üstte", self.set_on_top, "Ctrl+Shift+A", checkable=True)

        m = self.menuBar().addMenu("Yardım")
        act(m, "Kullanım Kılavuzu", self.show_guide, "F1")
        act(m, "Klavye Kısayolları", lambda: self.show_guide("kisayollar"))
        m.addSeparator()
        act(m, f"{APP_NAME} Hakkında", self.show_about)

    def show_guide(self, section=None):
        from .guide import GuideDialog
        dlg = getattr(self, "_guide", None)
        if dlg is None or dlg.colors != self.colors:
            if dlg is not None:
                dlg.close(); dlg.deleteLater()
            dlg = self._guide = GuideDialog(self, dict(self.colors))
        if section:
            dlg.goto(section)
        dlg.show(); dlg.raise_(); dlg.activateWindow()

    def show_about(self):
        AboutDialog(self, QApplication.instance().windowIcon()).exec()

    # ───────────────────────── ayarlar ─────────────────────────
    def restore_settings(self):
        s = self.settings
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        st = s.value("window_state")
        if st is not None:
            self.restoreState(st)            # panelin kenarı, boyutu, açık/kapalı ya da ayrı pencere olması
        area = s.value("dock_area", None)
        try:
            self.user_dock_area = Qt.DockWidgetArea(int(area)) if area is not None else self.dockWidgetArea(self.dock)
        except (TypeError, ValueError):
            self.user_dock_area = self.dockWidgetArea(self.dock)
        if self.user_dock_area == Qt.NoDockWidgetArea:
            self.user_dock_area = Qt.RightDockWidgetArea
        try:
            self.dock_ratio = float(s.value("dock_ratio")) if s.value("dock_ratio") else None
        except (TypeError, ValueError):
            self.dock_ratio = None
        if not s.value("layout_v46", False, type=bool):
            # 4.6 varsayılan yerleşimi (bir kereliğine): solda Kütüphane | Orijinal Belge | Alıntılar sekmeleri,
            # kütüphane açık ve dört kapak genişliğinde.
            s.setValue("layout_v46", True)
            doc_open = self.doc_dock.toggleViewAction().isChecked()
            q_open = self.quotes_dock.toggleViewAction().isChecked()
            for d in (self.lib_dock, self.doc_dock, self.quotes_dock):
                d.setFloating(False)
                self.addDockWidget(Qt.LeftDockWidgetArea, d)
            self.tabifyDockWidget(self.lib_dock, self.doc_dock)
            self.tabifyDockWidget(self.doc_dock, self.quotes_dock)
            self.lib_dock.show()
            self.doc_dock.setVisible(doc_open)
            self.quotes_dock.setVisible(q_open)
            self.lib_dock.raise_()
            QTimer.singleShot(0, lambda: self.resizeDocks([self.lib_dock], [self.library.columns_width()],
                                                          Qt.Horizontal))
        self.sec_voice.set_expanded(s.value("sec_voice", True, type=bool))
        self.sec_doc.set_expanded(s.value("sec_doc", True, type=bool))
        self.awake_act.setChecked(s.value("keep_awake", True, type=bool))
        self.thin_act.setChecked(s.value("thin_progress", True, type=bool))
        ap = self.appearance
        ap["family"] = s.value("text_family", ap["family"])
        ap["size"] = s.value("font_size", ap["size"], type=int)
        ap["line"] = s.value("line_spacing", ap["line"], type=int)
        ap["para"] = s.value("para_spacing", ap["para"], type=int)
        ap["margin"] = s.value("doc_margin", ap["margin"], type=int)
        self.apply_appearance(ap)
        self.rate.setValue(s.value("rate", 100, type=int))
        self.on_rate_changed(self.rate.value())
        self.pause.setValue(s.value("pause", 45, type=int))
        self.on_pause_changed(self.pause.value())
        self.auto_check.setChecked(s.value("auto", True, type=bool))
        self.follow_check.setChecked(s.value("follow", True, type=bool))
        self.follow_act.setChecked(self.follow_check.isChecked())
        self.ocr.setChecked(s.value("ocr", True, type=bool))
        self.skip_notes.setChecked(s.value("skip_notes", True, type=bool))
        self.strip_headers.setChecked(s.value("strip_headers", True, type=bool))
        try:
            self.wpm = {k: tuple(v) for k, v in json.loads(s.value("wpm", "{}") or "{}").items()}
        except (ValueError, TypeError):
            self.wpm = {}
        try:
            self.custom_theme = json.loads(s.value("custom_theme", "{}") or "{}")
        except (ValueError, TypeError):
            self.custom_theme = {}
        legacy = "Gece" if s.value("dark", False, type=bool) else DEFAULT_THEME   # sürüm 3'ten kalan ayar
        name = s.value("theme", legacy)
        if name not in THEMES and not (name == CUSTOM and self.custom_theme):
            name = DEFAULT_THEME
        self.theme_name = name
        if s.value("on_top", False, type=bool):
            self.on_top_act.setChecked(True)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        mode = s.value("mode", 0, type=int)
        if not IS_WINDOWS:
            mode = 0
        self.mode.blockSignals(True); self.mode.setCurrentIndex(mode); self.mode.blockSignals(False)
        self.on_mode_changed(mode, save=False)
        self.update_recent_menu()

    def save_settings(self):
        s = self.settings
        if self._auto_moved:                 # dar pencere için geçici taşımayı kalıcı sanmayalım
            self._auto_moving = True
            self.addDockWidget(self.user_dock_area, self.dock)
            self._auto_moving = False
        s.setValue("geometry", self.saveGeometry())
        s.setValue("window_state", self.saveState())
        if self.dock_ratio:
            s.setValue("dock_ratio", round(self.dock_ratio, 4))
        s.setValue("dock_area", int(self.user_dock_area.value))
        s.setValue("sec_voice", self.sec_voice.is_expanded())
        s.setValue("sec_doc", self.sec_doc.is_expanded())
        s.setValue("keep_awake", self.awake_act.isChecked())
        s.setValue("thin_progress", self.thin_act.isChecked())
        ap = self.appearance
        s.setValue("text_family", ap["family"]); s.setValue("font_size", ap["size"])
        s.setValue("line_spacing", ap["line"]); s.setValue("para_spacing", ap["para"])
        s.setValue("doc_margin", ap["margin"])
        s.setValue("rate", self.rate.value())
        s.setValue("pause", self.pause.value())
        s.setValue("auto", self.auto_check.isChecked())
        s.setValue("follow", self.follow_check.isChecked())
        s.setValue("ocr", self.ocr.isChecked())
        s.setValue("skip_notes", self.skip_notes.isChecked())
        s.setValue("strip_headers", self.strip_headers.isChecked())
        s.setValue("mode", self.mode.currentIndex())
        s.setValue("theme", self.theme_name)
        s.setValue("custom_theme", json.dumps(self.custom_theme))
        s.setValue("on_top", self.on_top_act.isChecked())
        s.setValue("wpm", json.dumps(self.wpm))
        s.remove("dark")

    def recent_files(self):
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if p]

    def add_recent(self, path):
        rec = [p for p in self.recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent", ([path] + rec)[:MAX_RECENT])
        self.update_recent_menu()

    def update_recent_menu(self):
        self.recent_menu.clear()
        stored = self.recent_files()
        files = [p for p in stored if os.path.exists(p)]
        if len(files) != len(stored):
            self.settings.setValue("recent", files)      # silinmiş/taşınmış dosyaları listeden at
        if hasattr(self, "empty"):
            self.empty.set_recent(files)
        if not files:
            a = self.recent_menu.addAction("(boş)"); a.setEnabled(False)
            return
        for p in files:
            a = self.recent_menu.addAction(Path(p).name)
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, p=p: self.load_path(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Listeyi Temizle", self.clear_recent)

    def clear_recent(self):
        self.settings.setValue("recent", [])
        self.update_recent_menu()

    # ───────────────────────── görünüm ─────────────────────────
    def current_theme(self):
        return self.custom_theme if self.theme_name == CUSTOM else THEMES[self.theme_name]

    def apply_theme(self, theme=None):
        pal, self.colors = palette_for(theme if theme is not None else self.current_theme())
        QApplication.instance().setPalette(pal)
        self.setStyleSheet("")      # aynı stil sayfası yeniden verilince Qt pencereyi yeniden boyamaz; önce sıfırla
        # Not: QSpinBox'a padding verilmez; Qt'de içteki yazı alanını 1 piksele düşürüp sayıyı görünmez yapıyor.
        self.setStyleSheet("QPushButton{padding:6px 12px} QComboBox{padding:4px 8px}"
                           "#topBar QPushButton{padding:6px 9px}"
                           "QGroupBox{font-weight:600; margin-top:14px; padding-top:6px}"
                           "QGroupBox::title{subcontrol-origin:margin; left:8px}"
                           "QProgressBar{min-height:20px}")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findText(self.theme_name)))
        if self.theme_name in self.theme_actions:
            self.theme_actions[self.theme_name].setChecked(True)
        self.overlay.apply_colors(self.colors)
        if hasattr(self, "thin_progress"):
            self.thin_progress.set_colors(self.colors)
        # Stil sayfası düğme boşluklarını değiştirir: panelin en küçük genişliğini yeniden hesapla
        if hasattr(self, "panel_scroll"):
            QTimer.singleShot(0, self.fit_panel_width)
            QTimer.singleShot(0, self.apply_dock_ratio)
        bg = QColor(self.colors["win"])
        self.toast.setStyleSheet(
            f"#toast {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},235); color: {self.colors['text']};"
            f" border: 1px solid {self.colors['mid']}; border-radius: 10px; padding: 10px 18px; }}")
        self.update_dim()
        if hasattr(self, "quotes"):
            self.rebuild_marks(highlight=False)
        self.empty.apply_colors(self.colors)
        self.edit_banner.setStyleSheet(
            f"#editBanner {{ background: {self.colors['sent_bg']}; border-radius: 6px; }}"
            f"#editBanner QLabel {{ color: {self.colors['sent_fg']}; }}")
        if self.sentences and not self.editing:
            self.highlight(scroll=False)

    def set_theme(self, name):
        if name == CUSTOM and not self.custom_theme:
            self.edit_custom_theme()
            return
        self.theme_name = name
        self.apply_theme()

    def next_theme(self):
        names = list(THEMES) + ([CUSTOM] if self.custom_theme else [])
        i = names.index(self.theme_name) if self.theme_name in names else -1
        self.set_theme(names[(i + 1) % len(names)])

    def edit_custom_theme(self):
        base = self.custom_theme or self.current_theme()
        dlg = CustomThemeDialog(self, base)
        dlg.changed.connect(lambda t: self.apply_theme(t))      # canlı ön izleme
        if dlg.exec() == QDialog.Accepted:
            self.custom_theme = dlg.result_theme()
            self.theme_name = CUSTOM
            self.settings.setValue("custom_theme", json.dumps(self.custom_theme))
        self.apply_theme()

    def apply_appearance(self, ap):
        self.appearance = dict(ap)
        f = QFont(ap["family"])
        f.setPointSize(ap["size"])
        self.text.setFont(f)
        self.text.document().setDefaultFont(f)
        self.text.document().setDocumentMargin(ap["margin"])
        self.apply_block_format()
        self.update_reader_margins()
        if self.sentences and not self.editing:
            self.highlight(scroll=False)

    def apply_block_format(self):
        """Satır ve paragraf aralığını tüm metne uygular (cümle konumlarını değiştirmez)."""
        doc = self.text.document()
        if doc.isEmpty():
            return
        fmt = QTextBlockFormat()
        fmt.setLineHeight(float(self.appearance["line"]), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        fmt.setBottomMargin(float(self.appearance["para"]))
        cur = QTextCursor(doc)
        cur.select(QTextCursor.Document)
        cur.mergeBlockFormat(fmt)

    def edit_appearance(self):
        dlg = TextAppearanceDialog(self, self.appearance)
        dlg.changed.connect(self.apply_appearance)
        dlg.exec()

    def change_font(self, delta):
        ap = dict(self.appearance)
        ap["size"] = max(8, min(40, ap["size"] + delta))
        self.apply_appearance(ap)

    def set_on_top(self, on):
        # Pencere bayrağı değişince Qt pencereyi gizler; konumu koruyup yeniden gösteriyoruz.
        geo = self.saveGeometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.restoreGeometry(geo)
        self.show()
        self.statusBar().showMessage("Pencere her zaman üstte." if on else "Her zaman üstte kapatıldı.", 3000)

    # ───────────────────────── panel yerleşimi ve dar pencere ─────────────────────────
    def place_dock(self, area):
        """Paneli bir kenara yerleştirir; area=None ise ayrı pencere yapar."""
        self.dock.show()
        if area is None:
            self.dock.setFloating(True)
            return
        self._auto_moved = False
        self.dock.setFloating(False)
        self.addDockWidget(area, self.dock)
        self.user_dock_area = area
        self.size_dock(area)
        self.adapt_to_width()

    def size_dock(self, area):
        """Panel alta/üste geçince metne yer bıraksın: pencere yüksekliğinin yaklaşık üçte biri."""
        if area in (Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea):
            QTimer.singleShot(0, lambda: self.resizeDocks([self.dock], [max(220, int(self.height() * 0.34))],
                                                          Qt.Vertical))

    def fit_panel_width(self):
        """Alt alta düzende panel, içeriğin sığabileceği genişlikten daha dar olamasın:
        böylece düğmeler kesilmez ve yatay kaydırma çubuğu çıkmaz."""
        sc = self.panel_scroll
        sc.widget().adjustSize()
        if self.panel_box.is_wide():
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setMinimumWidth(280)
        else:
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            need = sc.widget().minimumSizeHint().width() + sc.verticalScrollBar().sizeHint().width() + 4
            sc.setMinimumWidth(max(280, need))
            self._panel_side_min = max(280, need)        # dar pencere kararında hep bu kullanılır

    def on_dock_float_changed(self, floating):
        """Ayrı pencereden geri takılan panel, yerleşimi yeni genişliğine göre baştan kursun."""
        QTimer.singleShot(0, lambda: self.panel_box.update_direction(self.panel_scroll.viewport().width()))
        if not floating:
            QTimer.singleShot(0, lambda: self.size_dock(self.dockWidgetArea(self.dock)))
        self.adapt_to_width()

    def on_dock_moved(self, area):
        if not self._auto_moving and area != Qt.NoDockWidgetArea:
            self.user_dock_area = area       # kullanıcı sürükleyerek taşıdı
            self._auto_moved = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.adapt_to_width()
        if self._last_width is not None and self.width() != self._last_width:
            QTimer.singleShot(0, self.apply_dock_ratio)
        self._last_width = self.width()

    def side_dock_docked(self):
        return (self.dock.isVisible() and not self.dock.isFloating() and not self.immersive()
                and self.dockWidgetArea(self.dock) in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea))

    DEFAULT_DOCK_RATIO = 0.19
    MIN_TEXT_WIDTH = 520

    def apply_dock_ratio(self):
        """Pencere boyutu değişince: kontrol paneli oranını korur, kütüphane yer oldukça üç kapak genişliğinde kalır,
        metin alanı geri kalanı alır."""
        docks, sizes = [], []
        target = self.dock.width()
        if self.side_dock_docked():
            ratio = self.dock_ratio or self.DEFAULT_DOCK_RATIO
            target = max(self.dock.minimumSizeHint().width(), int(ratio * self.width()))
            docks.append(self.dock); sizes.append(target)
        lib = self.lib_dock
        if lib.isVisible() and not lib.isFloating() and not self.immersive() and \
                self.dockWidgetArea(lib) in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
            room = self.width() - (target if docks else 0) - self.MIN_TEXT_WIDTH
            lib_target = max(lib.minimumSizeHint().width(), min(self.library.columns_width(), room))
            docks.append(lib); sizes.append(lib_target)
        if docks and any(abs(sz - d.width()) > 2 for d, sz in zip(docks, sizes)):
            self._ratio_applying = True
            self.resizeDocks(docks, sizes, Qt.Horizontal)
            QTimer.singleShot(0, lambda: setattr(self, "_ratio_applying", False))

    def on_dock_resized(self):
        """Kullanıcı panelin kenarını sürükledi: yeni oranı hatırla (pencere boyutu değişmediyse)."""
        if self._ratio_applying or not self.side_dock_docked() or self.width() != self._last_width:
            return
        self.dock_ratio = self.dock.width() / max(1, self.width())

    def expand_library(self, on):
        """Kütüphaneyi ekranı kaplayan ayrı bir pencereye alır; kapatınca eski yerine döner."""
        if on:
            if self.immersive():
                self.exit_immersive()
            self._lib_was_floating = self.lib_dock.isFloating()
            self._lib_area = self.dockWidgetArea(self.lib_dock)
            self.lib_dock.show()
            self.lib_dock.setFloating(True)
            screen = self.screen() or QApplication.primaryScreen()
            self.lib_dock.setGeometry(screen.availableGeometry())
            self.lib_dock.raise_()
            self.lib_dock.activateWindow()
            self.library.view_combo.setFocus()
        else:
            if not getattr(self, "_lib_was_floating", False):
                self.lib_dock.setFloating(False)
                if getattr(self, "_lib_area", None) not in (None, Qt.NoDockWidgetArea):
                    self.addDockWidget(self._lib_area, self.lib_dock)
                self.resizeDocks([self.lib_dock], [self.library.columns_width()], Qt.Horizontal)
            self.activateWindow()
        self.library.expand_btn.blockSignals(True)
        self.library.expand_btn.setChecked(on)
        self.library.expand_btn.blockSignals(False)

    def adapt_to_width(self):
        """Dar pencerede yan panel metni ezmesin diye alta iner; pencere genişleyince yerine döner."""
        if self.immersive() or not hasattr(self, "dock") or self.dock.isFloating():
            return
        # Sınır sabit değil: metin alanı ile panelin en küçük genişliklerinin toplamına biraz pay eklenir.
        # Pencere bu sınıra yaklaşınca panel alta iner ve pencere daha da daralabilir hâle gelir.
        # Panel alta inince içi yan yana dizilip daha dar görünür; karar hep yandaki genişliğe göre verilsin,
        # yoksa panel alta inip yukarı çıkarak gidip gelir.
        side_min = getattr(self, "_panel_side_min", self.panel_scroll.minimumWidth())
        limit = self.centralWidget().minimumSizeHint().width() + side_min + 80
        for d in self.side_docks()[1:]:
            if d.isVisible() and not d.isFloating() and self.dockWidgetArea(d) in (
                    Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
                limit += d.minimumSizeHint().width()
        limit = max(NARROW_WIDTH, limit)
        narrow = self.width() < (limit + 40 if self._auto_moved else limit)
        side = self.user_dock_area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea)
        cur = self.dockWidgetArea(self.dock)
        target = None
        if narrow and side and cur in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
            target, self._auto_moved = Qt.BottomDockWidgetArea, True
        elif not narrow and self._auto_moved:
            target, self._auto_moved = self.user_dock_area, False
        if target is not None:
            self._auto_moving = True
            self.addDockWidget(target, self.dock)
            self._auto_moving = False
            self.size_dock(target)
        self.theme_combo.setVisible(self.width() >= 640)     # dar pencerede tema menüden seçilir

    # ───────────────────────── tam ekran ve odaklanma ─────────────────────────
    def immersive(self):
        return self.is_fullscreen or self.focus_mode

    def set_fullscreen(self, on):
        if on == self.is_fullscreen:
            self.fullscreen_act.setChecked(on)
            return
        if on:
            self._was_maximized = self.isMaximized()
            self.is_fullscreen = True
            self.apply_immersive()
            self.showFullScreen()
        else:
            self.is_fullscreen = False
            self.apply_immersive()
            if self._was_maximized:
                self.showMaximized()
            else:
                self.showNormal()

    def set_focus_mode(self, on):
        if on == self.focus_mode:
            self.focus_act.setChecked(on)
            return
        self.focus_mode = on
        self.apply_immersive()

    def exit_immersive(self):
        if self.is_fullscreen:
            self.set_fullscreen(False)
        if self.focus_mode:
            self.set_focus_mode(False)

    def on_escape(self):
        if self.loading:
            self.cancel_load()
        elif self.editing:
            self.cancel_edit_mode()
        elif self.immersive():
            self.exit_immersive()
        else:
            self.stop_playback()

    def apply_immersive(self):
        imm = self.immersive()
        entering = imm and not self._imm_applied
        if entering:
            self._docks_visible = {d: d.isVisible() for d in self.side_docks()}
        self.peek = False
        self._imm_applied = imm
        self.fullscreen_act.setChecked(self.is_fullscreen)
        self.focus_act.setChecked(self.focus_mode)
        self.overlay.set_exit_text("⤢ Tam Ekrandan Çık" if self.is_fullscreen else "⤢ Odaklanmadan Çık")
        self.update_chrome()
        self.update_dim()
        self.update_reader_margins()
        if imm:
            self.text.setFocus()
            if entering:
                self.show_toast("Menü ve panel için Enter  ·  Çıkmak için Esc")
        else:
            self.overlay.hide()
            self.cursor_timer.stop()
            self.text.viewport().unsetCursor()
            self.adapt_to_width()
        self.update_power()
        if self.sentences:
            QTimer.singleShot(60, self.reveal_current)      # yerleşim oturduktan sonra okunan yere git

    def side_docks(self):
        return [d for d in (getattr(self, "dock", None), getattr(self, "lib_dock", None),
                            getattr(self, "quotes_dock", None), getattr(self, "doc_dock", None)) if d is not None]

    def update_chrome(self):
        """Tam ekran/odaklanmada yalnızca metin kalır; Enter (peek) menü ve paneli geri getirir."""
        imm = self.immersive()
        show = not imm or self.peek
        self.menuBar().setVisible(show)
        self.top_bar.setVisible(show)
        self.statusBar().setVisible(show)
        self.progress_row.setVisible(show)
        for d in self.side_docks():
            was = self._docks_visible.get(d, d is self.dock)
            if not imm:
                d.setVisible(was)
            else:
                # Enter ile açılınca önceden açık olan paneller (ve her durumda kontrol paneli) görünür.
                d.setVisible(self.peek and (was or d is self.dock))
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if show else Qt.ScrollBarAlwaysOff)
        self.text.setFrameShape(QFrame.NoFrame if imm else QFrame.StyledPanel)
        if imm:
            self.root_layout.setContentsMargins(0, 0, 0, 0)
        else:
            self.root_layout.setContentsMargins(14, 10, 14, 4)
        for sc_ in self.enter_shortcuts:
            sc_.setEnabled(imm and not self.peek)
        self.update_thin_progress()

    def update_thin_progress(self):
        if not hasattr(self, "thin_progress"):
            return
        show = (self.immersive() and not self.peek and self.thin_act.isChecked() and bool(self.sentences))
        self.thin_progress.setVisible(show)
        if show:
            self.thin_progress.reposition()

    def toggle_peek(self):
        if not self.immersive():
            return
        self.peek = not self.peek
        self.update_chrome()
        if not self.peek:
            self.text.setFocus()

    def update_reader_margins(self):
        """Tam ekran ve odaklanmada metni okunaklı genişlikte, ortalanmış bir sütuna alır."""
        if not hasattr(self, "reader"):
            return
        if self.immersive():
            fm = QFontMetrics(self.text.font())
            col = fm.horizontalAdvance("n") * READING_COLUMN + 2 * self.appearance["margin"] + 24
            side = max(0, (self.reader.width() - col) // 2)
            self.reader_layout.setContentsMargins(side, 18, side, 0)
            self.reader.setAutoFillBackground(True)
        else:
            self.reader_layout.setContentsMargins(0, 0, 0, 0)
            self.reader.setAutoFillBackground(False)

    def update_dim(self):
        """Odaklanma modunda okunmayan metin soluklaşır; okunan cümle kendi rengiyle öne çıkar."""
        if not self.colors:
            return
        pal = self.text.palette()
        pal.setColor(QPalette.Text, QColor(self.colors["mid" if self.focus_mode else "text"]))
        self.text.setPalette(pal)

    def on_immersive_mouse(self):
        self.text.viewport().unsetCursor()
        self.overlay.poke()
        if self.is_fullscreen:
            self.cursor_timer.start()

    def hide_cursor(self):
        if self.is_fullscreen and not self.peek and not self.overlay.underMouse():
            self.text.viewport().setCursor(Qt.BlankCursor)

    def show_toast(self, text, ms=3200):
        self.toast.setText(text)
        self.toast.adjustSize()
        self.place_toast()
        self.toast.show()
        self.toast.raise_()
        self.toast_timer.start(ms)

    def place_toast(self):
        if hasattr(self, "toast"):
            self.toast.move((self.reader.width() - self.toast.width()) // 2, 30)

    def update_power(self):
        """Tam ekranda ekran ve sistem uyanık kalır; okurken (seçenek açıksa) yalnızca sistem."""
        if not hasattr(self, "awake_act"):
            return
        reading = self.state in ("playing", "loading") and self.awake_act.isChecked()
        set_awake(system=reading or self.is_fullscreen, display=self.is_fullscreen)

    # ───────────────────────── kütüphane ─────────────────────────
    def open_cleanup(self):
        from .maintenance import CleanupDialog, perform_cleanup
        cover_dir = os.path.join(data_dir(), "kapaklar")
        if self.loading:
            return
        if self.editing and not self.cancel_edit_mode():
            return
        dlg = CleanupDialog(self, self.store, self.cache_dir, cover_dir, self.tmpdir)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.chosen()
        self.close_document()                    # temiz bir sayfayla başla
        self.clear_audio_cache()
        self.flush_position()
        freed, done = perform_cleanup(chosen, self.store, self.cache_dir, cover_dir, self.tmpdir, self.settings)
        if "small" in chosen:
            self.wpm = {}
            self.update_wpm_label()
        self.rules = self.store.load_rules()
        self.rebuild_pronouncer()
        self.update_recent_menu()
        self.library.cover_cache.clear()
        self.refresh_library()
        self.quotes.refresh()
        msg = "Temizlendi: " + ", ".join(done) + f".\n\nKazanılan yer: {human_size(freed)}"
        if "settings" in chosen:
            self._skip_save = True               # kapanırken eski ayarları yeniden yazmasın
            msg += "\n\nAyarların varsayılana dönmesi için uygulamayı kapatıp yeniden açın."
        QMessageBox.information(self, "Temizlik tamamlandı", msg)

    def show_docview(self, on):
        if on and self.immersive():
            self.exit_immersive()
        self.doc_dock.setVisible(on)
        if on:
            self.doc_dock.raise_()                 # sekme olarak duruyorsa öne gelsin

    def sync_panel_buttons(self):
        """Üst çubuk düğmeleri panelin açık/kapalı olmasını gösterir (sekmenin önde olmasını değil)."""
        for dock, widgets in ((self.lib_dock, (self.lib_btn, self.lib_act)),
                              (self.doc_dock, (self.doc_btn, self.doc_act)),
                              (self.quotes_dock, (self.quotes_act,))):
            on = dock.toggleViewAction().isChecked()
            for w in widgets:
                w.blockSignals(True); w.setChecked(on); w.blockSignals(False)

    def on_doc_visibility(self, visible):
        self.sync_panel_buttons()
        if visible and not self.immersive():
            self.docview.open(self.doc_path)
            self._doc_label = None
            self.sync_docview()

    def sync_docview(self):
        """Okunan cümlenin sayfasını orijinal belge paneline bildirir (yalnızca sayfa değişince)."""
        if not self.sentences or not self.doc_dock.isVisible():
            return
        s = self.sentences[self.current_index]
        label = self.toc[s.section][0] if s.section < len(self.toc) else ""
        if label != self._doc_label:
            self._doc_label = label
            self.docview.set_reading_label(label)

    def make_backup(self):
        from .backup import create_backup
        name = f"Metin Dinleyici yedek {datetime.now():%Y-%m-%d %H.%M}.zip"
        start = os.path.join(self.settings.value("backup_dir", os.path.expanduser("~")), name)
        out, _ = QFileDialog.getSaveFileName(self, "Yedeği kaydet", start, "Yedek (*.zip)")
        if not out:
            return
        if not out.lower().endswith(".zip"):
            out += ".zip"
        self.flush_position()
        self.save_settings()
        try:
            info = create_backup(out, self.store, self.settings, os.path.join(data_dir(), "kapaklar"))
        except Exception as e:
            QMessageBox.warning(self, "Yedeklenemedi", str(e))
            return
        self.settings.setValue("backup_dir", os.path.dirname(out))
        c = ", ".join(f"{v} {k}" for k, v in info["counts"].items())
        show_done(self, "Yedek alındı", f"Yedek hazır: {c}.\n\nBelgelerin kendisi (PDF, EPUB…) yedeğe girmez; "
                  "onları ayrıca saklayın.", out)

    def restore_from_backup(self):
        from .backup import auto_backup, read_info, restore_backup
        path, _ = QFileDialog.getOpenFileName(self, "Yedeği seç", self.settings.value("backup_dir", ""),
                                              "Yedek (*.zip)")
        if not path:
            return
        try:
            info = read_info(path)
        except ValueError as e:
            QMessageBox.warning(self, "Geri yüklenemez", str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Yedekten geri yükle")
        lay = QVBoxLayout(dlg)
        c = ", ".join(f"{v} {k}" for k, v in (info.get("counts") or {}).items())
        lab = QLabel(f"<b>{os.path.basename(path)}</b><br>Tarih: {info.get('date', '?').replace('T', ' ')} · "
                     f"Sürüm {info.get('version', '?')}<br>İçerik: {c}")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        cb_data = QCheckBox("Kütüphane, kaldığınız yerler, alıntılar, sözlük ve düzeltmeler")
        cb_data.setChecked(True)
        cb_set = QCheckBox("Ayarlar ve pencere yerleşimi (yeniden başlatma gerekir)")
        cb_set.setChecked(info.get("has_settings", False))
        cb_set.setEnabled(info.get("has_settings", False))
        cb_cov = QCheckBox(f"Kapak resimleri ({info.get('covers', 0)})")
        cb_cov.setChecked(info.get("covers", 0) > 0)
        cb_cov.setEnabled(info.get("covers", 0) > 0)
        for cb in (cb_data, cb_set, cb_cov):
            lay.addWidget(cb)
        warn = QLabel("Seçilenler şu anki verilerin <b>yerine</b> geçer. Başlamadan önce şu anki durumun bir "
                      "güvenlik kopyası kendiliğinden alınır.")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Geri Yükle")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        parts = {k for k, cb in (("data", cb_data), ("settings", cb_set), ("covers", cb_cov))
                 if cb.isChecked() and cb.isEnabled()}
        if not parts:
            return
        if self.editing and not self.cancel_edit_mode():
            return
        self.close_document()
        self.flush_position()
        self.save_settings()
        cover_dir = os.path.join(data_dir(), "kapaklar")
        try:
            safety = auto_backup(self.store, self.settings, cover_dir, os.path.join(data_dir(), "yedekler"))
            restore_backup(path, self.store, self.settings, cover_dir, parts)
        except Exception as e:
            QMessageBox.warning(self, "Geri yükleme başarısız", f"{e}\n\nVerileriniz değiştirilmedi.")
            return
        self.rules = self.store.load_rules()
        self.rebuild_pronouncer()
        self.library.cover_cache.clear()
        self.update_recent_menu()
        self.refresh_library()
        self.quotes.refresh()
        missing = len(self.store.missing_in_library())
        msg = "Yedek geri yüklendi.\n\nGüvenlik kopyası: " + safety
        if "settings" in parts:
            self._skip_save = True              # kapanırken geri yüklenen ayarların üzerine yazmasın
            msg += "\n\nAyarların uygulanması için uygulamayı kapatıp yeniden açın."
        if missing:
            msg += (f"\n\n{missing} belgenin dosyası bu bilgisayarda bulunamadı. Kütüphanede ＋ Ekle › "
                    "“Eksik Dosyaları Bul” ile belgelerinizin bulunduğu klasörü taratabilirsiniz.")
        QMessageBox.information(self, "Geri yükleme tamamlandı", msg)

    def export_quotes(self):
        self.quotes.export()

    def library_visible(self):
        return hasattr(self, "lib_dock") and self.lib_dock.isVisible()

    def show_library(self, on):
        if on and self.immersive():
            self.exit_immersive()
        already = self.lib_dock.isVisible()
        self.lib_dock.setVisible(on)
        if on:
            if already:
                self.refresh_library()
            self.lib_dock.raise_()               # başka bir panelle sekme olarak birleşmişse öne gelsin
            self.library.search.setFocus()

    def on_lib_visibility(self, visible):
        self.sync_panel_buttons()
        if visible and not self.immersive():
            self.library.set_current(self.doc_id)
            self.library.refresh()

    def refresh_library(self):
        """Kütüphane paneli açıksa güncel durumu (açık belge, son açılma, ilerleme) göster."""
        if self.library_visible():
            self.library.set_current(self.doc_id)
            self.library.refresh()

    def open_from_library(self, path):
        if self.library.expand_btn.isChecked():
            self.expand_library(False)
        if self.doc_path and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.doc_path)):
            return                                   # zaten açık
        self.load_path(path)

    def on_doc_renamed(self, doc_id, new_path):
        old = None
        if doc_id == self.doc_id:
            old, self.doc_path = self.doc_path, new_path
            self.file_label.setText(Path(new_path).name)
            self.setWindowTitle(f"{Path(new_path).name} — {APP_NAME}")
        rec = self.recent_files()
        if old:
            rec = [new_path if os.path.normcase(p) == os.path.normcase(old) else p for p in rec]
            if self.docview.path and os.path.normcase(self.docview.path) == os.path.normcase(old):
                self.docview.path = new_path
        self.settings.setValue("recent", [p for p in rec if os.path.exists(p)])
        self.update_recent_menu()

    def on_docs_removing(self, ids):
        if self.doc_id in ids:
            self.close_document()

    # ───────────────────────── alıntılar, notlar, vurgular ─────────────────────────
    def toggle_quotes(self, on=None):
        on = (not self.quotes_dock.isVisible()) if on is None else on
        if on and self.immersive():
            self.exit_immersive()
        self.quotes_dock.setVisible(on)
        if on:
            self.quotes_dock.raise_()
            self.quotes.refresh()

    def on_quotes_visibility(self, visible):
        self.sync_panel_buttons()
        if visible and not self.immersive():
            self.quotes.set_doc(self.doc_id)

    def can_annotate(self):
        return bool(self.sentences) and bool(self.doc_id) and not self.editing

    def page_label_for(self, i):
        sec = self.sentences[i].section
        label = self.toc[sec][0] if sec < len(self.toc) else ""
        return label[6:] if label.startswith("Sayfa ") else label

    def add_annotation(self, kind, i, text=None, count=1, note="", tags=(), page=None, msg=None):
        s = self.sentences[i]
        aid = self.store.add_annotation(self.doc_id, kind, text or s.text, note, anchor_of(s.text), i, count,
                                        self.page_label_for(i) if page is None else page, tags=tags)
        self.last_annotation = aid
        self.after_annotation_change(msg)
        return aid

    def after_annotation_change(self, msg=None):
        self.rebuild_marks()
        self.quotes.refresh()
        if msg:
            self.statusBar().showMessage(msg, 6000)

    def quote_current(self):
        if not self.can_annotate():
            return
        sel = self.text.textCursor()
        if sel.hasSelection() and sel.selectedText().strip():
            self.quote_selection(sel)
        else:
            self.quote_sentence(self.current_index)

    def quote_sentence(self, i):
        if not self.can_annotate():
            return
        s = self.sentences[i]
        if any(r["kind"] == KIND_QUOTE and r["text"] == s.text for r in self.ann_by_sentence.get(i, [])):
            self.statusBar().showMessage("Bu cümle zaten alıntılanmış.", 4000)
            return
        self.add_annotation(KIND_QUOTE, i, msg=f"Alıntı eklendi (cümle {i + 1}) · Not ve etiket için Shift+M")

    def quote_selection(self, cur):
        if not self.can_annotate():
            return
        a, b = cur.selectionStart(), cur.selectionEnd()
        first, last = self.sentence_at(a), self.sentence_at(max(a, b - 1))
        text = cur.selectedText().replace(" ", " ")
        text = re.sub(r"—\s[^—\n]{1,60}\s—", " ", text)         # seçime giren "— Sayfa 3 —" başlıkları
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        self.add_annotation(KIND_QUOTE, first, text=text, count=last - first + 1,
                            msg="Seçili metin alıntılandı · Not ve etiket için Shift+M")

    def note_current(self):
        if self.can_annotate():
            self.note_sentence(self.current_index)

    def note_sentence(self, i):
        if not self.can_annotate():
            return
        dlg = AnnotationDialog(self, KIND_NOTE, self.sentences[i].text, "", (), self.page_label_for(i),
                               self.store.all_tags(), title="Not ekle")
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            self.add_annotation(KIND_NOTE, i, note=v["note"], tags=v["tags"], page=v["page_label"],
                                msg="Not eklendi")

    def highlight_current(self):
        if self.can_annotate():
            self.toggle_highlight(self.current_index)

    def toggle_highlight(self, i):
        if not self.can_annotate():
            return
        existing = [r["id"] for r in self.ann_by_sentence.get(i, []) if r["kind"] == KIND_HIGHLIGHT]
        if existing:
            self.store.delete_annotations(existing)
            self.after_annotation_change("Vurgu kaldırıldı")
        else:
            self.add_annotation(KIND_HIGHLIGHT, i, msg="Vurgulandı · Kaldırmak için yeniden V")

    def edit_last_annotation(self):
        if self.last_annotation and self.store.annotations(ids=[self.last_annotation]):
            self.quotes.edit(self.last_annotation)
        else:
            self.statusBar().showMessage("Düzenlenecek yeni bir kayıt yok.", 3000)

    def rebuild_marks(self, highlight=True):
        """Alıntı, not ve vurguları metinde işaretler: vurgu arka plan rengi, alıntı düz çizgi, not noktalı çizgi."""
        self.ann_marks, self.ann_by_sentence = [], {}
        if not self.doc_id or not self.sentences:
            self.ann_rows = []
            return
        self.ann_rows = self.store.annotations(self.doc_id)
        hl = QColor(self.colors.get("hl", "#b49a3a"))
        bg = QColor(hl); bg.setAlpha(80)
        doc = self.text.document()
        n = len(self.sentences)
        for r in self.ann_rows:
            k = locate_anchor(self.sentences, r["sent_index"], r["anchor"])
            if k is None:
                continue                         # metin değiştiyse yanlış cümleye işaret koymayalım
            e = min(n - 1, k + max(1, r["sent_count"] or 1) - 1)
            fmt = QTextCharFormat()
            if r["kind"] == KIND_HIGHLIGHT:
                fmt.setBackground(bg)
            else:
                fmt.setUnderlineStyle(QTextCharFormat.SingleUnderline if r["kind"] == KIND_QUOTE
                                      else QTextCharFormat.DotLine)
                fmt.setUnderlineColor(hl)
            # Cümle cümle işaretle: aradaki sayfa başlıkları ve boş satırlar işaretlenmesin.
            for j in range(k, e + 1):
                self.ann_by_sentence.setdefault(j, []).append(r)
                cur = QTextCursor(doc)
                cur.setPosition(self.sentences[j].start)
                cur.setPosition(self.sentences[j].end, QTextCursor.KeepAnchor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cur
                sel.format = fmt
                self.ann_marks.append(sel)
        if highlight and self.sentences and not self.editing:
            self.highlight(scroll=False)

    def show_annotation_tip(self, ev):
        c = self.text.cursorForPosition(ev.pos())
        rows = self.ann_by_sentence.get(self.sentence_at(c.position()))
        if not rows:
            QToolTip.hideText()
            return
        lines = []
        for r in rows:
            tags = " ".join("#" + t for t in (r["tags"] or "").split())
            if r["kind"] == KIND_NOTE:
                lines.append(f"<b>✎ Not:</b> {html.escape(r['note'])}")
            elif r["kind"] == KIND_QUOTE:
                lines.append("<b>❝ Alıntı</b>" + (f" — {html.escape(r['note'])}" if r["note"] else ""))
            else:
                lines.append("<b>▌ Vurgu</b>")
            if tags:
                lines[-1] += f" <i>{html.escape(tags)}</i>"
        QToolTip.showText(ev.globalPos(), "<br>".join(lines), self.text.viewport())

    def goto_annotation(self, doc_id, idx, anchor):
        if doc_id == self.doc_id and self.sentences:
            k = locate_anchor(self.sentences, idx, anchor)
            self.jump_to(k if k is not None else idx, reveal=True)
            self.text.setFocus()
            return
        row = self.store.get_document(doc_id)
        if not row or not os.path.exists(row["path"]):
            QMessageBox.information(self, "Belge bulunamadı",
                                    "Bu kaydın belgesi bulunamadı. Kütüphanede “Dosyayı Bul” ile yerini gösterebilirsiniz.")
            return
        self.pending_goto = (doc_id, idx, anchor)
        self.load_path(row["path"])

    def annotation_audio(self, texts, name):
        if self.engine() != "edge":
            QMessageBox.information(self, "Ses dosyası", "Ses dosyası çevrimiçi (Edge) seslerle oluşturulur. "
                                    "Ses modunu çevrimiçiye alıp tekrar deneyin.")
            return
        safe = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "alıntılar"
        folder = os.path.dirname(self.doc_path) if self.doc_path else os.path.expanduser("~")
        out, _ = QFileDialog.getSaveFileName(self, "Ses dosyasını kaydet", os.path.join(folder, safe + ".mp3"),
                                             "MP3 (*.mp3)")
        if not out:
            return
        groups, cur, size = [], [], 0
        for t in texts:
            t = self.pron.apply(t)
            if cur and size + len(t) > 2500:
                groups.append(cur); cur, size = [], 0
            cur.append(t); size += len(t) + 1
        if cur:
            groups.append(cur)
        self.start_mp3_job(groups, out)

    def edit_document_details(self):
        if not self.doc_id:
            return
        from .library import DetailsDialog
        row = self.store.get_document(self.doc_id)
        dlg = DetailsDialog(self, row)
        if dlg.exec() == QDialog.Accepted:
            dlg.save(self.store, self.doc_id)
            self.quotes.refresh()
            self.refresh_library()

    # ───────────────────────── karşılama ekranı ve düzenleme şeridi ─────────────────────────
    def build_extras(self):
        self.empty = EmptyState(self.text.viewport())
        self.empty.open_clicked.connect(self.open_file)
        self.empty.library_clicked.connect(lambda: self.show_library(True))
        self.empty.guide_clicked.connect(self.show_guide)
        self.empty.recent_clicked.connect(self.load_path)
        self.empty.setGeometry(self.text.viewport().rect())
        self.empty.show()

        self.edit_banner = QFrame()
        self.edit_banner.setObjectName("editBanner")
        bl = QHBoxLayout(self.edit_banner)
        bl.setContentsMargins(12, 6, 8, 6)
        info = QLabel("<b>Düzenleme modu.</b> Metni doğrudan düzeltebilirsiniz. Boş satır yeni paragraf, "
                      "“— Sayfa N —” satırları sayfa başlığıdır. Ses ve ekran bundan sonra bu metni kullanır; "
                      "dosyanın kendisi değişmez.")
        info.setWordWrap(True)
        save = QPushButton("Kaydet (Ctrl+S)")
        save.clicked.connect(self.save_edit_mode)
        cancel = QPushButton("Vazgeç (Esc)")
        cancel.clicked.connect(self.cancel_edit_mode)
        for b in (save, cancel):
            b.setFocusPolicy(Qt.NoFocus)
        bl.addWidget(info, 1); bl.addWidget(save); bl.addWidget(cancel)
        self.edit_banner.hide()
        self.reader_layout.insertWidget(0, self.edit_banner)
        self.thin_progress = ThinProgress(self.reader)

        # Kütüphane, okuma alanıyla aynı yerde ayrı bir sayfa olarak durur.
        self.library = LibraryView(self.store, self.work_pool, self.settings, os.path.join(data_dir(), "kapaklar"))
        self.library.open_requested.connect(self.open_from_library)
        self.library.renamed.connect(self.on_doc_renamed)
        self.library.about_to_remove.connect(self.on_docs_removing)
        self.library.expand_toggled.connect(self.expand_library)
        QShortcut(QKeySequence(Qt.Key_Escape), self.library,
                  lambda: self.library.expand_btn.setChecked(False), context=Qt.WidgetWithChildrenShortcut)
        # Kütüphane de taşınabilir bir panel: varsayılan yeri sol; metin ortada, kontroller sağda kalır.
        self.lib_dock = QDockWidget("Kütüphane", self)
        self.lib_dock.setObjectName("library_panel")
        self.lib_dock.setWidget(self.library)
        self.lib_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.lib_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                                  | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.lib_dock)
        self.resizeDocks([self.lib_dock], [self.library.columns_width()], Qt.Horizontal)
        self.lib_dock.visibilityChanged.connect(self.on_lib_visibility)
        self.lib_dock.visibilityChanged.connect(lambda _: QTimer.singleShot(0, self.adapt_to_width))

        self.quotes = QuotesView(self.store, self.settings)
        self.quotes.goto_requested.connect(self.goto_annotation)
        self.quotes.audio_requested.connect(self.annotation_audio)
        self.quotes.changed.connect(self.rebuild_marks)
        self.quotes_dock = QDockWidget("Alıntılar ve Notlar", self)
        self.quotes_dock.setObjectName("quotes_panel")
        self.quotes_dock.setWidget(self.quotes)
        self.quotes_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.quotes_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                                     | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.quotes_dock)
        self.quotes_dock.hide()
        self.quotes_dock.visibilityChanged.connect(self.on_quotes_visibility)
        self.quotes_dock.visibilityChanged.connect(lambda _: QTimer.singleShot(0, self.adapt_to_width))

        # Orijinal belge paneli: metin ile kontrol paneli arasında; okurken gözle takip için.
        self.docview = DocView(self.settings)
        self.doc_dock = QDockWidget("Orijinal Belge", self)
        self.doc_dock.setObjectName("document_panel")
        self.doc_dock.setWidget(self.docview)
        self.doc_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.doc_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                                  | QDockWidget.DockWidgetClosable)
        # Varsayılan: solda kütüphaneyle sekme olarak (Kütüphane | Orijinal Belge | Alıntılar)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.doc_dock)
        self.tabifyDockWidget(self.lib_dock, self.doc_dock)
        self.tabifyDockWidget(self.doc_dock, self.quotes_dock)
        self.doc_dock.hide()
        self.doc_dock.visibilityChanged.connect(self.on_doc_visibility)
        self.doc_dock.visibilityChanged.connect(lambda _: QTimer.singleShot(0, self.adapt_to_width))
        self._doc_label = None
        self.doc_btn = QPushButton("Orijinal")
        self.doc_btn.setCheckable(True)
        self.doc_btn.setToolTip("Orijinal belgeyi yanda göster (F7)")
        self.doc_btn.setFocusPolicy(Qt.NoFocus)
        self.doc_btn.toggled.connect(self.show_docview)
        self.top_bar.layout().insertWidget(1, self.doc_btn)
        self.lib_btn = QPushButton("Kütüphane")
        self.lib_btn.setCheckable(True)
        self.lib_btn.setToolTip("Kütüphane (Ctrl+L)")
        self.lib_btn.setFocusPolicy(Qt.NoFocus)
        self.lib_btn.toggled.connect(self.show_library)
        self.top_bar.layout().insertWidget(0, self.lib_btn)

    def update_empty_state(self):
        show = not self.sentences and not self.loading and not self.editing
        self.empty.setGeometry(self.text.viewport().rect())
        self.empty.setVisible(show)

    def update_edit_actions(self):
        has_doc = bool(self.sentences)
        self.edit_act.setEnabled(has_doc and not self.editing)
        self.edit_btn.setEnabled(has_doc and not self.editing)
        self.save_edit_act.setEnabled(self.editing)
        self.undo_edit_act.setEnabled(bool(self.edit_undo) and not self.editing)
        self.remove_edits_act.setEnabled(self.has_edits and not self.editing)

    # ───────────────────────── telaffuz sözlüğü ─────────────────────────
    def rebuild_pronouncer(self):
        self.pron = Pronouncer(self.rules, self.doc_id)
        self.pron_version += 1
        self.on_cfg_changed()          # eski okunuşla hazırlanmış sesleri at, sıradakileri yeniden hazırlat

    def doc_title(self):
        return Path(self.doc_path).stem if self.doc_path else ""

    def open_pron_dialog(self):
        cur = self.sentences[self.current_index].text if self.sentences else ""
        dlg = PronunciationDialog(self, self.rules, self.doc_id, self.doc_title(),
                                  [s.text for s in self.sentences], cur, speak=self.speak_preview)
        if dlg.exec() == QDialog.Accepted:
            self.save_rules(dlg.rules, "Telaffuz sözlüğü kaydedildi.")

    def save_rules(self, rules, msg):
        self.store.save_rules(rules)
        self.rules = self.store.load_rules()
        self.rebuild_pronouncer()
        self.statusBar().showMessage(msg, 4000)

    def add_rule_for(self, text):
        dlg = RuleDialog(self, Rule(pattern=text.strip(), replacement=""), self.doc_id, self.doc_title(),
                         [s.text for s in self.sentences])
        if dlg.exec() == QDialog.Accepted:
            self.save_rules(self.rules + [dlg.rule], f"Telaffuz kuralı eklendi: {dlg.rule.pattern}")

    def speak_preview(self, text):
        """Sözlük penceresindeki ön izlemeyi seçili ses ve hızla okur (okuma konumunu etkilemez)."""
        if not text.strip():
            return
        self.stop_playback()
        engine, voice, rate = self.engine(), self.voice.currentData() or "", self.rate.value()
        pause = self.pause.value() / 100
        out = os.path.join(self.tmpdir, f"onizleme_{uuid.uuid4().hex}.{'mp3' if engine == 'edge' else 'wav'}")

        def job():
            if engine == "edge":
                synth_edge_chunk([text], voice, rate, out, pause)
            else:
                synth_sapi(text, voice, rate, out)
            return out

        def done(f):
            try:
                payload = {"path": f.result()}
            except Exception as e:
                payload = {"error": str(e) or e.__class__.__name__}
            self._safe_emit(self.bridge.preview_done, payload)
        self.synth_pool.submit(job).add_done_callback(done)

    def on_preview_done(self, r):
        if self.closing:
            return
        if "error" in r:
            QMessageBox.warning(self, "Seslendirme hatası", r["error"])
            return
        old = self.preview_path
        self.player.setSource(QUrl.fromLocalFile(r["path"]))
        self.current_path, self.playing = r["path"], None
        self.preview_path = r["path"]
        self.player.play()
        if old and old != r["path"]:
            safe_remove(old)

    # ───────────────────────── elle düzeltme ─────────────────────────
    def apply_sections(self, new, msg):
        """Düzeltilmiş bölümleri kaydeder ve ekrana kurar. Geri alınabilir."""
        if new == self.doc_sections:
            self.statusBar().showMessage("Değişiklik yok.", 3000)
            return False
        if not build_document(new)[1]:
            QMessageBox.warning(self, "Düzeltme uygulanmadı",
                                "Bu düzeltmeden sonra okunacak metin kalmıyor.")
            return False
        anchor = anchor_of(self.sentences[self.current_index].text) if self.sentences else None
        self.edit_undo.append(self.doc_sections)
        del self.edit_undo[:-30]
        self.store_sections(new)
        self.show_document(new, self.current_index, anchor)
        self.statusBar().showMessage(f"{msg} · Geri almak için Ctrl+Z", 6000)
        return True

    def store_sections(self, sections):
        if sections == self.extracted_sections:
            self.store.delete_edits(self.doc_id)        # özgün metne dönüldüyse kayıt tutmaya gerek yok
            self.has_edits = False
        else:
            self.store.save_edits(self.doc_id, sections, self.doc_opts)
            self.has_edits = True

    def undo_edit(self):
        if self.editing:
            return
        if not self.edit_undo:
            self.statusBar().showMessage("Geri alınacak düzeltme yok.", 3000)
            return
        prev = self.edit_undo.pop()
        anchor = anchor_of(self.sentences[self.current_index].text) if self.sentences else None
        self.store_sections(prev)
        self.show_document(prev, self.current_index, anchor)
        self.statusBar().showMessage("Son düzeltme geri alındı.", 4000)

    def remove_all_edits(self):
        if not self.has_edits:
            return
        if QMessageBox.question(self, "Düzeltmeleri kaldır",
                                "Bu belgede elle yaptığınız tüm düzeltmeler kaldırılıp dosyadan çıkarılan "
                                "özgün metne dönülsün mü?") != QMessageBox.Yes:
            return
        anchor = anchor_of(self.sentences[self.current_index].text) if self.sentences else None
        self.edit_undo.append(self.doc_sections)
        self.store_sections(self.extracted_sections)
        self.show_document(self.extracted_sections, self.current_index, anchor)
        self.statusBar().showMessage("Özgün metne dönüldü · Geri almak için Ctrl+Z", 6000)

    def _edited_clone(self, edit):
        """Ekrandaki belgenin bir kopyası üzerinde düzeltme yapar ve sonucu bölümlere çevirir."""
        doc = self.text.document().clone()
        cur = QTextCursor(doc)
        edit(cur)
        return parse_display(doc.toPlainText())

    def delete_range(self, a, b, msg):
        def edit(cur):
            cur.setPosition(a)
            cur.setPosition(b, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        self.apply_sections(self._edited_clone(edit), msg)

    def delete_sentence(self, i):
        s = self.sentences[i]
        self.delete_range(s.start, s.end, f"Cümle {i + 1} silindi")

    def delete_paragraph(self, pos):
        def edit(cur):
            cur.setPosition(pos)
            cur.select(QTextCursor.BlockUnderCursor)
            cur.removeSelectedText()
        self.apply_sections(self._edited_clone(edit), "Paragraf silindi")

    def delete_everywhere(self, text):
        full = self.text.toPlainText()
        n = full.count(text)
        if not n:
            return
        self.apply_sections(parse_display(full.replace(text, " ")), f"“{text[:40]}” {n} yerden silindi")

    def enter_edit_mode(self):
        if not self.sentences or self.editing:
            return
        if self.immersive():
            self.exit_immersive()
        self.stop_playback()
        self.flush_position()
        self.editing = True
        s = self.sentences[self.current_index]
        self.text.setExtraSelections([])
        doc = self.text.document()
        doc.setUndoRedoEnabled(True)
        doc.clearUndoRedoStacks()
        self.text.setReadOnly(False)
        self.text.setTextInteractionFlags(Qt.TextEditorInteraction)
        c = QTextCursor(doc)
        c.setPosition(s.start)
        self.text.setTextCursor(c)
        self.text.ensureCursorVisible()
        doc.setModified(False)
        self.edit_banner.show()
        self.dock.widget().setEnabled(False)          # düzenlerken okuma denetimleri kapalı
        self.text.setFocus()
        self.update_empty_state()
        self.update_edit_actions()

    def leave_edit_mode(self):
        self.editing = False
        doc = self.text.document()
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        doc.setUndoRedoEnabled(False)
        self.edit_banner.hide()
        self.dock.widget().setEnabled(True)
        self.update_edit_actions()

    def save_edit_mode(self):
        if not self.editing:
            return
        modified = self.text.document().isModified()
        new = parse_display(self.text.toPlainText())
        # Konumu düzenleme imlecine göre koru: imlecin bulunduğu cümle okunacak cümle olur.
        cpos = self.text.textCursor().position()
        self.leave_edit_mode()
        if not modified or new == self.doc_sections:
            self.show_document(self.doc_sections, self.current_index,
                               anchor_of(self.sentences[self.current_index].text))
            self.statusBar().showMessage("Değişiklik yapılmadı.", 3000)
            return
        if not self.apply_sections(new, "Düzenleme kaydedildi"):
            self.show_document(self.doc_sections, self.current_index)
            return
        # imlecin olduğu yere yakın cümleye geç
        k = self.sentence_at(min(cpos, max(0, self.text.document().characterCount() - 1)))
        self.jump_to(k, reveal=True)

    def cancel_edit_mode(self):
        """Dönüş: düzenleme modundan çıkıldı mı (kullanıcı vazgeçmeyi iptal ederse False)."""
        if not self.editing:
            return True
        if self.text.document().isModified():
            r = QMessageBox.question(self, "Düzenleme", "Kaydedilmemiş değişiklikler var. Kaydedilsin mi?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                self.save_edit_mode()
                return True
        self.leave_edit_mode()
        self.show_document(self.doc_sections, self.current_index,
                           anchor_of(self.sentences[self.current_index].text))
        return True

    # ───────────────────────── sağ tık menüsü ─────────────────────────
    def show_text_menu(self, pos):
        if self.editing:
            menu = self.text.createStandardContextMenu()
            menu.exec(self.text.viewport().mapToGlobal(pos))
            return
        if not self.sentences:
            return
        click = self.text.cursorForPosition(pos)
        i = self.sentence_at(click.position())
        sel = self.text.textCursor()
        sel_text = sel.selectedText().replace(" ", "\n").strip() if sel.hasSelection() else ""
        word_cur = QTextCursor(click)
        word_cur.select(QTextCursor.WordUnderCursor)
        word = sel_text if sel_text and "\n" not in sel_text else word_cur.selectedText().strip()

        menu = QMenu(self)
        menu.addAction("▶ Buradan Oku", lambda: self.jump_to(i, play=True))
        menu.addSeparator()
        if sel_text:
            menu.addAction("Seçili Metni Alıntıla", lambda: self.quote_selection(sel))
        menu.addAction(f"Bu Cümleyi Alıntıla{'' if sel_text else '  (M)'}", lambda: self.quote_sentence(i))
        menu.addAction("Not Ekle…", lambda: self.note_sentence(i))
        has_hl = any(r["kind"] == KIND_HIGHLIGHT for r in self.ann_by_sentence.get(i, []))
        menu.addAction("Vurguyu Kaldır" if has_hl else "Vurgula", lambda: self.toggle_highlight(i))
        own = [r for r in self.ann_by_sentence.get(i, []) if r["kind"] != KIND_HIGHLIGHT]
        if own:
            menu.addAction("Bu Cümledeki Kaydı Düzenle…", lambda: self.quotes.edit(own[0]["id"]))
        menu.addSeparator()
        menu.addAction("Bu Cümleyi Kopyala",
                       lambda: QApplication.clipboard().setText(self.sentences[i].text))
        if sel_text:
            menu.addAction("Seçili Metni Kopyala", lambda: QApplication.clipboard().setText(sel_text))
        menu.addSeparator()
        fix = menu.addMenu("Metni Düzelt")
        fix.addAction(f"Bu Cümleyi Sil (cümle {i + 1})", lambda: self.delete_sentence(i))
        fix.addAction("Bu Paragrafı Sil", lambda: self.delete_paragraph(click.position()))
        # Seçime bağlı işlemler hep görünür; koşul yoksa soluk durur ve ne gerektiğini söyler.
        if sel_text:
            a, b = sel.selectionStart(), sel.selectionEnd()
            fix.addAction("Seçili Metni Sil", lambda: self.delete_range(a, b, "Seçili metin silindi"))
        else:
            fix.addAction("Seçili Metni Sil  (önce fareyle metin seçin)").setEnabled(False)
        if not sel_text:
            fix.addAction("Seçili Metni Tüm Belgeden Sil  (önce fareyle metin seçin)").setEnabled(False)
        elif "\n" in sel_text:
            fix.addAction("Seçili Metni Tüm Belgeden Sil  (tek satırlık bir seçim gerekir)").setEnabled(False)
        else:
            raw = sel.selectedText()
            n = self.text.toPlainText().count(raw)
            if n > 1:
                fix.addAction(f"Seçili Metni Tüm Belgeden Sil  ({n} yer)", lambda: self.delete_everywhere(raw))
            else:
                fix.addAction("Seçili Metni Tüm Belgeden Sil  (seçim başka yerde geçmiyor)").setEnabled(False)
        fix.addSeparator()
        fix.addAction("Metni Düzenle…", self.enter_edit_mode)
        if self.edit_undo:
            fix.addAction("Son Düzeltmeyi Geri Al", self.undo_edit)
        menu.addSeparator()
        if word:
            short = word if len(word) <= 30 else word[:28] + "…"
            menu.addAction(f"“{short}” için Telaffuz Kuralı Ekle…", lambda: self.add_rule_for(word))
        menu.addAction("Telaffuz Sözlüğü…", self.open_pron_dialog)
        menu.exec(self.text.viewport().mapToGlobal(pos))

    # ───────────────────────── dosya açma / kapama ─────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(SUPPORTED) for u in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(SUPPORTED):
                e.acceptProposedAction()
                self.load_path(p)
                return

    def open_file(self):
        start = os.path.dirname(self.doc_path) if self.doc_path else ""
        p, _ = QFileDialog.getOpenFileName(self, "Dosya aç", start, "Okunabilir dosyalar (*.pdf *.epub *.docx *.txt)")
        if p:
            self.load_path(p)

    def reload(self):
        if self.doc_path:
            self.load_path(self.doc_path)

    def on_load_progress(self, v):
        value, msg = v if isinstance(v, tuple) else (v, None)
        self.progress.setRange(0, 100)
        self.progress.setFormat(f"{msg}  ·  %p%" if msg else "Yükleniyor… %p%")
        self.progress.setValue(value)
        if msg and msg.startswith("OCR"):
            self.stop_load_btn.setText("■ Taramayı Durdur")

    def load_path(self, path):
        if self.editing and not self.cancel_edit_mode():
            return
        if self.loading:
            self.statusBar().showMessage("Bir dosya zaten yükleniyor.", 4000)
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "Dosya bulunamadı", path)
            return
        self.stop_playback()
        self.flush_position()
        self.loading = True
        self.load_cancel = threading.Event()
        self.open_btn.setEnabled(False)
        self.stop_load_btn.setText("■ Yüklemeyi Durdur")
        self.stop_load_btn.show()
        self.file_label.setText("Yükleniyor: " + Path(path).name)
        self.empty.hide()
        self.on_load_progress(0)
        opts = {"ocr": self.ocr.isChecked(), "skip_notes": self.skip_notes.isChecked(),
                "strip_headers": self.strip_headers.isChecked()}
        fut = self.work_pool.submit(load_document, path, opts,
                                    lambda v, msg=None: self._safe_emit(self.bridge.load_progress, (v, msg)),
                                    self.load_cancel, self.cache_dir)

        def done(f):
            try:
                sections, cached, doc_id = f.result()
                payload = {"path": path, "sections": sections, "cached": cached, "doc_id": doc_id, "opts": opts}
            except Cancelled:
                payload = {"path": path, "cancelled": True}
            except Exception as e:
                payload = {"path": path, "error": str(e) or e.__class__.__name__}
            self._safe_emit(self.bridge.load_done, payload)
        fut.add_done_callback(done)

    def cancel_load(self):
        if self.load_cancel and self.loading:
            self.load_cancel.set()
            self.file_label.setText("Durduruluyor…")
            self.stop_load_btn.setEnabled(False)
            # OCR o anda taradığı sayfayı bitirince durur (birkaç saniye sürebilir).
            self.progress.setFormat("Durduruluyor, o anki sayfa bitiriliyor…")

    def legacy_position(self, path):
        """Sürüm 3, kaldığınız yeri dosya yoluna bağlı olarak QSettings'te tutuyordu; bir kereliğine taşırız."""
        key = hashlib.sha1(os.path.abspath(path).lower().encode("utf-8")).hexdigest()[:16]
        v = self.settings.value(f"pos/{key}", None)
        if v is None:
            return 0
        self.settings.remove(f"pos/{key}")
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def on_loaded(self, r):
        self.loading = False
        self.stop_load_btn.hide()
        self.stop_load_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        QTimer.singleShot(0, self.adapt_to_width)
        if self.closing:
            return
        if r.get("cancelled") or "error" in r:
            self.file_label.setText(Path(self.doc_path).name if self.doc_path else "Dosya açılamadı")
            self.update_progress()
            self.update_empty_state()
            if r.get("cancelled"):
                self.statusBar().showMessage("Yükleme durduruldu.", 5000)
            if "error" in r:
                QMessageBox.critical(self, "Dosya açılamadı", r["error"])
            return
        path, doc_id, extracted = r["path"], r["doc_id"], r["sections"]
        sections, edited = extracted, False
        ed = self.store.get_edits(doc_id)
        if ed and (ed["opts"] == r["opts"] or self.ask_use_edits()):
            sections, edited = ed["sections"], True
        if not build_document(sections)[1]:
            self.update_progress()
            self.update_empty_state()
            QMessageBox.warning(self, "Okunacak metin yok",
                                "Dosyadan okunabilir cümle çıkarılamadı. Taranmış bir PDF ise OCR seçeneğini açın.")
            return
        self.doc_path, self.doc_id = path, doc_id
        self.extracted_sections, self.doc_opts = extracted, r["opts"]
        self.has_edits, self.edit_undo = edited, []
        self.rebuild_pronouncer()
        known = self.store.get_document(doc_id) is not None
        n = len(build_document(sections)[1])
        row = self.store.open_document(doc_id, path, n)
        if known:
            self.show_document(sections, row["position"], row["position_anchor"])
        else:
            self.show_document(sections, self.legacy_position(path))
        self.file_label.setText(Path(path).name)
        self.setWindowTitle(f"{Path(path).name} — {APP_NAME}")
        self.close_doc_btn.setEnabled(True)
        self.close_doc_act.setEnabled(True)
        self.add_recent(path)
        msg = f"{len(self.sentences)} cümle yüklendi"
        if r.get("cached"):
            msg += " (önbellekten)"
        if edited:
            msg += " · elle düzeltilmiş metin"
        if self.current_index > 0:
            msg += f" · kaldığınız yer: cümle {self.current_index + 1}"
        self.statusBar().showMessage(msg, 8000)
        self.refresh_library()
        self.quotes.set_doc(doc_id)
        if self.doc_dock.isVisible():
            self.docview.open(path)
            self._doc_label = None
            QTimer.singleShot(0, self.sync_docview)
        if self.pending_goto and self.pending_goto[0] == doc_id:
            _, idx, anc = self.pending_goto
            self.pending_goto = None
            k = locate_anchor(self.sentences, idx, anc)
            self.jump_to(k if k is not None else idx, reveal=True)

    def ask_use_edits(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Elle düzeltilmiş metin")
        box.setText("Bu belgede elle yaptığınız düzeltmeler var, ancak belge seçenekleri "
                    "(OCR, dipnotlar, üst/alt bilgi) düzeltmeleri yaptığınız andakinden farklı.")
        box.setInformativeText("Düzeltilmiş metni mi kullanalım?\n\nHayır derseniz metin yeni seçeneklerle "
                               "çıkarılır. Düzeltmeleriniz silinmez; seçenekleri eski hâline getirip belgeyi "
                               "yeniden yüklediğinizde yine kullanılabilir.")
        yes = box.addButton("Düzeltilmiş metni kullan", QMessageBox.YesRole)
        box.addButton("Yeni seçeneklerle çıkar", QMessageBox.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        return box.clickedButton() is yes

    def show_document(self, sections, index=0, anchor=None):
        """Bölümleri ekrana kurar ve okuma konumunu (cümle izine göre) geri yükler."""
        display, sentences, toc = build_document(sections)
        self.stop_playback()
        self.clear_audio_cache()
        self.doc_gen += 1
        self.doc_sections = sections
        self.text.setPlainText(display)
        self.apply_block_format()
        self.sentences, self.toc = sentences, toc
        self.starts = [s.start for s in sentences]
        self.section_combo.clear()
        self.combo_first = []
        for label, first in toc:
            if first is not None:
                self.section_combo.addItem(label)
                self.combo_first.append(first)
        self.index.blockSignals(True)
        self.index.setRange(1, len(sentences))
        self.index.blockSignals(False)
        self.total.setText(f"/ {len(sentences)}")
        self.current_index = resolve_anchor(sentences, index or 0, anchor)
        self.rebuild_marks(highlight=False)
        self.update_sentence(scroll=True)
        self.update_empty_state()
        self.update_edit_actions()

    def close_document(self):
        if not self.sentences and not self.doc_path:
            return
        if self.editing and not self.cancel_edit_mode():
            return
        self.stop_playback()
        self.flush_position()
        self.clear_audio_cache()
        self.doc_gen += 1
        self.doc_path = self.doc_id = None
        self.sentences, self.starts, self.toc, self.combo_first = [], [], [], []
        self.doc_sections, self.extracted_sections, self.edit_undo, self.has_edits = [], [], [], False
        self.current_index = 0
        self.rebuild_pronouncer()
        self.text.setExtraSelections([])
        self.text.clear()
        self.section_combo.clear()
        self.index.blockSignals(True); self.index.setRange(0, 0); self.index.blockSignals(False)
        self.total.setText("/ 0")
        self.where.setText("")
        self.current.setText("Okunacak cümle burada görünecek.")
        self.file_label.setText(PLACEHOLDER_LABEL)
        self.setWindowTitle(APP_NAME)
        self.close_doc_btn.setEnabled(False)
        self.close_doc_act.setEnabled(False)
        self.update_progress()
        self.update_empty_state()
        self.update_edit_actions()
        self.refresh_library()
        self.ann_rows, self.ann_marks, self.ann_by_sentence = [], [], {}
        self.quotes.set_doc(None)
        self.docview.clear()
        self._doc_label = None
        self.statusBar().showMessage("Belge kapatıldı. Kaldığınız yer kaydedildi.", 4000)

    def clear_cache(self):
        if self.cache_dir and os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)
        self.statusBar().showMessage("Metin önbelleği temizlendi.", 4000)

    def flush_position(self):
        self.pos_timer.stop()
        if self.doc_id and self.sentences:
            i = self.current_index
            try:
                self.store.set_position(self.doc_id, i, anchor_of(self.sentences[i].text))
            except Exception:
                pass

    # ───────────────────────── cümle gösterimi ─────────────────────────
    def update_progress(self):
        n = len(self.sentences)
        self.progress.setRange(0, max(1, n))
        self.progress.setValue(self.current_index + 1 if n else 0)
        # QProgressBar biçiminde %v = değer, %m = en büyük değer, %p = yüzde
        self.progress.setFormat("Cümle %v / %m  ·  %p%" if n else "")
        if hasattr(self, "thin_progress"):
            self.thin_progress.set_fraction((self.current_index + 1) / n if n else 0)

    def update_sentence(self, scroll=None):
        if not self.sentences:
            return
        i = self.current_index
        s = self.sentences[i]
        self.current.setText(s.text)
        self.index.blockSignals(True); self.index.setValue(i + 1); self.index.blockSignals(False)
        self.update_progress()
        self.where.setText(self.toc[s.section][0] if s.section < len(self.toc) else "")
        self.sync_docview()
        ci = bisect.bisect_right(self.combo_first, i) - 1
        if ci >= 0:
            self.section_combo.setCurrentIndex(ci)
        self.highlight(scroll=self.follow_check.isChecked() if scroll is None else scroll)
        if self.doc_id:
            self.pos_timer.start()

    def highlight(self, scroll=True):
        s = self.sentences[self.current_index]
        cur = QTextCursor(self.text.document())
        cur.setPosition(s.start)
        cur.setPosition(s.end, QTextCursor.KeepAnchor)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cur
        sel.format.setBackground(QColor(self.colors.get("sent_bg", "#e8d98d")))
        sel.format.setForeground(QColor(self.colors.get("sent_fg", "#201e18")))
        self.text.setExtraSelections(self.ann_marks + [sel])
        if scroll:
            self.scroll_to_current()

    def scroll_to_current(self, force=False):
        s = self.sentences[self.current_index]
        c = QTextCursor(self.text.document())
        c.setPosition(s.start)
        rect = self.text.cursorRect(c)
        vp = self.text.viewport().height()
        sb = self.text.verticalScrollBar()
        if self.focus_mode:
            # Odaklanma modunda okunan cümle hep ekranın ortasına yakın durur; kayma yumuşak olur.
            target = max(sb.minimum(), min(sb.maximum(), sb.value() + rect.top() - int(vp * 0.4)))
            if abs(target - sb.value()) < 4:
                return
            if self.scroll_anim is not None:
                self.scroll_anim.stop()
            self.scroll_anim = QPropertyAnimation(sb, b"value", self)
            self.scroll_anim.setDuration(260)
            self.scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
            self.scroll_anim.setStartValue(sb.value())
            self.scroll_anim.setEndValue(target)
            self.scroll_anim.start()
            return
        if force or rect.top() < vp * 0.12 or rect.bottom() > vp * 0.82:
            sb.setValue(sb.value() + rect.top() - int(vp * 0.3))

    def reveal_current(self):
        if self.sentences:
            self.scroll_to_current(force=True)

    def on_follow_toggled(self, on):
        self.follow_act.setChecked(on)
        if on and self.sentences:
            self.reveal_current()

    def on_user_scroll(self, _action):
        """Kullanıcı okuma sırasında metni kendisi kaydırırsa takibi bırakır ki geri çekilmesin."""
        if self.follow_check.isChecked() and self.state in ("playing", "loading"):
            self.follow_check.setChecked(False)
            self.statusBar().showMessage("Takip kapatıldı. Okunan yere dönmek için Ctrl+J ya da "
                                         "“Okunan metni takip et” kutusu.", 6000)

    def copy_sentence(self):
        if not self.sentences:
            return
        QApplication.clipboard().setText(self.sentences[self.current_index].text)
        self.statusBar().showMessage("Cümle panoya kopyalandı.", 2500)

    def sentence_at(self, pos):
        return max(0, bisect.bisect_right(self.starts, pos) - 1)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.text.viewport():
            if t == QEvent.Resize:
                self.empty.setGeometry(obj.rect())
            if t == QEvent.MouseButtonDblClick and self.sentences and not self.editing:
                pos = self.text.cursorForPosition(ev.position().toPoint()).position()
                self.jump_to(self.sentence_at(pos), play=True)
                return True
            if t == QEvent.MouseMove and self.immersive():
                self.on_immersive_mouse()
            if t == QEvent.ToolTip and self.ann_by_sentence and not self.editing:
                self.show_annotation_tip(ev)
                return True
        elif obj is self.text:
            if (t == QEvent.KeyPress and self.immersive() and self.peek
                    and ev.key() in (Qt.Key_Return, Qt.Key_Enter)):
                self.toggle_peek()
                return True
        elif obj is self.dock:
            if t == QEvent.Resize:
                self.on_dock_resized()
        elif obj is self.reader:
            if t == QEvent.Resize:
                self.update_reader_margins()
                if hasattr(self, "thin_progress"):
                    self.thin_progress.reposition()
                if self.overlay.isVisible():
                    self.overlay.reposition()
                self.place_toast()
            elif t == QEvent.MouseMove and self.immersive():
                self.on_immersive_mouse()
            elif t == QEvent.Wheel and self.immersive():
                # Ortalanmış sütunun yanındaki boşlukta da tekerlek metni kaydırsın
                QApplication.sendEvent(self.text.viewport(), ev)
                return True
        return super().eventFilter(obj, ev)

    def find_next(self):
        q = self.search.text().strip()
        if not q or not self.sentences:
            return
        doc = self.text.document()
        c = doc.find(q, self.sentences[self.current_index].end)
        if c.isNull():
            c = doc.find(q, 0)
        if c.isNull():
            self.statusBar().showMessage(f"“{q}” bulunamadı.", 4000)
            return
        self.jump_to(self.sentence_at(c.selectionStart()), reveal=True)

    # ───────────────────────── gezinme ─────────────────────────
    def _in_playing_chunk(self, i):
        c = self.playing
        return (c is not None and self.state in ("playing", "paused") and c.cfg == self.cfg()
                and c.path == self.current_path and c.a <= i < c.b)

    def jump_to(self, i, play=False, reveal=False):
        """reveal: arama, bölüm ya da numara ile açıkça bir yere gidildiğinde takip kapalı olsa da kaydır."""
        if not self.sentences or self.editing:
            return
        i = max(0, min(len(self.sentences) - 1, i))
        scroll = True if reveal else None
        if self._in_playing_chunk(i):              # aynı parçadaysa yalnızca sar: anında
            self.current_index = i
            self.update_sentence(scroll)
            self.seek(self.playing.times[i - self.playing.a][0])
            if play and self.state == "paused":
                self.player.play(); self.set_state("playing")
            return
        was_active = self.state in ("playing", "loading")
        self.stop_playback()
        self.current_index = i
        self.update_sentence(scroll)
        if play or was_active:
            self.play_current()

    def restart_sentence(self):
        if not self.sentences or self.editing:
            return
        if self._in_playing_chunk(self.current_index):
            self.seek(self.playing.times[self.current_index - self.playing.a][0])
            if self.state == "paused":
                self.player.play(); self.set_state("playing")
        else:
            self.stop_playback()
            self.play_current()

    # ───────────────────────── oynatma ─────────────────────────
    def engine(self):
        return "edge" if self.mode.currentIndex() == 0 else "sapi"

    def cfg(self):
        edge = self.engine() == "edge"
        # İlk öğe değişince (yeni belge, düzeltme, sözlük değişikliği) hazırlanmış sesler geçersiz olur.
        return ((self.doc_gen, self.pron_version), self.engine(), self.voice.currentData() or "",
                self.rate.value(), self.pause.value() if edge else 0)

    def chunk_end(self, a, first):
        """Parça sınırı. İlk parça küçük (hızlı başlasın), sonrakiler büyük (az geçiş, az es)."""
        if self.engine() != "edge":
            return a + 1
        max_n, max_c = (2, 350) if first else (CHUNK_SENTENCES, CHUNK_CHARS)
        b, chars = a, 0
        while b < len(self.sentences) and b - a < max_n:
            n = len(self.sentences[b].text)
            if b > a and chars + n > max_c:
                break
            chars += n + 1
            b += 1
        return b

    def set_state(self, st):
        self.state = st
        self.read_btn.setText({"playing": "⏸ Duraklat", "paused": "▶ Devam Et",
                               "loading": "⏳ Hazırlanıyor… (iptal)", "idle": "▶ Oku"}[st])
        self.overlay.play_btn.setText({"playing": "⏸ Duraklat", "paused": "▶ Devam Et",
                                       "loading": "⏳ Hazırlanıyor", "idle": "▶ Oku"}[st])
        self.update_power()
        if st == "playing":
            self.tick.start()
        else:
            self.tick.stop()

    def toggle_play(self):
        if self.editing:
            return
        if not self.sentences:
            QMessageBox.information(self, "Bilgi", "Önce bir dosya açın.")
            return
        if self.state == "playing":
            self.player.pause(); self.set_state("paused")
        elif self.state == "paused":
            self.player.play(); self.set_state("playing")
        elif self.state == "loading":
            self.stop_playback()
        else:
            self.play_current()

    def stop_playback(self):
        self.waiting_index = None
        self.pending_seek = None
        self.player.stop()
        self.set_state("idle")

    def find_chunk(self, i):
        cfg = self.cfg()
        for c in self.chunks.values():
            if c.cfg == cfg and c.a <= i < c.b:
                return c
        return None

    def play_current(self):
        if not self.sentences:
            return
        self.prune_cache()
        i = self.current_index
        c = self.find_chunk(i)
        if c:
            self.start_chunk(c, i)
        else:
            self.waiting_index = i
            self.set_state("loading")
            self.prefetch_after(self.request(i, first=True))

    def seek(self, ms):
        ms = max(0, (ms or 0) - 60)
        self.seek_guard = time.monotonic() + 0.4
        st = self.player.mediaStatus()
        if st in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
                  QMediaPlayer.MediaStatus.BufferingMedia, QMediaPlayer.MediaStatus.EndOfMedia):
            self.player.setPosition(ms)
            self.pending_seek = None
        else:
            self.pending_seek = ms

    def start_chunk(self, c, i):
        if self.current_path != c.path:
            self.player.setSource(QUrl.fromLocalFile(c.path))
            self.current_path = c.path
        self.playing = c
        start = c.times[i - c.a][0]
        if start or self.player.position() > 0:
            self.seek(start)
        self.player.play()
        self.set_state("playing")
        self.prefetch_after(c.b)

    def prefetch_after(self, b):
        if not self.auto_check.isChecked():
            return
        for _ in range(PREFETCH_CHUNKS):
            if b is None:
                break
            b = self.request(b)

    def request(self, a, first=False):
        """a. cümleden başlayan parçayı hazırlat; parçanın bittiği cümle numarasını döndürür."""
        if a is None or a >= len(self.sentences):
            return None
        cfg = self.cfg()
        c = self.find_chunk(a)
        if c:
            return c.b
        for ia, ib, icfg in self.inflight:
            if icfg == cfg and ia <= a < ib:
                return ib
        b = self.chunk_end(a, first)
        self.inflight.add((a, b, cfg))
        _, engine, voice, rate, pause_cs = cfg
        out = os.path.join(self.tmpdir, f"{uuid.uuid4().hex}.{'mp3' if engine == 'edge' else 'wav'}")
        texts = [self.pron.apply(s.text) for s in self.sentences[a:b]]

        def job():
            if engine == "edge":
                return synth_edge_chunk(texts, voice, rate, out, pause_cs / 100)
            return [(0, synth_sapi(texts[0], voice, rate, out))]

        def done(f):
            try:
                times, err = f.result(), None
            except Exception as e:
                times, err = None, str(e) or e.__class__.__name__
            self._safe_emit(self.bridge.synth_done,
                            {"a": a, "b": b, "cfg": cfg, "path": out, "times": times, "error": err,
                             "words": sum(word_count(t) for t in texts)})
        self.synth_pool.submit(job).add_done_callback(done)
        return b

    def _rerequest_waiting(self):
        if self.waiting_index is not None:
            self.prefetch_after(self.request(self.waiting_index, first=True))

    def on_synth_done(self, r):
        a, b, cfg, path = r["a"], r["b"], r["cfg"], r["path"]
        self.inflight.discard((a, b, cfg))
        if self.closing:
            safe_remove(path)
            return
        waiting = self.waiting_index is not None and a <= self.waiting_index < b
        if r["error"]:
            safe_remove(path)
            if waiting:
                if cfg == self.cfg():
                    self.waiting_index = None
                    self.set_state("idle")
                    QMessageBox.warning(self, "Seslendirme hatası", r["error"])
                else:
                    self._rerequest_waiting()
            return
        self.measure_wpm(cfg, r["times"], r["words"])
        if cfg != self.cfg() or b <= self.current_index or a > self.current_index + LOOKAHEAD:
            safe_remove(path)
            if waiting:
                self._rerequest_waiting()
            return
        old = self.chunks.get(a)
        if old and old.path != self.current_path:
            safe_remove(old.path)
        c = Chunk(cfg, a, b, path, r["times"])
        self.chunks[a] = c
        if waiting:
            i = self.waiting_index
            self.waiting_index = None
            self.start_chunk(c, i)

    def prune_cache(self):
        cfg, i = self.cfg(), self.current_index
        for a in list(self.chunks):
            c = self.chunks[a]
            if c.path == self.current_path:
                continue
            if c.cfg != cfg or c.b <= i or c.a > i + LOOKAHEAD:
                safe_remove(c.path)
                del self.chunks[a]

    def clear_audio_cache(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.current_path = None
        self.playing = None
        for c in self.chunks.values():
            safe_remove(c.path)
        self.chunks.clear()

    def on_tick(self):
        """Oynatma konumuna bakarak parçanın içindeki hangi cümlenin okunduğunu bulur."""
        c = self.playing
        if self.state != "playing" or c is None or c.path != self.current_path or time.monotonic() < self.seek_guard:
            return
        pos = self.player.position()
        j = c.a
        for k, (st, _) in enumerate(c.times):
            if st <= pos + 40:
                j = c.a + k
            else:
                break
        if j == self.current_index:
            return
        if j > self.current_index and not self.auto_check.isChecked():
            self.current_index = j
            self.update_sentence()
            self.stop_playback()
            return
        self.current_index = j
        self.update_sentence()

    def on_media_status(self, status):
        S = QMediaPlayer.MediaStatus
        if status in (S.LoadedMedia, S.BufferedMedia) and self.pending_seek is not None:
            self.player.setPosition(self.pending_seek)
            self.pending_seek = None
        elif status == S.EndOfMedia and self.state == "playing":
            c = self.playing
            nxt = c.b if c else self.current_index + 1
            if self.auto_check.isChecked() and nxt < len(self.sentences):
                self.current_index = nxt
                self.update_sentence()
                self.play_current()
            else:
                self.set_state("idle")
        elif status == S.InvalidMedia and self.state == "playing":
            self.set_state("idle")
            QMessageBox.warning(self, "Seslendirme hatası", "Ses dosyası oynatılamadı.")

    def on_player_error(self, error, msg):
        if error != QMediaPlayer.Error.NoError and self.state in ("playing", "paused"):
            self.set_state("idle")
            QMessageBox.warning(self, "Seslendirme hatası", msg or "Ses dosyası oynatılamadı.")

    # ───────────────────────── okuma hızı (kelime/dk) ─────────────────────────
    @staticmethod
    def speed_factor(engine, rate_pct):
        """Hız ayarının sese etkisi: Edge'de doğrusal, Windows SAPI'de logaritmik (+10 ≈ 3 kat)."""
        return rate_pct / 100 if engine == "edge" else 3 ** (sapi_rate(rate_pct) / 10)

    def measure_wpm(self, cfg, times, words):
        """Üretilen parçanın süresinden gerçek kelime/dk hızını ölçer ve %100 hıza indirger.
        Böylece tek bir ölçüm, kaydırıcının her konumu için tahmin vermeye yeter."""
        try:
            _, engine, voice, rate, _ = cfg
            dur = (times[-1][1] or 0) - (times[0][0] or 0)
        except (TypeError, IndexError, ValueError):
            return
        if not words or dur < 1500:
            return
        base = words / (dur / 60000) / self.speed_factor(engine, rate)
        key = f"{engine}|{voice}"
        old, n = self.wpm.get(key, (base, 0))
        n2 = min(n + words, 3000)                  # son ~3000 kelimeye ağırlık ver: ses değişse de güncel kalır
        self.wpm[key] = (round((old * n + base * words) / (n + words), 2), n2)
        self.update_wpm_label()

    def update_wpm_label(self):
        key = f"{self.engine()}|{self.voice.currentData() or ''}"
        if key in self.wpm:
            v = self.wpm[key][0] * self.speed_factor(self.engine(), self.rate.value())
            self.wpm_label.setText(f"≈ {round(v)} kelime/dk")
        else:
            self.wpm_label.setText("kelime/dk: okumaya başlayınca ölçülür")

    # ───────────────────────── ses ayarları ─────────────────────────
    def on_cfg_changed(self):
        self.prune_cache()
        self.update_wpm_label()
        if self.state in ("playing", "paused") and self.playing:
            self.prefetch_after(self.playing.b)     # sıradaki parçalar yeni ayarla hazırlansın

    def on_mode_changed(self, idx, save=True):
        if save:
            self.settings.setValue("mode", idx)
        online = idx == 0
        self.pause.setEnabled(online)
        if online:
            self.voice_note.setText("Doğal sinir ağı sesleri; internet bağlantısı gerekir. "
                                    "Çok dilli sesler Türkçe ve İngilizceyi aynı metinde okuyabilir.")
        else:
            self.voice_note.setText("Windows'ta kurulu sesler kullanılır; internet gerekmez. "
                                    "Türkçe için Ayarlar › Zaman ve dil › Konuşma bölümünden Türkçe ses paketi ekleyebilirsiniz.")
            if self.sapi_voices is None and IS_WINDOWS:
                self.sapi_voices = []
                fut = self.work_pool.submit(list_sapi_voices)
                fut.add_done_callback(lambda f: self._safe_emit(
                    self.bridge.voices_done, f.result() if not f.exception() else []))
        self.populate_voices()

    def on_voices(self, voices):
        self.sapi_voices = voices
        if self.engine() == "sapi":
            self.populate_voices()

    def populate_voices(self):
        self.voice.blockSignals(True)
        self.voice.clear()
        if self.engine() == "edge":
            for label, code in EDGE_VOICES:
                self.voice.addItem(label, code)
            saved = self.settings.value("voice_edge", "tr-TR-EmelNeural")
        else:
            self.voice.addItem("Windows varsayılan sesi", "")
            for name, culture in self.sapi_voices or []:
                self.voice.addItem(f"{name} ({culture})", name)
            saved = self.settings.value("voice_sapi", "")
        self.voice.setCurrentIndex(max(0, self.voice.findData(saved)))
        self.voice.blockSignals(False)
        self.on_cfg_changed()

    def on_voice_changed(self, _):
        self.settings.setValue("voice_edge" if self.engine() == "edge" else "voice_sapi", self.voice.currentData())
        self.on_cfg_changed()

    def on_rate_changed(self, v):
        self.rate_label.setText(f"%{v}")      # Türkçede yüzde işareti sayıdan önce gelir
        self.on_cfg_changed()

    def on_pause_changed(self, v):
        self.pause_label.setText(f"{v / 100:.2f}".replace(".", ",") + " sn")   # Türkçede ondalık ayırıcı virgüldür
        self.on_cfg_changed()

    # ───────────────────────── MP3 dışa aktarma ─────────────────────────
    def export_audio(self):
        """Ses dışa aktarma modülünü açar (okumayı engellemeden arka planda çalışır)."""
        if not self.sentences:
            QMessageBox.information(self, "Ses olarak dışa aktar", "Önce bir belge açın.")
            return
        from .audio_export import AudioExportDialog
        dlg = getattr(self, "audio_dlg", None)
        if dlg is not None and dlg.job is not None:
            dlg.show(); dlg.raise_(); dlg.activateWindow()
            return
        self.audio_dlg = AudioExportDialog(self)
        self.audio_dlg.show()

    def start_mp3_job(self, groups, out):
        """Metin gruplarını sırayla seslendirip tek bir MP3 dosyasında birleştirir (arka planda)."""
        voice, rate, pause = self.voice.currentData(), self.rate.value(), self.pause.value() / 100
        cancel = threading.Event()
        self.export_dialog = QProgressDialog("Ses dosyası hazırlanıyor…", "İptal", 0, len(groups), self)
        self.export_dialog.setWindowTitle("MP3 dışa aktarma")
        self.export_dialog.setWindowModality(Qt.WindowModal)
        self.export_dialog.setMinimumDuration(0)
        self.export_dialog.setAutoClose(False)
        self.export_dialog.canceled.connect(cancel.set)
        self.bridge.export_progress.connect(self.export_dialog.setValue)
        self.export_dialog.show()
        tmpdir = self.tmpdir

        def job():
            part = out + ".part"
            try:
                with open(part, "wb") as fo:
                    for k, texts in enumerate(groups):
                        if cancel.is_set():
                            raise Cancelled()
                        tmp = os.path.join(tmpdir, f"exp_{uuid.uuid4().hex}.mp3")
                        synth_edge_chunk(texts, voice, rate, tmp, pause)
                        with open(tmp, "rb") as fi:
                            fo.write(fi.read())     # MP3 çerçeveleri art arda eklenebilir
                        safe_remove(tmp)
                        self._safe_emit(self.bridge.export_progress, k + 1)
                os.replace(part, out)
                return {"path": out}
            except Cancelled:
                safe_remove(part)
                return {"cancelled": True}
            except Exception as e:
                safe_remove(part)
                return {"error": str(e)}
        self.work_pool.submit(job).add_done_callback(lambda f: self._safe_emit(self.bridge.export_done, f.result()))

    def on_export_done(self, r):
        try:
            self.bridge.export_progress.disconnect(self.export_dialog.setValue)
        except (RuntimeError, TypeError):
            pass
        self.export_dialog.close()
        if self.closing or r.get("cancelled"):
            return
        if "error" in r:
            QMessageBox.warning(self, "Dışa aktarma başarısız", r["error"])
        else:
            show_done(self, "Ses kaydı tamamlandı", "Ses dosyası hazır.", r["path"])

    # ───────────────────────── yardımcılar ─────────────────────────
    def _safe_emit(self, signal, payload):
        try:
            signal.emit(payload)
        except RuntimeError:
            pass        # pencere kapanmışsa sessizce geç

    def _emitter(self, signal):
        return lambda v: self._safe_emit(signal, v)

    def closeEvent(self, event):
        self.closing = True
        if self.immersive():
            # Panel tam ekranda gizli; kaydedilen yerleşim normal görünüm olsun.
            self.is_fullscreen = self.focus_mode = self.peek = False
            self.update_chrome()
        self.flush_position()
        if not getattr(self, "_skip_save", False):
            self.save_settings()
        set_awake(False, False)
        if self.load_cancel:
            self.load_cancel.set()
        self.stop_playback()
        self.player.setSource(QUrl())
        kill_all_processes()
        self.synth_pool.shutdown(wait=False, cancel_futures=True)
        self.work_pool.shutdown(wait=False, cancel_futures=True)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.docview.shutdown()
        self.store.close()
        super().closeEvent(event)

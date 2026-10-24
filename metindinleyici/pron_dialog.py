# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Telaffuz sözlüğü pencereleri."""
import copy
import html
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .pronounce import (KIND_REGEX, KIND_WORD, STARTER_RULES, Pronouncer, Rule, _excepted, compile_rule,
                        render)

MAX_SAMPLES = 60

HELP_REGEX = (
    "<b>Okunuşta kullanılabilecek yer tutucular</b> (yalnızca düzenli ifadede):<br>"
    "<code>{1}</code> 1. grubun kendisi · <code>{yazıyla:1}</code> 125 → yüz yirmi beş · "
    "<code>{sıra:1}</code> 19 → on dokuzuncu · <code>{roma:1}</code> XIX → on dokuz · "
    "<code>{romasıra:1}</code> II → ikinci<br>"
    "Örnek: yazılış <code>\\bs\\.\\s*(\\d+)</code>, okunuş <code>sayfa {yazıyla:1}</code>")


def find_samples(rule, sentences, limit=MAX_SAMPLES):
    """Kuralın belgede eşleştiği yerler. Dönüş: (toplam, [(önce, eşleşme, sonra, okunuş)])."""
    rx, err = compile_rule(rule)
    if rx is None:
        return 0, [], err
    total, out = 0, []
    for text in sentences:
        for m in rx.finditer(text):
            if _excepted(rule, text, m):
                continue
            total += 1
            if len(out) < limit:
                out.append((text[max(0, m.start() - 30):m.start()], m.group(0),
                            text[m.end():m.end() + 30], render(rule, m)))
    return total, out, None


def sample_html(before, match, after, spoken):
    return (f"…{html.escape(before)}<b><u>{html.escape(match)}</u></b>{html.escape(after)}…"
            f"&nbsp;&nbsp;→&nbsp;&nbsp;<i>{html.escape(spoken)}</i>")


class RuleDialog(QDialog):
    def __init__(self, parent, rule, doc_id=None, doc_title="", sentences=()):
        super().__init__(parent)
        self.setWindowTitle("Telaffuz kuralı")
        self.resize(640, 560)
        self.doc_id, self.sentences = doc_id, list(sentences)
        self.rule = copy.deepcopy(rule)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.pattern = QLineEdit(rule.pattern)
        self.pattern.setPlaceholderText("Metinde geçtiği biçim, ör. bkz.  ya da  TBMM")
        self.replacement = QLineEdit(rule.replacement)
        self.replacement.setPlaceholderText("Nasıl okunsun, ör. bakınız")
        self.kind = QComboBox()
        self.kind.addItem("Kelime ya da ifade (önerilen)", KIND_WORD)
        self.kind.addItem("Düzenli ifade (bağlama bağlı kalıplar)", KIND_REGEX)
        self.kind.setCurrentIndex(0 if rule.kind == KIND_WORD else 1)
        self.case = QCheckBox("Büyük/küçük harfe duyarlı (TBMM ile tbmm ayrı sayılır)")
        self.case.setChecked(rule.case_sensitive)
        self.scope = QComboBox()
        self.scope.addItem("Tüm belgeler", None)
        if doc_id:
            self.scope.addItem(f"Yalnızca bu belge: {doc_title}", doc_id)
        elif rule.doc_id:
            self.scope.addItem("Yalnızca başka bir belge", rule.doc_id)
        self.scope.setCurrentIndex(max(0, self.scope.findData(rule.doc_id)))
        self.exceptions = QPlainTextEdit("\n".join(rule.exceptions))
        self.exceptions.setPlaceholderText("Her satıra bir ifade. Eşleşmenin yakınında bu ifadelerden biri\n"
                                           "geçiyorsa kural orada uygulanmaz. Ör. AB kuralı için: kan grubu")
        self.exceptions.setMaximumHeight(80)
        self.note = QLineEdit(rule.note)
        self.enabled = QCheckBox("Etkin")
        self.enabled.setChecked(rule.enabled)
        form.addRow("Yazılış", self.pattern)
        form.addRow("Okunuş", self.replacement)
        form.addRow("Tür", self.kind)
        form.addRow("", self.case)
        form.addRow("Kapsam", self.scope)
        form.addRow("İstisnalar", self.exceptions)
        form.addRow("Not", self.note)
        form.addRow("", self.enabled)
        lay.addLayout(form)
        self.help = QLabel(HELP_REGEX)
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.RichText)
        lay.addWidget(self.help)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.samples = QListWidget()
        lay.addWidget(self.samples, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.try_accept)
        bb.rejected.connect(self.reject)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        lay.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        for w in (self.pattern, self.replacement, self.note):
            w.textChanged.connect(self.timer.start)
        self.exceptions.textChanged.connect(self.timer.start)
        self.kind.currentIndexChanged.connect(self.timer.start)
        self.case.toggled.connect(self.timer.start)
        self.refresh()

    def current(self):
        return Rule(pattern=self.pattern.text(), replacement=self.replacement.text(),
                    kind=self.kind.currentData(), case_sensitive=self.case.isChecked(),
                    enabled=self.enabled.isChecked(), doc_id=self.scope.currentData(),
                    exceptions=[x.strip() for x in self.exceptions.toPlainText().splitlines() if x.strip()],
                    note=self.note.text().strip(), id=self.rule.id)

    def refresh(self):
        r = self.current()
        self.help.setVisible(r.kind == KIND_REGEX)
        self.samples.clear()
        if not r.pattern.strip():
            self.status.setText("Yazılışı girin.")
            self.ok_btn.setEnabled(False)
            return
        total, samples, err = find_samples(r, self.sentences)
        if err:
            self.status.setText(f"<span style='color:#c0392b'><b>{html.escape(err)}</b></span>")
            self.ok_btn.setEnabled(False)
            return
        self.ok_btn.setEnabled(True)
        if not self.sentences:
            self.status.setText("Açık belge yok; eşleşmeler belge açıkken burada listelenir.")
            return
        self.status.setText(f"Açık belgede <b>{total}</b> yerde uygulanacak."
                            + (f" İlk {len(samples)} örnek:" if samples else ""))
        for s in samples:
            lbl = QLabel(sample_html(*s))
            lbl.setTextFormat(Qt.RichText)
            item = self.samples.addItem("")
            item = self.samples.item(self.samples.count() - 1)
            item.setSizeHint(lbl.sizeHint())
            self.samples.setItemWidget(item, lbl)

    def try_accept(self):
        r = self.current()
        rx, err = compile_rule(r)
        if rx is None:
            QMessageBox.warning(self, "Kural hatalı", err)
            return
        self.rule = r
        self.accept()


class PronunciationDialog(QDialog):
    """Sözlüğün tamamı: kural listesi, sıralama, ön izleme, dinleme, içe/dışa aktarma."""
    COLS = ["", "Yazılış", "Okunuş", "Tür", "Kapsam", "Not"]

    def __init__(self, parent, rules, doc_id=None, doc_title="", sentences=(), current_text="", speak=None):
        super().__init__(parent)
        self.setWindowTitle("Telaffuz sözlüğü")
        self.resize(980, 720)
        self.rules = [copy.deepcopy(r) for r in rules]
        self.doc_id, self.doc_title, self.sentences = doc_id, doc_title, list(sentences)
        self.speak = speak
        lay = QVBoxLayout(self)
        intro = QLabel("Kurallar yalnızca <b>okunuşu</b> değiştirir; ekrandaki metin olduğu gibi kalır. "
                       "Kurallar <b>yukarıdan aşağıya</b> sırayla uygulanır: özel kalıpları (ss. 12-15) "
                       "genel olanlardan (s. 12) önce koyun.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Kurallarda ara…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        left.addWidget(self.filter)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 220)
        self.table.itemDoubleClicked.connect(lambda _: self.edit_rule())
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.itemSelectionChanged.connect(self.on_selection)
        left.addWidget(self.table, 1)
        tl.addLayout(left, 1)

        btns = QVBoxLayout()

        def b(text, slot, tip=""):
            w = QPushButton(text)
            w.setToolTip(tip)
            w.clicked.connect(slot)
            btns.addWidget(w)
            return w
        b("Ekle…", self.add_rule)
        self.edit_btn = b("Düzenle…", self.edit_rule)
        self.dup_btn = b("Çoğalt", self.duplicate_rule, "Seçili kuralın bir kopyasını hemen altına ekler")
        self.del_btn = b("Sil", self.delete_rule)
        btns.addSpacing(8)
        self.up_btn = b("▲ Yukarı", lambda: self.move_rule(-1), "Daha önce uygulanır")
        self.down_btn = b("▼ Aşağı", lambda: self.move_rule(1), "Daha sonra uygulanır")
        btns.addSpacing(8)
        b("Başlangıç Kuralları", self.add_starters, "Akademik metinler için hazır kuralları ekler (eksik olanları)")
        b("İçe Aktar…", self.import_rules)
        b("Dışa Aktar…", self.export_rules)
        btns.addStretch(1)
        tl.addLayout(btns)
        split.addWidget(top)

        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        pv = QGroupBox("Ön izleme ve dinleme")
        pl = QVBoxLayout(pv)
        self.test = QPlainTextEdit(current_text or "Bu konu için bkz. Tekeli, ss. 12-15 ve TBMM Zabıt Ceridesi, s. 125.")
        self.test.setMaximumHeight(90)
        self.test.textChanged.connect(self.update_preview)
        pl.addWidget(self.test)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.result)
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        pl.addWidget(self.steps)
        r = QHBoxLayout()
        cur_btn = QPushButton("Okunan Cümleyi Al")
        cur_btn.setEnabled(bool(current_text))
        cur_btn.clicked.connect(lambda: self.test.setPlainText(current_text))
        self.listen_btn = QPushButton("▶ Dinle")
        self.listen_btn.setToolTip("Ön izlemedeki metni, seçili ses ve hızla, kurallar uygulanmış hâliyle okur")
        self.listen_btn.setEnabled(speak is not None)
        self.listen_btn.clicked.connect(lambda: self.speak and self.speak(self.preview_text()))
        r.addWidget(cur_btn); r.addStretch(1); r.addWidget(self.listen_btn)
        pl.addLayout(r)
        bl.addWidget(pv, 1)
        dg = QGroupBox("Seçili kural bu belgede")
        dl = QVBoxLayout(dg)
        self.doc_status = QLabel()
        self.doc_status.setWordWrap(True)
        dl.addWidget(self.doc_status)
        self.doc_samples = QListWidget()
        dl.addWidget(self.doc_samples, 1)
        bl.addWidget(dg, 1)
        split.addWidget(bottom)
        split.setSizes([400, 300])
        lay.addWidget(split, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.populate()
        self.update_preview()

    # ── tablo ──
    def scope_text(self, r):
        if not r.doc_id:
            return "Tüm belgeler"
        return "Bu belge" if r.doc_id == self.doc_id else "Başka belge"

    def populate(self, select=None):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rules))
        for i, r in enumerate(self.rules):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r.enabled else Qt.Unchecked)
            chk.setToolTip("Etkin")
            self.table.setItem(i, 0, chk)
            vals = [r.pattern, r.replacement, "Kelime" if r.kind == KIND_WORD else "Düzenli ifade",
                    self.scope_text(r), r.note]
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(v)
                it.setToolTip(v)
                self.table.setItem(i, c, it)
        self.table.blockSignals(False)
        if select is not None and 0 <= select < len(self.rules):
            self.table.selectRow(select)
        self.apply_filter()
        self.on_selection()

    def apply_filter(self):
        q = self.filter.text().strip().casefold()
        for i, r in enumerate(self.rules):
            hay = f"{r.pattern} {r.replacement} {r.note}".casefold()
            self.table.setRowHidden(i, bool(q) and q not in hay)

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def on_item_changed(self, item):
        if item.column() == 0:
            self.rules[item.row()].enabled = item.checkState() == Qt.Checked
            self.update_preview()
            self.on_selection()

    def on_selection(self):
        i = self.selected()
        has = i is not None
        for w in (self.edit_btn, self.dup_btn, self.del_btn):
            w.setEnabled(has)
        self.up_btn.setEnabled(has and i > 0)
        self.down_btn.setEnabled(has and i < len(self.rules) - 1)
        self.doc_samples.clear()
        if not has:
            self.doc_status.setText("Bir kural seçin; açık belgede nerelerde uygulandığı burada görünür.")
            return
        r = self.rules[i]
        if not self.sentences:
            self.doc_status.setText("Açık belge yok.")
            return
        total, samples, err = find_samples(r, self.sentences)
        if err:
            self.doc_status.setText(err)
            return
        state = "" if r.enabled else " (kural şu an kapalı)"
        self.doc_status.setText(f"<b>{total}</b> yerde uygulanıyor{state}.")
        for s in samples:
            lbl = QLabel(sample_html(*s))
            lbl.setTextFormat(Qt.RichText)
            self.doc_samples.addItem("")
            item = self.doc_samples.item(self.doc_samples.count() - 1)
            item.setSizeHint(lbl.sizeHint())
            self.doc_samples.setItemWidget(item, lbl)

    # ── işlemler ──
    def open_rule(self, rule):
        dlg = RuleDialog(self, rule, self.doc_id, self.doc_title, self.sentences)
        return dlg.rule if dlg.exec() == QDialog.Accepted else None

    def add_rule(self, _=False, pattern=""):
        r = self.open_rule(Rule(pattern=pattern, replacement=""))
        if r:
            i = self.selected()
            pos = len(self.rules) if i is None else i + 1
            self.rules.insert(pos, r)
            self.populate(select=pos)
            self.update_preview()

    def edit_rule(self):
        i = self.selected()
        if i is None:
            return
        r = self.open_rule(self.rules[i])
        if r:
            self.rules[i] = r
            self.populate(select=i)
            self.update_preview()

    def duplicate_rule(self):
        i = self.selected()
        if i is None:
            return
        r = copy.deepcopy(self.rules[i]); r.id = None
        self.rules.insert(i + 1, r)
        self.populate(select=i + 1)

    def delete_rule(self):
        i = self.selected()
        if i is None:
            return
        del self.rules[i]
        self.populate(select=min(i, len(self.rules) - 1))
        self.update_preview()

    def move_rule(self, d):
        i = self.selected()
        if i is None or not 0 <= i + d < len(self.rules):
            return
        self.rules[i], self.rules[i + d] = self.rules[i + d], self.rules[i]
        self.populate(select=i + d)
        self.update_preview()

    def add_starters(self):
        have = {(r.kind, r.pattern) for r in self.rules}
        new = [copy.deepcopy(r) for r in STARTER_RULES if (r.kind, r.pattern) not in have]
        if not new:
            QMessageBox.information(self, "Başlangıç kuralları", "Başlangıç kurallarının hepsi zaten sözlükte.")
            return
        self.rules = new + self.rules        # özel kalıplar başta kalsın
        self.populate(select=0)
        self.update_preview()

    def import_rules(self):
        path, _ = QFileDialog.getOpenFileName(self, "Sözlüğü içe aktar", "", "Telaffuz sözlüğü (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("rules", data) if isinstance(data, dict) else data
            new = [Rule.from_dict(d) for d in items if isinstance(d, dict) and d.get("pattern")]
        except (OSError, ValueError, AttributeError) as e:
            QMessageBox.warning(self, "İçe aktarılamadı", f"Dosya okunamadı:\n{e}")
            return
        have = {(r.kind, r.pattern, r.doc_id) for r in self.rules}
        added = [r for r in new if (r.kind, r.pattern, r.doc_id) not in have]
        self.rules += added
        self.populate()
        self.update_preview()
        QMessageBox.information(self, "İçe aktarıldı",
                                f"{len(added)} kural eklendi; {len(new) - len(added)} kural zaten vardı.")

    def export_rules(self):
        path, _ = QFileDialog.getSaveFileName(self, "Sözlüğü dışa aktar", "telaffuz_sozlugu.json",
                                              "Telaffuz sözlüğü (*.json)")
        if not path:
            return
        data = {"format": "metin-dinleyici-telaffuz", "version": 1, "rules": [r.to_dict() for r in self.rules]}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Kaydedilemedi", str(e))
            return
        from .dialogs import show_done
        show_done(self, "Sözlük dışa aktarıldı", f"{len(self.rules)} kural kaydedildi.", path)

    # ── ön izleme ──
    def pronouncer(self):
        return Pronouncer(self.rules, self.doc_id)

    def preview_text(self):
        return self.pronouncer().apply(self.test.toPlainText())

    def update_preview(self):
        text = self.test.toPlainText()
        out, steps = self.pronouncer().trace(text)
        self.result.setText(f"<b>Okunuş:</b> {html.escape(out)}")
        if steps:
            self.steps.setText("Uygulanan kurallar: " + ", ".join(
                f"<code>{html.escape(r.pattern)}</code>" + (f" ×{n}" if n > 1 else "") for r, n in steps))
        else:
            self.steps.setText("Bu metne uygulanan kural yok.")

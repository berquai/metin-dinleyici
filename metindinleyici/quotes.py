# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Alıntılar paneli, alıntı/not düzenleme ve dışa aktarma pencereleri."""
import html
import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .annotations import (KIND_HIGHLIGHT, KIND_NAMES, KIND_NOTE, KIND_QUOTE, STYLES, citation, doc_title,
                          hashtags_in, matches, page_number, parse_tags, runs_text, split_query, tr_lower,
                          write_export)

ROLE_AID = Qt.UserRole + 10
ICONS = {KIND_QUOTE: "❝", KIND_NOTE: "✎", KIND_HIGHLIGHT: "▌"}
FORMATS = [("Word belgesi (*.docx)", ".docx"), ("Markdown (*.md)", ".md"), ("Düz metin (*.txt)", ".txt"),
           ("CSV, Excel için (*.csv)", ".csv")]


class AnnotationDialog(QDialog):
    """Alıntı, not ya da vurgunun metnini, notunu, etiketlerini ve sayfasını düzenler."""

    def __init__(self, parent, kind, text, note="", tags=(), page_label="", all_tags=(), title=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(title or {KIND_QUOTE: "Alıntı", KIND_NOTE: "Not", KIND_HIGHLIGHT: "Vurgu"}[kind])
        self.resize(620, 480)
        form = QFormLayout(self)
        self.text = QPlainTextEdit(text)
        self.text.setMaximumHeight(110)
        if kind == KIND_NOTE:
            self.text.setReadOnly(True)
            form.addRow("Cümle", self.text)
        else:
            self.text.setToolTip("Kaynaktaki metin. Gerekirse kısaltabilir ya da OCR hatasını düzeltebilirsiniz.")
            form.addRow("Kaynaktaki metin", self.text)
        self.note = QPlainTextEdit(note)
        self.note.setPlaceholderText("Kendi notunuz. Metin içine #etiket yazarsanız etiket olarak da eklenir."
                                     if kind == KIND_NOTE else "İsteğe bağlı: bu alıntıyla ilgili kendi notunuz")
        form.addRow("Notunuz" if kind == KIND_NOTE else "Notunuz (isteğe bağlı)", self.note)
        self.tags = QLineEdit(" ".join("#" + t for t in tags))
        self.tags.setPlaceholderText("#köycülük #1930lar  (boşluk ya da virgülle ayırın)")
        form.addRow("Etiketler", self.tags)
        if all_tags:
            links = " ".join(f'<a href="{html.escape(t)}">#{html.escape(t)}</a>' for t, _ in list(all_tags)[:40])
            pick = QLabel(f"<small>Mevcut etiketler (eklemek için tıklayın): {links}</small>")
            pick.setWordWrap(True)
            pick.setTextFormat(Qt.RichText)
            pick.linkActivated.connect(self.add_tag)
            form.addRow("", pick)
        self.page = QLineEdit(page_label)
        self.page.setToolTip("Belgedeki sayfa etiketi. Basılı sayfa için belge bilgilerindeki “sayfa farkı” uygulanır.")
        form.addRow("Sayfa", self.page)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.try_accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        (self.note if kind == KIND_NOTE else self.tags).setFocus()

    def add_tag(self, tag):
        cur = parse_tags(self.tags.text())
        if tag not in cur:
            cur.append(tag)
        self.tags.setText(" ".join("#" + t for t in cur) + " ")
        self.tags.setFocus()

    def values(self):
        note = self.note.toPlainText().strip()
        tags = parse_tags(self.tags.text())
        for t in hashtags_in(note):
            if t not in tags:
                tags.append(t)
        return {"text": self.text.toPlainText().strip(), "note": note, "tags": tags,
                "page_label": self.page.text().strip()}

    def try_accept(self):
        v = self.values()
        if self.kind == KIND_NOTE and not v["note"]:
            QMessageBox.information(self, "Not boş", "Notunuzu yazın.")
            return
        if self.kind != KIND_NOTE and not v["text"]:
            QMessageBox.information(self, "Metin boş", "Alıntılanacak metin boş olamaz.")
            return
        self.accept()


class ExportQuotesDialog(QDialog):
    def __init__(self, parent, counts, settings):
        super().__init__(parent)
        self.setWindowTitle("Alıntıları dışa aktar")
        self.settings = settings
        lay = QVBoxLayout(self)
        scope_box = QGroupBox("Neler aktarılsın?")
        sl = QVBoxLayout(scope_box)
        self.scope = QButtonGroup(self)
        labels = [("selected", f"Seçili olanlar ({counts['selected']})"),
                  ("visible", f"Listede görünenler — arama ve süzgece uyanlar ({counts['visible']})"),
                  ("doc", f"Açık belgedeki tümü ({counts['doc']})"),
                  ("all", f"Bütün belgelerdeki tümü ({counts['all']})")]
        self.scope_keys = []
        for k, (key, text) in enumerate(labels):
            rb = QRadioButton(text)
            rb.setEnabled(counts[key] > 0)
            self.scope.addButton(rb, k)
            self.scope_keys.append(key)
            sl.addWidget(rb)
        first = next((k for k, (key, _) in enumerate(labels) if counts[key] > 0), 3)
        self.scope.button(first).setChecked(True)
        lay.addWidget(scope_box)
        form = QFormLayout()
        self.fmt = QComboBox()
        for label, ext in FORMATS:
            self.fmt.addItem(label, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(settings.value("exp_fmt", ".docx"))))
        self.style = QComboBox()
        for key, label in STYLES:
            self.style.addItem(label, key)
        self.style.setCurrentIndex(max(0, self.style.findData(settings.value("exp_style", "chicago"))))
        self.group = QComboBox()
        for key, label in (("doc", "Belgeye göre (künyeli başlıklar)"), ("tag", "Etikete göre"), ("none", "Gruplama yok")):
            self.group.addItem(label, key)
        self.group.setCurrentIndex(max(0, self.group.findData(settings.value("exp_group", "doc"))))
        self.notes = QCheckBox("Alıntılara eklediğim notları da yaz")
        self.notes.setChecked(settings.value("exp_notes", True, type=bool))
        self.tags = QCheckBox("Etiketleri yaz")
        self.tags.setChecked(settings.value("exp_tags", True, type=bool))
        form.addRow("Biçim", self.fmt)
        form.addRow("Künye", self.style)
        form.addRow("Gruplama", self.group)
        form.addRow("", self.notes)
        form.addRow("", self.tags)
        lay.addLayout(form)
        hint = QLabel("Künyede yazar, yıl, yayınevi ve şehir, kütüphanedeki “Bilgileri Düzenle” penceresinden gelir. "
                      "Basılı sayfa numarası için orada “sayfa farkı” da ayarlanabilir.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Dışa Aktar…")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def choices(self):
        c = {"scope": self.scope_keys[self.scope.checkedId()], "ext": self.fmt.currentData(),
             "style": self.style.currentData(), "group": self.group.currentData(),
             "notes": self.notes.isChecked(), "tags": self.tags.isChecked()}
        s = self.settings
        s.setValue("exp_fmt", c["ext"]); s.setValue("exp_style", c["style"]); s.setValue("exp_group", c["group"])
        s.setValue("exp_notes", c["notes"]); s.setValue("exp_tags", c["tags"])
        return c


class QuotesView(QWidget):
    goto_requested = Signal(str, int, str)        # belge kimliği, cümle numarası, cümle izi
    audio_requested = Signal(list, str)           # okunacak metinler, önerilen dosya adı
    changed = Signal()                            # metindeki işaretler yenilensin

    def __init__(self, store, settings, parent=None):
        super().__init__(parent)
        self.store, self.settings = store, settings
        self.doc_id = None
        self.rows = {}
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        r1 = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ara…  #etiket ile etikete göre")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.tag_btn = QToolButton()
        self.tag_btn.setText("# Etiketler")
        self.tag_btn.setPopupMode(QToolButton.InstantPopup)
        self.tag_menu = QMenu(self.tag_btn)
        self.tag_menu.aboutToShow.connect(self.fill_tag_menu)
        self.tag_btn.setMenu(self.tag_menu)
        r1.addWidget(self.search, 1)
        r1.addWidget(self.tag_btn)
        r2 = QHBoxLayout()
        self.scope = QComboBox(); self.scope.addItems(["Bu belge", "Tüm belgeler"])
        self.kind = QComboBox(); self.kind.addItems(["Tümü", "Alıntılar", "Notlar", "Vurgular"])
        self.group = QComboBox(); self.group.addItems(["Gruplama yok", "Belgeye göre", "Etikete göre"])
        self.scope.setCurrentIndex(self.settings.value("q_scope", 0, type=int))
        self.kind.setCurrentIndex(self.settings.value("q_kind", 0, type=int))
        self.group.setCurrentIndex(self.settings.value("q_group", 0, type=int))
        for c in (self.scope, self.kind, self.group):
            c.setFocusPolicy(Qt.NoFocus)
            c.activated.connect(lambda _: self.on_filter_changed())
            r2.addWidget(c, 1)
        lay.addLayout(r1)
        lay.addLayout(r2)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setIndentation(14)
        self.tree.setTextElideMode(Qt.ElideRight)
        # Kayıtlar arasında boşluk ve ince bir ayraç: nerede bitip nerede başladıkları seçilsin.
        self.tree.setStyleSheet(
            "QTreeWidget::item { padding: 6px 2px; border-bottom: 1px solid palette(midlight); }"
            "QTreeWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }")
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_menu)
        self.tree.itemDoubleClicked.connect(lambda it, _: self.goto(it))
        self.tree.itemSelectionChanged.connect(self.update_status)
        lay.addWidget(self.tree, 1)
        r3 = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        all_btn = QPushButton("Tümünü Seç")
        all_btn.clicked.connect(self.select_all)
        exp_btn = QPushButton("Dışa Aktar…")
        exp_btn.clicked.connect(lambda: self.export())
        for b in (all_btn, exp_btn):
            b.setFocusPolicy(Qt.NoFocus)
        r3.addWidget(self.status, 1)
        r3.addWidget(all_btn)
        r3.addWidget(exp_btn)
        lay.addLayout(r3)
        QShortcut(QKeySequence.Copy, self.tree, lambda: self.copy(self.selected_ids()), context=Qt.WidgetShortcut)
        QShortcut(QKeySequence.Delete, self.tree, lambda: self.delete(self.selected_ids()), context=Qt.WidgetShortcut)

    # ── süzme ve liste ──
    def on_filter_changed(self):
        s = self.settings
        s.setValue("q_scope", self.scope.currentIndex()); s.setValue("q_kind", self.kind.currentIndex())
        s.setValue("q_group", self.group.currentIndex())
        self.refresh()

    def set_doc(self, doc_id):
        self.doc_id = doc_id
        self.refresh()

    def visible_rows(self):
        kind = {1: KIND_QUOTE, 2: KIND_NOTE, 3: KIND_HIGHLIGHT}.get(self.kind.currentIndex())
        rows = self.store.annotations(self.doc_id if self.scope.currentIndex() == 0 else None) \
            if (self.scope.currentIndex() == 1 or self.doc_id) else []
        tags, words = split_query(self.search.text())
        out = []
        for r in rows:
            if kind and r["kind"] != kind:
                continue
            if not matches(f"{r['text']} {r['note']} {doc_title(r)} {r['author'] or ''}",
                           (r["tags"] or "").split(), tags, words):
                continue
            out.append(r)
        return out

    def item_text(self, r):
        tags = " ".join("#" + t for t in (r["tags"] or "").split())
        page = page_number(r["page_label"], r["page_offset"])
        src = " · ".join(x for x in (doc_title(r) if self.scope.currentIndex() == 1 or self.group.currentIndex() == 2
                                     else "", f"s. {page}" if page else (r["page_label"] or ""), tags) if x)
        if r["kind"] == KIND_NOTE:
            main = f"{ICONS[KIND_NOTE]} {r['note']}\n“{r['text']}”"
        else:
            main = f"{ICONS[r['kind']]} “{r['text']}”" + (f"\n✎ {r['note']}" if r["note"] else "")
        return main + (f"\n{src}" if src else "")

    def make_item(self, r):
        it = QTreeWidgetItem([self.item_text(r)])
        it.setData(0, ROLE_AID, r["id"])
        tip = f"{KIND_NAMES[r['kind']]} · {doc_title(r)}"
        page = page_number(r["page_label"], r["page_offset"])
        if page:
            tip += f", s. {page}"
        it.setToolTip(0, tip + "\n\n" + r["text"] + (f"\n\nNot: {r['note']}" if r["note"] else ""))
        return it

    def refresh(self):
        selected = set(self.selected_ids())
        rows = self.visible_rows()
        self.rows = {r["id"]: r for r in rows}
        self.tree.clear()
        group = self.group.currentIndex()
        bold = QFont(); bold.setBold(True)
        if group == 0:
            for r in rows:
                self.tree.addTopLevelItem(self.make_item(r))
        else:
            groups, order = {}, []
            for r in rows:
                keys = [doc_title(r)] if group == 1 else ["#" + t for t in (r["tags"] or "").split()] or ["(etiketsiz)"]
                for k in keys:
                    if k not in groups:
                        groups[k] = []; order.append(k)
                    groups[k].append(r)
            if group == 2:
                order.sort(key=lambda k: (k == "(etiketsiz)", tr_lower(k)))
            for k in order:
                g = QTreeWidgetItem([f"{k}  ({len(groups[k])})"])
                g.setFont(0, bold)
                g.setFlags(Qt.ItemIsEnabled)
                for r in groups[k]:
                    g.addChild(self.make_item(r))
                self.tree.addTopLevelItem(g)
                g.setExpanded(True)
        for it in self.all_items():
            if it.data(0, ROLE_AID) in selected:
                it.setSelected(True)
        self.update_status()

    def all_items(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, ROLE_AID) is not None:
                out.append(top)
            for j in range(top.childCount()):
                out.append(top.child(j))
        return out

    def selected_ids(self):
        ids = []
        for it in self.tree.selectedItems():
            a = it.data(0, ROLE_AID)
            if a is not None and a not in ids:
                ids.append(a)
        return ids

    def select_all(self):
        for it in self.all_items():
            it.setSelected(True)

    def update_status(self):
        n = len(self.rows)
        sel = len(self.selected_ids())
        if not n:
            if self.scope.currentIndex() == 0 and not self.doc_id:
                t = "Belge açık değil. Tüm belgelerdeki alıntılar için kapsamı değiştirin."
            elif self.search.text().strip():
                t = "Aramaya uyan kayıt yok."
            else:
                t = "Henüz kayıt yok. Okurken M alıntılar, N not ekler, H vurgular."
        else:
            t = f"{n} kayıt" + (f" · {sel} seçili" if sel else "")
        self.status.setText(t)

    def fill_tag_menu(self):
        self.tag_menu.clear()
        tags = self.store.all_tags()
        if not tags:
            self.tag_menu.addAction("Henüz etiket yok").setEnabled(False)
            return
        current = split_query(self.search.text())[0]
        for row in tags:
            a = self.tag_menu.addAction(f"#{row['tag']}  ({row['n']})")
            a.setCheckable(True)
            a.setChecked(row["tag"] in current)
            a.triggered.connect(lambda _=False, t=row["tag"]: self.toggle_tag(t))
        self.tag_menu.addSeparator()
        self.tag_menu.addAction("Etiket süzgecini temizle", self.clear_tags)

    def toggle_tag(self, tag):
        tags, words = split_query(self.search.text())
        tags = [t for t in tags if t != tag] if tag in tags else tags + [tag]
        self.search.setText(" ".join(["#" + t for t in tags] + ([words] if words else [])))

    def clear_tags(self):
        self.search.setText(split_query(self.search.text())[1])

    # ── işlemler ──
    def show_menu(self, pos):
        it = self.tree.itemAt(pos)
        if it is not None and it.data(0, ROLE_AID) is not None and not it.isSelected():
            self.tree.clearSelection()
            it.setSelected(True)
        ids = self.selected_ids()
        menu = QMenu(self)
        if ids:
            one = len(ids) == 1
            a = menu.addAction("İlgili Sayfaya Git", lambda: self.goto(self.tree.selectedItems()[0]))
            a.setEnabled(one)
            menu.addAction("Ses Dosyası Oluştur…" if one else f"Ses Dosyası Oluştur ({len(ids)} kayıt)…",
                           lambda: self.make_audio(ids))
            menu.addSeparator()
            menu.addAction("Kopyala", lambda: self.copy(ids))
            menu.addAction("Künyeyle Kopyala", lambda: self.copy(ids, cite=True))
            menu.addSeparator()
            a = menu.addAction("Düzenle…", lambda: self.edit(ids[0]))
            a.setEnabled(one)
            menu.addAction("Dışa Aktar…", lambda: self.export(preselect="selected"))
            menu.addSeparator()
            menu.addAction("Sil" if one else f"Sil ({len(ids)} kayıt)", lambda: self.delete(ids))
        else:
            menu.addAction("Tümünü Seç", self.select_all)
            menu.addAction("Dışa Aktar…", lambda: self.export())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def goto(self, item):
        aid = item.data(0, ROLE_AID) if item is not None else None
        if aid is None:
            return
        r = self.rows.get(aid) or (self.store.annotations(ids=[aid]) or [None])[0]
        if r:
            self.goto_requested.emit(r["doc_id"], r["sent_index"] or 0, r["anchor"] or "")

    def rows_for(self, ids):
        rows = self.store.annotations(ids=list(ids))
        order = {a: k for k, a in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r["id"], 0))

    def copy(self, ids, cite=False):
        style = self.settings.value("exp_style", "chicago")
        parts = []
        for r in self.rows_for(ids):
            body = r["note"] if r["kind"] == KIND_NOTE else f"“{r['text']}”"
            if cite:
                body += " " + runs_text(citation(r, style, page_number(r["page_label"], r["page_offset"])))
            parts.append(body)
        QApplication.clipboard().setText("\n\n".join(parts))
        self.status.setText(f"{len(parts)} kayıt panoya kopyalandı.")

    def make_audio(self, ids):
        rows = self.rows_for(ids)
        # Notlardaki #etiketler sesli okunmasın
        texts = [(re.sub(r"\s*#[^\W_][\w\-]*", "", r["note"]).strip() if r["kind"] == KIND_NOTE else r["text"])
                 for r in rows]
        texts = [t for t in texts if t]
        name = doc_title(rows[0]) if len({r["doc_id"] for r in rows}) == 1 else "alıntılar"
        self.audio_requested.emit(texts, f"{name} - alıntılar" if len(rows) > 1 else f"{name} - alıntı")

    def edit(self, aid):
        rows = self.store.annotations(ids=[aid])
        if not rows:
            return
        r = rows[0]
        dlg = AnnotationDialog(self, r["kind"], r["text"], r["note"], (r["tags"] or "").split(), r["page_label"],
                               self.store.all_tags())
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            self.store.update_annotation(aid, note=v["note"], tags=v["tags"], page_label=v["page_label"])
            if v["text"] != r["text"]:
                with self.store.db:
                    self.store.db.execute("UPDATE annotations SET text=? WHERE id=?", (v["text"], aid))
            self.refresh()
            self.changed.emit()

    def delete(self, ids):
        if not ids:
            return
        if QMessageBox.question(self, "Sil", f"{len(ids)} kayıt silinsin mi?" if len(ids) > 1
                                else "Bu kayıt silinsin mi?") != QMessageBox.Yes:
            return
        self.store.delete_annotations(ids)
        self.refresh()
        self.changed.emit()

    def export(self, preselect=None):
        sel = self.selected_ids()
        doc_rows = self.store.annotations(self.doc_id) if self.doc_id else []
        all_rows = self.store.annotations()
        counts = {"selected": len(sel), "visible": len(self.rows), "doc": len(doc_rows), "all": len(all_rows)}
        if not counts["all"]:
            QMessageBox.information(self, "Dışa aktar", "Henüz alıntı, not ya da vurgu yok.")
            return
        dlg = ExportQuotesDialog(self, counts, self.settings)
        if preselect == "selected" and sel:
            dlg.scope.button(0).setChecked(True)
        if dlg.exec() != QDialog.Accepted:
            return
        c = dlg.choices()
        rows = {"selected": lambda: self.rows_for(sel), "visible": lambda: list(self.rows.values()),
                "doc": lambda: doc_rows, "all": lambda: all_rows}[c["scope"]]()
        base = doc_title(rows[0]) + " - alıntılar" if len({r["doc_id"] for r in rows}) == 1 else "Alıntılar"
        start = os.path.join(self.settings.value("exp_dir", os.path.expanduser("~")), base + c["ext"])
        filt = next(label for label, ext in FORMATS if ext == c["ext"])
        path, _ = QFileDialog.getSaveFileName(self, "Alıntıları kaydet", start, filt)
        if not path:
            return
        if not path.lower().endswith(c["ext"]):
            path += c["ext"]
        try:
            write_export(path, rows, c["style"], c["group"], c["notes"], c["tags"])
        except Exception as e:
            QMessageBox.warning(self, "Kaydedilemedi", f"{e}\n\nDosya başka bir programda açık olabilir.")
            return
        self.settings.setValue("exp_dir", os.path.dirname(path))
        self.status.setText(f"{len(rows)} kayıt dışa aktarıldı: {os.path.basename(path)}")
        from .dialogs import show_done
        show_done(self, "Dışa aktarma tamamlandı", f"{len(rows)} kayıt dışa aktarıldı.", path)

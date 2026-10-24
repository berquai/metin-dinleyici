# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Temizlik ve sıfırlama: deneme verilerini ve gereksiz dosyaları temizler, kütüphaneyi korur."""
import glob
import os
import shutil
import tempfile

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QLabel, QMessageBox, QVBoxLayout)

from .library_info import human_size


def folder_size(path):
    total = 0
    for root, _, files in os.walk(path or ""):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def temp_audio_dirs(current):
    return [d for d in glob.glob(os.path.join(tempfile.gettempdir(), "metin_dinleyici_*"))
            if os.path.normcase(d) != os.path.normcase(current or "")]


class CleanupDialog(QDialog):
    """Her kalemin kapladığı yer görünür. Yeniden üretilebilen şeyler işaretli gelir; geri getirilemeyecek
    olanlar (alıntılar, düzeltmeler, ayarlar) işaretsiz gelir ki kazara silinmesin."""

    def __init__(self, parent, store, cache_dir, cover_dir, tmpdir):
        super().__init__(parent)
        self.setWindowTitle("Temizlik ve sıfırlama")
        self.resize(620, 0)
        c = store.cleanup_counts()
        missing = len(store.missing_in_library())
        lay = QVBoxLayout(self)
        intro = QLabel("Kütüphanedeki belgeler korunur. Seçtikleriniz silinir; işlemden sonra açık belge kapanır "
                       "ve temiz bir sayfayla başlarsınız.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.items = {}

        def add(box, key, text, checked, enabled=True, warn=False):
            cb = QCheckBox(text)
            cb.setChecked(checked and enabled)
            cb.setEnabled(enabled)
            if warn:
                cb.setStyleSheet("QCheckBox { color: #c0392b; }")
            box.layout().addWidget(cb)
            self.items[key] = cb

        safe = QGroupBox("Yeniden üretilebilenler (önerilir)")
        safe.setLayout(QVBoxLayout())
        temp_size = folder_size(tmpdir) + sum(folder_size(d) for d in temp_audio_dirs(tmpdir))
        add(safe, "text_cache", f"Metin önbelleği — {human_size(folder_size(cache_dir))}  "
            "(belgeler ilk açılışta yeniden çıkarılır; OCR'lı kitaplar yeniden taranır)", True)
        add(safe, "covers", f"Kapak resimleri — {human_size(folder_size(cover_dir))}  (yeniden oluşturulur)", True)
        add(safe, "temp", f"Geçici ses dosyaları — {human_size(temp_size)}", True)
        add(safe, "small", "Son açılanlar listesi ve okuma hızı ölçümleri", True)
        add(safe, "vacuum", f"Veritabanını sıkıştır — şu an {human_size(store.file_size())}", True)
        lay.addWidget(safe)

        data = QGroupBox("Kayıtlar (geri getirilemez; dikkatle seçin)")
        data.setLayout(QVBoxLayout())
        out_txt = (f"Kütüphanede olmayan belgelerin kayıtları — {c['docs_out']} belge"
                   + (f", {c['ann_out']} alıntı/not" if c["ann_out"] else "")
                   + (f", {c['edits_out']} düzeltme" if c["edits_out"] else "")
                   + "  (kaldığınız yer dahil)")
        add(data, "outside", out_txt, c["ann_out"] == 0 and c["edits_out"] == 0, enabled=c["docs_out"] > 0 or c["ann_out"] > 0)
        add(data, "missing", f"Dosyası bulunamayan {missing} belgeyi kütüphaneden çıkar", False, enabled=missing > 0)
        add(data, "annotations", f"Tüm alıntılar, notlar ve vurgular — {c['annotations']} kayıt", False,
            enabled=c["annotations"] > 0, warn=True)
        add(data, "edits", f"Elle yapılmış tüm metin düzeltmeleri — {c['edits']} belge", False,
            enabled=c["edits"] > 0, warn=True)
        add(data, "rules", f"Telaffuz sözlüğünü başlangıç kurallarına döndür — şu an {c['rules']} kural", False,
            warn=True)
        add(data, "settings", "Tüm ayarlar ve pencere yerleşimi (tema, ses, panel konumları) — yeniden başlatma gerekir",
            False, warn=True)
        lay.addWidget(data)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Seçilenleri Temizle")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.confirm)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def chosen(self):
        return {k for k, cb in self.items.items() if cb.isChecked() and cb.isEnabled()}

    def confirm(self):
        risky = self.chosen() & {"annotations", "edits", "rules", "settings", "outside"}
        if risky:
            names = {"annotations": "tüm alıntılar, notlar ve vurgular", "edits": "tüm metin düzeltmeleri",
                     "rules": "telaffuz sözlüğündeki kendi kurallarınız", "settings": "tüm ayarlar",
                     "outside": "kütüphane dışındaki belgelerin kayıtları"}
            text = "Şunlar kalıcı olarak silinecek:\n\n" + "\n".join(f"• {names[k]}" for k in sorted(risky))
            if QMessageBox.warning(self, "Emin misiniz?", text + "\n\nBu işlem geri alınamaz.",
                                   QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                return
        self.accept()


def perform_cleanup(chosen, store, cache_dir, cover_dir, tmpdir, settings):
    """Seçilen temizliği yapar. Dönüş: (kazanılan bayt, yapılanlar listesi)."""
    from .pronounce import STARTER_RULES
    before = folder_size(cache_dir) + folder_size(cover_dir) + folder_size(tmpdir) + store.file_size() \
        + sum(folder_size(d) for d in temp_audio_dirs(tmpdir))
    done = []
    if "text_cache" in chosen and cache_dir and os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
        done.append("metin önbelleği")
    if "covers" in chosen and cover_dir and os.path.isdir(cover_dir):
        shutil.rmtree(cover_dir, ignore_errors=True)
        store.reset_info()
        done.append("kapak resimleri")
    if "temp" in chosen:
        for d in temp_audio_dirs(tmpdir):
            shutil.rmtree(d, ignore_errors=True)
        for f in glob.glob(os.path.join(tmpdir, "*")):
            try:
                os.remove(f)
            except OSError:
                pass
        done.append("geçici ses dosyaları")
    if "small" in chosen:
        settings.remove("recent")
        settings.remove("wpm")
        done.append("son açılanlar ve hız ölçümleri")
    if "missing" in chosen:
        for r in store.missing_in_library():
            store.remove_from_library(r["id"])
        done.append("bulunamayan belgeler")
    if "outside" in chosen:
        store.purge_outside_library()
        done.append("kütüphane dışı kayıtlar")
    if "annotations" in chosen:
        store.clear_annotations()
        done.append("alıntılar, notlar, vurgular")
    if "edits" in chosen:
        store.clear_edits()
        done.append("metin düzeltmeleri")
    if "rules" in chosen:
        store.save_rules(STARTER_RULES)
        done.append("telaffuz sözlüğü")
    if "vacuum" in chosen:
        try:
            store.vacuum()
            done.append("veritabanı sıkıştırıldı")
        except Exception:
            pass
    if "settings" in chosen:
        settings.clear()
        done.append("ayarlar")
    after = folder_size(cache_dir) + folder_size(cover_dir) + folder_size(tmpdir) + store.file_size() \
        + sum(folder_size(d) for d in temp_audio_dirs(tmpdir))
    return max(0, before - after), done

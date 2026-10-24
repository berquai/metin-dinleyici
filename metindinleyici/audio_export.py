# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Ses dışa aktarma modülü.

Belgenin tamamını ya da bir bölümünü bir veya birden çok ses dosyasına dönüştürür.
- Çevrimiçi seslerde MP3 (ID3 etiketleriyle: başlık, yazar, albüm, parça no — telefonda kitap gibi sıralanır),
  çevrimdışı Windows seslerinde WAV.
- Dosyalara bölme: tek dosya, her sayfa/bölüm, her N sayfa, yaklaşık her N dakika.
- Parçalar üç iş parçacığında paralel üretilir ama dosyaya sırayla yazılır.
"""
import os
import re
import struct
import threading
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSlider, QSpinBox, QVBoxLayout,
)

from .textproc import word_count
from .tts import safe_remove, synth_edge_chunk, synth_sapi

GROUP_CHARS = 2500            # tek seslendirme isteğindeki en fazla karakter
MP3_BYTES_PER_SEC = 6000      # Edge: 48 kbps
WAV_BYTES_PER_SEC = 44000     # SAPI varsayılanı: 22 kHz 16 bit mono
FALLBACK_WPM = 150


# ───────────────────────────── ID3 etiketi ─────────────────────────────

def _id3_frame(fid, text):
    data = b"\x01" + "﻿".encode("utf-16-le") + text.encode("utf-16-le")   # 1 = UTF-16 (BOM'lu)
    return fid.encode("ascii") + struct.pack(">I", len(data)) + b"\x00\x00" + data


def _synchsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def id3_tag(title="", artist="", album="", track=None, total=None, genre="Sesli Kitap"):
    """En yaygın oynatıcıların okuduğu ID3v2.3 etiketi (ek kütüphane gerektirmez)."""
    frames = b""
    for fid, val in (("TIT2", title), ("TPE1", artist), ("TALB", album), ("TCON", genre)):
        if val:
            frames += _id3_frame(fid, val)
    if track:
        frames += _id3_frame("TRCK", f"{track}/{total}" if total else str(track))
    return b"ID3\x03\x00\x00" + _synchsafe(len(frames)) + frames


# ───────────────────────────── plan ─────────────────────────────

def seconds_text(sec):
    sec = int(sec)
    h, m = divmod(sec // 60, 60)
    if h:
        return f"{h} sa {m} dk"
    return f"{max(1, m)} dk" if sec >= 60 else f"{sec} sn"


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip().rstrip(". ")
    return s or "kayit"


def build_plan(sentences, toc, a, b, split, n, title, pron, wpm, announce=False):
    """Seçilen cümle aralığını dosyalara böler.
    split: 'single' | 'section' | 'sections_n' | 'minutes'.  Dönüş: dosya listesi (her biri sözlük)."""
    files = []
    cur = None

    def section_label(i):
        sec = sentences[i].section
        return toc[sec][0] if sec < len(toc) else ""

    def start_file(i):
        return {"first": i, "last": i, "texts": [], "words": 0, "labels": []}

    last_sec, sec_in_file, words_in_file = None, 0, 0
    for i in range(a, b + 1):
        s = sentences[i]
        new_sec = s.section != last_sec
        if cur is None:
            cur = start_file(i)
        elif new_sec and (split == "section" or (split == "sections_n" and sec_in_file >= n)):
            files.append(cur); cur = start_file(i); sec_in_file = 0; words_in_file = 0
        elif split == "minutes" and words_in_file >= n * wpm:
            files.append(cur); cur = start_file(i); words_in_file = 0
        if new_sec:
            sec_in_file += 1
            lab = section_label(i)
            if lab and lab not in cur["labels"]:
                cur["labels"].append(lab)
            if announce and lab:
                cur["texts"].append(lab + ".")
            last_sec = s.section
        t = pron.apply(s.text) if pron else s.text
        cur["texts"].append(t)
        w = word_count(t)
        cur["words"] += w
        words_in_file += w
        cur["last"] = i
    if cur and cur["texts"]:
        files.append(cur)
    total = len(files)
    for k, f in enumerate(files, start=1):
        labs = f["labels"]
        part = (labs[0] if len(labs) == 1 else f"{labs[0]} – {labs[-1]}") if labs else f"Bölüm {k}"
        f["track"], f["total"] = k, total
        f["part"] = part
        f["title"] = title if total == 1 else f"{title} — {part}"
        f["est_sec"] = f["words"] / max(1, wpm) * 60
        groups, g, size = [], [], 0
        for t in f["texts"]:
            if g and size + len(t) > GROUP_CHARS:
                groups.append(g); g, size = [], 0
            g.append(t); size += len(t) + 1
        if g:
            groups.append(g)
        f["groups"] = groups
        f["chars"] = sum(len(t) for t in f["texts"])
    return files


def file_name(template, title, k, total, part):
    width = max(2, len(str(total)))
    name = template.replace("{belge}", title).replace("{no}", str(k).zfill(width)).replace("{bölüm}", part)
    return safe_name(name)


# ───────────────────────────── üretim ─────────────────────────────

class ExportSignals(QObject):
    progress = Signal(object)          # {"done": karakter, "total": karakter, "file": k, "files": n, "name": ...}
    finished = Signal(object)          # {"paths": [...], "cancelled": bool, "error": str|None}


class AudioExportJob:
    def __init__(self, files, folder, template, engine, voice, rate, pause, tags, playlist, tmpdir):
        self.files, self.folder, self.template = files, folder, template
        self.engine, self.voice, self.rate, self.pause = engine, voice, rate, pause
        self.tags, self.playlist, self.tmpdir = tags, playlist, tmpdir
        self.cancel = threading.Event()
        self.sig = ExportSignals()

    def emit(self, signal, payload):
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def synth_group(self, texts):
        if self.cancel.is_set():
            return None
        ext = "mp3" if self.engine == "edge" else "wav"
        tmp = os.path.join(self.tmpdir, f"dis_{uuid.uuid4().hex}.{ext}")
        if self.engine == "edge":
            synth_edge_chunk(texts, self.voice, self.rate, tmp, self.pause)
        else:
            synth_sapi(" ".join(texts), self.voice, self.rate, tmp)
        return tmp

    def run(self):
        total_chars = sum(f["chars"] for f in self.files) or 1
        done_chars = 0
        paths = []
        ext = ".mp3" if self.engine == "edge" else ".wav"
        pool = ThreadPoolExecutor(max_workers=3 if self.engine == "edge" else 1)
        try:
            for f in self.files:
                if self.cancel.is_set():
                    break
                name = file_name(self.template, self.tags["album"], f["track"], f["total"], f["part"]) + ext
                out = os.path.join(self.folder, name)
                part = out + ".part"
                self.emit(self.sig.progress, {"done": done_chars, "total": total_chars, "file": f["track"],
                                              "files": f["total"], "name": name})
                wav_writer = None
                try:
                    with open(part, "wb") as fo:
                        if ext == ".mp3":
                            fo.write(id3_tag(f["title"], self.tags["artist"], self.tags["album"],
                                             f["track"], f["total"]))
                        # map: üç parça aynı anda hazırlanır, sonuçlar sırayla gelir
                        for texts, tmp in zip(f["groups"], pool.map(self.synth_group, f["groups"])):
                            if tmp is None or self.cancel.is_set():
                                raise InterruptedError()
                            try:
                                if ext == ".mp3":
                                    with open(tmp, "rb") as fi:
                                        fo.write(fi.read())          # MP3 çerçeveleri art arda eklenebilir
                                else:
                                    with wave.open(tmp, "rb") as wi:
                                        if wav_writer is None:
                                            wav_writer = wave.open(fo, "wb")
                                            wav_writer.setparams(wi.getparams())
                                        wav_writer.writeframes(wi.readframes(wi.getnframes()))
                                        gap = int(wi.getframerate() * 0.35)
                                        wav_writer.writeframes(b"\x00" * gap * wi.getsampwidth() * wi.getnchannels())
                            finally:
                                safe_remove(tmp)
                            done_chars += sum(len(t) for t in texts)
                            self.emit(self.sig.progress, {"done": done_chars, "total": total_chars,
                                                          "file": f["track"], "files": f["total"], "name": name})
                        if wav_writer is not None:
                            wav_writer.close()
                    os.replace(part, out)
                    paths.append(out)
                except InterruptedError:
                    safe_remove(part)
                    break
                except Exception:
                    safe_remove(part)
                    raise
            if self.playlist and len(paths) > 1 and not self.cancel.is_set():
                m3u = os.path.join(self.folder, safe_name(self.tags["album"]) + ".m3u8")
                with open(m3u, "w", encoding="utf-8") as fp:
                    fp.write("#EXTM3U\n")
                    for f, p in zip(self.files, paths):
                        fp.write(f"#EXTINF:{int(f['est_sec'])},{f['title']}\n{os.path.basename(p)}\n")
                paths.append(m3u)
            self.emit(self.sig.finished, {"paths": paths, "cancelled": self.cancel.is_set(), "error": None})
        except Exception as e:
            self.emit(self.sig.finished, {"paths": paths, "cancelled": False, "error": str(e) or e.__class__.__name__})
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


# ───────────────────────────── pencere ─────────────────────────────

class AudioExportDialog(QDialog):
    """Okumayı engellemeden arka planda çalışan ses dışa aktarma penceresi."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Ses olarak dışa aktar")
        self.setModal(False)
        self.resize(640, 0)
        self.job = None
        self.thread = None
        m = main
        self.sentences, self.toc = m.sentences, m.toc
        self.engine = m.engine()
        lay = QVBoxLayout(self)

        # ── kapsam ──
        g1 = QGroupBox("Ne seslendirilsin?")
        f1 = QVBoxLayout(g1)
        self.scope = QButtonGroup(self)
        self.r_all = QRadioButton(f"Belgenin tamamı ({len(self.sentences)} cümle)")
        self.r_here = QRadioButton(f"Okunan yerden sona (cümle {m.current_index + 1}'den)")
        self.r_secs = QRadioButton("Sayfa / bölüm aralığı")
        self.r_sent = QRadioButton("Cümle aralığı")
        for k, r in enumerate((self.r_all, self.r_here, self.r_secs, self.r_sent)):
            self.scope.addButton(r, k)
        self.sec_from, self.sec_to = QComboBox(), QComboBox()
        self.sec_first = []
        for label, first in self.toc:
            if first is not None:
                self.sec_from.addItem(label); self.sec_to.addItem(label); self.sec_first.append(first)
        self.sec_to.setCurrentIndex(self.sec_to.count() - 1)
        cur_sec = max(0, next((k for k, f in reversed(list(enumerate(self.sec_first))) if f <= m.current_index), 0))
        self.sec_from.setCurrentIndex(cur_sec)
        self.s_from, self.s_to = QSpinBox(), QSpinBox()
        for sp in (self.s_from, self.s_to):
            sp.setRange(1, max(1, len(self.sentences)))
        self.s_from.setValue(m.current_index + 1)
        self.s_to.setValue(len(self.sentences))
        f1.addWidget(self.r_all)
        f1.addWidget(self.r_here)
        row = QHBoxLayout(); row.addWidget(self.r_secs); row.addWidget(self.sec_from, 1); row.addWidget(QLabel("→"))
        row.addWidget(self.sec_to, 1); f1.addLayout(row)
        row = QHBoxLayout(); row.addWidget(self.r_sent); row.addWidget(self.s_from); row.addWidget(QLabel("→"))
        row.addWidget(self.s_to); row.addStretch(1); f1.addLayout(row)
        self.r_here.setChecked(m.current_index > 0)
        self.r_all.setChecked(m.current_index == 0)
        lay.addWidget(g1)

        # ── bölme ──
        g2 = QGroupBox("Dosyalara bölme")
        f2 = QHBoxLayout(g2)
        self.split = QComboBox()
        self.split.addItem("Tek dosya", "single")
        self.split.addItem("Her sayfa / bölüm ayrı dosya", "section")
        self.split.addItem("Her N sayfa / bölümde bir dosya", "sections_n")
        self.split.addItem("Yaklaşık her N dakikada bir dosya", "minutes")
        self.split_n = QSpinBox()
        self.split_n.setRange(1, 600)
        self.split.setCurrentIndex(max(0, self.split.findData(m.settings.value("ax_split", "single"))))
        self.split_n.setValue(m.settings.value("ax_n", 20, type=int))
        f2.addWidget(self.split, 1)
        self.n_label = QLabel()
        f2.addWidget(self.split_n)
        f2.addWidget(self.n_label)
        lay.addWidget(g2)

        # ── ses ──
        g3 = QGroupBox("Ses")
        f3 = QFormLayout(g3)
        self.voice = QComboBox()
        for k in range(m.voice.count()):
            self.voice.addItem(m.voice.itemText(k), m.voice.itemData(k))
        self.voice.setCurrentIndex(m.voice.currentIndex())
        self.rate = QSlider(Qt.Horizontal); self.rate.setRange(50, 200); self.rate.setSingleStep(5)
        self.rate.setValue(m.rate.value())
        self.rate_label = QLabel()
        rr = QHBoxLayout(); rr.addWidget(self.rate, 1); rr.addWidget(self.rate_label)
        self.pause = QSlider(Qt.Horizontal); self.pause.setRange(10, 120); self.pause.setValue(m.pause.value())
        self.pause.setEnabled(self.engine == "edge")
        self.pause_label = QLabel()
        pr = QHBoxLayout(); pr.addWidget(self.pause, 1); pr.addWidget(self.pause_label)
        f3.addRow("Ses", self.voice)
        f3.addRow("Hız", rr)
        f3.addRow("Cümle arası es", pr)
        self.announce = QCheckBox("Her sayfa / bölüm başında adını da oku")
        self.announce.setChecked(m.settings.value("ax_announce", False, type=bool))
        f3.addRow("", self.announce)
        fmt = QLabel("Biçim: MP3 (çevrimiçi ses)" if self.engine == "edge"
                     else "Biçim: WAV (çevrimdışı Windows sesi; MP3 için çevrimiçi sese geçin)")
        f3.addRow("", fmt)
        lay.addWidget(g3)

        # ── çıktı ──
        g4 = QGroupBox("Kayıt yeri ve etiketler")
        f4 = QFormLayout(g4)
        stem = os.path.splitext(os.path.basename(m.doc_path or "kayit"))[0]
        row = m.store.get_document(m.doc_id) if m.doc_id else None
        title = (row["custom_title"] or row["title"]) if row else stem
        author = (row["author"] if row else "") or ""
        self.folder = QLineEdit(m.settings.value("ax_dir", os.path.dirname(m.doc_path or os.path.expanduser("~"))))
        browse = QPushButton("Gözat…")
        browse.clicked.connect(self.pick_folder)
        fr = QHBoxLayout(); fr.addWidget(self.folder, 1); fr.addWidget(browse)
        self.template = QLineEdit()
        self.template.setToolTip("{belge}: albüm adı · {no}: parça numarası (01, 02…) · {bölüm}: sayfa/bölüm adı")
        self.album = QLineEdit(title)
        self.artist = QLineEdit(author)
        self.playlist = QCheckBox("Çalma listesi (.m3u8) oluştur")
        self.playlist.setChecked(True)
        f4.addRow("Klasör", fr)
        f4.addRow("Dosya adı", self.template)
        f4.addRow("Albüm (eser adı)", self.album)
        f4.addRow("Sanatçı (yazar)", self.artist)
        f4.addRow("", self.playlist)
        lay.addWidget(g4)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(True)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.start_btn = QPushButton("Başlat")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Kapat")
        self.cancel_btn.clicked.connect(self.cancel_or_close)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.cancel_btn)
        lay.addLayout(btns)

        for w in (self.sec_from, self.sec_to, self.split, self.voice):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.s_from, self.s_to, self.split_n):
            w.valueChanged.connect(self.refresh)
        for w in (self.rate, self.pause):
            w.valueChanged.connect(self.refresh)
        self.scope.idClicked.connect(lambda _: self.refresh())
        self.announce.toggled.connect(lambda _: self.refresh())
        self.album.textChanged.connect(lambda _: self.refresh())
        self.split.currentIndexChanged.connect(self.reset_template)
        self.reset_template()
        self.refresh()

    # ── hesaplar ──
    def wpm(self):
        key = f"{self.engine}|{self.voice.currentData() or ''}"
        base = self.main.wpm.get(key, (FALLBACK_WPM / self.main.speed_factor(self.engine, 100), 0))[0]
        return max(60, base * self.main.speed_factor(self.engine, self.rate.value()))

    def bounds(self):
        n = len(self.sentences)
        sid = self.scope.checkedId()
        if sid == 1:
            return self.main.current_index, n - 1
        if sid == 2 and self.sec_first:
            i, j = sorted((self.sec_from.currentIndex(), self.sec_to.currentIndex()))
            end = self.sec_first[j + 1] - 1 if j + 1 < len(self.sec_first) else n - 1
            return self.sec_first[i], end
        if sid == 3:
            a, b = sorted((self.s_from.value(), self.s_to.value()))
            return a - 1, b - 1
        return 0, n - 1

    def plan(self):
        a, b = self.bounds()
        return build_plan(self.sentences, self.toc, a, b, self.split.currentData(), self.split_n.value(),
                          self.album.text().strip() or "Kayıt", self.main.pron, self.wpm(), self.announce.isChecked())

    def reset_template(self):
        multi = self.split.currentData() != "single"
        self.template.setText("{belge} - {no}" if multi else "{belge}")
        self.n_label.setText({"sections_n": "sayfa / bölüm", "minutes": "dakika"}.get(self.split.currentData(), ""))
        self.split_n.setVisible(self.split.currentData() in ("sections_n", "minutes"))
        self.playlist.setEnabled(multi)

    def refresh(self):
        self.rate_label.setText(f"%{self.rate.value()}")
        self.pause_label.setText(f"{self.pause.value() / 100:.2f}".replace(".", ",") + " sn")
        if not self.sentences:
            self.summary.setText("Açık belge yok.")
            self.start_btn.setEnabled(False)
            return
        files = self.plan()
        sec = sum(f["est_sec"] for f in files)
        bps = MP3_BYTES_PER_SEC if self.engine == "edge" else WAV_BYTES_PER_SEC
        measured = f"{self.engine}|{self.voice.currentData() or ''}" in self.main.wpm
        self.summary.setText(
            f"<b>{len(files)} dosya</b> · tahmini süre <b>{seconds_text(sec)}</b> · yaklaşık "
            f"{max(1, round(sec * bps / 1_048_576))} MB · dakikada ~{round(self.wpm())} kelime"
            + ("" if measured else " (bu ses için henüz ölçüm yok; tahmin)")
            + (f"<br>İlk dosya: {file_name(self.template.text(), self.album.text() or 'Kayıt', 1, len(files), files[0]['part'])}"
               if files else ""))
        self.start_btn.setEnabled(bool(files) and self.job is None)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Kayıt klasörü", self.folder.text())
        if d:
            self.folder.setText(d)

    # ── çalıştırma ──
    def start(self):
        files = self.plan()
        folder = self.folder.text().strip()
        if not files:
            return
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Klasör", "Geçerli bir kayıt klasörü seçin.")
            return
        ext = ".mp3" if self.engine == "edge" else ".wav"
        names = [file_name(self.template.text(), self.album.text() or "Kayıt", f["track"], len(files), f["part"]) + ext
                 for f in files]
        if len(set(n.lower() for n in names)) < len(names):
            QMessageBox.warning(self, "Dosya adı", "Dosya adları birbirinin aynısı olacak. Dosya adına {no} ekleyin.")
            return
        existing = [n for n in names if os.path.exists(os.path.join(folder, n))]
        if existing and QMessageBox.question(
                self, "Üzerine yazılsın mı?", f"{len(existing)} dosya bu klasörde zaten var "
                f"(ör. {existing[0]}). Üzerine yazılsın mı?") != QMessageBox.Yes:
            return
        s = self.main.settings
        s.setValue("ax_dir", folder); s.setValue("ax_split", self.split.currentData())
        s.setValue("ax_n", self.split_n.value()); s.setValue("ax_announce", self.announce.isChecked())
        self.job = AudioExportJob(files, folder, self.template.text(), self.engine, self.voice.currentData() or "",
                                  self.rate.value(), self.pause.value() / 100,
                                  {"album": self.album.text().strip() or "Kayıt", "artist": self.artist.text().strip()},
                                  self.playlist.isChecked() and self.playlist.isEnabled(), self.main.tmpdir)
        self.job.sig.progress.connect(self.on_progress)
        self.job.sig.finished.connect(self.on_finished)
        for w in self.findChildren(QGroupBox):
            w.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText("İptal")
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText("Başlıyor…")
        self.thread = threading.Thread(target=self.job.run, daemon=True)
        self.thread.start()

    def on_progress(self, p):
        self.bar.setValue(int(1000 * p["done"] / max(1, p["total"])))
        self.bar.setFormat(f"%p%  ·  dosya {p['file']} / {p['files']}")
        self.status.setText(f"Hazırlanıyor: {p['name']}")

    def on_finished(self, r):
        self.job = None
        for w in self.findChildren(QGroupBox):
            w.setEnabled(True)
        self.cancel_btn.setText("Kapat")
        self.cancel_btn.setEnabled(True)
        self.refresh()
        audio = [p for p in r["paths"] if not p.endswith(".m3u8")]
        if r["error"]:
            self.status.setText("Hata.")
            QMessageBox.warning(self, "Ses kaydı tamamlanamadı",
                                f"{r['error']}\n\n{len(audio)} dosya tamamlanmıştı; yarım kalan dosya silindi.")
            return
        if r["cancelled"]:
            self.status.setText(f"İptal edildi. {len(audio)} dosya tamamlanmıştı; yarım kalan dosya silindi.")
            return
        self.bar.setValue(1000)
        self.status.setText(f"Tamamlandı: {len(audio)} dosya.")
        from .dialogs import show_done
        show_done(self, "Ses kaydı tamamlandı",
                  f"{len(audio)} ses dosyası hazır." if len(audio) > 1 else "Ses dosyası hazır.",
                  audio[0] if len(audio) == 1 else (r["paths"][-1] if r["paths"] else self.folder.text()))

    def cancel_or_close(self):
        if self.job is not None:
            self.job.cancel.set()
            self.status.setText("İptal ediliyor… (o anda hazırlanan parça bitince durur)")
            self.cancel_btn.setEnabled(False)
            return
        self.close()

    def closeEvent(self, e):
        if self.job is not None:
            if QMessageBox.question(self, "Kayıt sürüyor", "Ses kaydı sürüyor. İptal edilsin mi?") != QMessageBox.Yes:
                e.ignore()
                return
            self.job.cancel.set()
        super().closeEvent(e)

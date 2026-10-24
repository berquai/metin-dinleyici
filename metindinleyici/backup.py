# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Yedekleme ve geri yükleme.

Yedek tek bir .zip dosyasıdır:
- metin_dinleyici.db : kütüphane, kaldığınız yerler, alıntılar, notlar, vurgular, etiketler,
                       telaffuz sözlüğü, elle düzeltmeler, künye bilgileri
- ayarlar.json       : tema, ses, hız, panel yerleşimi ve diğer ayarlar
- kapaklar/          : kapak resimleri (isteğe bağlı; zaten yeniden üretilebilir)
- bilgi.json         : yedeğin sürümü, tarihi ve içerik sayıları

Belgelerin kendisi (PDF, EPUB…) yedeğe girmez; onlar sizin klasörlerinizde durur.
Veritabanı, SQLite'ın yedekleme arayüzüyle kopyalanır: uygulama açıkken bile tutarlı bir anlık görüntü alınır.
"""
import base64
import glob
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime

from PySide6.QtCore import QByteArray

from . import APP_NAME, APP_VERSION
from .store import SCHEMA_VERSION

FORMAT = "metin-dinleyici-yedek"


def _encode(v):
    if isinstance(v, QByteArray):
        return {"__b64__": bytes(v.toBase64()).decode("ascii")}
    if isinstance(v, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_encode(x) for x in v]
    return str(v)


def _decode(v):
    if isinstance(v, dict) and "__b64__" in v:
        return QByteArray.fromBase64(v["__b64__"].encode("ascii"))
    if isinstance(v, list):
        return [_decode(x) for x in v]
    return v


def counts(db):
    q = lambda sql: db.execute(sql).fetchone()[0]
    try:
        return {"belge": q("SELECT count(*) FROM documents WHERE in_library=1"),
                "alıntı/not/vurgu": q("SELECT count(*) FROM annotations"),
                "telaffuz kuralı": q("SELECT count(*) FROM pron_rules"),
                "düzeltilmiş belge": q("SELECT count(*) FROM doc_edits")}
    except sqlite3.Error:
        return {}


def create_backup(out, store, settings, cover_dir, include_covers=True):
    tmp = tempfile.mkdtemp(prefix="md_yedek_")
    db_copy = os.path.join(tmp, "metin_dinleyici.db")
    dst = sqlite3.connect(db_copy)
    store.db.commit()
    store.db.backup(dst)                      # açık veritabanının tutarlı anlık görüntüsü
    dst.close()
    settings.sync()
    data = {k: _encode(settings.value(k)) for k in settings.allKeys()}
    info = {"format": FORMAT, "app": APP_NAME, "version": APP_VERSION, "schema": SCHEMA_VERSION,
            "date": datetime.now().isoformat(timespec="seconds"), "counts": counts(store.db)}
    part = out + ".part"
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bilgi.json", json.dumps(info, ensure_ascii=False, indent=2))
        z.write(db_copy, "metin_dinleyici.db")
        z.writestr("ayarlar.json", json.dumps(data, ensure_ascii=False, indent=1))
        if include_covers and cover_dir and os.path.isdir(cover_dir):
            for f in glob.glob(os.path.join(cover_dir, "*.png")):
                z.write(f, "kapaklar/" + os.path.basename(f))
    os.replace(part, out)
    try:
        os.remove(db_copy)
        os.rmdir(tmp)
    except OSError:
        pass
    return info


def read_info(path):
    """Yedeğin bilgilerini okur ve doğrular. Hata varsa ValueError."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "bilgi.json" not in names or "metin_dinleyici.db" not in names:
                raise ValueError("Bu dosya bir Metin Dinleyici yedeği değil.")
            info = json.loads(z.read("bilgi.json").decode("utf-8"))
            info["has_settings"] = "ayarlar.json" in names
            info["covers"] = sum(1 for n in names if n.startswith("kapaklar/"))
    except zipfile.BadZipFile:
        raise ValueError("Dosya bozuk ya da bir zip arşivi değil.")
    if info.get("format") != FORMAT:
        raise ValueError("Bu dosya bir Metin Dinleyici yedeği değil.")
    if int(info.get("schema", 0)) > SCHEMA_VERSION:
        raise ValueError(f"Bu yedek uygulamanın daha yeni bir sürümüyle ({info.get('version')}) alınmış. "
                         "Geri yüklemek için uygulamayı güncelleyin.")
    return info


def restore_backup(path, store, settings, cover_dir, parts):
    """parts: {'data', 'settings', 'covers'} alt kümesi. Veritabanı yerinde değiştirilir (bağlantı açık kalır)."""
    read_info(path)
    tmp = tempfile.mkdtemp(prefix="md_geri_")
    with zipfile.ZipFile(path) as z:
        if "data" in parts:
            z.extract("metin_dinleyici.db", tmp)
            src = sqlite3.connect(os.path.join(tmp, "metin_dinleyici.db"))
            src.backup(store.db)              # mevcut veritabanının yerine yedektekini yazar
            src.close()
            store._migrate()                  # eski bir sürümün yedeğiyse şemayı güncelle
        if "settings" in parts and "ayarlar.json" in z.namelist():
            data = json.loads(z.read("ayarlar.json").decode("utf-8"))
            settings.clear()
            for k, v in data.items():
                settings.setValue(k, _decode(v))
            settings.sync()
        if "covers" in parts and cover_dir:
            os.makedirs(cover_dir, exist_ok=True)
            for n in z.namelist():
                if n.startswith("kapaklar/") and n.endswith(".png"):
                    with open(os.path.join(cover_dir, os.path.basename(n)), "wb") as f:
                        f.write(z.read(n))
    try:
        for f in glob.glob(os.path.join(tmp, "*")):
            os.remove(f)
        os.rmdir(tmp)
    except OSError:
        pass


def auto_backup(store, settings, cover_dir, folder, keep=5):
    """Geri yüklemeden önce güvenlik kopyası; en yeni `keep` tanesi saklanır."""
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"otomatik_{time.strftime('%Y%m%d_%H%M%S')}.zip")
    create_backup(out, store, settings, cover_dir, include_covers=False)
    olds = sorted(glob.glob(os.path.join(folder, "otomatik_*.zip")))
    for f in olds[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass
    return out

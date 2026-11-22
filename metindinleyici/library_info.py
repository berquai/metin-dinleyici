# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Kütüphane için belge bilgileri ve dosya işlemleri.

Buradaki işlevler arka plan iş parçacığında çalışır; Qt arayüz nesnelerine dokunmazlar.
"""
import os
import re
import subprocess
import sys
import zipfile

from .extract import SUPPORTED, document_id
from .paths import IS_WINDOWS

COVER_WIDTH = 180


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz


def _clean_meta(v):
    v = re.sub(r"\s+", " ", (v or "")).strip()
    # PDF'lerde sık görülen anlamsız başlıklar: "Microsoft Word - tez.docx", "untitled"
    if not v or re.match(r"(?i)^(microsoft word\s*-|untitled|başlıksız|document\d*$)", v):
        return ""
    return v[:200]


def document_info(path, cover_path=None):
    """Dönüş: {"pages", "pages_approx", "author", "meta_title", "cover"}.
    PDF ve EPUB'ın ilk sayfası kapak olarak cover_path'e PNG yazılır."""
    ext = os.path.splitext(path)[1].lower()
    info = {"pages": None, "pages_approx": False, "author": "", "meta_title": "", "cover": False}
    if ext in (".pdf", ".epub"):
        from .pdflock import FITZ_LOCK
        with FITZ_LOCK:          # PDF motoruna aynı anda tek iş parçacığı (bkz. pdflock.py)
            return _pdf_info(path, ext, cover_path, info)
    elif ext == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                if "docProps/app.xml" in names:
                    m = re.search(r"<Pages>(\d+)</Pages>", z.read("docProps/app.xml").decode("utf-8", "replace"))
                    if m:
                        info["pages"] = int(m.group(1))
                        info["pages_approx"] = True           # Word'ün son kaydettiği değer; eskimiş olabilir
                if "docProps/core.xml" in names:
                    core = z.read("docProps/core.xml").decode("utf-8", "replace")
                    a = re.search(r"<dc:creator>(.*?)</dc:creator>", core, re.S)
                    t = re.search(r"<dc:title>(.*?)</dc:title>", core, re.S)
                    info["author"] = _clean_meta(a.group(1) if a else "")
                    info["meta_title"] = _clean_meta(t.group(1) if t else "")
        except (OSError, zipfile.BadZipFile, KeyError):
            pass
    elif ext == ".txt":
        try:
            info["pages"] = max(1, round(os.path.getsize(path) / 1800))   # ~1800 karakter/sayfa
            info["pages_approx"] = True
        except OSError:
            pass
    return info


def _pdf_info(path, ext, cover_path, info):
    fitz = _fitz()
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            return info
        info["pages"] = len(doc)
        info["pages_approx"] = ext == ".epub"        # EPUB'da sayfa sayısı yazı boyutuna bağlıdır
        md = doc.metadata or {}
        info["author"] = _clean_meta(md.get("author"))
        info["meta_title"] = _clean_meta(md.get("title"))
        if cover_path and len(doc):
            page = doc[0]
            zoom = COVER_WIDTH / max(1, page.rect.width)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            os.makedirs(os.path.dirname(cover_path), exist_ok=True)
            pix.save(cover_path)
            info["cover"] = True
    finally:
        doc.close()
    return info


def scan_paths(paths, recursive=True):
    """Dosya ve klasörlerden desteklenen belgeleri bulur → [(yol, belge kimliği)]."""
    found = []
    seen = set()
    for p in paths:
        if os.path.isdir(p):
            walker = os.walk(p) if recursive else [(p, [], os.listdir(p))]
            for root, _, files in walker:
                for f in files:
                    if f.lower().endswith(SUPPORTED) and not f.startswith("~$"):
                        found.append(os.path.join(root, f))
        elif os.path.isfile(p) and p.lower().endswith(SUPPORTED):
            found.append(p)
    out = []
    for f in found:
        f = os.path.abspath(f)
        key = os.path.normcase(f)
        if key in seen:
            continue
        seen.add(key)
        try:
            out.append((f, document_id(f)))
        except OSError:
            pass
    return out


# ───────────────────────────── dosya işlemleri ─────────────────────────────

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def validate_name(stem):
    """Windows'ta geçersiz dosya adlarını yakalar. Dönüş: hata iletisi ya da None."""
    s = stem.strip()
    if not s:
        return "Ad boş olamaz."
    if _BAD_CHARS.search(s):
        return 'Ad şu karakterleri içeremez: < > : " / \\ | ? *'
    if s.rstrip(". ") != s:
        return "Ad nokta ya da boşlukla bitemez."
    if s.upper().split(".")[0] in _RESERVED:
        return f"“{s}” Windows'ta ayrılmış bir addır."
    return None


def move_to_trash(path):
    """Dosyayı Geri Dönüşüm Kutusu'na gönderir (kalıcı silmez). Dönüş: başarılı mı."""
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
        FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + "\0"          # çift sıfırla biten liste
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return rc == 0 and not op.fAnyOperationsAborted and not os.path.exists(path)
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except Exception:
        return False


def reveal_in_folder(path):
    """Dosyayı, bulunduğu klasörde seçili olarak gösterir."""
    if IS_WINDOWS:
        # explorer, "/select," ile yolun tek bir argüman olarak gelmesini bekler
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def human_size(n):
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            v = f"{n:.0f}" if unit in ("B", "KB") else f"{n:.1f}"
            return v.replace(".", ",") + " " + unit
        n /= 1024

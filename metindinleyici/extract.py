# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""PDF / EPUB / DOCX / TXT dosyalarından metin çıkarma ve metin önbelleği."""
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from .paths import IS_WINDOWS, resource_path
from .textproc import norm_para, merge_continuations

CACHE_VERSION = 4
MAX_TEXT_CACHE_FILES = 100        # metin önbelleğindeki en fazla belge
MAX_TEXT_CACHE_MB = 300           # metin önbelleğinin en fazla boyutu
SUPPORTED = (".pdf", ".epub", ".docx", ".txt")


class Cancelled(Exception):
    pass



def find_tesseract():
    # 1) Exe ile birlikte paketlenmiş Tesseract (başka bilgisayarda kurulum gerektirmez)
    exe_name = "tesseract.exe" if IS_WINDOWS else "tesseract"
    bundled = resource_path(os.path.join("tesseract", exe_name))
    if os.path.isfile(bundled):
        return bundled
    # 2) Bilgisayara ayrıca kurulmuş Tesseract
    env = os.environ.get("TESSERACT_CMD")
    candidates = [env] if env else []
    candidates += [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tesseract.exe"),
        r"C:\Program Files\NAPS2\lib\_win64\tesseract.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return shutil.which("tesseract")


def _run_tesseract(tess, args, data=None, timeout=60):
    """Tesseract'ı Türkçe karakterli klasör yollarından etkilenmeyecek biçimde çalıştırır.

    Windows'taki Tesseract dosya yollarını ANSI olarak okur; “Masaüstü”, “Yeni klasör” ya da Türkçe
    kullanıcı adı gibi yollarda dil verisini bulamaz. Bu yüzden Tesseract kendi klasöründe
    çalıştırılır ve dil verisi göreli yolla (“tessdata”) verilir; görüntü de dosya yerine standart
    girişten aktarılır. Böylece Tesseract'a hiçbir mutlak yol gitmez.
    """
    tdir = os.path.dirname(os.path.abspath(tess))
    cmd, cwd, env = [tess] + list(args), None, None
    if os.path.isdir(os.path.join(tdir, "tessdata")):
        cmd += ["--tessdata-dir", "tessdata"]
        cwd = tdir
        env = {k: v for k, v in os.environ.items() if k.upper() != "TESSDATA_PREFIX"}
    return subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, cwd=cwd, env=env,
                          stdin=None if data is not None else subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def tesseract_langs(tess):
    try:
        out = _run_tesseract(tess, ["--list-langs"], timeout=15).stdout.decode("utf-8", "replace")
        return {l.strip() for l in out.splitlines()[1:] if l.strip()}
    except Exception:
        return set()


def tesseract_lang(tess):
    langs = tesseract_langs(tess)
    if {"tur", "eng"} <= langs:
        return "tur+eng"
    for l in ("tur", "eng"):
        if l in langs:
            return l
    raise RuntimeError("Tesseract kurulu ama Türkçe (tur) ya da İngilizce (eng) dil verisi yok. "
                       "Tesseract kurulumunu tekrar çalıştırıp bu dilleri seçin.")


def ocr_png(tess, png, lang, timeout=180):
    """PNG baytlarını OCR ile metne çevirir."""
    r = _run_tesseract(tess, ["stdin", "stdout", "-l", lang], data=png, timeout=timeout)
    text = r.stdout.decode("utf-8", "replace")
    if r.returncode == 0:
        return text
    # Standart girişi okuyamayan eski bir Tesseract sürümü için yedek yol: geçici dosya
    fd, tmp = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(png)
        r2 = _run_tesseract(tess, [tmp, "stdout", "-l", lang], timeout=timeout)
        if r2.returncode == 0:
            return r2.stdout.decode("utf-8", "replace")
        err = (r2.stderr or r.stderr).decode("utf-8", "replace").strip()
        raise RuntimeError(err.splitlines()[-1] if err else f"Tesseract hata kodu {r2.returncode}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


_PAGENUM = re.compile(r"[\s\-–—|•]*(?:(?:sayfa|page|s\.|p\.)\s*)?(?:\d{1,4}|[ivxlcdm]{1,7})"
                      r"(?:\s*(?:/|of|-|–)\s*\d{1,4})?[\s\-–—|•]*", re.I)
_NOTE_MARK = re.compile(r"\s*[\d*†‡]{1,3}[.,)]?\s*")


def strip_page_furniture(page_blocks, heights):
    """Her sayfanın üst/alt kenarında tekrar eden başlıkları ve sayfa numaralarını atar."""
    n = len(page_blocks)

    def key(t):
        return re.sub(r"\d+", "#", re.sub(r"\s+", " ", t.strip().lower()))

    def edges(blocks, height):
        # Yalnızca sayfanın en üst/alt şeridindeki bloklar başlık/altlık adayıdır.
        if height:
            return {i for i, b in enumerate(blocks) if b["y0"] < height * 0.12 or b["y0"] > height * 0.88}
        order = sorted(range(len(blocks)), key=lambda i: blocks[i]["y0"])
        return set(order[:1] + order[-1:])

    counts = Counter()
    if n >= 4:
        for blocks, h in zip(page_blocks, heights):
            counts.update({key(blocks[i]["text"]) for i in edges(blocks, h) if len(blocks[i]["text"]) < 150})
    thr = max(3, math.ceil(n * 0.3))
    out = []
    for blocks, h in zip(page_blocks, heights):
        e, keep = edges(blocks, h), []
        for i, b in enumerate(blocks):
            t = b["text"].strip()
            if not t:
                continue
            if i in e and (_PAGENUM.fullmatch(t) or (n >= 4 and len(t) < 150 and counts[key(t)] >= thr)):
                continue
            keep.append(b["text"])
        out.append(keep)
    return out


def extract_pdf(path, opts, progress, cancel):
    try:
        import pymupdf as fitz   # yeni paket adı
    except ImportError:
        import fitz              # eski PyMuPDF sürümleri
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            raise RuntimeError("Bu PDF parola korumalı. Önce parolasını kaldırıp tekrar deneyin.")
        flags = getattr(fitz, "TEXTFLAGS_DICT", 0) & ~getattr(fitz, "TEXT_PRESERVE_IMAGES", 0)
        pages, sizes, ocr_needed, n = [], Counter(), [], len(doc)
        for i, page in enumerate(doc):
            if cancel.is_set():
                raise Cancelled()
            d = page.get_text("dict", flags=flags) if flags else page.get_text("dict")
            blocks, chars = [], 0
            for b in d.get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                lines = []
                for ln in b.get("lines", []):
                    spans = [(s.get("text", ""), float(s.get("size", 0)), int(s.get("flags", 0)))
                             for s in ln.get("spans", [])]
                    for t, sz, _ in spans:
                        k = len(t.strip())
                        chars += k
                        sizes[round(sz, 1)] += k
                    lines.append(spans)
                blocks.append({"lines": lines, "y0": b["bbox"][1]})
            try:
                label = page.get_label() or str(i + 1)
            except Exception:
                label = str(i + 1)
            pages.append({"label": label, "blocks": blocks, "height": page.rect.height, "ocr": None})
            if chars < 25 and opts.get("ocr"):
                ocr_needed.append(i)
            progress(int((i + 1) / max(1, n) * 30), f"Metin okunuyor: sayfa {i + 1} / {n}")

        if ocr_needed:
            tess = find_tesseract()
            if not tess:
                raise RuntimeError(
                    "Bu PDF'in bazı sayfaları taranmış görüntü, ama Tesseract OCR bulunamadı.\n\n"
                    "1) README'deki bağlantıdan Tesseract OCR'ı kurun.\n"
                    "2) Kurulumda Turkish (tur) ve English (eng) dil verilerini seçin.\n\n"
                    "İsterseniz OCR seçeneğini kapatıp yalnızca metin katmanı olan sayfaları okuyabilirsiniz.")
            lang = tesseract_lang(tess)
            for j, idx in enumerate(ocr_needed):
                if cancel.is_set():
                    raise Cancelled()
                # Tesseract en iyi ~300 DPI gri tonlamalı görüntüde çalışır.
                pix = doc[idx].get_pixmap(dpi=300, colorspace=fitz.csGRAY, alpha=False)
                try:
                    txt = ocr_png(tess, pix.tobytes("png"), lang)
                except Exception as e:
                    raise RuntimeError(f"OCR çalıştırılamadı (sayfa {idx + 1}).\nAyrıntı: {e}") from e
                pages[idx]["ocr"] = [p for p in re.split(r"\n\s*\n", txt) if p.strip()]
                progress(30 + int((j + 1) / len(ocr_needed) * 70),
                         f"OCR taranıyor: {j + 1} / {len(ocr_needed)} sayfa (belgenin {idx + 1}. sayfası)")
    finally:
        doc.close()

    body = sizes.most_common(1)[0][0] if sizes else 0
    notes = bool(opts.get("skip_notes"))
    page_blocks = []
    for p in pages:
        if p["ocr"] is not None:
            page_blocks.append([{"text": t, "y0": k} for k, t in enumerate(p["ocr"])])
            continue
        items = []
        for b in p["blocks"]:
            total = sum(len(t) for ln in b["lines"] for t, _, _ in ln)
            if not total:
                continue
            avg = sum(sz * len(t) for ln in b["lines"] for t, sz, _ in ln) / total
            raw = "\n".join("".join(t for t, _, _ in ln) for ln in b["lines"])
            items.append({"lines": b["lines"], "y0": b["y0"], "avg": avg, "raw": raw})
        # Dipnotlar: sayfanın alt yarısında, gövde metinden küçük puntolu bloklar dizisi.
        # (Sayfa ortasındaki küçük puntolu blok alıntılar korunur.)
        note_ids = set()
        if notes and body:
            for it in sorted(items, key=lambda x: x["y0"], reverse=True):
                if _PAGENUM.fullmatch(it["raw"].strip()):
                    continue
                if it["avg"] < body * 0.9 and it["y0"] > p["height"] * 0.45:
                    note_ids.add(id(it))
                else:
                    break
        blocks = []
        for it in items:
            if id(it) in note_ids:
                continue
            lines = []
            for ln in it["lines"]:
                parts = []
                for t, sz, fl in ln:
                    # Gövde içindeki üst simge dipnot numaraları (…yapılmıştır.¹²)
                    if notes and body and (fl & 1 or sz < body * 0.8) and _NOTE_MARK.fullmatch(t):
                        continue
                    parts.append(t)
                lines.append("".join(parts))
            blocks.append({"text": "\n".join(lines), "y0": it["y0"]})
        page_blocks.append(blocks)

    if opts.get("strip_headers"):
        heights = [None if p["ocr"] is not None else p["height"] for p in pages]
        texts = strip_page_furniture(page_blocks, heights)
    else:
        texts = [[b["text"] for b in blocks if b["text"].strip()] for blocks in page_blocks]

    sections = []
    for p, blocks in zip(pages, texts):
        paras = [q for q in (norm_para(t, notes) for t in blocks) if q]
        sections.append((f"Sayfa {p['label']}", paras))
    return merge_continuations(sections)


_BLOCK_TAGS = ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "tr",
               "dd", "dt", "figcaption", "section", "article", "td", "th"]


def extract_epub(path, opts, progress, cancel):
    from ebooklib import epub, ITEM_DOCUMENT
    from bs4 import BeautifulSoup
    try:
        book = epub.read_epub(path, options={"ignore_ncx": True})
    except TypeError:
        book = epub.read_epub(path)
    notes = bool(opts.get("skip_notes"))
    note_attr = re.compile(r"noteref|footnote|endnote|rearnote")
    spine = [s[0] if isinstance(s, (tuple, list)) else s for s in book.spine]
    sections, k = [], 0
    for n, idref in enumerate(spine):
        if cancel.is_set():
            raise Cancelled()
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for node in soup(["script", "style", "nav", "head"]):
            node.decompose()
        if notes:
            for node in soup.find_all(attrs={"epub:type": note_attr}):
                node.decompose()
            for node in soup.find_all(attrs={"role": re.compile(r"doc-(noteref|footnote|endnote)")}):
                node.decompose()
            for node in soup.find_all("sup"):
                node.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for tag in soup.find_all(_BLOCK_TAGS):
            tag.insert_before("\n\n")
            tag.insert_after("\n\n")
        paras = [q for q in (norm_para(p, notes) for p in re.split(r"\n\s*\n", soup.get_text())) if q]
        if paras:
            k += 1
            h = soup.find(["h1", "h2", "h3"])
            title = norm_para(h.get_text(" ")) if h else ""
            sections.append((title[:70] if title else f"Bölüm {k}", paras))
        progress(int((n + 1) / max(1, len(spine)) * 100))
    return sections


def extract_docx(path, opts, progress, cancel):
    try:
        import docx
    except ImportError as e:
        raise RuntimeError("Word dosyaları için gerekli paket eksik:\npy -m pip install python-docx") from e
    d = docx.Document(path)
    sections, label, paras = [], "Başlangıç", []
    for p in d.paragraphs:
        t = norm_para(p.text)
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if style.startswith(("heading", "başlık")) or style == "title":
            if paras:
                sections.append((label, paras))
            label, paras = t[:70], [t]
        else:
            paras.append(t)
    if paras:
        sections.append((label, paras))
    progress(100)
    return sections


def extract_txt(path, opts, progress, cancel):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1254", "latin-1"):   # cp1254: eski Türkçe Windows kodlaması
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = [q for q in (norm_para(p, opts.get("skip_notes")) for p in re.split(r"\n\s*\n", text)) if q]
    progress(100)
    return [("Metin", paras)]


EXTRACTORS = {".pdf": extract_pdf, ".epub": extract_epub, ".docx": extract_docx, ".txt": extract_txt}


def prune_text_cache(cache_dir, max_files=MAX_TEXT_CACHE_FILES, max_mb=MAX_TEXT_CACHE_MB):
    """En uzun süredir kullanılmayan önbellek dosyalarını, sınırlar aşılınca siler (LRU)."""
    try:
        files = sorted(Path(cache_dir).glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return
    total, limit = 0, max_mb * 1024 * 1024
    for k, f in enumerate(files):
        try:
            total += f.stat().st_size
            if k >= max_files or total > limit:
                f.unlink()
        except OSError:
            pass


def cleanup_stale_temp_dirs(max_age_hours=12):
    """Program çöker ya da elektrik kesilirse geride kalan eski geçici ses klasörlerini siler."""
    now = time.time()
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "metin_dinleyici_*")):
        try:
            if now - os.path.getmtime(d) > max_age_hours * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def document_id(path, sample=256 * 1024):
    """İçeriğe dayalı belge kimliği: dosyanın boyutu ile baş ve son kısmının özeti.
    Dosya yeniden adlandırılsa ya da taşınsa da kimlik değişmez; böylece kaldığınız yer,
    (ileride) alıntılar ve notlar dosya adına değil belgenin kendisine bağlı kalır."""
    size = os.path.getsize(path)
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(sample))
        if size > sample * 2:
            f.seek(-sample, os.SEEK_END)
            h.update(f.read(sample))
    return h.hexdigest()[:20]


def load_document(path, opts, progress, cancel, cache_dir):
    """Dönüş: (bölümler, önbellekten mi geldi, belge kimliği)."""
    ext = Path(path).suffix.lower()
    if ext not in EXTRACTORS:
        raise RuntimeError(f"Desteklenmeyen dosya türü: {ext}")
    doc_id = document_id(path)
    key_src = f"{doc_id}|{ext}|{sorted(opts.items())}|{CACHE_VERSION}"
    cpath = Path(cache_dir) / (hashlib.sha1(key_src.encode("utf-8")).hexdigest() + ".json") if cache_dir else None
    if cpath and cpath.exists():
        try:
            data = json.loads(cpath.read_text(encoding="utf-8"))
            try:
                os.utime(cpath)          # "son kullanılma" zamanını tazele: budamada en sona kalsın
            except OSError:
                pass
            progress(100)
            return [(lbl, paras) for lbl, paras in data["sections"]], True, doc_id
        except Exception:
            pass
    sections = EXTRACTORS[ext](path, opts, progress, cancel)
    if cpath:
        try:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps({"sections": sections}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        prune_text_cache(cache_dir)
    return sections, False, doc_id

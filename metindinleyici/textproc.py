# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Metin temizleme, cümle bölme ve görüntülenecek belgenin kurulması."""
import re
import unicodedata
from dataclasses import dataclass


_LOWER = "a-zçğıöşüâîû"
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad]")
_SUPERSCRIPT_NOTES = re.compile(r"[\u00b9\u00b2\u00b3\u2070-\u2079]+")


def norm_para(text, skip_notes=False):
    """Bir paragrafı seslendirmeye hazırlar: satır sonu tirelerini birleştirir, boşlukları sadeleştirir."""
    if skip_notes:
        text = _SUPERSCRIPT_NOTES.sub("", text)          # ¹ ² ³ gibi dipnot işaretleri
    text = re.sub(r"\u00ad\s*\n\s*", "", text)           # yumuşak tire + satır sonu
    text = unicodedata.normalize("NFKC", text)           # ﬁ → fi gibi bitişik harfleri çözer
    text = _CTRL.sub("", text)
    text = re.sub(rf"(?<=[{_LOWER}])-[ \t]*\n\s*(?=[{_LOWER}])", "", text)   # kal-\nkınma → kalkınma
    text = re.sub(r"(?<=\w)-[ \t]*\n\s*(?=[A-ZÇĞİÖŞÜ0-9])", "-", text)      # Ordu-\nGiresun → Ordu-Giresun
    return re.sub(r"\s+", " ", text).strip()


ABBREVIATIONS = {
    "dr", "prof", "doç", "yrd", "öğr", "gör", "arş", "bkz", "bk", "krş", "karş", "vb", "vd", "vs",
    "s", "ss", "c", "cilt", "sy", "no", "nr", "yy", "yay", "haz", "çev", "ed", "eds", "ör", "örn",
    "st", "mr", "mrs", "ms", "vol", "pp", "p", "cf", "e.g", "i.e", "fig", "şek", "tab", "ibid",
    "op", "cit", "age", "agm", "a.g.e", "a.g.m", "a.y", "m.ö", "m.s", "hz", "ca", "jr", "sr",
    "inc", "ltd", "şti", "a.ş", "md", "mad", "fık", "bşk", "gen", "kur", "alb", "yzb", "mah", "cad", "sok",
}
_BOUNDARY = re.compile(r"([.!?…]+[\"”’»)\]]*)(\s+)(?=[\"“‘'«(\[]?[A-ZÇĞİÖŞÜÂÎÛ0-9])")
_ROMAN = re.compile(r"[IVXLCDM]+")
_INNER_DOTS = re.compile(r"(?:\w\.)+\w")


_REF_WORDS = {"s", "ss", "c", "no", "nr", "sy", "p", "pp", "vol", "cilt", "md", "mad", "madde", "sayfa"}


def _no_split(word, prev=""):
    w = word.lstrip("([\"“‘'«")
    if not w:
        return False
    low = w.lower()
    if w.isdigit() and prev.lower().rstrip(".") in _REF_WORDS:
        return False                                     # "s. 45. Sonra…" → sayfa atfı, burada cümle biter
    return (
        low in ABBREVIATIONS
        or (len(w) == 1 and w.isalpha())                 # baş harfler: M. Kemal
        or (w.isdigit() and len(w) <= 3)                 # sıra sayıları: 1. Dünya Savaşı, 19. yüzyıl
        or bool(_ROMAN.fullmatch(w))                     # II. Abdülhamid, XIX. yüzyıl
        or bool(_INNER_DOTS.fullmatch(w))                # a.g.e., M.Ö.
    )


def _split_long(para, s, e, limit=450):
    """Çok uzun 'cümleleri' (ör. noktalaması bozuk OCR metni) ; : , noktalarından böler."""
    out = []
    while e - s > limit:
        window = para[s:s + limit]
        sp = max(window.rfind("; "), window.rfind(": "), window.rfind(", "))
        sp = sp + 1 if sp >= 0 else -1
        if sp < limit * 0.4:
            sp = window.rfind(" ")
        if sp <= 0:
            break
        out.append((s, s + sp))
        s = s + sp + 1
    out.append((s, e))
    return out


def sentence_spans(para):
    """Paragraf içindeki cümlelerin (başlangıç, bitiş) konumlarını döndürür."""
    spans, start = [], 0
    for m in _BOUNDARY.finditer(para):
        punct = m.group(1)
        if punct.startswith(".") and not punct.startswith(".."):
            tok = re.search(r"(\S+)\s*(\S*)$", para[start:m.start(1)])
            if tok and _no_split(tok.group(2) or tok.group(1), tok.group(1) if tok.group(2) else ""):
                continue
        spans.extend(_split_long(para, start, m.end(1)))
        start = m.end(2)
    if start < len(para):
        spans.extend(_split_long(para, start, len(para)))
    return spans


@dataclass
class Sentence:
    text: str
    start: int      # QTextDocument konumu (UTF-16 birimi)
    end: int
    section: int


def u16(s):
    # Qt metin konumlarını UTF-16 birimiyle sayar; Python ise kod noktasıyla.
    return len(s.encode("utf-16-le")) // 2


_SPEAKABLE = re.compile(r"[^\W\d_]")


def build_document(sections):
    """[(etiket, [paragraflar])] → (görüntülenecek metin, cümleler, içindekiler)."""
    parts, pos, sentences, toc = [], 0, [], []
    for label, paras in sections:
        if not paras:
            continue
        sec = len(toc)
        first = len(sentences)
        header = f"— {label} —"
        parts += [header, "\n\n"]
        pos += u16(header) + 2
        for para in paras:
            for s, e in sentence_spans(para):
                txt = para[s:e].strip()
                if not _SPEAKABLE.search(txt):
                    continue
                sentences.append(Sentence(txt, pos + u16(para[:s]), pos + u16(para[:e]), sec))
            parts += [para, "\n\n"]
            pos += u16(para) + 2
        toc.append((label, first if len(sentences) > first else None))
    return "".join(parts), sentences, toc


_TERMINAL = tuple('.!?…:;"”»)]')


def merge_continuations(sections):
    """Sayfa ya da blok sınırında yarıda kalan cümleleri birleştirir (küçük harfle devam ediyorsa)."""
    out, last_list = [], None
    for label, paras in sections:
        cur = []
        out.append((label, cur))
        for p in paras:
            if last_list and last_list[-1] and p and not last_list[-1].endswith(_TERMINAL) and p[0].islower():
                prev = last_list[-1]
                if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha():
                    last_list[-1] = prev[:-1] + p
                else:
                    last_list[-1] = prev + " " + p
            else:
                cur.append(p)
                last_list = cur
    return out


def anchor_of(text):
    """Bir cümleyi, cümle numaraları kaysa da yeniden bulmaya yarayan kısa iz."""
    return re.sub(r"\s+", " ", text).strip()[:80]


def resolve_anchor(sentences, index, anchor, window=400):
    """Kayıtlı konumdaki cümle izle uyuşmuyorsa (dipnot seçeneği değişti, metin düzeltildi…)
    izi önce yakında, sonra tüm belgede arar. Bulamazsa kayıtlı numarayı sınırlar içinde döndürür."""
    n = len(sentences)
    if not n:
        return 0
    index = min(max(0, index or 0), n - 1)
    if not anchor:
        return index
    if anchor_of(sentences[index].text) == anchor:
        return index
    for d in range(1, window + 1):
        for k in (index - d, index + d):
            if 0 <= k < n and anchor_of(sentences[k].text) == anchor:
                return k
    for k, s in enumerate(sentences):
        if anchor_of(s.text).startswith(anchor[:40]):
            return k
    return index


_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?|\d+")


def word_count(text):
    return len(_WORD.findall(text))


_HEADER = re.compile(r"^— (.+) —$")


def parse_display(text):
    """build_document'in ürettiği görüntü metnini (elle düzeltilmiş hâliyle) yeniden bölümlere çevirir.
    '— Sayfa 3 —' satırları bölüm başlığıdır; boş satırla ayrılmış bloklar paragraftır.
    Paragraf içine tek Enter ile konan satır sonları boşluğa dönüşür."""
    sections, cur = [], None
    for block in re.split(r"\n[ \t ]*\n", text.replace("\r", "").replace(" ", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        m = _HEADER.match(lines[0].strip())
        if m:
            cur = (m.group(1), [])
            sections.append(cur)
            lines = lines[1:]
            if not lines:
                continue
        if cur is None:
            cur = ("Başlangıç", [])
            sections.append(cur)
        para = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if para:
            cur[1].append(para)
    return [(lbl, paras) for lbl, paras in sections]


def locate_anchor(sentences, index, anchor, window=400):
    """resolve_anchor gibi, ama iz bulunamazsa None döndürür (işaret yanlış cümleye konmasın)."""
    n = len(sentences)
    if not n or not anchor:
        return None
    index = min(max(0, index or 0), n - 1)
    if anchor_of(sentences[index].text) == anchor:
        return index
    for d in range(1, window + 1):
        for k in (index - d, index + d):
            if 0 <= k < n and anchor_of(sentences[k].text) == anchor:
                return k
    for k, s in enumerate(sentences):
        if anchor_of(s.text) == anchor:
            return k
    return None

# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Alıntılar, notlar, vurgular: etiketler, künye biçimleri ve dışa aktarma.

Ayrım: alıntı kaynakta yazandır; not kullanıcının kendi yazdığıdır (bir cümleye iliştirilir);
vurgu metinde renklendirilen cümledir.
"""
import csv
import os
import re
from datetime import datetime

KIND_QUOTE, KIND_NOTE, KIND_HIGHLIGHT = "quote", "note", "highlight"
KIND_NAMES = {KIND_QUOTE: "Alıntı", KIND_NOTE: "Not", KIND_HIGHLIGHT: "Vurgu"}

STYLE_CHICAGO, STYLE_APA, STYLE_PLAIN = "chicago", "apa", "plain"
STYLES = [(STYLE_CHICAGO, "Chicago (dipnot)"), (STYLE_APA, "APA 7"), (STYLE_PLAIN, "Yalın (Yazar, Eser, s.)")]

# ───────────────────────────── etiketler ─────────────────────────────

_TAG = re.compile(r"#([^\W_][\w\-]*)", re.UNICODE)


def tr_lower(s):
    """Türkçe küçük harf: I → ı, İ → i (Python'un lower()'ı İ'yi 'i̇' yapar)."""
    return s.replace("I", "ı").replace("İ", "i").lower()


def parse_tags(text):
    """'#köycülük, 1930lar  #Tek_Parti' → ['köycülük', '1930lar', 'tek_parti']"""
    out = []
    for part in re.split(r"[\s,;]+", text or ""):
        t = tr_lower(part.strip().lstrip("#").strip())
        t = re.sub(r"[^\w\-]", "", t)
        if t and t not in out:
            out.append(t)
    return out


def hashtags_in(text):
    """Not metnine yazılmış #etiketleri bulur."""
    return [tr_lower(m.group(1)) for m in _TAG.finditer(text or "")]


def split_query(q):
    """Arama: '#köycülük enstitü #1940lar' → (['köycülük', '1940lar'], 'enstitü')"""
    tags, words = [], []
    for part in (q or "").split():
        if part.startswith("#") and len(part) > 1:
            tags.append(tr_lower(part[1:]))
        else:
            words.append(part)
    return tags, " ".join(words)


def matches(row_text, row_tags, tags, words):
    """Etiketlerin hepsi (ön ek eşleşmesi) ve aranan kelimeler bulunmalı."""
    rt = row_tags or []
    for t in tags:
        if not any(x.startswith(t) for x in rt):
            return False
    if words:
        hay = tr_lower(row_text)
        return all(tr_lower(w) in hay for w in words.split())
    return True


# ───────────────────────────── künye ─────────────────────────────

def page_number(label, offset=0):
    """Bölüm etiketinden basılı sayfa: 'Sayfa 59' ya da '59' → 59 + fark; 'iv' gibi etiketler olduğu gibi."""
    lab = re.sub(r"^\s*(sayfa|page|s\.)\s*", "", label or "", flags=re.I).strip()
    if not lab:
        return ""
    if lab.isdigit():
        n = int(lab) + int(offset or 0)
        return str(n) if n > 0 else ""          # farkla sıfıra/eksiye düşen ön sayfalar: yanlış sayfa vermeyelim
    if re.fullmatch(r"[ivxlcdmIVXLCDM]+", lab) or re.fullmatch(r"\d+[-–]\d+", lab):
        return lab
    return ""                                    # 'Bölüm 3' gibi etiketler sayfa değildir


def _authors(author):
    parts = [a.strip() for a in re.split(r";|\s+ve\s+|\s*&\s*", author or "") if a.strip()]
    return parts


def _surname(name):
    bits = name.replace(",", " ").split()
    return bits[-1] if bits else name


def _initials(name):
    bits = name.split()
    return " ".join(b[0] + "." for b in bits[:-1] if b)


def doc_title(row):
    return row["custom_title"] or row["doc_title"] or os.path.splitext(os.path.basename(row["path"] or ""))[0]


def citation(row, style, page=""):
    """Dönüş: [(metin, italik mi)] parçaları; Word'de eser adı italik yazılır."""
    title = doc_title(row)
    authors = _authors(row["author"])
    year, pub, city = (row["year"] or "").strip(), (row["publisher"] or "").strip(), (row["city"] or "").strip()
    if style == STYLE_APA:
        if authors:
            names = [_surname(a) for a in authors]
            who = names[0] if len(names) == 1 else (" ve ".join(names) if len(names) == 2 else names[0] + " vd.")
        else:
            who = title
        return [(f"({who}, {year or 't.y.'}" + (f", s. {page}" if page else "") + ")", False)]
    if style == STYLE_PLAIN:
        runs = []
        if authors:
            runs.append((", ".join(authors) + ", ", False))
        runs.append((title, False))
        if page:
            runs.append((f", s. {page}", False))
        return runs
    # Chicago dipnot: Yazar, Eser (Şehir: Yayınevi, Yıl), sayfa.
    runs = []
    if authors:
        runs.append(((" ve ".join(authors) if len(authors) <= 3 else authors[0] + " vd.") + ", ", False))
    runs.append((title, True))
    pubinfo = ", ".join(x for x in (f"{city}: {pub}" if city and pub else (pub or city), year) if x)
    if pubinfo:
        runs.append((f" ({pubinfo})", False))
    runs.append((f", {page}." if page else ".", False))
    return runs


def reference(row, style):
    """Kaynakça girdisi (belgeye göre gruplamada başlık olarak)."""
    title = doc_title(row)
    authors = _authors(row["author"])
    year, pub, city = (row["year"] or "").strip(), (row["publisher"] or "").strip(), (row["city"] or "").strip()
    if style == STYLE_APA:
        who = ", ".join(f"{_surname(a)}, {_initials(a)}".rstrip(", ") for a in authors) if authors else ""
        runs = [(f"{who} " if who else "", False), (f"({year or 't.y.'}). ", False), (title, True), (".", False)]
        if pub:
            runs.append((f" {pub}.", False))
        return runs
    if style == STYLE_PLAIN:
        return [((", ".join(authors) + ", ") if authors else "", False), (title, False)]
    who = ""
    if authors:
        first = authors[0].split()
        who = (f"{first[-1]}, {' '.join(first[:-1])}" if len(first) > 1 else authors[0])
        if len(authors) > 1:
            who += ", " + ", ".join(authors[1:])
        who = who.rstrip(".") + ". "             # "Kemal H." → çift nokta olmasın
    tail = ", ".join(x for x in (f"{city}: {pub}" if city and pub else (pub or city), year) if x)
    runs = [(who, False), (title, True), (". " if tail else ".", False)]
    if tail:
        runs.append((tail + ".", False))
    return runs


def runs_text(runs, md=False):
    return "".join((f"*{t}*" if md and it and t else t) for t, it in runs)


# ───────────────────────────── dışa aktarma ─────────────────────────────

def build_blocks(rows, style, group="doc", include_notes=True, include_tags=True):
    """Satırları belge ya da etikete göre gruplanmış bloklara çevirir: [(tür, parçalar)]
    tür: 'h' başlık, 'p' paragraf, 'meta' künye/etiket satırı, 'sep' ayraç."""
    blocks = []

    def entry(r):
        page = page_number(r["page_label"], r["page_offset"])
        kind = r["kind"]
        tags = (r["tags"] or "").split()
        if kind == KIND_NOTE:
            blocks.append(("p", [("Not:", True), (" " + (r["note"] or ""), False)]))
            blocks.append(("meta", [("Bağlam: “" + r["text"] + "” ", False)] + citation(r, style, page)))
        else:
            body = [("Vurgu:", True), (" ", False)] if kind == KIND_HIGHLIGHT else []
            body.append(("“" + r["text"] + "”", False))
            if style == STYLE_APA:
                body += [(" ", False)] + citation(r, style, page)
            blocks.append(("p", body))
            if style != STYLE_APA:
                blocks.append(("meta", citation(r, style, page)))
            if include_notes and r["note"]:
                blocks.append(("meta", [("Notum:", True), (" " + r["note"], False)]))
        if include_tags and tags:
            blocks.append(("meta", [(" ".join("#" + t for t in tags), False)]))
        blocks.append(("sep", []))

    if group == "doc":
        seen = []
        by = {}
        for r in rows:
            if r["doc_id"] not in by:
                seen.append(r["doc_id"]); by[r["doc_id"]] = []
            by[r["doc_id"]].append(r)
        for d in seen:
            blocks.append(("h", reference(by[d][0], style)))
            for r in by[d]:
                entry(r)
    elif group == "tag":
        by, order = {}, []
        for r in rows:
            for t in ((r["tags"] or "").split() or ["(etiketsiz)"]):
                if t not in by:
                    by[t] = []; order.append(t)
                by[t].append(r)
        for t in sorted(order, key=lambda x: (x == "(etiketsiz)", tr_lower(x))):
            blocks.append(("h", [("#" + t if t != "(etiketsiz)" else t, False)]))
            for r in by[t]:
                entry(r)
    else:
        for r in rows:
            entry(r)
    return blocks


def write_export(path, rows, style, group, include_notes=True, include_tags=True, title="Alıntılar ve notlar"):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return _write_csv(path, rows, style)
    blocks = build_blocks(rows, style, group, include_notes, include_tags)
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    if ext == ".docx":
        return _write_docx(path, blocks, title, stamp)
    md = ext == ".md"
    lines = [f"# {title}" if md else title, "", f"_{stamp} · Metin Dinleyici_" if md else f"{stamp} · Metin Dinleyici", ""]
    for kind, runs in blocks:
        if kind == "h":
            lines += ["", ("## " if md else "") + runs_text(runs, md), ""] + ([] if md else ["-" * 40])
        elif kind == "p":
            lines.append(runs_text(runs, md))
        elif kind == "meta":
            t = runs_text(runs, md)
            lines.append(f"> {t}" if md else f"    {t}")
        elif kind == "sep":
            lines.append("")
    with open(path, "w", encoding="utf-8-sig" if ext == ".txt" else "utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return path


def _write_docx(path, blocks, title, stamp):
    import docx
    from docx.shared import Pt, RGBColor
    d = docx.Document()
    d.add_heading(title, level=0)
    p = d.add_paragraph(f"{stamp} · Metin Dinleyici")
    p.runs[0].font.size = Pt(9)
    for kind, runs in blocks:
        if kind == "h":
            h = d.add_heading(level=2)
            for t, it in runs:
                h.add_run(t).italic = it
        elif kind in ("p", "meta"):
            par = d.add_paragraph()
            for t, it in runs:
                r = par.add_run(t)
                r.italic = it
                if kind == "meta":
                    r.font.size = Pt(9.5)
                    r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            if kind == "meta":
                par.paragraph_format.left_indent = Pt(18)
                par.paragraph_format.space_after = Pt(2)
        elif kind == "sep":
            d.add_paragraph().paragraph_format.space_after = Pt(2)
    d.save(path)
    return path


def _write_csv(path, rows, style):
    # utf-8-sig: Excel Türkçe karakterleri ancak BOM varsa doğru açar; ayraç ';' (Türkçe Excel varsayılanı)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Tür", "Metin", "Not", "Etiketler", "Belge", "Yazar", "Yıl", "Sayfa", "Künye", "Tarih"])
        for r in rows:
            page = page_number(r["page_label"], r["page_offset"])
            w.writerow([KIND_NAMES.get(r["kind"], r["kind"]), r["text"], r["note"],
                        " ".join("#" + t for t in (r["tags"] or "").split()), doc_title(r), r["author"],
                        r["year"], page, runs_text(citation(r, style, page)),
                        datetime.fromtimestamp(r["created_at"] or 0).strftime("%d.%m.%Y %H:%M")])
    return path

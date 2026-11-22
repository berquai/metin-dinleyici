# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Paket öz-sınaması: MetinDinleyici.exe --self-test rapor.txt

Paketlenmiş programda eksik modül, eksik veri dosyası ya da çalışmayan Tesseract olup olmadığını
pencere açmadan denetler. Paketleme betiği derlemeden sonra bunu çalıştırır; böylece başka bir
bilgisayarda ancak kullanılırken ortaya çıkacak bir eksik daha derleme sırasında yakalanır.
"""
import io
import os
import sys
import traceback


def _checks():
    from .paths import resource_path

    def resources():
        missing = [f for f in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "metin_dinleyici.ico")
                   if not os.path.isfile(resource_path(f))]
        assert not missing, "eksik dosya: " + ", ".join(missing)
        return "lisans dosyaları ve simge yerinde"

    def qt():
        from PySide6 import QtMultimedia, QtWidgets  # noqa: F401
        from . import mainwindow  # noqa: F401  (bütün arayüz modüllerini zincirleme yükler)
        return "PySide6 ve arayüz modülleri"

    def pdf():
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Metin Dinleyici deneme", fontsize=14)
        data = doc.tobytes()
        text = fitz.open(stream=data, filetype="pdf")[0].get_text()
        assert "Dinleyici" in text, text
        return f"PyMuPDF {fitz.VersionBind}"

    def docx_():
        import docx
        d = docx.Document()                       # varsayılan şablon pakette olmalı
        d.add_paragraph("deneme")
        d.save(io.BytesIO())
        return "python-docx (Word dışa aktarma şablonu)"

    def epub():
        import bs4  # noqa: F401
        import ebooklib  # noqa: F401
        from ebooklib import epub as _  # noqa: F401
        return "EbookLib ve BeautifulSoup"

    def edge():
        import certifi
        import edge_tts  # noqa: F401
        assert os.path.isfile(certifi.where()), "sertifika dosyası yok: " + certifi.where()
        return "edge-tts ve TLS sertifikaları"

    def ocr():
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        from .extract import find_tesseract, ocr_png, tesseract_lang
        tess = find_tesseract()
        assert tess, "Tesseract bulunamadı"
        bundled = os.path.normcase(os.path.abspath(tess)).startswith(
            os.path.normcase(os.path.abspath(resource_path("tesseract"))))
        lang = tesseract_lang(tess)
        assert "tur" in lang, f"Türkçe dil verisi yok (bulunan: {lang})"
        doc = fitz.open()
        page = doc.new_page(width=500, height=120)
        page.insert_text((20, 70), "Metin Dinleyici", fontsize=36)
        pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY)
        got = ocr_png(tess, pix.tobytes("png"), lang)
        assert "Dinleyici" in got, f"OCR sonucu beklenmedik: {got!r}"
        where = "paketin içindeki" if bundled else "BİLGİSAYARA KURULU (paket dışı!)"
        return f"{where} Tesseract, diller: {lang}, OCR: {got.strip()!r}"

    def python():
        v = sys.version_info
        assert v[:2] < (3, 15), (f"Python {v.major}.{v.minor} ile derlenmiş: bu sürümün tembel içe aktarma düzeni "
                                 "paketlenmiş programda çevrimiçi sesleri bozabiliyor. Python 3.13 ile derleyin.")
        return f"Python {v.major}.{v.minor}.{v.micro}"

    return [("Python", python), ("Dosyalar", resources), ("Arayüz", qt), ("PDF", pdf), ("Word", docx_), ("EPUB", epub),
            ("Çevrimiçi ses", edge), ("OCR", ocr)]


def run(report_path=None):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines, ok = [], True
    for name, fn in _checks():
        try:
            lines.append(f"[TAMAM] {name}: {fn()}")
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"[HATA]  {name}: {e}\n" + "".join(traceback.format_exception(e)[-3:]))
    lines.append("SONUÇ: " + ("BAŞARILI" if ok else "BAŞARISIZ"))
    text = "\n".join(lines)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))

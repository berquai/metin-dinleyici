# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""PyMuPDF için ortak kilit.

PyMuPDF (MuPDF) iş parçacığı güvenli değildir: belgeleri aynı anda birden çok iş parçacığından kullanmak,
Python'un altındaki C katmanında programı uyarısız çökertebilir. Programda PDF motoru üç ayrı yerde
arka planda çalışır (metin çıkarma, kütüphane kapakları, orijinal belge görünümü). Bu kilit, motora aynı
anda yalnızca birinin girmesini sağlar. Uzun işler (ör. Tesseract OCR) kilit dışında yapılır; böylece
kilit yalnızca kısa PDF çağrılarında tutulur ve arayüz akıcı kalır.
"""
import threading

FITZ_LOCK = threading.RLock()


def fitz():
    try:
        import pymupdf as m
    except ImportError:
        import fitz as m
    return m

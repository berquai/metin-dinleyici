# Metin Dinleyici — PDF / EPUB / DOCX / TXT sesli okuyucu
# Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Bu program özgür yazılımdır: GNU Affero Genel Kamu Lisansı'nın 3. sürümü ya da (tercihinize
# göre) daha sonraki bir sürümü ve NOTICE dosyasındaki ek koşullar çerçevesinde yeniden
# dağıtabilir ve/veya değiştirebilirsiniz. Program HİÇBİR GARANTİ OLMAKSIZIN dağıtılmaktadır.
# Ayrıntılar için LICENSE ve NOTICE dosyalarına bakın.
"""Çalıştırma: py main.py   ·   Paketleme talimatı için README.md dosyasına bakın."""
import sys

if hasattr(sys, "set_lazy_imports_filter"):
    # Python 3.15+ "tembel içe aktarma" (lazy import): modüller ilk kullanıldıkları anda yüklenir. Paketlenmiş
    # programda arka plan iş parçacıklarıyla birlikte "'lazy_import' object is not callable" hatasına yol açtı.
    # Filtre her içe aktarmayı hemen (eskisi gibi) yaptırır; bu satır başka hiçbir içe aktarmadan önce durmalı.
    sys.set_lazy_imports_filter(lambda *args: False)

from metindinleyici.app import main  # noqa: E402

if __name__ == "__main__":
    main()

# Üçüncü taraf bileşenler

Metin Dinleyici aşağıdaki açık kaynak bileşenleri kullanır. Her bileşen kendi lisansına tabidir;
bu dosya bileşenlerin lisans koşullarını değiştirmez. Paketlenmiş (exe) dağıtımlarda bu
bileşenlerin lisans metinleri, PyInstaller'ın kopyaladığı `*.dist-info` klasörlerinde bulunur.

| Bileşen | Kullanım amacı | Lisans |
|---|---|---|
| Qt 6 / PySide6 | Arayüz, ses oynatma | LGPL-3.0 (GPL-2.0/3.0 seçenekleriyle) |
| FFmpeg (Qt Multimedia içinde) | Ses dosyalarını çözme | LGPL-2.1 veya sonrası |
| PyMuPDF / MuPDF (Artifex) | PDF okuma ve metin çıkarma | AGPL-3.0 (ya da Artifex ticari lisansı) |
| EbookLib | EPUB okuma | AGPL-3.0 veya sonrası |
| Beautiful Soup 4 | EPUB içindeki HTML'i ayrıştırma | MIT |
| python-docx | Word (DOCX) okuma | MIT |
| edge-tts | Çevrimiçi sinir ağı sesleri | LGPL-3.0 |
| aiohttp | edge-tts ağ bağlantısı | Apache-2.0 ve MIT |
| Tesseract OCR | Taranmış sayfalarda karakter tanıma | Apache-2.0 |

## Not

PyMuPDF ve EbookLib AGPL lisanslı olduğundan, bunlarla birlikte dağıtılan Metin Dinleyici de
AGPL-3.0-or-later lisansıyla dağıtılmaktadır. Programı alan herkes, karşılık beklenmeksizin
kaynak koduna erişebilmelidir (bkz. README.md, “Dağıtım” bölümü).

Çevrimiçi sesler Microsoft'un Edge tarayıcısı için sunduğu sesli okuma hizmetini kullanır;
bu hizmetin kullanımı Microsoft'un koşullarına tabidir ve hizmet önceden haber verilmeksizin
değişebilir.

Kurulum dosyası Inno Setup (JRSoftware, Inno Setup lisansı) ile, program paketi PyInstaller (GPL-2.0, paketlenen programlara serbestçe izin veren istisnayla) ile hazırlanır.

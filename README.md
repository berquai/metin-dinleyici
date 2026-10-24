# Metin Dinleyici

PDF, EPUB, DOCX ve TXT belgeleri için sesli okuma uygulaması.

Copyright © 2026 Berkay Çelik · <berkcel@gmail.com>
Lisans: **AGPL-3.0-or-later**, yazar atfını koruyan ek koşullarla (bkz. `NOTICE`).

## İndirme

Hazır kurulum dosyasını [Releases](https://github.com/berquai/metin-dinleyici/releases) sayfasından indirebilirsiniz. Kaynak koddan çalıştırmak ya da kendiniz paketlemek için aşağıdaki bölümlere bakın.

## Çalıştırma

```
py -m pip install -r requirements.txt
py main.py
```

## Kurulum dosyası hazırlama (Windows)

`packaging\build.bat` dosyasına çift tıklayın. Betik her şeyi kendisi yapar:

1. `.build\venv` içine ayrı bir Python ortamı kurar; sisteminizdeki Python paketlerine dokunmaz.
2. Bilgisayardaki Tesseract OCR'ı bulur (yoksa `winget` ile kurar) ve Türkçe + İngilizce dil
   verisiyle birlikte pakete koyar. Türkçe veri eksikse indirir.
3. PyInstaller ile `dist\MetinDinleyici` klasörünü oluşturur ve kaynak kodu
   `kaynak_kod` alt klasörüne ekler (AGPL gereği).
4. Paketlenmiş programı **öz-sınamadan** geçirir: arayüz, PDF, Word, EPUB, çevrimiçi ses
   sertifikaları ve paketin içindeki Tesseract ile gerçek bir OCR denemesi. Bir eksik varsa durur.
5. Inno Setup'ı bulur (yoksa `winget` ile kurar) ve `dist` klasörüne şunları koyar:
   - `MetinDinleyici_<sürüm>_Kurulum.exe` — dağıtacağınız dosya
   - `MetinDinleyici_<sürüm>_tasinabilir.zip` — kurulumsuz, klasörden çalışan sürüm

Gereken tek şey Python 3.10 veya üstü ve internet bağlantısıdır (ilk derleme 5–10 dakika sürer).
Baştan derlemek için: `packaging\build.bat -Clean`.

Kurulum dosyasının özellikleri:
- Yönetici izni istemez; kullanıcının kendi klasörüne kurulur (kurum bilgisayarlarında da çalışır).
- Başlat menüsü ve isteğe bağlı masaüstü kısayolu; PDF/EPUB/DOCX/TXT için sağ tık › Birlikte aç.
- Güncellemede eski sürümün üstüne kurulur; kütüphane, alıntılar ve ayarlar korunur.
- Kaldırırken kişisel verilerin de silinip silinmeyeceğini sorar (varsayılan: hayır).

Paketlenmiş programın denetimi elle de yapılabilir:
`dist\MetinDinleyici\MetinDinleyici.exe --self-test rapor.txt`

Simge: proje kökünde `metin_dinleyici.ico` varsa o, yoksa `packaging\metin_dinleyici.ico` kullanılır.

## Dağıtım (AGPL yükümlülüğü)

Programı başkasına verdiğinizde (eşinize, danışmanınıza, iş arkadaşlarınıza) kaynak kodunu
da erişilebilir kılmanız gerekir. En kolay iki yol:

1. Kaynak kodu GitHub'da herkese açık bir depoda tutun (`SOURCE_URL`, `metindinleyici/__init__.py`).
2. Ya da exe ile birlikte kaynak kodun zip dosyasını da verin.

## Veriler nerede durur?

- Ayarlar: Windows kayıt defteri (`HKCU\Software\MetinDinleyici`)
- Belge veritabanı (kaldığınız yer, ileride kütüphane ve alıntılar):
  `%LOCALAPPDATA%\MetinDinleyici\Metin Dinleyici\metin_dinleyici.db`
- Metin önbelleği: aynı klasörde `metin_onbellek`

Belgeler dosya yoluna değil içeriğe göre tanınır; dosyayı yeniden adlandırsanız ya da başka
klasöre taşısanız da kaldığınız yer korunur. Sürüm 3'te kaydedilmiş konumlar, belge ilk kez
açıldığında veritabanına taşınır.

## Proje yapısı

```
main.py                    başlatıcı
metindinleyici/
  __init__.py              ad, sürüm, yazar, lisans bilgileri
  app.py                   QApplication kurulumu
  mainwindow.py            ana pencere
  dialogs.py               Hakkında, lisans, metin görünümü, özel tema, işlem sonu penceresi
  themes.py                renk temaları
  textproc.py              metin temizleme, cümle bölme
  extract.py               PDF/EPUB/DOCX/TXT'den metin çıkarma, önbellek
  tts.py                   Edge ve Windows SAPI seslendirme
  store.py                 SQLite veri katmanı
  pronounce.py             telaffuz kuralları, Türkçe sayı ve Roma rakamı okuma
  pron_dialog.py           telaffuz sözlüğü pencereleri
  library.py               kütüphane görünümü ve yönetimi
  library_info.py          sayfa/yazar bilgisi, kapaklar, Geri Dönüşüm Kutusu
  annotations.py           etiketler, künye biçimleri, dışa aktarma
  quotes.py                alıntılar paneli ve pencereleri
  docview.py               orijinal belge paneli
  maintenance.py           temizlik ve sıfırlama
  audio_export.py          ses dışa aktarma modülü
  backup.py                yedekleme ve geri yükleme
  widgets.py               katlanabilir bölüm, denetim çubuğu, uyarlanır yerleşim
  power.py                 uyku modunu engelleme
  guide.py                 kullanım kılavuzu (F1)
  selftest.py              paketlenmiş program için öz-sınama
packaging/
  build.bat, build.ps1     kurulum dosyası hazırlama betiği
  MetinDinleyici.spec      PyInstaller derleme tarifi
  installer.iss            Inno Setup kurulum betiği
  kurulum_bilgi.txt        kurulumda gösterilen bilgi metni
  metin_dinleyici.ico      program simgesi
```

## Sürüm notları

### 4.7.2
- OCR, Türkçe karakter içeren klasörlerde (Masaüstü, “Yeni klasör”, Türkçe kullanıcı adları) de çalışıyor:
  Tesseract'a artık hiçbir mutlak yol gitmiyor; dil verisi göreli yolla, görüntü standart girişten veriliyor.
- pytesseract ve Pillow bağımlılıkları kaldırıldı (Tesseract doğrudan çağrılıyor).

### 4.7.1
- Tek tıkla kurulum dosyası hazırlama (`packaging\build.bat`): Tesseract OCR ve Türkçe dil verisi pakete dahil,
  yönetici izni gerektirmeyen kurulum, sağ tık › Birlikte aç, paketlenmiş program için öz-sınama (`--self-test`).
- Program simgesi.

### 4.7
- **Kullanım kılavuzu** (Yardım › Kullanım Kılavuzu, F1): 15 bölüm, içindekiler listesi, arama ve tema renkleriyle
  uyumlu görünüm. Yardım › Klavye Kısayolları doğrudan kısayol tablosunu açar; karşılama ekranında da kılavuz düğmesi var.
- **Tam ekranda ince ilerleme çizgisi**: tam ekran ve odaklanma modunda ekranın altında temaya uygun renkte, 3 piksellik
  ilerleme çizgisi. Görünüm › Tam Ekranda İnce İlerleme Çizgisi ile açılıp kapanır.

### 4.6
- **Ses dışa aktarma modülü** (Dosya › Ses Olarak Dışa Aktar, Ctrl+E). Okumayı engellemeden arka planda çalışır.
  - Kapsam: belgenin tamamı, okunan yerden sona, sayfa/bölüm aralığı, cümle aralığı.
  - Bölme: tek dosya, her sayfa/bölüm, her N sayfa/bölüm, yaklaşık her N dakika.
  - Bu kayda özel ses, hız ve cümle arası es; istenirse sayfa/bölüm adlarının okunması.
  - MP3'lere ID3 etiketi (başlık, yazar, albüm, parça no) yazılır; telefonda kitap gibi sıralanır.
    Çok dosyada .m3u8 çalma listesi oluşturulur.
  - Süre, dosya sayısı ve boyut tahmini (ölçülen kelime/dk hızına göre); üç parça paralel üretilir.
  - Çevrimdışı Windows sesleriyle WAV olarak kaydeder. İptal edilince yarım dosya bırakmaz.
- **Yedekleme ve geri yükleme** (Dosya menüsü): kütüphane, kaldığınız yerler, alıntılar, sözlük, düzeltmeler,
  künyeler, ayarlar ve kapaklar tek bir .zip dosyasına. Geri yüklemeden önce mevcut durumun güvenlik kopyası
  kendiliğinden alınır (son beşi saklanır).
- **Eksik Dosyaları Bul** (Kütüphane › ＋ Ekle): yeri değişmiş ya da başka bilgisayardan gelen belgeleri bir
  klasörde içeriklerine göre arar; dosya adı değişmiş olsa da bulur.
- Kütüphanede kitabın üzerinden sürükleyince kitap taşınır (okuma alanına bırakınca açılır), boşluktan
  sürükleyince seçim kutusu çizilir.
- Varsayılan yerleşim: solda Kütüphane | Orijinal Belge | Alıntılar sekmeleri; kütüphane dört kapak genişliğinde;
  okuma düğmeleri daha iri.
- Düzeltme: dar pencerede kontrol panelinin alta inip yukarı çıkarak gidip gelmesi.
- Düzeltme: tema uygulandıktan sonra kontrol paneli içeriğinin sağdan taşması.

### 4.5
- **Orijinal belge paneli** (üst çubukta “Orijinal”, F7): PDF ve EPUB sayfaları metnin yanında.
  - İlk / önceki / sonraki / son sayfa, sayfa numarasına atlama, PageUp/PageDown/Home/End.
  - Genişliğe ya da sayfaya sığdır, %50–%300; Ctrl+tekerlek ile yakınlaştırma. Sayfa sonunda tekerlekle
    kaydırmaya devam edince sonraki sayfaya geçer.
  - ⌖ okunan cümlenin sayfasına gider; “İzle” açıkken okuma ilerledikçe sayfa kendiliğinden değişir.
  - ⋯ menüsü: sayfayı resim olarak kaydet (150/300/600 dpi, PNG/JPEG), panoya kopyala, döndür,
    belgeyi varsayılan uygulamada aç.
  - Belge belleğe okunarak açılır; panel açıkken de dosya yeniden adlandırılabilir ya da silinebilir.
- Kütüphane varsayılan olarak açık ve üç kapak genişliğinde; kontrol paneli pencereyle orantılı büyür/küçülür
  (oranı kenarını sürükleyerek değiştirebilirsiniz). Kütüphanedeki ⛶ düğmesi kütüphaneyi tam ekrana alır (Esc).
- Yükleme ve OCR için belirgin “■ Taramayı Durdur” düğmesi ve sayfa sayfa ilerleme; Esc de durdurur.
- Menü ayraçları koyu temalarda da görünür.
- İşlem sonrası pencerelerde “Dosyayı Aç” ve “Klasörde Göster” (ses kaydı, alıntı ve sözlük dışa aktarma,
  sayfa resmi).
- **Temizlik ve Sıfırlama** (Dosya menüsü): önbellek, kapaklar, geçici sesler, kütüphane dışı kayıtlar,
  alıntılar, düzeltmeler, sözlük ve ayarlar ayrı ayrı seçilerek temizlenir; kapladıkları yer gösterilir.
  Kütüphanedeki belgeler korunur.

### 4.4
- **Alıntılar, notlar, vurgular** (Alıntılar menüsü; sağ tık menüsünde de).
  - M: okunan cümleyi (ya da seçili metni) alıntılar · N: cümleye not ekler · V: vurgular / vurguyu kaldırır ·
    Shift+M: son kaydın notunu ve etiketlerini düzenler · C: okunan cümleyi kopyalar.
  - Alıntı kaynakta yazandır; not sizin yazdığınızdır. Metinde alıntılar düz, notlar noktalı çizgiyle,
    vurgular renkle işaretlenir; işaretin üzerine gelince not ve etiketler görünür.
- **Alıntılar ve Notlar paneli** (F8; solda kütüphaneyle sekme olarak).
  - Bu belge / tüm belgeler; alıntı, not, vurgu süzgeci; belgeye ya da etikete göre gruplama.
  - Etiketler: #köycülük gibi; notun içine yazılan #etiketler de eklenir. Aramada “#köy enstitü” hem etikete
    hem metne göre süzer. “# Etiketler” düğmesi tüm etiketleri kullanım sayısıyla listeler.
  - Çoklu seçim; sağ tık: İlgili Sayfaya Git (başka belgedeyse onu açar), Ses Dosyası Oluştur, Kopyala,
    Künyeyle Kopyala, Düzenle, Dışa Aktar, Sil.
- **Dışa aktarma**: seçili / görünen / bu belge / tümü; Word, Markdown, düz metin, CSV (Excel);
  Chicago dipnot, APA 7 ya da yalın künye; belgeye ya da etikete göre gruplama.
- **Belge bilgileri (künye)** (Ctrl+I; kütüphanede “Bilgileri Düzenle”): eser adı, yazar, yıl, yayınevi,
  şehir ve basılı sayfa için sayfa farkı.
- Açılır listeler artık kutunun altından açılıyor (Fusion stilinin üstten açma davranışı kapatıldı).
- Kütüphane ayrı sayfa yerine taşınabilir bir panel: kütüphane, metin ve kontroller yan yana.
- Menüler ayraçlarla gruplandı; yeni Alıntılar menüsü.

### 4.3
- **Kütüphane** (üst çubukta “Kütüphane” düğmesi, Ctrl+L).
  - Kapak görünümü (PDF ve EPUB'da ilk sayfa, diğerlerinde türüne göre renkli kapak) ve liste görünümü.
  - Liste sütunları: ad, yazar, tür, sayfa, boyut, ilerleme, son açılma, eklenme, klasör.
    EPUB, DOCX ve TXT'de sayfa sayısı yaklaşıktır (≈).
  - Ad, yazar ve klasöre göre arama; ada (Türkçe alfabe sırasıyla), yazara, tarihe, boyuta, sayfa
    sayısına, ilerlemeye ve türe göre sıralama.
  - Belge ve klasör ekleme (alt klasörler dahil), kütüphaneye sürükleyip bırakma. Açılan belgeler
    kendiliğinden eklenir.
  - Sağ tık: Aç, Klasörde Göster, Yeniden Adlandır, Bilgileri Düzenle (görünen ad, yazar), Kapağı Yenile,
    Kütüphaneden Kaldır (dosya silinmez), Diskten Sil (Geri Dönüşüm Kutusu'na). Çoklu seçim desteklenir.
  - Yeri değişmiş dosyalar soluk görünür; “Dosyayı Bul” ile yeni yeri gösterilince kaldığınız yer korunur.
- Üst çubuğa “✎ Düzenle” düğmesi.
- Sağ tık › Metni Düzelt menüsünde seçime bağlı işlemler hep görünür; koşul eksikse ne gerektiği yazar.

### 4.2
- Karşılama ekranı: belge açık değilken metin alanında yönerge, “Dosya Aç” düğmesi ve son açılan üç belge.
- **Telaffuz sözlüğü** (Düzen › Telaffuz Sözlüğü, Ctrl+Shift+L). Kurallar yalnızca okunuşu değiştirir.
  - Kelime kuralları (bkz. → bakınız; “AB” kuralı “ABD”nin içinde çalışmaz) ve bağlama bağlı
    düzenli ifade kuralları.
  - Okunuşta sayı ve Roma rakamı dönüştürme: `{yazıyla:1}`, `{sıra:1}`, `{roma:1}`, `{romasıra:1}`.
  - İstisnalar, büyük/küçük harf duyarlılığı, tüm belgeler ya da yalnızca bu belge kapsamı, sıralama.
  - Canlı ön izleme, “Dinle” düğmesi, kuralın açık belgede uygulandığı yerlerin listesi.
  - İçe/dışa aktarma (JSON) ve akademik metinler için başlangıç kuralları
    (s. 125, ss. 12-15, 250 s., 19. yy., XIX. yüzyıl, II. Abdülhamid, bkz., vb., a.g.e., TBMM…).
- **Metin üzerinde elle düzeltme**
  - Sağ tık › Metni Düzelt: cümleyi, paragrafı ya da seçili metni silme; seçili metni tüm belgeden silme.
  - Düzen › Metni Düzenle (Ctrl+Shift+E): metni doğrudan düzeltme; Ctrl+S kaydeder, Esc vazgeçer.
  - Ctrl+Z son düzeltmeyi geri alır; Düzen › Elle Yapılan Tüm Düzeltmeleri Kaldır özgün metne döner.
  - Düzeltmeler dosyaya değil belgeye bağlı saklanır, belge yeniden açılınca kullanılır.
    Belge seçenekleri değiştiyse hangisinin kullanılacağı sorulur.
- Sağ tık menüsü: Buradan Oku, cümleyi/seçimi kopyala, seçili kelime için telaffuz kuralı ekle.

### 4.1.1
- Düzeltme: ayrı pencereye alınıp yeniden takılan panelin bir kısmı kesiliyor ve yatay kaydırma
  çubuğu çıkıyordu. Panelin düzeni artık görünür genişliğine göre kuruluyor ve panel, içeriğinin
  sığabileceği genişlikten daha dar olamıyor.
- Dar pencere sınırı sabit değil, metin alanı ile panelin gerçek en küçük genişliklerinden hesaplanıyor.

### 4.1
- Kontrol paneli dört kenardan birine sürüklenebiliyor ya da ayrı pencereye alınabiliyor
  (Görünüm › Panel Konumu; F9 ile gizle/göster). Konumu ve boyutu bir sonraki açılışta korunuyor.
- “Ses ve Hız” ile “Belge Seçenekleri” katlanabilir bölümler oldu.
- Panel alta ya da üste alındığında bölümler yan yana sütunlara diziliyor.
- Dar pencere desteği: pencere daralınca yan panel kendiliğinden alta iniyor, genişleyince yerine dönüyor.
- Tam ekran (F11): yalnızca metin kalır. Enter menü ve paneli açıp kapatır, Esc çıkar.
  Fare hareket edince Önceki / Tekrar Oku / Oku-Duraklat / Sonraki / Tam Ekrandan Çık çubuğu belirir.
  Metin okunaklı genişlikte ortalanmış bir sütuna alınır, fare imleci kısa süre sonra gizlenir.
- Odaklanma modu (F12): pencere içinde yalnızca metin; okunan cümle ekranın ortasında durur,
  çevresindeki metin soluklaşır, kayma yumuşaktır.
- Tam ekranda ekran kararmaz, bilgisayar uyku moduna geçmez.
- Okuma › Okurken Uyku Modunu Engelle (varsayılan açık): sesli okuma sürerken bilgisayar uyumaz.
- Seçili tema tam ekran, odaklanma ve denetim çubuğunda da geçerli.
- Menü çubuğu gizliyken de tüm klavye kısayolları çalışıyor.

### 4.0
- Kod modüllere ayrıldı; kalıcı veriler için SQLite veritabanı eklendi.
- Belgeler içerik kimliğiyle tanınıyor; yeniden adlandırma ve taşıma kaldığınız yeri bozmuyor.
- Kaldığınız yer, cümle numarası kaysa bile (ör. dipnot seçeneği değişince) cümle iziyle bulunuyor.
- Oku/Duraklat ile Cümleyi Baştan Oku düğmelerinin yeri değişti.
- Okunan cümlenin altına “Kopyala” düğmesi (kısayol: C).
- “Belgeyi Kapat” düğmesi (Ctrl+W).
- Yedi hazır tema ve özel tema (Görünüm › Tema; Ctrl+T sonraki tema).
- Metin görünümü: yazı tipi, boyut, satır aralığı, paragraf aralığı, kenar boşluğu (Ctrl+Shift+T).
- “Okunan metni takip et” kutusu; okurken elle kaydırınca takip kendiliğinden kapanır, Ctrl+J okunan yere döner.
- Okuma hızı kelime/dakika olarak da gösteriliyor (ölçüme dayalı).
- “Her zaman üstte” seçeneği (Ctrl+Shift+A).
- AGPL-3.0-or-later lisansı, yazar atfını koruyan ek koşullar ve yeni Hakkında penceresi.

## Yol haritası

İyileştirme listesinin bütün aşamaları (0–8) tamamlandı. Yeni istekler buraya eklenecek.

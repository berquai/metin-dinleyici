# Metin Dinleyici — Copyright (C) 2026 Berkay Çelik <berkcel@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-or-later  (ek koşullar için NOTICE dosyasına bakın)
"""Kullanım kılavuzu: içindekiler, arama ve bölümler (Yardım › Kullanım Kılavuzu, F1)."""
import html
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import APP_NAME, APP_VERSION

# (kimlik, başlık, HTML gövde)
SECTIONS = [
("baslarken", "1. Başlarken", """
<p>Metin Dinleyici, PDF, EPUB, DOCX ve TXT belgelerini sesli okur. Okunan cümle metinde renkle işaretlenir;
kaldığınız yer, alıntılarınız ve notlarınız belgeye bağlı olarak saklanır.</p>
<h3>Belge açmak</h3>
<ul>
<li><b>Dosya Aç</b> düğmesi ya da <kbd>Ctrl+O</kbd>.</li>
<li>Dosyayı Windows Gezgini'nden ya da kütüphaneden metin alanına <b>sürükleyip bırakmak</b>.</li>
<li>Kütüphanede bir kitaba çift tıklamak.</li>
<li>Belge açık değilken metin alanında görünen karşılama ekranındaki son açılan belgeler.</li>
</ul>
<p>Belgeyi daha önce açtıysanız <b>kaldığınız yerden</b> devam eder. Dosyayı yeniden adlandırsanız ya da başka
klasöre taşısanız da bu bilgi kaybolmaz; belgeler adına değil içeriğine göre tanınır.</p>
<h3>Ekranın bölümleri</h3>
<ul>
<li><b>Solda</b>: Kütüphane, Orijinal Belge ve Alıntılar sekmeleri.</li>
<li><b>Ortada</b>: okunan metin. Okunan cümle vurgulanır.</li>
<li><b>Sağda</b>: Kontrol Paneli (okuma düğmeleri, ses, hız, belge seçenekleri).</li>
</ul>
<p>Bütün paneller başlıklarından tutulup başka kenara sürüklenebilir, ayrı pencereye alınabilir ya da
kapatılabilir. Kapattığınız paneli <b>Görünüm</b> menüsünden geri açarsınız.</p>
"""),
("okuma", "2. Okuma", """
<h3>Temel denetimler</h3>
<ul>
<li><b>▶ Oku / ⏸ Duraklat</b>: <kbd>Boşluk</kbd>. Duraklatınca aynı yerden devam eder.</li>
<li><b>■ Durdur</b>: <kbd>Esc</kbd>.</li>
<li><b>◀ Önceki / Sonraki ▶</b> cümle: <kbd>←</kbd> / <kbd>→</kbd> ya da <kbd>Ctrl+←</kbd> / <kbd>Ctrl+→</kbd>.</li>
<li><b>↺ Cümleyi Baştan Oku</b>: <kbd>Ctrl+R</kbd>.</li>
<li><b>Bir cümleye çift tıklamak</b> okumayı oradan başlatır. Sağ tık › <b>Buradan Oku</b> da aynı işi yapar.</li>
<li><b>Cümle</b> kutusuna numara yazıp Enter'a basmak ya da <b>Git</b> listesinden sayfa/bölüm seçmek o yere götürür.</li>
<li><b>Metinde ara</b>: <kbd>Ctrl+F</kbd>. Enter ya da <b>▼</b> (<kbd>F3</kbd>) sonraki, <kbd>Shift+Enter</kbd> ya da
<b>▲</b> (<kbd>Shift+F3</kbd>) önceki eşleşmeye gider. <b>⇤ Baştan Ara</b> aranan ifadenin metindeki ilk geçtiği
yere gider. Kutunun yanındaki sayı kaçıncı sonuçta olduğunuzu gösterir.</li>
</ul>
<h3>Okunan metni takip etmek</h3>
<p><b>Okunan metni takip et</b> kutusu açıkken metin, okunan cümle görünür kalacak şekilde kayar
(<kbd>Ctrl+Shift+F</kbd>). Okuma sırasında metni elle kaydırırsanız takip kendiliğinden kapanır; böylece önceki bir
yere bakarken uygulama sizi geri çekmez. Okunan yere dönmek için <b>Okunan yere git</b> ya da <kbd>Ctrl+J</kbd>.</p>
<h3>Ses ve hız</h3>
<ul>
<li><b>Çevrimiçi (Edge sinir ağı sesleri)</b>: doğal sesler; internet gerekir. “Çok dilli” sesler Türkçe ve
İngilizceyi aynı metinde okuyabilir.</li>
<li><b>Çevrimdışı (Windows sesleri)</b>: bilgisayarda kurulu sesler; internet gerekmez. Türkçe ses için Windows
Ayarlar › Zaman ve dil › Konuşma bölümünden Türkçe ses paketi eklenebilir.</li>
<li><b>Hız</b>: %50–%200. Altında <b>dakikada okunan kelime</b> görünür; bu bir tahmin değil, o ses için okudukça
ölçülen değerdir ve cümle arası esleri de içerir.</li>
<li><b>Cümle arası es</b>: cümleler arasındaki sessizlik (yalnızca çevrimiçi seslerde).</li>
<li><b>Cümle bitince otomatik devam et</b>: kapalıysa her cümlenin sonunda durur.</li>
</ul>
<p><b>Okuma › Okurken Uyku Modunu Engelle</b> açıkken (varsayılan) sesli okuma sürerken bilgisayar uyku moduna
geçmez.</p>
"""),
("gorunum", "3. Görünüm, tam ekran ve odaklanma", """
<h3>Temalar ve metin görünümü</h3>
<ul>
<li>Üst çubuktaki tema listesi ya da <b>Görünüm › Tema</b>: Kâğıt, Sepya, Bulut, Gece, Gece Mavisi, Orman,
Yüksek Kontrast. <kbd>Ctrl+T</kbd> sıradaki temaya geçer.</li>
<li><b>Özel tema</b>: Görünüm › Tema › Özel Temayı Düzenle. Arka plan, yazı, panel, okunan cümle ve vurgu renklerini
kendiniz seçersiniz; değişiklik anında görünür.</li>
<li><b>Metin Görünümü</b> (<kbd>Ctrl+Shift+T</kbd>): yazı tipi, boyut, satır aralığı, paragraf aralığı, kenar
boşluğu. Yazıyı hızlıca büyütmek/küçültmek için <kbd>Ctrl++</kbd> / <kbd>Ctrl+-</kbd>.</li>
</ul>
<h3>Tam ekran (F11)</h3>
<p>Ekranda yalnızca metin kalır; metin okunaklı genişlikte, ortalanmış bir sütuna alınır. Seçili tema burada da
geçerlidir ve tam ekrandayken ekran kararmaz, bilgisayar uyumaz.</p>
<ul>
<li><kbd>Enter</kbd>: menüyü ve panelleri açar/kapatır.</li>
<li><kbd>Esc</kbd>: tam ekrandan çıkar.</li>
<li>Fareyi oynatınca alt tarafta Önceki · Tekrar Oku · Oku/Duraklat · Sonraki · Tam Ekrandan Çık düğmeleri belirir;
fare durunca kaybolur.</li>
<li>Ekranın en altındaki <b>ince çizgi</b> belgede ne kadar ilerlediğinizi gösterir. Görünüm › Tam Ekranda İnce
İlerleme Çizgisi ile açılıp kapanır.</li>
</ul>
<h3>Odaklanma modu (F12)</h3>
<p>Pencere içinde yalnızca metin kalır; okunan cümle ekranın ortasında durur, çevresindeki metin soluklaşır.
Uzun okumalarda gözü yormamak için. <kbd>Esc</kbd> ile çıkılır.</p>
<h3>Paneller</h3>
<ul>
<li>Üst çubuktaki düğmeler ya da kısayollar panelleri açıp kapatır: Kütüphane Paneli <kbd>Ctrl+L</kbd>,
Orijinal Belge Paneli <kbd>F7</kbd>, Alıntılar ve Notlar Paneli <kbd>F8</kbd>, Kontrol Paneli <kbd>F9</kbd>.</li>
<li>Panellerin yeri, boyutu ve açık/kapalı durumu bir sonraki açılışta aynen geri gelir
(<b>Görünüm › Panel Yerleşimi › Panel Yerleşimini Hatırla</b>). Varsayılan düzene dönmek için
<b>Görünüm › Panel Yerleşimi › Panel Düzenini Varsayılana Sıfırla</b>.</li>
<li>Kontrol Paneli <b>Görünüm › Kontrol Panelinin Konumu</b> ile dört kenardan birine ya da ayrı pencereye
alınabilir. Alta veya üste alınınca bölümleri yan yana dizilir.</li>
<li>Kontrol Paneli pencere genişliğiyle orantılı büyür/küçülür; kenarını sürükleyerek oranı değiştirirsiniz.</li>
<li>Pencere çok daralınca yan panel kendiliğinden alta iner, genişleyince yerine döner.</li>
<li><b>Her Zaman Üstte</b> (<kbd>Ctrl+Shift+A</kbd>): pencere diğer programların üstünde kalır.</li>
</ul>
"""),
("kutuphane", "4. Kütüphane", """
<p>Açtığınız her belge kütüphaneye kendiliğinden eklenir. Ayrıca <b>＋ Ekle</b> menüsünden tek tek belge ya da
alt klasörleriyle birlikte bütün bir klasör ekleyebilir, dosyaları kütüphaneye sürükleyip bırakabilirsiniz.</p>
<h3>Görünümler, arama ve sıralama</h3>
<ul>
<li><b>Kapak</b> görünümü: PDF ve EPUB'da ilk sayfa kapak olarak gösterilir; DOCX ve TXT'ye türüne göre renkli
kapak çizilir. <b>Liste</b> görünümü: ad, yazar, tür, sayfa, boyut, ilerleme, son açılma, eklenme, klasör.</li>
<li>EPUB, DOCX ve TXT'de sayfa sayısının başındaki <b>≈</b> değerin yaklaşık olduğunu gösterir.</li>
<li>Arama kutusu ad, yazar ve klasör adında arar.</li>
<li>Sıralama: ad (Türkçe alfabe sırasıyla), yazar, son açılma, eklenme, boyut, sayfa sayısı, ilerleme, tür.
Liste görünümünde sütun başlığına tıklamak da sıralar.</li>
<li><b>⛶</b> düğmesi kütüphaneyi tam ekrana alır; liste görünümünde bütün sütunlar sığar. <kbd>Esc</kbd> ile döner.</li>
</ul>
<h3>Sürükleme</h3>
<p>Bir kitabın <b>üzerinden</b> sürüklerseniz kitap taşınır: okuma alanına bırakınca açılır, Windows Gezgini'ne
bırakınca dosyanın bir kopyası oluşur. Kitapların arasındaki <b>boşluktan</b> sürüklerseniz birden çok kitabı
seçmek için seçim kutusu çizilir. <kbd>Ctrl</kbd> ve <kbd>Shift</kbd> ile tıklayarak da çoklu seçim yapılır.</p>
<h3>Sağ tık menüsü</h3>
<ul>
<li><b>Aç</b>, <b>Klasörde Göster</b>.</li>
<li><b>Yeniden Adlandır</b>: diskteki dosyanın adını değiştirir; kaldığınız yer, alıntılar ve notlar korunur.</li>
<li><b>Bilgileri Düzenle</b>: görünen ad, yazar, yıl, yayınevi, şehir ve sayfa farkı. Bu bilgiler alıntıları dışa
aktarırken künyede kullanılır (bkz. 6. bölüm).</li>
<li><b>Kapağı ve Bilgileri Yenile</b>.</li>
<li><b>Kütüphaneden Kaldır</b>: dosyayı silmez; belgeyi yeniden açarsanız kaldığınız yerle birlikte geri gelir.</li>
<li><b>Diskten Sil</b>: dosyayı <b>Geri Dönüşüm Kutusu'na</b> gönderir (kalıcı silmez) ve kütüphaneden kaldırır.</li>
</ul>
<h3>Yeri değişen dosyalar</h3>
<p>Dosyası bulunamayan belgeler soluk görünür. Tek bir belge için sağ tık › <b>Dosyayı Bul</b>. Çok sayıda belge
için (ör. yedeği yeni bilgisayara taşıdığınızda) <b>＋ Ekle › Eksik Dosyaları Bul</b> ile belgelerinizin bulunduğu
klasörü taratın: belgeler içeriklerine göre eşleştiği için dosya adları değişmiş olsa da bulunur.</p>
"""),
("orijinal", "5. Orijinal belge paneli", """
<p>PDF ve EPUB belgelerin sayfalarını metnin yanında gösterir (üst çubukta <b>Orijinal Belge Paneli</b>, <kbd>F7</kbd>).
Dinlerken taranmış sayfayı ya da tabloları, resimleri gözle takip etmek için.</p>
<ul>
<li><b>⏮ ◀ ▶ ⏭</b>: ilk, önceki, sonraki, son sayfa. Sayfa numarasını yazıp Enter'a basarak da gidilir.
Panel seçiliyken <kbd>PageUp</kbd>, <kbd>PageDown</kbd>, <kbd>Home</kbd>, <kbd>End</kbd>.</li>
<li>Sayfanın sonunda tekerlekle aşağı kaydırmaya devam edince sonraki sayfaya geçer.</li>
<li>Yakınlaştırma: <b>Genişliğe sığdır</b>, <b>Sayfaya sığdır</b>, %50–%300, <b>−</b> / <b>+</b>,
<kbd>Ctrl+tekerlek</kbd>.</li>
<li><b>⌖</b>: okunan cümlenin sayfasına gider. <b>İzle</b> açıkken okuma ilerledikçe sayfa kendiliğinden değişir.</li>
<li><b>⇆ Eşle</b> (sayfa kalibrasyonu): panel okunan metinden farklı bir sayfa gösteriyorsa, okunan metnin bulunduğu
sayfayı ◀ ▶ ile açıp <b>⇆ Eşle</b>'ye basın. Aradaki fark (ör. “kayma +2”) bu belge için hatırlanır ve sonraki
sayfalara da uygulanır. Elle girmek ya da sıfırlamak için <b>⋯</b> menüsü.</li>
<li><b>⋯</b> menüsü: sayfayı resim olarak kaydet (150 / 300 / 600 dpi, PNG ya da JPEG; tez eki için 300 dpi
yeterlidir), panoya kopyala, döndür, belgeyi varsayılan uygulamada aç.</li>
</ul>
<p>DOCX ve TXT dosyalarında sayfa görünümü yoktur; metinleri zaten okuma alanında olduğu gibi görünür.</p>
"""),
("alintilar", "6. Alıntılar, notlar, vurgular ve künye", """
<p><b>Alıntı</b> kaynakta yazan metindir; <b>not</b> sizin yazdığınızdır ve bir cümleye iliştirilir; <b>vurgu</b>
cümleyi metinde kalıcı olarak renklendirir.</p>
<h3>Kaydetmek</h3>
<ul>
<li><kbd>M</kbd>: okunan cümleyi alıntılar. Fareyle bir metin seçtiyseniz seçimi alıntılar (birkaç cümle de olabilir).</li>
<li><kbd>N</kbd>: okunan cümleye not ekler.</li>
<li><kbd>H</kbd>: okunan cümleyi vurgular (highlight); yeniden basınca vurgu kalkar.</li>
<li><kbd>Shift+M</kbd>: son kaydın notunu ve etiketlerini düzenler. M ile hızlıca alıntılayıp etiketi sonra eklemek için.</li>
<li><kbd>C</kbd>: okunan cümleyi panoya kopyalar.</li>
<li>Aynı işlemler metne sağ tıklayınca da çıkar; sağ tık, tıkladığınız cümleye uygulanır.</li>
</ul>
<p>Metinde alıntılar düz çizgiyle, notlar noktalı çizgiyle, vurgular renkle işaretlenir. İşaretin üzerine gelince
not ve etiketler görünür.</p>
<h3>Etiketler</h3>
<p>Kayda <code>#köycülük #1930lar</code> gibi etiketler ekleyebilirsiniz. Notun içine yazdığınız #etiketler de
kendiliğinden etiket olur. Etiketler Türkçe büyük/küçük harf kurallarına göre eşleşir (#İnkılap = #inkılap).</p>
<h3>Alıntılar ve Notlar paneli (F8)</h3>
<ul>
<li>Bu belge / tüm belgeler; tümü / alıntılar / notlar / vurgular; gruplama yok / belgeye göre / etikete göre.</li>
<li>Arama: <code>#köy enstitü</code> hem etikete (ön ekle: #köy, #köycülük'ü de bulur) hem metne göre süzer.
<b># Etiketler</b> düğmesi bütün etiketleri kullanım sayısıyla listeler.</li>
<li>Çift tık ya da sağ tık › <b>İlgili Sayfaya Git</b>: kayıt başka bir belgedeyse o belgeyi açıp doğru cümleye
götürür.</li>
<li>Sağ tık: Ses Dosyası Oluştur, Kopyala, Künyeyle Kopyala, Düzenle, Dışa Aktar, Sil. <kbd>Ctrl+C</kbd> ve
<kbd>Delete</kbd> da çalışır. Birden çok kayıt seçilebilir.</li>
</ul>
<h3>Künye ve sayfa numarası</h3>
<p><b>Dosya › Belge Bilgileri</b> (<kbd>Ctrl+I</kbd>) ya da kütüphanede <b>Bilgileri Düzenle</b>: eser adı, yazar,
yıl, yayınevi, şehir. Birden çok yazar için adları noktalı virgülle ayırın.</p>
<p><b>Sayfa farkı</b>: basılı sayfa = belgedeki sayfa + fark. Kitabın 1. sayfası PDF'in 15. sayfasıysa fark −14'tür.
PDF'te sayfa etiketleri doğru tanımlıysa fark 0 kalabilir. Farkla sıfıra ya da eksiye düşen ön sayfalarda künyeye
sayfa yazılmaz; yanlış sayfa görmektense hiç görmemek daha iyidir.</p>
<h3>Dışa aktarma (Ctrl+Shift+X)</h3>
<ul>
<li>Kapsam: seçili kayıtlar, listede görünenler, açık belgedeki tümü, bütün belgelerdeki tümü.</li>
<li>Biçim: Word (.docx), Markdown, düz metin, CSV (Excel için; Türkçe karakterler doğru açılır).</li>
<li>Künye: <b>Chicago dipnot</b> (ör. <i>Mehmet İnan, Köy Enstitüleri (Ankara: Gece, 1998), 45.</i>),
<b>APA 7</b> (ör. <i>(İnan, 1998, s. 45)</i>) ya da yalın.</li>
<li>Gruplama: belgeye göre (künyeli başlıklarla), etikete göre ya da yok.</li>
</ul>
"""),
("duzeltme", "7. Metni düzeltmek", """
<p>Taranmış ya da dağınık metinlerde gereksiz kısımları temizleyebilirsiniz. <b>Dosyanızın kendisi hiç
değişmez</b>; düzeltmeler belgeye bağlı olarak saklanır ve belge yeniden açılınca kullanılır.</p>
<ul>
<li>Sağ tık › <b>Metni Düzelt</b>: bu cümleyi sil, bu paragrafı sil, seçili metni sil.</li>
<li><b>Seçili Metni Tüm Belgeden Sil</b>: önce tekrar eden artığı (ör. her sayfada kalan bir başlık) fareyle seçin,
sonra seçimin üzerine sağ tıklayın. Kaç yerden silineceği menüde yazar.</li>
<li><b>✎ Düzenle</b> düğmesi ya da <kbd>Ctrl+Shift+E</kbd>: metni doğrudan düzeltme modu. Boş satır yeni
paragraftır; “— Sayfa N —” satırları sayfa başlığıdır. <kbd>Ctrl+S</kbd> kaydeder, <kbd>Esc</kbd> vazgeçer.</li>
<li><kbd>Ctrl+Z</kbd>: son düzeltmeyi geri alır.</li>
<li><b>Düzen › Elle Yapılan Tüm Düzeltmeleri Kaldır</b>: dosyadan çıkarılan özgün metne döner.</li>
</ul>
<p>Düzeltmeleri yaptıktan sonra belge seçeneklerini (OCR, dipnot, üst/alt bilgi) değiştirirseniz, belge açılırken
düzeltilmiş metni mi yoksa yeni seçeneklerle çıkarılmış metni mi istediğiniz sorulur.</p>
"""),
("telaffuz", "8. Telaffuz sözlüğü", """
<p><b>Düzen › Telaffuz Sözlüğü</b> (<kbd>Ctrl+Shift+L</kbd>). Kurallar yalnızca <b>okunuşu</b> değiştirir; ekrandaki
metin olduğu gibi kalır. İlk açılışta akademik metinler için başlangıç kuralları eklenir (bkz. → bakınız,
s. 125 → sayfa yüz yirmi beş, ss. 12-15, 250 s., 19. yy., XIX. yüzyıl, II. Abdülhamid, vb., a.g.e., TBMM…).</p>
<h3>Kural türleri</h3>
<ul>
<li><b>Kelime ya da ifade</b>: yazılış metinde ayrı bir kelime olarak geçtiğinde okunuşla değiştirilir. “AB” kuralı
“ABD”nin içinde, “Köy” kuralı “Köycülük”ün içinde çalışmaz.</li>
<li><b>Düzenli ifade</b>: bağlama bağlı kalıplar için. Okunuşta şu yer tutucular kullanılabilir:
<code>{1}</code> grubun kendisi, <code>{yazıyla:1}</code> 125 → yüz yirmi beş, <code>{sıra:1}</code> 19 → on
dokuzuncu, <code>{roma:1}</code> XIX → on dokuz, <code>{romasıra:1}</code> II → ikinci.<br>
Örnek: yazılış <code>\\bs\\.\\s*(\\d+)</code>, okunuş <code>sayfa {yazıyla:1}</code>.</li>
</ul>
<h3>Ayrıntılar</h3>
<ul>
<li><b>Sıra önemlidir</b>: kurallar yukarıdan aşağıya uygulanır. Özel kalıpları (ss. 12-15) genel olanlardan
(s. 12) önce koyun; ▲/▼ ile sıralayın.</li>
<li><b>İstisnalar</b>: her satıra bir ifade. Eşleşmenin yakınında (±40 karakter) bu ifadelerden biri geçiyorsa kural
orada uygulanmaz. Ör. “AB → Avrupa Birliği” kuralına istisna: <i>kan grubu</i>.</li>
<li><b>Kapsam</b>: tüm belgeler ya da yalnızca bu belge.</li>
<li><b>Ön izleme ve Dinle</b>: bir cümle yazıp nasıl okunacağını görün ve seçili sesle hemen dinleyin. Sağdaki
liste, seçili kuralın açık belgede uygulandığı yerleri gösterir.</li>
<li>En hızlı yol: okurken kulağınızı tırmalayan kelimeye sağ tıklayıp <b>“… için Telaffuz Kuralı Ekle”</b>.</li>
<li>Sözlüğü <b>İçe/Dışa Aktar</b> ile başka bilgisayara taşıyabilirsiniz (JSON).</li>
</ul>
"""),
("ses", "9. Ses olarak dışa aktarma", """
<p><b>Dosya › Ses Olarak Dışa Aktar</b> (<kbd>Ctrl+E</kbd>). Belgeyi yürüyüşte, yolda dinlemek için ses dosyalarına
dönüştürür. Kayıt arka planda sürer; bu sırada okumaya devam edebilirsiniz.</p>
<ul>
<li><b>Ne seslendirilsin</b>: belgenin tamamı, okunan yerden sona, sayfa/bölüm aralığı, cümle aralığı.</li>
<li><b>Dosyalara bölme</b>: tek dosya, her sayfa/bölüm ayrı dosya, her N sayfada bir dosya, yaklaşık her N
dakikada bir dosya.</li>
<li><b>Ses</b>: bu kayda özel ses, hız ve cümle arası es; istenirse her sayfa/bölüm başında adı da okunur.
Telaffuz sözlüğü kayıtta da uygulanır.</li>
<li><b>Etiketler</b>: MP3'lere başlık, yazar, albüm ve parça numarası yazılır; telefonunuzdaki oynatıcı dosyaları
kitap gibi sırayla gösterir. Birden çok dosyada bir çalma listesi (.m3u8) de oluşturulur.</li>
<li><b>Dosya adı</b>: <code>{belge}</code> albüm adı, <code>{no}</code> parça numarası (01, 02…),
<code>{bölüm}</code> sayfa/bölüm adı.</li>
<li>Başlamadan önce dosya sayısı, süre ve boyut tahmini gösterilir; süre, o ses için ölçülen okuma hızına dayanır.</li>
<li>Çevrimiçi seslerle MP3, çevrimdışı Windows sesleriyle WAV kaydedilir. İptal edince yarım dosya kalmaz.</li>
</ul>
<p>Alıntılar panelinde seçtiğiniz kayıtlardan da sağ tık › <b>Ses Dosyası Oluştur</b> ile tek bir ses dosyası
yapılabilir.</p>
"""),
("secenekler", "10. Belge seçenekleri ve OCR", """
<p>Kontrol panelindeki <b>Belge Seçenekleri</b> metnin dosyadan nasıl çıkarılacağını belirler. Değiştirdikten sonra
belgeyi <b>F5</b> ile yeniden yükleyin.</p>
<ul>
<li><b>Taranmış sayfalar için OCR</b>: metin katmanı olmayan (resim olarak taranmış) sayfaları Tesseract OCR ile
okur. Türkçe ve İngilizce dil verisi gerekir. OCR ilk açılışta zaman alır; sonuç önbelleğe alındığı için ikinci
açılış anında olur.</li>
<li><b>Dipnotları ve dipnot numaralarını atla</b>: sayfa altındaki küçük puntolu dipnotları ve metin içindeki dipnot
numaralarını okumaz.</li>
<li><b>Üst/alt bilgi ve sayfa numaralarını temizle</b>: her sayfada tekrar eden başlıkları ve sayfa numaralarını
atar. Yine de kalan bir artık olursa 7. bölümdeki “Tüm Belgeden Sil”i kullanın.</li>
</ul>
<p><b>Taramayı durdurmak</b>: yükleme ve OCR sırasında ilerleme çubuğunun yanında <b>■ Taramayı Durdur</b> düğmesi
belirir; <kbd>Esc</kbd> de durdurur. Tarama o anda işlediği sayfayı bitirince durur ve belge açılmaz. Yanlışlıkla
taranmış bir kitabı yalnızca metin katmanıyla okumak için OCR seçeneğini kapatıp yeniden açın.</p>
<p>Sayfa sonunda bölünen cümleler birleştirilir; satır sonu tireleri (kal-kınma) düzeltilir; Dr., bkz., s., 19.,
II. gibi kısaltma ve sıra sayılarında cümle bölünmez.</p>
"""),
("yedek", "11. Yedekleme, geri yükleme ve temizlik", """
<h3>Yedekle / Yedekten Geri Yükle (Dosya menüsü)</h3>
<p>Kütüphane, kaldığınız yerler, alıntılar, notlar, etiketler, telaffuz sözlüğü, elle düzeltmeler, künyeler,
ayarlar ve kapaklar tek bir .zip dosyasına yedeklenir. <b>Belgelerin kendisi (PDF, EPUB…) yedeğe girmez</b>;
onları kendi klasörlerinizde ayrıca saklayın.</p>
<p>Geri yüklerken neyin geri geleceğini seçersiniz. Başlamadan önce mevcut durumun bir <b>güvenlik kopyası</b>
kendiliğinden alınır (son beşi saklanır). Ayarları geri yüklediyseniz uygulamayı yeniden başlatın. Yedeği başka
bir bilgisayara taşıdıysanız kütüphanede <b>＋ Ekle › Eksik Dosyaları Bul</b> ile belgelerinizin klasörünü
taratın.</p>
<h3>Temizlik ve Sıfırlama (Dosya menüsü)</h3>
<p>Her kalemin kapladığı yer gösterilir; kütüphanedeki belgeler her durumda korunur.</p>
<ul>
<li>Varsayılan olarak işaretli olanlar yeniden üretilebilir: metin önbelleği, kapaklar, geçici ses dosyaları, son
açılanlar ve hız ölçümleri, veritabanını sıkıştırma.</li>
<li>İşaretsiz gelenler geri getirilemez: kütüphane dışı belgelerin kayıtları, alıntılar, düzeltmeler, telaffuz
sözlüğü, ayarlar. Bunları seçerseniz bir kez daha onay istenir.</li>
</ul>
<p>Önemli bir temizlikten önce yedek almanızı öneririz.</p>
"""),
("kisayollar", "12. Klavye kısayolları", """
<table cellspacing="0" cellpadding="4" width="100%">
<tr><th align="left" colspan="2">Okuma</th></tr>
<tr><td><kbd>Boşluk</kbd></td><td>Oku / Duraklat</td></tr>
<tr><td><kbd>Esc</kbd></td><td>Durdur · tam ekrandan / odaklanmadan / düzenlemeden çık · yüklemeyi durdur</td></tr>
<tr><td><kbd>←</kbd> / <kbd>→</kbd> · <kbd>Ctrl+←</kbd> / <kbd>Ctrl+→</kbd></td><td>Önceki / sonraki cümle</td></tr>
<tr><td><kbd>Ctrl+R</kbd></td><td>Cümleyi baştan oku</td></tr>
<tr><td><kbd>Ctrl+J</kbd></td><td>Okunan yere git</td></tr>
<tr><td><kbd>Ctrl+Shift+F</kbd></td><td>Okunan metni takip et (aç/kapat)</td></tr>
<tr><td><kbd>Ctrl+F</kbd></td><td>Metinde ara</td></tr>
<tr><td><kbd>F3</kbd> / <kbd>Shift+F3</kbd></td><td>Sonraki / önceki arama sonucu</td></tr>
<tr><td><kbd>Ctrl+Shift+F3</kbd></td><td>Baştan ara (ilk geçtiği yer)</td></tr>
<tr><th align="left" colspan="2">Alıntılar</th></tr>
<tr><td><kbd>C</kbd></td><td>Okunan cümleyi kopyala</td></tr>
<tr><td><kbd>M</kbd></td><td>Okunan cümleyi (ya da seçimi) alıntıla</td></tr>
<tr><td><kbd>N</kbd></td><td>Not ekle</td></tr>
<tr><td><kbd>H</kbd></td><td>Vurgula / vurguyu kaldır</td></tr>
<tr><td><kbd>Shift+M</kbd></td><td>Son kaydın notunu ve etiketlerini düzenle</td></tr>
<tr><td><kbd>F8</kbd></td><td>Alıntılar paneli</td></tr>
<tr><td><kbd>Ctrl+Shift+X</kbd></td><td>Alıntıları dışa aktar</td></tr>
<tr><th align="left" colspan="2">Dosya</th></tr>
<tr><td><kbd>Ctrl+O</kbd></td><td>Dosya aç</td></tr>
<tr><td><kbd>Ctrl+W</kbd></td><td>Belgeyi kapat</td></tr>
<tr><td><kbd>Ctrl+E</kbd></td><td>Ses olarak dışa aktar</td></tr>
<tr><td><kbd>Ctrl+I</kbd></td><td>Belge bilgileri (künye)</td></tr>
<tr><td><kbd>F5</kbd></td><td>Seçeneklerle yeniden yükle</td></tr>
<tr><td><kbd>Ctrl+Q</kbd></td><td>Çıkış</td></tr>
<tr><th align="left" colspan="2">Düzen</th></tr>
<tr><td><kbd>Ctrl+Shift+E</kbd></td><td>Metni düzenle</td></tr>
<tr><td><kbd>Ctrl+S</kbd></td><td>Düzenlemeyi kaydet</td></tr>
<tr><td><kbd>Ctrl+Z</kbd></td><td>Son düzeltmeyi geri al</td></tr>
<tr><td><kbd>Ctrl+Shift+L</kbd></td><td>Telaffuz sözlüğü</td></tr>
<tr><th align="left" colspan="2">Görünüm</th></tr>
<tr><td><kbd>F11</kbd></td><td>Tam ekran (içindeyken <kbd>Enter</kbd>: menü ve paneller)</td></tr>
<tr><td><kbd>F12</kbd></td><td>Odaklanma modu</td></tr>
<tr><td><kbd>Ctrl+L</kbd></td><td>Kütüphane paneli</td></tr>
<tr><td><kbd>F7</kbd></td><td>Orijinal belge paneli</td></tr>
<tr><td><kbd>F9</kbd></td><td>Kontrol paneli</td></tr>
<tr><td><kbd>Ctrl+Shift+T</kbd></td><td>Metin görünümü</td></tr>
<tr><td><kbd>Ctrl++</kbd> / <kbd>Ctrl+-</kbd></td><td>Yazıyı büyüt / küçült</td></tr>
<tr><td><kbd>Ctrl+T</kbd></td><td>Sonraki tema</td></tr>
<tr><td><kbd>Ctrl+Shift+A</kbd></td><td>Her zaman üstte</td></tr>
<tr><td><kbd>F1</kbd></td><td>Kullanım kılavuzu</td></tr>
<tr><th align="left" colspan="2">Orijinal belge panelinde</th></tr>
<tr><td><kbd>PageUp</kbd> / <kbd>PageDown</kbd></td><td>Önceki / sonraki sayfa</td></tr>
<tr><td><kbd>Home</kbd> / <kbd>End</kbd></td><td>İlk / son sayfa</td></tr>
<tr><td><kbd>Ctrl+tekerlek</kbd></td><td>Yakınlaştır / uzaklaştır</td></tr>
</table>
<p>Tek harfli kısayollar (C, M, N, H) ve ← / → arama kutusunda ya da düzenleme modunda yazarken devreye girmez.</p>
"""),
("sorunlar", "13. Sık karşılaşılan durumlar", """
<dl>
<dt><b>Ses gelmiyor, “çevrimiçi ses üretilemedi” uyarısı çıkıyor.</b></dt>
<dd>İnternet bağlantısını denetleyin. Kurum ağındaysanız vekil sunucu (proxy) gerekebilir: <code>HTTPS_PROXY</code>
ortam değişkeni tanımlıysa uygulama onu kullanır. Geçici olarak çevrimdışı Windows seslerine geçebilirsiniz.</dd>
<dt><b>“Ahmet” sesi bazen hiç okumuyor.</b></dt>
<dd>Bu ses Microsoft sunucusunda kararsız çalışıyor; sorun uygulamada değil. Emel'i ya da çok dilli erkek
seslerinden birini (William, Andrew, Brian, Florian) deneyin.</dd>
<dt><b>Taranmış bir PDF'te metin çıkmıyor.</b></dt>
<dd>“Taranmış sayfalar için OCR” seçeneğinin açık olduğundan ve Tesseract OCR'ın Türkçe/İngilizce dil verisiyle
kurulu olduğundan emin olun; sonra F5.</dd>
<dt><b>Bazı kelimeler yanlış okunuyor.</b></dt>
<dd>Kelimeye sağ tıklayıp “Telaffuz Kuralı Ekle” (8. bölüm).</dd>
<dt><b>Her sayfada aynı başlık okunuyor.</b></dt>
<dd>“Üst/alt bilgi ve sayfa numaralarını temizle” açık değilse açıp F5; yine kalırsa artığı seçip
“Seçili Metni Tüm Belgeden Sil” (7. bölüm).</dd>
<dt><b>Künyede sayfa numarası kitaptakiyle tutmuyor.</b></dt>
<dd>Belge Bilgileri'nde (<kbd>Ctrl+I</kbd>) sayfa farkını ayarlayın (6. bölüm).</dd>
<dt><b>Kontrol paneli alta indi.</b></dt>
<dd>Pencere üç panele dar gelince panel kendiliğinden alta iner; pencereyi genişletin ya da kütüphaneyi kapatın.</dd>
<dt><b>Panelleri kaybettim.</b></dt>
<dd>Üst çubuktaki panel düğmeleriyle ya da Görünüm menüsünden açın; düzeni toptan geri almak için
Görünüm › Panel Yerleşimi › Panel Düzenini Varsayılana Sıfırla.</dd>
</dl>
"""),
("gizlilik", "14. Veriler ve gizlilik", """
<ul>
<li><b>Çevrimiçi sesler</b>, okunacak metni seslendirilmek üzere Microsoft'un sesli okuma hizmetine gönderir.
Yayımlanmamış ya da gizli bir belgeyi dinlerken bunu göz önünde bulundurun; böyle belgeler için çevrimdışı
Windows seslerini kullanabilirsiniz (metin bilgisayarınızdan çıkmaz).</li>
<li>Metin çıkarma, OCR, kütüphane, alıntılar, notlar ve bütün ayarlar <b>yalnızca bilgisayarınızda</b> tutulur.</li>
<li>Veriler: <code>%LOCALAPPDATA%\\MetinDinleyici\\Metin Dinleyici</code> klasöründe (veritabanı, metin önbelleği,
kapaklar, otomatik güvenlik kopyaları). Ayarlar Windows kayıt defterinde.</li>
</ul>
"""),
("hakkinda", "15. Hakkında ve lisans", f"""
<p><b>{APP_NAME} {APP_VERSION}</b> — Berkay Çelik tarafından kişisel bir proje olarak geliştirilmiş, ücretsiz ve
açık kaynaklı bir yazılımdır. GNU AGPL v3 veya sonraki sürümleri ve NOTICE dosyasındaki ek koşullar kapsamında
dağıtılır; yazar atfı lisans gereği korunur. Ayrıntılar: Yardım › {APP_NAME} Hakkında › Lisans ve Bildirimler.</p>
<p>İletişim: berkcel@gmail.com</p>
"""),
]


def build_html(colors):
    c = colors or {}
    text, base, mid, hl = c.get("text", "#222"), c.get("base", "#fff"), c.get("mid", "#888"), c.get("hl", "#b49a3a")
    css = f"""
    body {{ color: {text}; background: {base}; }}
    h2 {{ margin-top: 26px; border-bottom: 1px solid {mid}; padding-bottom: 4px; }}
    h3 {{ margin-top: 14px; margin-bottom: 4px; }}
    kbd {{ background: {c.get('btn', '#ddd')}; border: 1px solid {mid}; padding: 0 4px; font-family: monospace; }}
    code {{ font-family: monospace; color: {hl}; }}
    th {{ border-bottom: 1px solid {mid}; padding-top: 10px; }}
    dt {{ margin-top: 8px; }}
    li {{ margin-bottom: 3px; }}
    """
    parts = [f"<html><head><style>{css}</style></head><body>",
             f"<h1>{APP_NAME} — Kullanım Kılavuzu</h1><p>Sürüm {APP_VERSION}</p>"]
    for sid, title, body in SECTIONS:
        parts.append(f'<a name="{sid}"></a><h2>{html.escape(title)}</h2>{body}')
    parts.append("</body></html>")
    return "".join(parts)


class GuideDialog(QDialog):
    def __init__(self, parent, colors, start=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Kullanım Kılavuzu")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1000, 760)
        self.colors = colors
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Kılavuzda ara (Enter: sonraki)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.find_next)
        self.search.textChanged.connect(self.highlight_all)
        self.count = QLabel()
        self.count.setMinimumWidth(self.count.fontMetrics().horizontalAdvance("500 sonuç") + 8)
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.toc = QListWidget()
        for sid, title, _ in SECTIONS:
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, sid)
            self.toc.addItem(it)
        self.toc.currentItemChanged.connect(lambda it, _: it and self.view.scrollToAnchor(it.data(Qt.UserRole)))
        self.toc.setMaximumWidth(300)
        self.toc.setSpacing(2)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setHtml(build_html(colors))
        f = self.view.font(); f.setPointSizeF(f.pointSizeF() * 1.08); self.view.setFont(f)
        split.addWidget(self.toc)
        split.addWidget(self.view)
        split.setSizes([260, 740])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        QShortcut(QKeySequence.Find, self, lambda: (self.search.setFocus(), self.search.selectAll()))
        if start:
            self.goto(start)

    def goto(self, sid):
        for k in range(self.toc.count()):
            if self.toc.item(k).data(Qt.UserRole) == sid:
                self.toc.setCurrentRow(k)
                return

    def highlight_all(self, q):
        sels = []
        q = q.strip()
        n = 0
        if len(q) >= 2:
            doc = self.view.document()
            fmt = QTextCharFormat()
            col = QColor(self.colors.get("hl", "#b49a3a")); col.setAlpha(110)
            fmt.setBackground(col)
            c = doc.find(q, 0)
            while not c.isNull() and n < 500:
                s = QTextEdit.ExtraSelection()
                s.cursor = c
                s.format = fmt
                sels.append(s)
                n += 1
                c = doc.find(q, c)
        self.view.setExtraSelections(sels)
        self.count.setText(f"{n} sonuç" if q and len(q) >= 2 else "")
        if n:
            self.view.setTextCursor(QTextCursor(sels[0].cursor))
            self.view.ensureCursorVisible()

    def find_next(self):
        q = self.search.text().strip()
        if not q:
            return
        if not self.view.find(q):
            self.view.moveCursor(QTextCursor.Start)
            self.view.find(q)


def plain_text():
    """Kılavuzun düz metin hâli (README ya da test için)."""
    out = []
    for _, title, body in SECTIONS:
        t = re.sub(r"<[^>]+>", "", body.replace("</li>", "\n").replace("<br>", "\n").replace("</p>", "\n"))
        out.append(title + "\n" + html.unescape(t).strip())
    return "\n\n".join(out)

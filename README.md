# Aurea

Aurea, Transfermarkt piyasa etiketinin yanında oyuncunun üretimine dayalı bir adil değer gösterir.

Site Türkçedir. Ligler birinci liglerle sınırlıdır. TFF Fantezi Lig sekmesi aynı depodaki eniyileme motoruna bağlanır.

Bu proje TFF’nin resmî bir ürünü değildir. Üretilen kadrolar istatistiksel tahmindir; karar desteği amacıyla sunulur.

## Ne gösterir

- **Transfermarkt:** Piyasanın yazdığı etiket.
- **Aurea değeri:** Dakika, gol, asist, yaş, lig ve emsalden gelen tahmin.
- **Scout:** Etiketi Aurea değerinin altında kalan isimler.
- **Süper Lig:** 2026/27 gelen transferler; bedel, etiket ve Aurea karşılaştırması.
- **TFF Fantezi Lig:** Hesaba girince kadro, diziliş ve menajer kartı önerisi.

## Siteyi çalıştırma

Python 3.11 veya üzeri gerekir.

```bat
baslat.bat
```

veya

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app
```

Tarayıcı: [http://127.0.0.1:8787](http://127.0.0.1:8787)

İlk açılışta Transfermarkt açık veri seti iner ve değer motoru bir kez eğitilir. Sonraki açılışlar kayıtlı motoru kullanır.

Site giriş bilgisi yalnızca oturumda tutulur; depoya yazılmaz.

## Aurea değeri nasıl hesaplanır?

Aurea, güncel Transfermarkt etiketini modele özellik olarak sokmaz. Aksi halde site piyasayı kendi kendine tekrar eder.

Motor, açık Transfermarkt oyuncu ve maç kayıtlarıyla eğitilir. Öğrenilen hedef, tarihteki piyasa düzeyidir; girdi ise üretim ve bağlamdır: dakika, maç sayısı, gol, asist, 90 dakikaya indirgenmiş üretim, yaş, mevki, lig, kulüp düzeyi, sözleşme süresi ve milli takım kaydı.

Tahmin, gradyan artırmalı bir regresyonla üretilir. Aynı modelin alt ve üst bantları aralık verir; tutar, tutulmuş bir örneklem üzerinde kalibre edilir. Güven, dakika, maç sayısı ve son maçın yeniliğine bakılarak 0 ile 1 arasında bir ağırlıktır.

Yayımlanan Aurea bu iki okumayı birleştirir. Dakikası ve kanıtı yüksek oyuncuda model ağır basar; kanıt zayıfsa okuma etikete daha yakın durur. Ardından yaş, süre, gol-asist temposu ve sözleşme gibi üretim sinyalleri çarpan olarak uygulanır. Sonuç, modelin alt–üst bandının dışına taşmaz.

Scout ve kulüp sayfasındaki ucuz/pahalı etiket, bu Aurea ile Transfermarkt tutarı arasındaki boşluktur. Boşluk tek başına fırsat demek değildir; dakika azsa ucuzluk süre alınmadığı için de oluşur.

## Analiz neye dayanıyor?

TFF Fantezi Lig sekmesinde her hafta birkaç kaynak birlikte okunur:

**Bu sezon** — Son haftaların formu (L6) ile sezon toplam istatistikleri Sofascore üzerinden gelir. FotMob, ilk 11 durumu, xG, xA, şut ve güncel maç bilgisi için ikinci kaynak olarak kullanılır.

**Geçen sezon** — Oyuncunun Süper Lig geçmişi erken haftalarda daha ağırlıklıdır; sezon ilerledikçe bu pay kendiliğinden azalır.

**Resmî TFF puanları** — TFF’deki dakika, maç sayısı ve maç başı puan, özellikle sezonun ilk haftalarında modeli kalibre eder.

**Fikstür** — Haftanın rakibi, iç veya dış saha ile rakip takımın hücum-savunma gücü beklenen puana yansır. Kadro seçiminde bu hafta ağır basar, sonraki iki rakip daha düşük ağırlıkla eklenir. Kaptan ve otomatik yedek hâlâ yalnızca bu haftaya bakar.

**Yedek sırası** — TFF’nin otomatik değişik kuralına göre hesaplanır: aynı mevkideki yedek önce gelir, ardından oynama olasılığı × beklenen puan en yüksek olan tercih edilir.

**Menajer kartı** — Sezon boyunca toplam 10 hak vardır. Kalan hafta ve kalan hak oranına bakılarak erken haftalarda kart kullanımı daha temkinli önerilir.

Oyuncular TFF’nin resmî puan kurallarına göre puanlanır. Sakat, cezalı veya kadro dışı oyuncular optimizasyona alınmaz.

## Kadro seçimi

Optimizasyon şu kurallara uyar: 100 milyon TL bütçe; 2 kaleci, 5 savunmacı, 5 orta saha, 3 forvet; kulüp başına en fazla 3 oyuncu; geçerli bir ilk 11 dizilişi.

PuLP ile kurulan tamsayı programlama modeli yasal kadroyu seçer. İlk 11 ve yedek değeri, TFF otomatik değişik kuralına göre hesaplanır.

## Lig dönüşüm verisini yenileme

```bat
python calibrate_leagues.py
```

Çıktı `data/league_translation.json` dosyasına yazılır. Normal kullanımda bu dosya repoda hazır gelir.

## Testler

```bat
python -m unittest discover -s tests -v
```

Testler ağ bağlantısı gerektirmez.

## Yapı

- `app/` FastAPI, ambar, değer motoru, transfer masası
- `web/` site arayüzü
- `src/` TFF Fantezi Lig eniyileme motoru
- `data/` indirilen ve türetilen veri (giriş bilgisi ve ham çekimler gitte yok)
- `models/` eğitilmiş değer motoru (gitte yok)

## Lisans

Aurea özel bir yapıttır. Telif hakkı © 2026 Arda’ya aittir; tüm hakları saklıdır. Kaynak kod, arayüz, metin, görsel, model ve üretilen çıktı bu kapsamdadır.

Yazılı izin olmadan yapı olduğu gibi kopyalanamaz, yayımlanamaz, barındırılamaz veya dağıtılamaz. Satış, abonelik, reklam, beyaz etiket veya SaaS dahil ticari kullanım yasaktır. Aurea adı, markası ve tasarımı izinsiz kullanılamaz.

Çatal, değişiklik veya uyarlama orijinal hakları ortadan kaldırmaz; türetilmiş iş de aynı sınırlara tabidir. İnceleme ve özel öğrenme dahi önceden yazılı onay ister.

Transfermarkt, FotMob ve TFF Fantezi Lig üçüncü taraf hizmetlerdir. Bu lisans onların verisini veya markasını devretmez.

Yapıt “olduğu gibi” sunulur. Yatırım, transfer veya bahis tavsiyesi değildir. İzinsiz kullanımda lisans sona erer.

Tam metin `LICENSE` dosyasındadır. İzin için hak sahibiyle iletişime geçin.

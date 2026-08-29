# Aurea

Aurea, Transfermarkt piyasa etiketinin yanında oyuncunun üretimine dayalı bir adil değer gösterir. Değer, güncel Transfermarkt tutarını modele sokmadan hesaplanır.

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

Fantezi motoru varsayılan olarak bu deponun kökündedir (`src/`). Ayrı bir klasör kullanıyorsanız:

```bat
set FANTASY_ROOT=C:\yol\Fantezi Ligi
.venv\Scripts\python -m app
```

Site giriş bilgisi yalnızca oturumda tutulur; depoya yazılmaz.

## TFF Fantezi Lig (komut satırı)

Haftalık kadro kurarken fiyat, form, sezon istatistikleri ve fikstür zorluğunu bir arada değerlendirir. 100 milyon TL bütçeye uyan 15 kişilik kadroyu seçer; diziliş, ilk 11, yedek sırası ve kaptanı da aynı analizden çıkarır.

TFF hesabınızdan canlı fiyat çekmek için örnek dosyayı kopyalayıp kendi bilgilerinizi yazın:

```bat
copy data\tff_login.example.txt data\tff_login.txt
```

`data/tff_login.txt` GitHub’a gönderilmez. İsterseniz `TFF_EMAIL` ve `TFF_PASSWORD` ortam değişkenlerini kullanın.

```bat
calistir.bat
```

```bat
python -m src.main
python -m src.main --verbose
python -m src.main --no-fetch-prices
python -m src.main --refresh-cache
python -m src.main --export-stats out.csv
python -m src.main --report-png data/weekly_report.png
```

İlk komut yalnızca kadro sonucunu gösterir. `--verbose` ayrıntılı kayıt alır; `--no-fetch-prices` kayıtlı fiyat dosyasını kullanır; `--refresh-cache` Sofascore önbelleğini yeniler.

Fiyatları çevrimdışı denemek için `data/prices.example.csv` dosyasını `data/prices.csv` olarak kopyalayıp `--no-fetch-prices` kullanın. İstatistik adımı yine Sofascore’dan veri ister.

Sofascore ara sıra 403/429 ile geçici engel koyar. Program önce farklı tarayıcı kimlikleriyle ve kısa aralarla tekrar dener; olmazsa bir önceki başarılı çekimin önbelleğini kullanır. `--refresh-cache` bu yedeği siler. Fikstür Sofascore’dan gelmezse FotMob takvimi devreye girer.

## Analiz neye dayanıyor?

Her hafta birkaç kaynak birlikte okunur:

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

Özel kullanım.

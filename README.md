# Aurea

Aurea, Transfermarkt piyasa etiketinin yanında oyuncunun üretimine dayalı bir adil değer gösterir. Değer, güncel Transfermarkt tutarını modele sokmadan hesaplanır.

Site Türkçedir. Ligler birinci liglerle sınırlıdır. TFF Fantezi Lig sekmesi, ayrı bir eniyileme motoruna bağlanır.

## Ne gösterir

- **Transfermarkt:** Piyasanın yazdığı etiket.
- **Aurea değeri:** Dakika, gol, asist, yaş, lig ve emsalden gelen tahmin.
- **Scout:** Etiketi Aurea değerinin altında kalan isimler.
- **Süper Lig:** 2026/27 gelen transferler; bedel, etiket ve Aurea karşılaştırması.
- **TFF Fantezi Lig:** Hesaba girince kadro, diziliş ve menajer kartı önerisi.

## Çalıştırma

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

## TFF Fantezi Lig

Fantezi motoru varsayılan olarak `C:\Users\Arda\Desktop\Apps\Fantezi Ligi` klasöründedir. Başka bir yoldaysa:

```bat
set FANTASY_ROOT=C:\yol\Fantezi Ligi
.venv\Scripts\python -m app
```

Giriş bilgisi yalnızca oturumda tutulur; depoya yazılmaz.

## Yapı

- `app/` FastAPI, ambar, değer motoru, transfer masası
- `web/` arayüz
- `data/` indirilen ve türetilen veri (gitte yok)
- `models/` eğitilmiş motor (gitte yok)

## Lisans

Özel kullanım.

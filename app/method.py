"""Yöntem sayfası: kısa güven metni."""

from __future__ import annotations

from typing import Any


def method_pack() -> dict[str, Any]:
    return {
        "title": "Yöntem",
        "lede": (
            "Aurea, Transfermarkt etiketinin yanında oyunun ürettiği tutarı gösterir. "
            "İki rakam ayrı durur; biri diğerini doğrulamak zorunda değildir."
        ),
        "sections": [
            {
                "id": "iki-tutar",
                "title": "İki tutar",
                "paragraphs": [
                    "Transfermarkt, piyasanın o gün yazdığı etikettir. Aurea değeri dakika, gol, asist, yaş, lig ve benzer profilden hesaplanır.",
                    "Güncel piyasa etiketi modele özellik olarak girmez. Aksi halde site, piyasayı kendi kendine tekrar eder.",
                    "Ucuz etiket, her zaman fırsat demek değildir. Dakikası az olan oyuncuda ucuzluk, süre almadığı için de oluşur. As kadroda üretim varken etiket gerideyse boşluk anlam kazanır.",
                ],
            },
            {
                "id": "hangi-veri",
                "title": "Hangi veri",
                "paragraphs": [
                    "Değer motoru, açık Transfermarkt oyuncu ve maç kayıtlarıyla eğitilir. Oyuncu dosyasında güncel etiket ve sezon toplamı oradan okunur.",
                    "Şut ve beklenen gol FotMob kaydından tamamlanır. Bu rakamlar metne işlenir; harici bir maç notu sitede puan olarak durmaz.",
                    "Scout listesi, Aurea değeri ile Transfermarkt etiketi arasındaki boşluğu, dakika ve yaş eşiğiyle birlikte okur. Sağlık ve sözleşme, hükümden önce dosyada doğrulanır.",
                ],
            },
            {
                "id": "okuma",
                "title": "Nasıl okunur",
                "paragraphs": [
                    "Büyük ligde, genç veya tanınmış oyuncuda etiket çoğu zaman Aurea’nın üzerindedir. Bu bir hata değildir; isim, lig ve gelecek primidir.",
                    "Aurea bir taban okumasıdır. Karar sağlık, sözleşme ve rolle birlikte alınır. Rol üç bantta okunur: as kadro, rotasyon ve kenar.",
                    "Site tavsiye veya bahis ürünü değildir. Metin, dosyayı resmi Türkçe ile okur; hüküm vermez.",
                ],
            },
            {
                "id": "fantezi",
                "title": "TFF Fantezi Lig",
                "paragraphs": [
                    "Kadro, beklenen puana göre dizilir. Rakam, forma çıkma olasılığı yüzdesi değildir. Forma çıkmayan oyuncu bu tutarı getirmez.",
                    "Kaptan, beklenen puana ve fikstüre bakılarak seçilir. Menajer kartı, beklenen ek puana göre okunur; hakkı harcamaya yetmezse kart tutulur.",
                    "Hazırlık bölümü sakatlık ve ceza kaydını ayırır. Riskli ismi ilk 11’de tutmak, beklenen puanı düşürür.",
                    "Diziliş karşılaştırması, aynı kadronun farklı şekillerdeki beklenen puanını yan yana koyar. En yüksek okuma her zaman seçilen diziliş olmayabilir; kilitlenmiş isim veya kart kısıtı seçimi kaydırabilir.",
                ],
            },
            {
                "id": "lisans",
                "title": "Lisans",
                "paragraphs": [
                    "Aurea özel bir yapıttır. Telif hakkı saklıdır. Olduğu gibi kopyalanamaz, yayımlanamaz, barındırılamaz ve ticari kullanılamaz. Çatal veya uyarlama bu sınırları kaldırmaz.",
                    "Transfermarkt, FotMob ve TFF Fantezi Lig üçüncü taraf hizmetlerdir; bu lisans onların haklarını vermez. Ayrıntı proje LICENSE dosyasındadır.",
                ],
            },
        ],
    }

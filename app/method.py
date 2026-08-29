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
                    "Transfermarkt, piyasanın o gün yazdığı etikettir. Aurea değeri; dakika, gol, asist, yaş, lig ve benzer profilden hesaplanır.",
                    "Güncel piyasa etiketi modele özellik olarak girmez. Aksi halde site, piyasayı kendi kendine tekrar eder.",
                ],
            },
            {
                "id": "hangi-veri",
                "title": "Hangi veri",
                "paragraphs": [
                    "Değer motoru, açık Transfermarkt oyuncu ve maç kayıtlarıyla eğitilir. Oyuncu dosyasında güncel etiket, sakatlık ve sezon toplamı oradan okunur.",
                    "Şut ve beklenen gol FotMob kaydından tamamlanır. Bu rakamlar metne işlenir; harici bir maç notu sitede puan olarak durmaz.",
                ],
            },
            {
                "id": "okuma",
                "title": "Nasıl okunur",
                "paragraphs": [
                    "Büyük ligde, genç veya tanınmış oyuncuda etiket çoğu zaman Aurea’nın üzerindedir. Bu bir hata değildir; isim, lig ve gelecek primidir.",
                    "Aurea bir taban okumasıdır. Karar, sağlık, sözleşme ve rol ile birlikte alınır. Site tavsiye veya bahis ürünü değildir.",
                ],
            },
            {
                "id": "lisans",
                "title": "Lisans",
                "paragraphs": [
                    "Aurea özel bir yapıttır. Olduğu gibi kopyalanamaz, yayımlanamaz ve ticari kullanılamaz. Telif hakkı saklıdır; ayrıntı proje LICENSE dosyasındadır.",
                ],
            },
        ],
    }

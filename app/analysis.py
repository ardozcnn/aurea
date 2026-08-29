"""Oyuncu dosyası için resmi Türkçe analiz metinleri."""

from __future__ import annotations

from typing import Any

from app.config import LEAGUE_NAMES, POSITION_TR, SUB_POSITION_TR
from app.money import format_eur, format_pct, gap_direction


def _pos(row: dict) -> str:
    sub = row.get("sub_position")
    if sub in SUB_POSITION_TR:
        return SUB_POSITION_TR[sub]
    return POSITION_TR.get(row.get("position") or "", row.get("position") or "Oyuncu")


def _league(row: dict) -> str:
    live = row.get("league_live") or row.get("league")
    if live and str(live).strip() and str(live) not in {"None", "nan"}:
        return str(live)
    code = str(row.get("league_id") or row.get("current_club_domestic_competition_id") or "")
    return LEAGUE_NAMES.get(code, row.get("current_club_name") or "Bilinmeyen lig")


def _club(row: dict) -> str:
    return row.get("club") or row.get("current_club_name") or row.get("club_name_official") or "Kulüpsüz"


def _n(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _starter_minutes(position: str | None) -> int:
    if position == "Goalkeeper":
        return 2700
    return 2200


def build_report(row: dict, similar: list[dict], live: dict | None) -> dict[str, Any]:
    name = row.get("name") or "Oyuncu"
    pos = _pos(row)
    club = _club(row)
    league = _league(row)
    age = _n(row.get("age"))
    tm = row.get("tm_value") or row.get("market_value_in_eur")
    true = row.get("true_value")
    gap = row.get("gap_pct")
    minutes = _n(row.get("minutes_365"))
    minutes_2y = _n(row.get("minutes_2y"))
    goals = _n(row.get("goals_2y"))
    assists = _n(row.get("assists_2y"))
    contrib_p90 = _n(row.get("contrib_p90"))
    goals_p90 = _n(row.get("goals_p90"))
    assists_p90 = _n(row.get("assists_p90"))
    apps = _n(row.get("apps_2y"))
    yellow = _n(row.get("yellow_2y"))
    red = _n(row.get("red_2y"))
    caps = _n(row.get("intl_caps") or row.get("international_caps"))
    contract = _n(row.get("contract_years"), 1.5)
    peak = _n(row.get("highest_market_value_in_eur"))
    direction = gap_direction(gap)
    years = int(round(age)) if age else 0
    tm_n = _n(tm)
    true_n = _n(true)
    gap_eur = tm_n - true_n if tm_n and true_n else 0.0
    pos_raw = str(row.get("position") or "")

    if direction == "dusuk":
        verdict_title = "Piyasa ucuz yazıyor"
        verdict_body = (
            f"Transfermarkt {name} için {format_eur(tm)} yazıyor. "
            f"Aurea değeri {format_eur(true)}. "
            "Aurea, oyuncunun dakika, gol, asist, yaş ve ligine bakarak adil tutarı tahmin eder. "
            "Piyasa etiketi bunun altında kaldığı için oyuncu, üretime göre ucuz duruyor."
        )
        if abs(gap_eur) >= 150_000:
            verdict_body += f" Fark {format_eur(abs(gap_eur))}."
    elif direction == "yuksek":
        verdict_title = "Piyasa pahalı yazıyor"
        verdict_body = (
            f"Transfermarkt {name} için {format_eur(tm)} yazıyor. "
            f"Aurea değeri {format_eur(true)}. "
            "Etiket, oyunun hak ettiği tutarın üzerinde. "
            "Bu fiyattan almak, isim, lig veya gelecek beklentisi için prim ödemek demektir."
        )
        if abs(gap_eur) >= 150_000:
            verdict_body += f" Fark {format_eur(abs(gap_eur))}."
    else:
        verdict_title = "İki tutar uyumlu"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "Piyasa ile üretim aynı bantta. Hamle, taktik ihtiyaç veya sözleşme süresine bağlıdır."
        )

    kim = []
    kim.append(
        f"{name}, {years} yaşında {pos}. Şu an {club} forması giyiyor; lig {league}."
    )
    if age <= 21:
        kim.append(
            "Henüz kariyerinin başında. Bu yaşta as kadro dakikası tutarsa değer hızlı yükselir. "
            "Az oynuyorsa etiket çoğu zaman umut fiyatıdır, henüz kanıtlanmış üretim değildir."
        )
        if minutes < 400:
            kim.append("Son 12 ayda dakika çok az. Bu yüzden fiyat spekülatif kalır; hüküm temkinli okunmalı.")
        elif minutes >= 1200:
            kim.append("Bu yaşta bu kadar dakika, kulüp için gerçek bir varlık birikimidir.")
    elif age <= 24:
        kim.append(
            "Zirve öncesi yaş. En verimli yıllar henüz gelmemiş olabilir. "
            "Düzenli oynayan bu gruptaki oyuncu, hem bugünü hem yarını fiyatlar."
        )
        if minutes >= 1800:
            kim.append("Rotasyon değil; as kadro temposu. Kulüp ona güveniyor.")
    elif age <= 28:
        kim.append(
            "Futbolcunun en verimli yaş aralığında. Burada sapma genelde form, sakatlık veya rol değişiminden gelir; "
            "yaş priminden değil."
        )
        if minutes < 900:
            kim.append("Zirve yaşında az dakika uyarıdır. Ya yedek kalmıştır ya da sağlık kesmiştir.")
    elif age <= 32:
        kim.append(
            "Zirve sonrası. Alıcı, kalan sözleşme yılına ve sakatlık geçmişine daha sıkı bakar. "
            "Yüksek etiket ancak hâlâ as kadroysa savunulur."
        )
        if contract <= 1:
            kim.append("Sözleşme kısa. Serbest kalma penceresi yakın; satıcı pazarlık gücünü kaybeder.")
    else:
        kim.append(
            "Amortisman dönemi. Kısa sözleşme ve düşen dakika tutarı aşağı çeker. "
            "Yüksek bedel ancak kısa süreli net katkı ile açıklanır."
        )

    oyun = []
    hedef = _starter_minutes(pos_raw)
    if minutes_2y < 400:
        oyun.append(
            f"Son iki sezonda yalnızca {int(minutes_2y)} dakika var. "
            "Bu kadar az süreyle gol, asist veya ‘pahalı / ucuz’ hükmü zayıf kalır. "
            "Lig, yaş ve sözleşme daha ağır basar."
        )
    elif pos_raw == "Goalkeeper":
        oyun.append(
            f"Kaleci. Son iki sezon {int(apps)} maç, {int(minutes_2y)} dakika. "
            f"Son 12 ayda {int(minutes)} dakika."
        )
        if minutes >= hedef:
            oyun.append("Kalede as numara temposu; düzenli oynuyor.")
        elif minutes < 900:
            oyun.append("Kalede dakika kırılmamış. Yedek veya paylaşılmış kalesi olabilir.")
    else:
        oyun.append(
            f"Son iki sezon {int(apps)} maç, {int(goals)} gol, {int(assists)} asist, "
            f"{int(minutes_2y)} dakika. Son 12 ayda {int(minutes)} dakika oynadı."
        )
        if minutes >= hedef:
            oyun.append(
                f"As kadro dakikası. {hedef} dakikanın üzerinde olmak, takımın ona güvendiğini gösterir. "
                "Üretim ölçülebilir; etiket spekülasyona daha az açık."
            )
        elif minutes >= 900:
            oyun.append(
                "Düzenli ama her hafta 90 dakika değil. Rotasyon veya paylaşılmış mevki olabilir. "
                "Fiyat, tam as kadro oyuncusuna göre daha temkinli okunur."
            )
        else:
            oyun.append(
                "Dakika az. Ya yeni geldi, ya sakatlık kesti, ya da kadroda arka planda. "
                "Bu durumda yüksek etiket çoğu zaman isim primidir."
            )
        if contrib_p90 >= 0.55 and pos_raw in ("Attack", "Midfield"):
            oyun.append(
                f"90 dakikada {contrib_p90:.2f} gol+asist. "
                f"Bunun {goals_p90:.2f}’si gol, {assists_p90:.2f}’si asist. "
                "Mevkisine göre tempo yüksek; hücum katkısı fiyatı taşır."
            )
        elif contrib_p90 <= 0.18 and pos_raw == "Attack" and minutes_2y >= 800:
            oyun.append(
                f"Forvet olarak 90 dakikada yalnızca {contrib_p90:.2f} gol+asist. "
                "Hücum üretimi zayıfken yüksek etiket şişmiş olabilir."
            )
        elif contrib_p90 >= 0.30 and pos_raw in ("Attack", "Midfield"):
            oyun.append(
                f"90 dakikada {contrib_p90:.2f} gol+asist. Mevki için makul bir tempo."
            )

    season = (live or {}).get("season_totals") or {}
    season_apps = _n(season.get("apps"))
    if season_apps >= 3:
        season_id = season.get("season") or "bu sezon"
        oyun.append(
            f"{season_id} sezonunda {int(season_apps)} maç, "
            f"{int(_n(season.get('goals')))} gol, {int(_n(season.get('assists')))} asist, "
            f"{int(_n(season.get('minutes')))} dakika. Güncel form burada okunur."
        )

    fiyat = []
    fiyat.append(
        "Sitede iki tutar vardır. Transfermarkt, piyasanın bugün yazdığı etikettir. "
        "Aurea değeri, güncel etiketi modele sokmadan; dakika, yaş, lig ve emsalden hesaplanır."
    )
    if tm_n and true_n:
        if gap_eur > 400_000:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea {format_eur(true)}. "
                "Piyasa daha yüksek yazıyor. Alıcı bu farkı isim, lig veya gelecek için prim olarak öder."
            )
        elif gap_eur < -400_000:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea {format_eur(true)}. "
                "Piyasa daha düşük yazıyor. Üretim henüz etikete yansımamış olabilir; alım tarafında izlenir."
            )
        else:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea {format_eur(true)}. "
                "İki tutar yakın; piyasa üretimi büyük ölçüde fiyatlamış."
            )
        if peak >= 1_000_000 and tm_n and peak > tm_n * 1.25:
            fiyat.append(
                f"Kariyer tepesi {format_eur(peak)}. Güncel etiket bunun altında. "
                "Yaş, lig düşüşü veya sakatlık tepeden indirmiş olabilir."
            )
        elif peak >= 1_000_000 and tm_n and tm_n >= peak * 0.92:
            fiyat.append(f"Etiket kariyer tepesine ({format_eur(peak)}) yakın.")
    else:
        fiyat.append("Karşılaştırma için yeterli tutar yok.")

    action = []
    if direction == "dusuk" and minutes >= 900:
        action.append(
            "Düzenli oynuyor ve etiket üretimden geride. "
            "Sağlık ve sözleşme dosyada doğrulanırsa takip listesine alınır."
        )
    elif direction == "dusuk":
        action.append(
            "Etiket ucuz görünüyor fakat dakika az. Ucuzluk, oynamadığı için de oluşmuş olabilir. "
            "Önce rol netleşmeli."
        )
    elif direction == "yuksek" and minutes >= 1800 and contrib_p90 >= 0.45:
        action.append(
            "Pahalı etiket, yüksek üretimle kısmen açıklanır. Prim, ancak bu tempo sürerse kapanır."
        )
    elif direction == "yuksek":
        action.append(
            "Etiket pahalı. Bu fiyattan almak üretimden kopuk bir prim ödemektir. "
            "Daha uygun emsal bakmak daha sağlıklıdır."
        )
    else:
        action.append("Fiyat ile oyun uyumlu. Hamle ihtiyaca kalır; sapma söylemi zayıf.")

    soz = []
    if contract <= 0.7:
        soz.append(
            "Sözleşme bir yıldan kısa. Serbest kalma yakın. Satıcı prim isteyemez; alıcı güçlenir."
        )
    elif contract <= 1.2:
        soz.append(f"Kalan sözleşme yaklaşık {contract:.1f} yıl. Pazarlık penceresi daralıyor.")
    elif contract >= 4:
        soz.append(
            f"Sözleşme yaklaşık {contract:.1f} yıl. Kulüp oyuncuyu uzun süre elinde tutar; satıcı güçlüdür."
        )
    else:
        soz.append(f"Kalan sözleşme yaklaşık {contract:.1f} yıl. Süre makul; acil satış baskısı yok.")
    if caps >= 50:
        soz.append(f"Milli forma: {int(caps)} maç. Düzenli milli dakika, alıcı kümesini genişletir.")
    elif caps >= 8:
        soz.append(f"Milli forma: {int(caps)} maç. Seçilmiş kadro, otomatik prim değildir.")

    saglik = []
    if live:
        open_days = live.get("injury_days") or 0
        injuries = live.get("injuries") or []
        if open_days:
            saglik.append(
                f"Açık sakatlık yaklaşık {open_days} gün. "
                "Aurea değerine iskonto uygulanmıştır; dönüş tarihi netleşmeden yüksek bedel risklidir."
            )
        elif injuries:
            last = injuries[0]
            saglik.append(
                f"Son kayıtlı sakatlık: {last.get('injury') or 'belirtilmemiş'} "
                f"({last.get('season') or '—'}, {last.get('days') or 0} gün). "
                "Şu an açık görünmüyor; yine de geçmişe bakılır."
            )
        hist = live.get("market_history") or []
        if len(hist) >= 2:
            old = hist[-2].get("marketValue") if isinstance(hist[-2], dict) else None
            new = hist[-1].get("marketValue") if isinstance(hist[-1], dict) else None
            if old and new and old > 0:
                ch = 100.0 * (new - old) / old
                saglik.append(f"Transfermarkt etiketinin son adımı {format_pct(ch)}.")

    disc_bits = []
    if yellow >= 8 or red >= 1:
        line = f"Son iki sezonda {int(yellow)} sarı"
        line += f", {int(red)} kırmızı kart." if red else " kart."
        if yellow >= 14:
            line += " Kart yükü yüksek; özellikle defans için ceza riski fiyata yansır."
        disc_bits.append(line)

    emsal = []
    comps = [c for c in (similar or []) if c.get("name")][:5]
    if comps:
        names = ", ".join(str(c.get("name") or "") for c in comps[:4])
        emsal.append(f"Yaş, mevki ve üretime göre yakın profiller: {names}.")
        peer_tm = [_n(c.get("market_value_in_eur")) for c in comps if _n(c.get("market_value_in_eur")) > 0]
        peer_true = [_n(c.get("true_value")) for c in comps if _n(c.get("true_value")) > 0]
        if peer_tm and tm_n:
            avg = sum(peer_tm) / len(peer_tm)
            if tm_n > avg * 1.18:
                emsal.append(
                    f"Bu oyuncunun Transfermarkt etiketi, emsal ortalamasının ({format_eur(avg)}) üzerinde. "
                    "Piyasa onu benzerlerinden pahalı yazıyor."
                )
            elif tm_n < avg * 0.82:
                emsal.append(
                    f"Etiket, emsal ortalamasının ({format_eur(avg)}) altında. "
                    "Benzer üretim daha pahalıya yazılıyor olabilir."
                )
            else:
                emsal.append(f"Emsal ortalama Transfermarkt {format_eur(avg)}; hizalı.")
        if peer_true and true_n:
            tavg = sum(peer_true) / len(peer_true)
            emsal.append(f"Emsallerin Aurea değeri ortalaması {format_eur(tavg)}.")

    sections = [
        {"id": "ozet", "title": "Ne anlama geliyor", "paragraphs": [verdict_body] + action, "body": verdict_body},
        {"id": "oyuncu", "title": "Oyuncu", "paragraphs": kim, "body": " ".join(kim)},
        {"id": "uretim", "title": "Oyun", "paragraphs": oyun, "body": " ".join(oyun)},
        {"id": "fiyat", "title": "Fiyat", "paragraphs": fiyat, "body": " ".join(fiyat)},
        {"id": "sozlesme", "title": "Sözleşme", "paragraphs": soz, "body": " ".join(soz)},
    ]
    if saglik:
        sections.append({"id": "canli", "title": "Güncel", "paragraphs": saglik, "body": " ".join(saglik)})
    if disc_bits:
        sections.append({"id": "disiplin", "title": "Disiplin", "paragraphs": disc_bits, "body": " ".join(disc_bits)})
    if emsal:
        sections.append({"id": "emsal", "title": "Benzer oyuncular", "paragraphs": emsal, "body": " ".join(emsal)})

    metrics = [
        {"k": "12 ay", "v": f"{int(minutes)} dk"},
        {"k": "Maç", "v": str(int(apps)) if apps else "—"},
        {"k": "Gol", "v": str(int(goals))},
        {"k": "Asist", "v": str(int(assists))},
    ]
    gap_txt = format_pct(gap) if gap is not None else ""
    headline = verdict_title
    if gap_txt and gap_txt != "—":
        headline = f"{verdict_title} ({gap_txt})"
    return {
        "headline": headline,
        "direction": direction,
        "summary": verdict_body,
        "sections": sections,
        "metrics": metrics,
        "identity": {
            "name": name,
            "position": pos,
            "club": club,
            "league": league,
            "age": int(round(age)) if age else None,
        },
    }

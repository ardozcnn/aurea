"""Oyuncu dosyası için resmi Türkçe analiz metinleri."""

from __future__ import annotations

from typing import Any

from app.config import LEAGUE_NAMES, POSITION_TR, SUB_POSITION_TR
from app.money import GAP_CHEAP, GAP_RICH, format_eur, format_pct, format_tr_num, gap_direction
from app.slugs import club_display, is_free_agent


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
    raw = row.get("club") or row.get("current_club_name") or row.get("club_name_official") or ""
    return club_display(str(raw))


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


def _comma(value: float, digits: int = 2) -> str:
    return format_tr_num(value, digits)


def _yuzde(value) -> str:
    try:
        n = abs(float(value))
    except (TypeError, ValueError):
        return ""
    if n != n:
        return ""
    return f"yüzde {int(round(n))}"


def _yil(value) -> str:
    return f"{format_tr_num(value, 1)} yıl"


def _fotmob(live: dict | None) -> dict[str, Any]:
    if not live:
        return {}
    pack = live.get("fotmob") or {}
    return pack if isinstance(pack, dict) else {}


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
    fm = _fotmob(live)
    starts = int(fm.get("starts") or 0)
    apps_fm = int(fm.get("apps") or 0)
    start_share = (starts / apps_fm) if apps_fm >= 4 else None
    hedef = _starter_minutes(pos_raw)
    if minutes >= hedef * 0.85 and (start_share is None or start_share >= 0.70):
        rol = "as"
    elif minutes >= 900 or (start_share is not None and start_share >= 0.40):
        rol = "rotasyon"
    else:
        rol = "kenar"

    prod_ok = minutes >= hedef * 0.75
    if pos_raw == "Attack":
        prod_ok = prod_ok or (minutes >= 1000 and contrib_p90 >= 0.40)
    elif pos_raw == "Midfield":
        prod_ok = prod_ok or (minutes >= 1200 and contrib_p90 >= 0.22)
    elif pos_raw == "Goalkeeper":
        prod_ok = minutes >= 1800
    if rol == "as":
        prod_ok = True
    elif rol == "kenar":
        prod_ok = False

    gap_txt = f" Fark {format_eur(abs(gap_eur))}." if abs(gap_eur) >= 200_000 else ""
    if direction == "dusuk" and rol == "kenar":
        verdict_title = "Etiket ucuz görünüyor"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "Piyasa, üretime göre daha düşük yazıyor. "
            "Dakika ve ilk 11 payı ince olduğu için bu ucuzluk yanıltıcı olabilir; "
            "önce rol, sağlık ve sözleşme netleşir."
            f"{gap_txt}"
        )
    elif direction == "dusuk":
        verdict_title = "Etiket üretimden geride"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "As kadro temposu varken piyasa etiketi üretim tabanının altında. "
            "Bu bir fırsat olabilir; sağlık ve sözleşme dosyada doğrulanır."
            f"{gap_txt}"
        )
    elif direction == "yuksek" and prod_ok:
        verdict_title = "Piyasa primi var"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "Aurea bir üretim tabanıdır. Büyük lig, isim veya yaş primi etiketi sık yükseltir; "
            "bu, tek başına yanıltıcı bir fark değildir. Dakika ve katkı da güçlüyse prim savunulur."
        )
        if abs(gap_eur) >= 400_000:
            verdict_body += f" Fark {format_eur(abs(gap_eur))}."
    elif direction == "yuksek":
        verdict_title = "Etiket üretimden kopuk"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "Dakika veya katkı zayıfken etiket yüksek kalmış. "
            "Prim; isim, gelecek beklentisi veya eski formaya dayanıyor olabilir."
            f"{gap_txt}"
        )
    else:
        verdict_title = "İki tutar aynı bantta"
        verdict_body = (
            f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
            "Piyasa ile üretim aynı aralıkta. Hamle, ihtiyaç ve sözleşmeye kalır."
        )

    kim = []
    pos_run = (pos[:1].lower() + pos[1:]) if pos else pos
    if is_free_agent(club) or club == "Kulüpsüz":
        kim.append(
            f"{name}, {years} yaşında, {pos_run}. Şu anda kulüpsüz. Lig kaydı: {league}."
        )
        kim.append("Kulüp bağı kopunca etiket, alıcı kümesine ve sözleşmeye daha bağlı okunur.")
    else:
        kim.append(
            f"{name}, {years} yaşında, {pos_run}. Şu anda {club} forması giyiyor; lig {league}."
        )
    if age <= 21:
        kim.append(
            "Kariyerinin başında. Bu yaşta as kadro dakikası tuttuğunda değer hızlı yükselir. "
            "Dakikası azsa etiket çoğu zaman umut fiyatıdır; henüz kanıtlanmış üretim değildir."
        )
        if minutes < 400:
            kim.append("Son 12 ayda dakika çok az. Bu yüzden fiyat spekülatif kalır; hüküm temkinli okunmalıdır.")
        elif minutes >= 1200:
            kim.append("Bu yaşta bu kadar dakika, kulüp için ölçülebilir bir varlık birikimidir.")
    elif age <= 24:
        kim.append(
            "Zirve öncesi yaş bandında. En verimli yıllar henüz gelmemiş olabilir. "
            "Düzenli süre alan bu gruptaki oyuncu hem bugünü hem yarını fiyatlar."
        )
        if minutes >= 1800:
            kim.append("Rotasyon değil; as kadro temposu. Kulüp, bu isme güvenilir süre vermiş.")
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
            "Yüksek etiket ancak hâlâ as kadrodaysa savunulur."
        )
        if contract <= 1:
            kim.append("Sözleşme kısa. Serbest kalma penceresi yakın; satıcı pazarlık gücünü kaybeder.")
    else:
        kim.append(
            "Amortisman dönemi. Kısa sözleşme ve düşen dakika tutarı aşağı çeker. "
            "Yüksek bedel ancak kısa süreli net katkı ile açıklanır."
        )

    oyun = []
    if rol == "as":
        oyun.append("Rol: as kadro. Süre ve ilk 11 payı, takımın bu isme güvendiğini gösterir.")
    elif rol == "rotasyon":
        oyun.append("Rol: rotasyon. Düzenli süre vardır; her hafta tam 90 dakika beklenmez.")
    else:
        oyun.append("Rol: kenar veya belirsiz. Dakika ince; yüksek etiket çoğu zaman isim veya umut primidir.")
    if minutes_2y < 400:
        oyun.append(
            f"Son iki sezonda yalnızca {int(minutes_2y)} dakika var. "
            "Bu kadar az süreyle gol, asist veya ucuz–pahalı hükmü zayıf kalır. "
            "Lig, yaş ve sözleşme daha ağır basar."
        )
    elif pos_raw == "Goalkeeper":
        oyun.append(
            f"Kaleci. Son iki sezon {int(apps)} maç, {int(minutes_2y)} dakika. "
            f"Son 12 ayda {int(minutes)} dakika."
        )
        if minutes >= hedef:
            oyun.append("Kalede as numara temposu; düzenli süre alıyor.")
        elif minutes < 900:
            oyun.append("Kalede dakika kırılmamış. Yedek veya paylaşılmış kale olabilir.")
    else:
        oyun.append(
            f"Son iki sezon {int(apps)} maç, {int(goals)} gol, {int(assists)} asist, "
            f"{int(minutes_2y)} dakika. Son 12 ayda {int(minutes)} dakika süre aldı."
        )
        if minutes >= hedef:
            oyun.append(
                f"As kadro dakikası. {hedef} dakikanın üzerinde olmak, takımın bu isme güvendiğini gösterir. "
                "Üretim ölçülebilir; etiket spekülasyona daha az açıktır."
            )
        elif minutes >= 900:
            oyun.append(
                "Düzenli ama her hafta 90 dakika değil. Rotasyon veya paylaşılmış mevki olabilir. "
                "Fiyat, tam as kadro oyuncusuna göre daha temkinli okunur."
            )
        else:
            oyun.append(
                "Dakika az. Ya yeni gelmiştir, ya sakatlık kesmiştir, ya da kadroda arka plandadır. "
                "Bu durumda yüksek etiket çoğu zaman isim primidir."
            )
        if contrib_p90 >= 0.55 and pos_raw in ("Attack", "Midfield"):
            oyun.append(
                f"90 dakikada {_comma(contrib_p90)} gol ve asist. "
                f"Bunun {_comma(goals_p90)} kadarı gol, {_comma(assists_p90)} kadarı asist. "
                "Mevkisine göre tempo yüksek; hücum katkısı fiyatı taşır."
            )
        elif contrib_p90 <= 0.18 and pos_raw == "Attack" and minutes_2y >= 800:
            oyun.append(
                f"Forvet olarak 90 dakikada yalnızca {_comma(contrib_p90)} gol ve asist. "
                "Hücum üretimi zayıfken yüksek etiket gerçek üretimden kopuk olabilir."
            )
        elif contrib_p90 >= 0.30 and pos_raw in ("Attack", "Midfield"):
            oyun.append(
                f"90 dakikada {_comma(contrib_p90)} gol ve asist. Mevki için makul bir tempo."
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

    guncel = []
    if fm.get("injured") and not (live or {}).get("injury_days"):
        guncel.append(
            "Açık sakatlık kaydı var. Dönüş netleşmeden yüksek bedel risklidir."
        )
    if fm.get("apps"):
        lig_ad = fm.get("league") or league
        sezon_ad = fm.get("season") or "bu sezon"
        line = (
            f"{sezon_ad} {lig_ad} kaydı: {int(fm['apps'])} maç, "
            f"{int(fm.get('starts') or 0)} ilk 11, {int(fm.get('minutes') or 0)} dakika, "
            f"{int(fm.get('goals') or 0)} gol, {int(fm.get('assists') or 0)} asist."
        )
        guncel.append(line)
        if fm.get("xg") or fm.get("xa"):
            xg, xa = _n(fm.get("xg")), _n(fm.get("xa"))
            gls, ast = _n(fm.get("goals")), _n(fm.get("assists"))
            line = _xg_read(
                name,
                xg,
                gls,
                xa,
                ast,
                shots=_n(fm.get("shots")),
                apps=_n(fm.get("apps")),
            )
            if line:
                guncel.append(line)
        if fm.get("shots") or fm.get("sot"):
            shots, sot = int(fm.get("shots") or 0), int(fm.get("sot") or 0)
            xg = _n(fm.get("xg"))
            if shots:
                oran = (100.0 * sot / shots) if shots else 0
                bit = f"{shots} şut, {sot} isabet. İsabet yüzde {oran:.0f}."
                if xg and shots >= 8:
                    per = xg / shots
                    if per >= 0.14:
                        bit += f" Şut başına {_comma(per, 2)} xG; pozisyonlar kaliteli."
                    elif per <= 0.07:
                        bit += f" Şut başına {_comma(per, 2)} xG; hacim var, net şans az."
                elif oran >= 42:
                    bit += " Kaleyi bulan şut oranı yüksek."
                elif shots >= 18 and oran < 32:
                    bit += " Hacim yüksek, isabet düşük; bitiricilik geride kalmış olabilir."
                guncel.append(bit)
        if fm.get("xg_p90") or fm.get("goals_p90"):
            guncel.append(
                f"90 dakikada gol {_comma(_n(fm.get('goals_p90')))}, "
                f"beklenen gol {_comma(_n(fm.get('xg_p90')))}, "
                f"asist {_comma(_n(fm.get('assists_p90')))}."
            )
        if fm.get("key_passes"):
            guncel.append(f"Anahtar pas veya yaratılan şans: {int(_n(fm.get('key_passes')))}.")
        if pos_raw in ("Defender", "Goalkeeper") and (fm.get("tackles") or fm.get("interceptions") or fm.get("clean_sheets")):
            bits = []
            if fm.get("tackles"):
                bits.append(f"{int(fm['tackles'])} top çalma")
            if fm.get("interceptions"):
                bits.append(f"{int(fm['interceptions'])} kesme")
            if fm.get("clean_sheets"):
                bits.append(f"{int(fm['clean_sheets'])} gol yemeden")
            if bits:
                guncel.append("Savunma kaydı: " + ", ".join(bits) + ".")
        if fm.get("pass_pct") and _n(fm.get("pass_pct")) >= 40:
            guncel.append(f"Pas isabeti yüzde {_comma(_n(fm.get('pass_pct')), 1)}.")
        if fm.get("dribbles") and pos_raw in ("Attack", "Midfield"):
            guncel.append(f"Başarılı dribling: {int(fm['dribbles'])}.")
    if apps_fm >= 4:
        share = starts / apps_fm
        if share >= 0.78:
            oyun.append(
                f"Bu sezon {starts}/{apps_fm} ilk 11; as kadro rolü. Kulüp, bu ismi düzenli olarak sahaya sürüyor."
            )
        elif share <= 0.40:
            oyun.append(
                f"Bu sezon {starts}/{apps_fm} ilk 11; rotasyon veya kenar rolü. "
                "Etiket as kadroya yazılmışsa gerçek üretimden kopar."
            )
        else:
            oyun.append(
                f"Bu sezon {starts}/{apps_fm} ilk 11; paylaşılmış dakika. "
                "Fiyat, tam as ile yedek arasında okunur."
            )
    if pos_raw == "Defender" and minutes >= 1800:
        oyun.append("Defansta as kadro dakikası istikrardır; gol temposu ikincildir. Burada süre tutuluyorsa profil sağlamdır.")
    elif pos_raw == "Midfield" and contrib_p90 >= 0.32 and minutes >= 1400:
        oyun.append("Orta sahada hem dakika hem kutu katkısı var. Bu tempo, etiket primini daha kolay taşır.")
    elif pos_raw == "Attack" and minutes >= 1400 and contrib_p90 < 0.24:
        oyun.append("Forvet dakikası var ama 90 dakikalık katkı düşük. Yüksek etiket ancak farklı bir rolle (perde, kanat işi) açıklanır.")
    elif pos_raw == "Goalkeeper" and minutes >= 2400:
        oyun.append("Kalede sezonluk as numara. Değer, takım savunması ve kalan sözleşmeyle birlikte okunur.")

    fiyat = []
    fiyat.append(
        "Sitede iki tutar vardır. Transfermarkt, piyasanın bugün yazdığı etikettir. "
        "Aurea değeri, güncel etiketi modele sokmadan dakika, yaş, lig ve emsalden hesaplanır."
    )
    if tm_n and true_n:
        if gap_eur > 800_000 and not prod_ok:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
                "Fark geniş ve üretim zayıf; prim büyük ölçüde isim veya beklenti."
            )
        elif gap_eur > 400_000:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
                "Piyasa daha yüksek yazıyor. Büyük ligde bu prim sık görülür; Aurea tabanı hatırlatır."
            )
        elif gap_eur < -400_000:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
                "Piyasa daha düşük yazıyor. Üretim henüz etikete yansımamış olabilir."
            )
        else:
            fiyat.append(
                f"Transfermarkt {format_eur(tm)}, Aurea değeri {format_eur(true)}. "
                "İki tutar yakın; piyasa üretimi büyük ölçüde fiyatlamış."
            )
        if peak >= 1_000_000 and tm_n and peak > tm_n * 1.25:
            fiyat.append(
                f"Kariyer tepesi {format_eur(peak)}. Güncel etiket bunun altında. "
                "Yaş, lig düşüşü veya sakatlık tepeden indirmiş olabilir."
            )
        elif peak >= 1_000_000 and tm_n and tm_n >= peak * 0.92:
            fiyat.append(f"Etiket kariyer tepesine ({format_eur(peak)}) yakın.")
        lo = _n(row.get("value_lo"))
        hi = _n(row.get("value_hi"))
        if lo and hi and hi > lo:
            fiyat.append(
                f"Aurea bandı {format_eur(lo)}–{format_eur(hi)}. "
                "Tek rakam bir nokta tahmindir; bant, belirsizliği gösterir."
            )
    else:
        fiyat.append("Karşılaştırma için yeterli tutar yok.")

    action = []
    if direction == "dusuk" and rol == "as":
        action.append(
            "Düzenli as kadro ve etiket üretimden geride. "
            "Sağlık ve sözleşme dosyada doğrulanırsa öncelikli izleme listesine alınır."
        )
    elif direction == "dusuk" and rol == "rotasyon":
        action.append(
            "Etiket ucuz görünüyor; rol ise rotasyon. "
            "As kadro payı artarsa boşluk anlam kazanır; aksi halde ucuzluk yanıltır."
        )
    elif direction == "dusuk":
        action.append(
            "Etiket ucuz görünüyor fakat dakika az. Ucuzluk, süre almadığı için de oluşmuş olabilir. "
            "Önce rol netleşmelidir."
        )
    elif direction == "yuksek" and prod_ok:
        action.append(
            "Prim var ama oyun da taşıyor. Alım, tempo ve sağlık sürerse anlamlıdır; "
            "yalnızca etikete bakılarak reddedilmez."
        )
    elif direction == "yuksek":
        action.append(
            "Etiket yüksek, üretim geride. Önce dakika ve rol netleşmelidir; "
            "yalnızca isim primi zayıf bir gerekçedir."
        )
    else:
        action.append("Fiyat ile oyun uyumlu. Hamle ihtiyaca kalır; sapma söylemi zayıf kalır.")

    soz = []
    if contract <= 0.7:
        soz.append(
            "Sözleşme bir yıldan kısa. Serbest kalma yakın. Satıcı prim isteyemez; alıcı güçlenir."
        )
    elif contract <= 1.2:
        soz.append(f"Kalan sözleşme yaklaşık {_yil(contract)}. Pazarlık penceresi daralıyor.")
    elif contract >= 4:
        soz.append(
            f"Sözleşme yaklaşık {_yil(contract)}. Kulüp oyuncuyu uzun süre elinde tutar; satıcı güçlüdür."
        )
    else:
        soz.append(f"Kalan sözleşme yaklaşık {_yil(contract)}. Süre makul; acil satış baskısı yok.")
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
                "Şu anda açık görünmüyor; yine de geçmişe bakılır."
            )
        hist = live.get("market_history") or []
        if len(hist) >= 2:
            old = hist[-2].get("marketValue") if isinstance(hist[-2], dict) else None
            new = hist[-1].get("marketValue") if isinstance(hist[-1], dict) else None
            if old and new and old > 0:
                ch = 100.0 * (new - old) / old
                saglik.append(f"Transfermarkt etiketinin son adımı {format_pct(ch)}.")
                if true_n and tm_n:
                    prev_gap = old - true_n
                    now_gap = new - true_n
                    if abs(now_gap) < abs(prev_gap) * 0.85:
                        saglik.append(
                            "Son etiket adımı, Aurea değerine yaklaşmış. Piyasa üretimi kısmen fiyatlamış olabilir."
                        )
                    elif abs(now_gap) > abs(prev_gap) * 1.15:
                        saglik.append(
                            "Son etiket adımı Aurea’dan uzaklaşmış. Sapma büyümüş; isim primi veya panik satışı olabilir."
                        )

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
        emsal.append(
            f"Aynı mevki, yakın yaş ve benzer dakika/katkı bandındaki profiller: {names}."
        )
        closest = comps[0]
        c_age = closest.get("age")
        c_club = closest.get("club") or ""
        if closest.get("name"):
            bit = f"En yakın okuma {closest.get('name')}"
            if c_club:
                bit += f" ({c_club})"
            if c_age:
                bit += f", {int(round(_n(c_age)))} yaş"
            if closest.get("true_value"):
                bit += f", Aurea {format_eur(closest.get('true_value'))}"
            emsal.append(bit + ".")
        peer_tm = [_n(c.get("market_value_in_eur")) for c in comps if _n(c.get("market_value_in_eur")) > 0]
        peer_true = [_n(c.get("true_value")) for c in comps if _n(c.get("true_value")) > 0]
        if peer_tm and tm_n:
            avg = sum(peer_tm) / len(peer_tm)
            if tm_n > avg * 1.18:
                emsal.append(
                    f"Transfermarkt etiketi, emsal ortalamasının ({format_eur(avg)}) üzerinde. "
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
            if true_n > tavg * 1.12:
                emsal.append(f"Aurea, bu ismi emsal ortalamasının ({format_eur(tavg)}) üzerinde tutuyor.")
            elif true_n < tavg * 0.88:
                emsal.append(f"Aurea, bu ismi emsal ortalamasının ({format_eur(tavg)}) altında tutuyor.")
            else:
                emsal.append(f"Emsallerin Aurea ortalaması {format_eur(tavg)}; üretim bandı uyumlu.")

    karar = []
    hurt_now = bool((live or {}).get("injury_days")) or bool(fm.get("injured"))
    if hurt_now:
        karar.append("Açık sakatlık varken yüksek bedel ve kesin hüküm ertelenir. Dönüş netleşince dosya yeniden okunur.")
    elif direction == "dusuk" and rol == "as" and age <= 26:
        karar.append(
            "Genç, as kadroda ve etiket üretimden geride. "
            "Sağlık ile sözleşme temizse bu profil öncelikli izleme listesine alınır."
        )
    elif direction == "dusuk" and rol == "as":
        karar.append("Düzenli üretim var, etiket geride. Rol değişmezse piyasanın Aurea’ya yaklaşması beklenir.")
    elif direction == "dusuk":
        karar.append("Etiket ucuz görünüyor fakat dakika ince. Önce as kadro rolü kanıtlanmalıdır; aksi halde ucuzluk yanıltır.")
    elif direction == "yuksek" and prod_ok and age <= 24:
        karar.append("Prim var ama yaş ve tempo bunu kısmen taşır. Alım, sağlık ve ilk 11 payı sürerse anlamlıdır.")
    elif direction == "yuksek" and prod_ok:
        karar.append("Piyasa primi var; oyun da taşıyor. Reddetmek için tek gerekçe etiket olmamalıdır.")
    elif direction == "yuksek":
        karar.append("Etiket yüksek, üretim geride. İsim veya gelecek primi olabilir; önce dakika ve rol netleşmelidir.")
    else:
        karar.append("İki tutar ve oyun aynı bantta. Hamle ihtiyaca, sözleşmeye ve sağlığa kalır.")
    if contract <= 0.8 and direction != "yuksek":
        karar.append("Sözleşme kısa; satıcı prim isteyemez. Bedel görüşmesi alıcı lehine açılır.")

    sections = [
        {"id": "ozet", "title": "Ne anlama geliyor", "paragraphs": [verdict_body] + action, "body": verdict_body},
        {"id": "karar", "title": "Karar", "paragraphs": karar, "body": " ".join(karar)},
        {"id": "oyuncu", "title": "Oyuncu", "paragraphs": kim, "body": " ".join(kim)},
        {"id": "uretim", "title": "Oyun", "paragraphs": oyun, "body": " ".join(oyun)},
    ]
    if guncel:
        sections.append(
            {
                "id": "guncel-uretim",
                "title": "Güncel üretim",
                "paragraphs": guncel + [
                    "Gol, şut ve beklenen gol rakamları FotMob kaydından okunur. "
                    "Harici maç notu, sitede puan olarak gösterilmez."
                ],
                "body": " ".join(guncel),
            }
        )
    sections.append({"id": "fiyat", "title": "Fiyat", "paragraphs": fiyat, "body": " ".join(fiyat)})
    sections.append({"id": "sozlesme", "title": "Sözleşme", "paragraphs": soz, "body": " ".join(soz)})
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
        {"k": "Gol/90", "v": _comma(goals_p90) if goals_p90 > 0 else "—"},
        {"k": "Asist/90", "v": _comma(assists_p90) if assists_p90 > 0 else "—"},
        {"k": "G+A/90", "v": _comma(contrib_p90) if contrib_p90 > 0 else "—"},
        {"k": "Kart", "v": f"{int(yellow)} sarı" + (f", {int(red)} kırmızı" if red else "") if yellow or red else "—"},
    ]
    if fm.get("xg"):
        metrics.append({"k": "xG", "v": _comma(_n(fm.get("xg")))})
    if fm.get("xa"):
        metrics.append({"k": "xA", "v": _comma(_n(fm.get("xa")))})
    if fm.get("shots"):
        metrics.append({"k": "Şut", "v": str(int(fm.get("shots") or 0))})
    if fm.get("tackles"):
        metrics.append({"k": "Top çalma", "v": str(int(fm.get("tackles") or 0))})
    if fm.get("clean_sheets"):
        metrics.append({"k": "Gol yemeden", "v": str(int(fm.get("clean_sheets") or 0))})
    headline = verdict_title
    mag_txt = _yuzde(gap) if gap is not None else ""
    if mag_txt:
        try:
            mag = abs(float(gap))
        except (TypeError, ValueError):
            mag = 0.0
        if mag >= 1:
            headline = f"{verdict_title}: {mag_txt}."
    summary = verdict_body
    if karar:
        summary = (verdict_body + " " + karar[0]).strip()
    return {
        "headline": headline,
        "direction": direction,
        "summary": summary,
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


def _xg_read(
    name: str,
    xg: float,
    goals: float,
    xa: float = 0.0,
    assists: float = 0.0,
    shots: float = 0.0,
    apps: float = 0.0,
) -> str:
    bits = []
    if xg:
        delta = goals - xg
        thin = xg < 1.2 and apps and apps < 8
        if thin:
            bits.append(
                f"{name} için örnek henüz ince: {_comma(goals)} gol, {_comma(xg)} xG. "
                "Bu kadar az şanstan bitiricilik hükmü çıkmaz."
            )
        elif xg >= 2.2 and goals < xg * 0.72:
            bits.append(
                f"{name} şans buluyor ama bitiricilik geride: {_comma(goals)} gol, {_comma(xg)} xG. "
                "Pozisyon geliyor; isabet düşük. Tempo beklenen gole yaklaşırsa gol artar."
            )
        elif xg >= 2.0 and goals > xg * 1.35:
            bits.append(
                f"{name} beklenen golün üzerinde koşuyor: {_comma(goals)} gol, {_comma(xg)} xG. "
                "Bir kısmı form veya şans olabilir; sürdürülebilir tempo beklenen gole daha yakındır."
            )
        elif delta <= -0.8:
            bits.append(
                f"{name} beklenen golün altında: {_comma(goals)} gol, {_comma(xg)} xG. "
                "Şans geliyor; bitiricilik geride."
            )
        elif delta >= 0.9:
            bits.append(
                f"{name} beklenen golün üzerinde: {_comma(goals)} gol, {_comma(xg)} xG. "
                "Şu andaki gol temposu, sürdürülebilir düzeyin biraz üzerinde olabilir."
            )
        else:
            bits.append(
                f"{name} bitiriciliği beklenenle uyumlu ({_comma(goals)} gol, {_comma(xg)} xG)."
            )
        if shots and xg and shots >= 10 and not thin:
            per = xg / shots
            bits.append(f"Şut başına {_comma(per, 2)} xG.")
    if xa:
        ad = assists - xa
        if xa >= 1.4 and ad <= -0.8:
            bits.append(
                f"Asist bekleneninin altında: {_comma(assists)} asist, {_comma(xa)} xA. "
                "Son pas veya bitirici eksik kalmış olabilir."
            )
        elif xa >= 1.2 and ad >= 0.8:
            bits.append(
                f"Asist bekleneninin üzerinde: {_comma(assists)} asist, {_comma(xa)} xA."
            )
        else:
            bits.append(
                f"Beklenen asist {_comma(xa)}"
                + (f", gerçekleşen {_comma(assists)}" if assists else "")
                + "."
            )
    return " ".join(bits)


def compare_verdict(left: dict, right: dict) -> list[str]:
    a_name = (left.get("player") or {}).get("name") or "Birinci"
    b_name = (right.get("player") or {}).get("name") or "İkinci"
    a = left.get("player") or {}
    b = right.get("player") or {}
    lines = []
    ta, tb = _n(a.get("true_value")), _n(b.get("true_value"))
    ma, mb = _n(a.get("tm_value")), _n(b.get("tm_value"))
    ga, gb = _n(a.get("gap_pct")), _n(b.get("gap_pct"))
    if ta and tb:
        if ta > tb * 1.08:
            lines.append(
                f"Aurea, {a_name} üretimini {format_eur(ta)} ile {b_name} üzerinde ({format_eur(tb)}) okuyor."
            )
        elif tb > ta * 1.08:
            lines.append(
                f"Aurea, {b_name} üretimini {format_eur(tb)} ile {a_name} üzerinde ({format_eur(ta)}) okuyor."
            )
        else:
            lines.append(
                f"Aurea iki ismi yakın tutuyor: {a_name} {format_eur(ta)}, {b_name} {format_eur(tb)}."
            )
    if ma and mb and ta and tb:
        cheap_a = ga <= GAP_CHEAP
        cheap_b = gb <= GAP_CHEAP
        if cheap_a and not cheap_b:
            lines.append(f"Piyasa {a_name} için daha geniş bir boşluk bırakmış; etiket üretime göre daha ucuz.")
        elif cheap_b and not cheap_a:
            lines.append(f"Piyasa {b_name} için daha geniş bir boşluk bırakmış; etiket üretime göre daha ucuz.")
        elif ga >= GAP_RICH and gb < GAP_RICH * 0.5:
            lines.append(f"{a_name} etiketinde prim daha belirgin; büyük ligde bu sık görülür.")
        elif gb >= GAP_RICH and ga < GAP_RICH * 0.5:
            lines.append(f"{b_name} etiketinde prim daha belirgin; büyük ligde bu sık görülür.")
    pa, pb = _n(a.get("contrib_p90")), _n(b.get("contrib_p90"))
    if pa or pb:
        lines.append(
            f"90 dakikada gol ve asist: {a_name} {_comma(pa)}, {b_name} {_comma(pb)}."
        )
    ya, yb = a.get("age"), b.get("age")
    if ya and yb:
        lines.append(f"Yaş: {a_name} {int(ya)}, {b_name} {int(yb)}.")
    fa = ((left.get("live") or {}).get("fotmob") or {})
    fb = ((right.get("live") or {}).get("fotmob") or {})
    xa = _xg_read(
        a_name,
        _n(fa.get("xg")),
        _n(fa.get("goals")),
        _n(fa.get("xa")),
        _n(fa.get("assists")),
        shots=_n(fa.get("shots")),
        apps=_n(fa.get("apps")),
    )
    xb = _xg_read(
        b_name,
        _n(fb.get("xg")),
        _n(fb.get("goals")),
        _n(fb.get("xa")),
        _n(fb.get("assists")),
        shots=_n(fb.get("shots")),
        apps=_n(fb.get("apps")),
    )
    if xa:
        lines.append(xa)
    if xb:
        lines.append(xb)
    xga, xgb = _n(fa.get("xg")), _n(fb.get("xg"))
    if xga and xgb:
        if xga > xgb * 1.15:
            lines.append(f"Şans yaratımı {a_name} lehine: {_comma(xga)} xG’ye karşı {_comma(xgb)}.")
        elif xgb > xga * 1.15:
            lines.append(f"Şans yaratımı {b_name} lehine: {_comma(xgb)} xG’ye karşı {_comma(xga)}.")
    sa, sb = int(_n(fa.get("shots"))), int(_n(fb.get("shots")))
    if sa or sb:
        lines.append(f"Şut hacmi: {a_name} {sa}, {b_name} {sb}.")
    if not lines:
        lines.append("Karşılaştırma için iki dosyada da yeterli tutar yok.")
    return lines

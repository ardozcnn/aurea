"""Süper Lig transfer masası: bedel, Aurea değeri, üretim ve sakatlık."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from app.config import SUB_POSITION_TR, TM_WEB
from app.live_tm import (
    _get_cache,
    _get_html,
    _player_id_from_href,
    _scrape_injuries,
    _set_cache,
    club_overlay_put,
    parse_euro,
)
from app.money import format_eur
from app.store import json_safe

_DESK_TTL = 12 * 60
_INJ_TTL = 12 * 3600
_SERIOUS = (
    "cruciate",
    "kreuzband",
    "çapraz",
    "acl",
    "rupture",
    "yırtık",
    "fracture",
    "kırık",
    "achilles",
    "aşil",
    "cancer",
    "kanser",
    "heart",
    "kalp",
    "meniscus",
    "menisk",
    "ligament",
    "bağ",
)

_KIND_TR = {
    "bedel": "Satın alma",
    "kiralik": "Kiralık",
    "bedelsiz": "Bedelsiz",
    "belirsiz": "Bedel açıklanmadı",
}

_VERDICT_TR = {
    "firsat": "Fırsat",
    "uygun": "Uygun",
    "pahali": "Pahalı",
    "riskli": "Riskli",
}


def _season_id() -> int:
    now = datetime.now()
    return now.year if now.month >= 7 else now.year - 1


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        n = float(value)
        if n != n:
            return default
        return n
    except (TypeError, ValueError):
        return default


def _season_in_title(title: str, season: int) -> bool:
    raw = (title or "").lower()
    found = re.findall(r"(\d{2})\s*/\s*(\d{2})", raw)
    if found:
        yy = f"{season % 100:02d}"
        nxt = f"{(season + 1) % 100:02d}"
        return any(a == yy and b == nxt for a, b in found)
    if str(season) in raw and str(season + 1) in raw:
        return True
    return not bool(re.search(r"20\d{2}|\d{2}\s*/\s*\d{2}", raw))


def _is_arrivals(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in ("arrival", "gelen", "zugänge", "zugaenge", "zugange", "arrivals"))


def _is_departures(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in ("departure", "giden", "abgänge", "abgaenge", "abgang", "departures"))


def _fee_listed(kind: str, fee: int | None) -> bool:
    if kind in {"skip", "belirsiz"}:
        return False
    if fee is None and kind != "bedelsiz":
        return False
    return True


def _parse_fee(text: str) -> tuple[str, int | None]:
    raw = (text or "").replace("\xa0", " ").strip()
    low = raw.lower()
    if not raw or raw in {"-", "–"}:
        return "belirsiz", None
    if "end of loan" in low or "leihende" in low or "kiralık sonu" in low:
        return "skip", None
    if "loan fee" in low or "leihgebühr" in low:
        return "kiralik", parse_euro(raw)
    if "loan" in low or "leihe" in low or "kiralık" in low:
        fee = parse_euro(raw)
        return "kiralik", fee
    if any(w in low for w in ("free", "ablösefrei", "bedelsiz", "ücretsiz")):
        return "bedelsiz", 0
    if raw in {"?", "–", "n/a"}:
        return "belirsiz", None
    fee = parse_euro(raw)
    if fee is None:
        return "belirsiz", None
    return "bedel", fee


def _club_name(box) -> str:
    link = box.select_one("h2 a[title]")
    if link and link.get("title"):
        return str(link.get("title")).replace("Array", "").strip()
    headline = box.select_one("h2")
    return headline.get_text(" ", strip=True) if headline else ""


def _club_crest(box) -> str:
    img = box.select_one("h2 img")
    return str(img.get("src") or "") if img else ""


def _spend(box) -> int | None:
    blob = box.select_one(".transfer-zusatzinfo-box")
    if not blob:
        return None
    text = blob.get_text(" ", strip=True)
    match = re.search(r"Expenditure:\s*([€\d.,a-zA-Z]+)", text, re.I)
    if not match:
        match = re.search(r"Harcama:\s*([€\d.,a-zA-Z]+)", text, re.I)
    return parse_euro(match.group(1)) if match else None


def _player_cell(td) -> tuple[str, str | None]:
    for link in td.select("a"):
        href = link.get("href") or ""
        if "/spieler/" not in href:
            continue
        parent = " ".join(link.parent.get("class") or []) if link.parent else ""
        if "show-for-small" in parent:
            continue
        name = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
        return name, href
    return td.get_text(" ", strip=True), None


def _scrape_season(season: int) -> dict[str, Any]:
    html = _get_html(
        f"/super-lig/transfers/wettbewerb/TR1/plus/?saison_id={season}&leihe=1&intern=0"
    )
    soup = BeautifulSoup(html, "lxml")
    clubs: list[dict[str, Any]] = []
    arrivals: list[dict[str, Any]] = []
    for box in soup.select("div.box"):
        tables = box.select("div.responsive-table table")
        if not tables:
            continue
        club = _club_name(box)
        if not club:
            continue
        clubs.append(
            {
                "club": club,
                "crest": _club_crest(box),
                "spend": _spend(box),
                "spend_label": format_eur(_spend(box)),
            }
        )
        table = tables[0]
        heads = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
        if heads and not any("in" == h or "gelen" in h for h in heads[:1]):
            continue
        for tr in table.select("tbody tr"):
            tds = tr.select("td")
            if len(tds) < 6:
                continue
            name, href = _player_cell(tds[0])
            pid = _player_id_from_href(href)
            if not name or not pid:
                continue
            fee_text = tds[-1].get_text(" ", strip=True)
            kind, fee = _parse_fee(fee_text)
            if not _fee_listed(kind, fee):
                continue
            left = ""
            for td in tds:
                cls = " ".join(td.get("class") or [])
                if "verein-flagge" in cls:
                    left = td.get_text(" ", strip=True)
                    break
            mv = parse_euro(tr.select_one(".mw-transfer-cell").get_text(" ", strip=True) if tr.select_one(".mw-transfer-cell") else "")
            age_txt = tr.select_one(".alter-transfer-cell")
            pos = tr.select_one(".pos-transfer-cell")
            try:
                age = int(re.sub(r"\D", "", age_txt.get_text() if age_txt else "") or 0) or None
            except ValueError:
                age = None
            arrivals.append(
                {
                    "player_id": int(pid),
                    "name": name,
                    "age": age,
                    "position": (pos.get_text(" ", strip=True) if pos else ""),
                    "club": club,
                    "left": left,
                    "kind": kind,
                    "fee": fee,
                    "fee_label": format_eur(fee) if fee else ("Bedelsiz" if kind == "bedelsiz" else ("Kiralık" if kind == "kiralik" else "—")),
                    "tm_value": mv,
                    "tm_label": format_eur(mv),
                    "fee_raw": fee_text,
                }
            )
    return {"season": season, "clubs": clubs, "arrivals": arrivals}


def _scrape_latest_feed() -> tuple[dict[int, str], list[dict[str, Any]]]:
    dates: dict[int, str] = {}
    extras: list[dict[str, Any]] = []
    try:
        html = _get_html("/statistik/neuestetransfers?land_id=174&plus=1")
    except Exception:
        return dates, extras
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if not table:
        return dates, extras
    seen: set[int] = set()
    for tr in table.select("tbody tr"):
        blob = tr.get_text(" ", strip=True)
        if "Süper Lig" not in blob and "Super Lig" not in blob:
            continue
        href = ""
        name = ""
        for link in tr.select("a"):
            h = link.get("href") or ""
            if "/spieler/" in h:
                href = h
                name = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
                break
        pid = _player_id_from_href(href)
        if not pid or not name:
            continue
        pid_i = int(pid)
        found = re.search(r"(\d{2}/\d{2}/20\d{2})", blob)
        date = found.group(1) if found else ""
        if date:
            dates[pid_i] = date
        if pid_i in seen:
            continue
        seen.add(pid_i)
        tds = tr.select("td")
        fee_text = ""
        for td in reversed(tds):
            t = td.get_text(" ", strip=True)
            low = t.lower()
            if "€" in t or "loan" in low or "leihe" in low or "free" in low or "ablöse" in low or "bedelsiz" in low:
                fee_text = t
                break
        if not fee_text and tds:
            fee_text = tds[-1].get_text(" ", strip=True)
        kind, fee = _parse_fee(fee_text)
        if not _fee_listed(kind, fee):
            continue
        clubs: list[str] = []
        for link in tr.select("a"):
            h = link.get("href") or ""
            if "/verein/" in h:
                title = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
                if title and title not in clubs:
                    clubs.append(title)
        left = clubs[0] if clubs else ""
        club = clubs[-1] if clubs else ""
        age_txt = tr.select_one(".zentriert")
        age = None
        try:
            raw_age = re.sub(r"\D", "", age_txt.get_text() if age_txt else "")
            age = int(raw_age) if raw_age else None
        except ValueError:
            age = None
        extras.append(
            {
                "player_id": pid_i,
                "name": name,
                "age": age,
                "position": "",
                "club": club,
                "left": left,
                "kind": kind,
                "fee": fee,
                "fee_label": format_eur(fee)
                if fee
                else ("Bedelsiz" if kind == "bedelsiz" else ("Kiralık" if kind == "kiralik" else "—")),
                "tm_value": None,
                "tm_label": "—",
                "fee_raw": fee_text,
                "date": date,
                "fresh": True,
            }
        )
    return dates, extras


def _scrape_latest_dates(season: int) -> dict[int, str]:
    dates, _extras = _scrape_latest_feed()
    return dates


def _injuries(player_id: int) -> list[dict[str, Any]]:
    key = f"injuries:{player_id}"
    cached = _get_cache(key)
    if cached is not None:
        return cached if isinstance(cached, list) else []
    rows = _scrape_injuries(str(player_id))
    _set_cache(key, rows, ttl=_INJ_TTL)
    return rows


def _injury_season_ok(label: str, floor: int) -> bool:
    text = str(label or "")
    found = re.search(r"(20)?(\d{2})\s*/\s*(\d{2})", text)
    if found:
        return int(found.group(2)) >= floor
    found = re.search(r"20(\d{2})", text)
    if found:
        return int(found.group(1)) >= floor
    return True


def _injury_digest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    days = 0
    missed = 0
    serious = []
    open_now = False
    recent = []
    floor = (_season_id() % 100) - 2
    for item in rows[:14]:
        if not _injury_season_ok(str(item.get("season") or ""), floor):
            continue
        d = int(item.get("days") or 0)
        m = int(item.get("gamesMissed") or 0)
        days += d
        missed += m
        label = str(item.get("injury") or "")
        until = item.get("untilDate")
        cur = _season_id() % 100
        if until in (None, "", "-", "None") and _injury_season_ok(str(item.get("season") or ""), cur):
            open_now = True
        low = label.lower()
        if any(word in low for word in _SERIOUS):
            serious.append(label)
        recent.append(
            {
                "injury": label,
                "season": item.get("season"),
                "days": d,
                "missed": m,
            }
        )
    return {
        "days": days,
        "missed": missed,
        "open": open_now,
        "serious": serious[:3],
        "recent": recent[:4],
    }


def _lookup(player_id: int, name: str) -> dict[str, Any]:
    from app.store import universe

    df = universe()
    hit = df[df["player_id"] == player_id]
    if hit.empty and name:
        needle = name.strip().lower()
        names = df["name"].astype("string").str.lower()
        hit = df[names == needle]
        if hit.empty:
            hit = df[names.str.contains(needle, regex=False, na=False)]
    if hit.empty:
        return {}
    row = hit.iloc[0]
    return {
        "player_id": int(row.get("player_id")),
        "true_value": None if row.get("true_value") != row.get("true_value") else _num(row.get("true_value"), 0) or None,
        "fair_value": None if row.get("fair_value") != row.get("fair_value") else _num(row.get("fair_value"), 0) or None,
        "tm_stored": None if row.get("market_value_in_eur") != row.get("market_value_in_eur") else _num(row.get("market_value_in_eur"), 0) or None,
        "minutes_365": _num(row.get("minutes_365")),
        "minutes_2y": _num(row.get("minutes_2y")),
        "apps_2y": _num(row.get("apps_2y")),
        "goals_2y": _num(row.get("goals_2y")),
        "assists_2y": _num(row.get("assists_2y")),
        "contrib_p90": _num(row.get("contrib_p90")),
        "contract_years": _num(row.get("contract_years"), 1.5),
        "peak": _num(row.get("highest_market_value_in_eur")),
        "position_group": str(row.get("position") or ""),
        "age_stored": None if row.get("age") != row.get("age") else int(round(_num(row.get("age")))),
    }


def _offer_band(market: float | None, fee: int | None = None) -> str:
    if not market or market < 250_000:
        return ""
    lo = market * 0.75
    hi = market * 0.95
    if fee and fee < lo:
        return f"Tavan {format_eur(hi)}; ödenen bedel bunun altında."
    return f"Bu profil için makul bedel {format_eur(lo)} – {format_eur(hi)}."


def _in_season(date_str: str, season: int) -> bool:
    found = re.search(r"(\d{2})/(\d{2})/(20\d{2})", str(date_str or ""))
    if not found:
        return False
    day, month, year = int(found.group(1)), int(found.group(2)), int(found.group(3))
    start = (season, 7, 1)
    end = (season + 1, 6, 30)
    return start <= (year, month, day) <= end


def _analyze(deal: dict[str, Any]) -> dict[str, Any]:
    kind = deal.get("kind") or "belirsiz"
    fee = deal.get("fee")
    tm = _num(deal.get("tm_value")) or _num(deal.get("tm_stored"))
    true = _num(deal.get("true_value")) or None
    age = deal.get("age") or deal.get("age_stored")
    minutes = _num(deal.get("minutes_365"))
    minutes_2y = _num(deal.get("minutes_2y"))
    apps = _num(deal.get("apps_2y"))
    goals = _num(deal.get("goals_2y"))
    assists = _num(deal.get("assists_2y"))
    contrib = _num(deal.get("contrib_p90"))
    inj = deal.get("injury") or {}
    days = int(inj.get("days") or 0)
    missed = int(inj.get("missed") or 0)
    open_now = bool(inj.get("open"))
    serious = inj.get("serious") or []
    pos = deal.get("position") or ""
    pos_tr = SUB_POSITION_TR.get(pos, pos)
    club = deal.get("club") or ""
    left = deal.get("left") or ""
    name = deal.get("name") or "Oyuncu"

    vs_tm = (float(fee) / tm) if fee and tm and tm > 0 else None
    vs_true = (float(fee) / true) if fee and true and true > 0 else None
    compressed = bool(true and tm and true < tm * 0.68)
    ratio = vs_tm if vs_tm is not None else vs_true
    thin = minutes < 700 and minutes_2y < 1400
    dry = contrib <= 0.18 and str(deal.get("position_group") or "") in {"Attack", "Midfield"} and minutes_2y >= 800
    old = bool(age and age >= 32)
    young = bool(age and age <= 25)
    peak_age = bool(age and 22 <= age <= 27)
    productive = bool(
        minutes_2y >= 1400
        and (
            contrib >= 0.45
            or (str(deal.get("position_group") or "") == "Attack" and goals >= 12)
        )
    )
    hurt = days >= 70 or missed >= 22 or open_now or bool(serious)
    very_hurt = days >= 120 or missed >= 35 or len(serious) >= 2
    free_asset = bool(kind == "bedelsiz" and young and minutes_2y >= 800 and not hurt and not thin)
    verdict = "uygun"
    if kind == "kiralik":
        if very_hurt or (old and thin) or (open_now and fee and fee >= 1_500_000):
            verdict = "riskli"
        elif young and not hurt and not thin and minutes >= 900:
            verdict = "firsat"
        else:
            verdict = "uygun"
    elif kind == "bedelsiz":
        if very_hurt or (old and thin) or (hurt and old):
            verdict = "riskli"
        elif free_asset:
            verdict = "firsat"
        else:
            verdict = "uygun"
    elif kind == "belirsiz" or fee is None:
        if very_hurt or (hurt and old):
            verdict = "riskli"
        elif young and minutes >= 1200 and not hurt:
            verdict = "firsat"
        else:
            verdict = "uygun"
    else:
        if very_hurt or (open_now and bool(serious)):
            verdict = "riskli"
        elif hurt and (old or thin) and (vs_tm is None or vs_tm >= 0.95):
            verdict = "riskli"
        elif vs_tm is not None and vs_tm <= 0.88 and not hurt and not old:
            verdict = "firsat"
        elif vs_tm is not None and vs_tm <= 1.08:
            if (young or peak_age) and productive and not hurt:
                verdict = "firsat"
            else:
                verdict = "uygun"
        elif compressed:
            if vs_tm is not None and vs_tm >= 1.32:
                verdict = "pahali"
            else:
                verdict = "uygun"
        elif old and fee >= 10_000_000 and (thin or dry):
            verdict = "pahali"
        elif vs_tm is not None and vs_tm >= 1.35:
            verdict = "pahali"
        elif vs_true is not None and vs_true >= 1.55 and (vs_tm is None or vs_tm >= 1.22):
            verdict = "pahali"
        else:
            verdict = "uygun"

    bits: list[str] = []
    if kind == "kiralik":
        if fee:
            bits.append(f"{club}, {name} için kiralama bedeli {format_eur(fee)} ödüyor.")
        else:
            bits.append(f"{club}, {name} ile kiralama yaptı; kiralama bedeli açıklanmadı.")
        bits.append("Kiralıkta asıl yük çoğu zaman maaş ve satın alma hakkıdır.")
        if tm:
            bits.append(f"Transfermarkt {format_eur(tm)}.")
        if true:
            bits.append(f"Aurea değeri {format_eur(true)}.")
    elif kind == "bedelsiz":
        bits.append(
            f"{club}, {name} adlı oyuncuyu bedelsiz kadrosuna kattı. "
            "Transfer ücreti yok; yük maaş ve sözleşmedir."
        )
        if tm:
            bits.append(f"Transfermarkt {format_eur(tm)}.")
        if true:
            bits.append(f"Aurea değeri {format_eur(true)}.")
    elif fee:
        bits.append(f"{club}, {name} için {format_eur(fee)} ödedi.")
        if left:
            bits.append(f"{left} takımından geldi.")
        if tm:
            bits.append(f"Transfermarkt {format_eur(tm)}.")
        if true:
            bits.append(f"Aurea değeri {format_eur(true)}.")
        offer = _offer_band(tm or true, fee)
        if offer:
            bits.append(offer)
        if vs_tm is not None and vs_tm <= 1.05 and tm:
            bits.append("Ödenen bedel, piyasa etiketinin içinde veya altında.")
        elif vs_tm is not None and vs_tm >= 1.25 and tm:
            bits.append("Ödenen bedel, piyasa etiketinin belirgin üstünde.")
    else:
        bits.append(f"{club} kadrosuna {name} katıldı; bedel açıklanmadı.")
        if tm:
            bits.append(f"Transfermarkt {format_eur(tm)}.")
        if true:
            bits.append(f"Aurea değeri {format_eur(true)}.")

    if age:
        if age <= 22:
            bits.append(f"{age} yaşında; değerin bir kısmı gelecek dakikaya yazılır.")
        elif age <= 27:
            bits.append(f"{age} yaşında; en verimli döneme yakın.")
        elif age <= 31:
            bits.append(f"{age} yaşında; bedel mevcut oyuna dayanmalıdır.")
        else:
            bits.append(f"{age} yaşında; yüksek bedel kısa süreli net oyunla savunulur.")

    if minutes_2y or minutes:
        bits.append(
            f"Son iki sezon {int(apps)} maç, {int(goals)} gol, {int(assists)} asist, {int(minutes_2y)} dakika. "
            f"Son 12 ayda {int(minutes)} dakika."
        )
        if thin:
            bits.append("Dakika az; bedel oyundan kopuk olabilir.")
        elif productive:
            bits.append("Gol ve asist temposu bu bedeli taşır.")
        elif dry:
            bits.append("Hücum üretimi mevkisine göre zayıf.")

    if days or missed or open_now:
        bits.append(
            f"Sakatlık: {days} gün, {missed} maç kaçırma."
            + (" Açık sakatlık var." if open_now else "")
        )
        if very_hurt:
            bits.append("Bu geçmiş yüksek bedeli tek başına bozar.")

    if verdict == "pahali":
        headline = "Ödenen bedel, piyasa etiketinin üzerinde."
    elif verdict == "riskli":
        headline = "Sağlık, yaş veya dakika bu hamleyi zayıflatır."
    elif verdict == "firsat":
        if kind == "bedelsiz":
            headline = "Bedelsiz ve oynuyor; ücret dışında yük yok."
        elif kind == "kiralik":
            headline = "Kiralık. Yaş ve sağlık tutuyor."
        else:
            headline = "Bedel, piyasa etiketi ve oyuna göre düşük."
    else:
        if kind == "kiralik":
            headline = "Kiralık. Süre ve sağlık tutuyorsa uygun."
        elif kind == "bedelsiz":
            headline = "Bedelsiz. Hüküm maaş ve dakikaya kalır."
        elif fee is None:
            headline = "Bedel açıklanmadı."
        else:
            headline = "Bedel, piyasa etiketiyle aynı bantta."

    return {
        "verdict": verdict,
        "verdict_label": _VERDICT_TR.get(verdict, "Uygun"),
        "kind_label": _KIND_TR.get(kind, kind),
        "headline": headline,
        "body": " ".join(bits),
        "ratio": round(ratio, 2) if ratio is not None else None,
        "position_tr": pos_tr,
        "wage_label": "Açıklanmadı",
    }


def _enrich(deal: dict[str, Any], with_injury: bool) -> dict[str, Any]:
    extra = _lookup(int(deal["player_id"]), str(deal.get("name") or ""))
    out = {**deal, **{k: v for k, v in extra.items() if v is not None or k == "true_value"}}
    if extra.get("true_value"):
        out["true_value"] = extra["true_value"]
        out["true_label"] = format_eur(extra["true_value"])
    else:
        out["true_label"] = "—"
    if extra.get("fair_value"):
        out["fair_value"] = extra["fair_value"]
    if with_injury:
        inj_rows = _injuries(int(deal["player_id"]))
        out["injury"] = _injury_digest(inj_rows)
    else:
        out["injury"] = {"days": 0, "missed": 0, "open": False, "serious": [], "recent": []}
    judged = _analyze(out)
    out.update(judged)
    pid = extra.get("player_id") or out.get("player_id")
    from app.slugs import player_path

    out["href"] = player_path(pid, out.get("name")) if pid else f"/ara?q={out.get('name') or ''}"
    tm = extra.get("tm_stored") or out.get("tm_value") or deal.get("tm_value")
    if tm:
        out["tm_value"] = tm
        out["tm_label"] = format_eur(tm)
    else:
        out["tm_label"] = out.get("tm_label") or "—"
    return out


def _recency(deal: dict[str, Any]) -> int:
    found = re.search(r"(\d{2})/(\d{2})/(20\d{2})", str(deal.get("date") or ""))
    if not found:
        return 0
    return int(found.group(3) + found.group(2) + found.group(1))


def _priority(deal: dict[str, Any]) -> tuple:
    fee = deal.get("fee") or 0
    tm = deal.get("tm_value") or 0
    kind = deal.get("kind")
    rank = 0 if kind == "bedel" and fee else 1 if kind == "kiralik" else 2
    return (-_recency(deal), rank, -(fee or 0), -(tm or 0))


def desk(*, refresh: bool = False) -> dict[str, Any]:
    season = _season_id()
    key = f"superlig:desk:{season}:v8"
    if not refresh:
        cached = _get_cache(key)
        if cached:
            return cached
    scraped = _scrape_season(season)
    dates, extras = _scrape_latest_feed()
    arrivals = scraped["arrivals"]
    have = {int(row["player_id"]) for row in arrivals}
    for row in extras:
        pid = int(row["player_id"])
        if pid in have:
            continue
        if not _in_season(str(row.get("date") or ""), season):
            continue
        arrivals.append(row)
        have.add(pid)
    for row in arrivals:
        if row["player_id"] in dates:
            row["date"] = dates[row["player_id"]]
    ranked = sorted(arrivals, key=_priority)
    deep_ids: set[int] = set()
    for row in ranked:
        if _recency(row) and len(deep_ids) < 12:
            deep_ids.add(int(row["player_id"]))
    for row in ranked:
        fee = row.get("fee") or 0
        tm = row.get("tm_value") or 0
        if len(deep_ids) >= 32:
            break
        if fee >= 400_000 or tm >= 2_500_000 or row.get("kind") == "bedel" or row.get("fresh"):
            deep_ids.add(int(row["player_id"]))
    to_deep = [row for row in ranked if int(row["player_id"]) in deep_ids][:32]
    rest = [row for row in ranked if int(row["player_id"]) not in deep_ids]

    enriched: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_enrich, row, True) for row in to_deep]
        for fut in futures:
            try:
                enriched.append(fut.result())
            except Exception:
                continue
    light = []
    for row in rest[:40]:
        try:
            light.append(_enrich(row, False))
        except Exception:
            continue
    deals = sorted(enriched, key=_priority) + sorted(light, key=_priority)
    counts = {}
    for row in deals:
        counts[row.get("verdict") or "uygun"] = counts.get(row.get("verdict") or "uygun", 0) + 1
    spenders = sorted(
        [c for c in scraped["clubs"] if c.get("spend")],
        key=lambda c: int(c.get("spend") or 0),
        reverse=True,
    )
    payload = {
        "ok": True,
        "season": f"{season}/{str(season + 1)[2:]}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": f"{TM_WEB}/super-lig/transfers/wettbewerb/TR1",
        "clubs": spenders[:10],
        "deals": deals[:56],
        "counts": counts,
        "note": "",
    }
    _set_cache(key, payload, ttl=_DESK_TTL)
    return json_safe(payload)


def _direct_rows(table):
    body = table.find("tbody") if table is not None else None
    if body is None:
        return []
    return [tr for tr in body.find_all("tr", recursive=False)]


def _main_move_table(box):
    return box.select_one("table.items") or box.select_one("div.responsive-table > table")


def _row_player(row) -> tuple[str, str | None]:
    fallback: tuple[str, str | None] | None = None
    for link in row.select("a"):
        href = link.get("href") or ""
        if "/spieler/" not in href:
            continue
        parent = " ".join(link.parent.get("class") or []) if link.parent else ""
        if "show-for-small" in parent:
            continue
        name = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
        if not name:
            continue
        if "/profil/spieler/" in href:
            return name, href
        if fallback is None:
            fallback = (name, href)
    return fallback or ("", None)


def _parse_move_table(table, club: str, side: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tr in _direct_rows(table):
        tds = tr.find_all("td", recursive=False) or tr.select("td")
        if len(tds) < 3:
            continue
        name, href = _row_player(tr)
        pid = _player_id_from_href(href)
        if not name or name.lower() in {"player", "oyuncu"}:
            continue
        key = pid or name
        if key in seen:
            continue
        seen.add(key)
        fee_text = tds[-1].get_text(" ", strip=True)
        kind, fee = _parse_fee(fee_text)
        if not _fee_listed(kind, fee):
            continue
        other = ""
        for link in tr.find_all("a"):
            h = link.get("href") or ""
            if "/verein/" not in h:
                continue
            title = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
            if title and title.lower() != (club or "").lower():
                other = title
                break
        age = None
        age_cell = tr.select_one(".alter-transfer-cell")
        if age_cell is None and len(tds) >= 3:
            age_cell = tds[2]
        try:
            age = int(re.sub(r"\D", "", age_cell.get_text() if age_cell else "") or 0) or None
        except (ValueError, AttributeError):
            age = None
        if age is not None and not 15 <= age <= 50:
            age = None
        date = ""
        date_el = tr.select_one(".datum-transfer-cell")
        blob = date_el.get_text(" ", strip=True) if date_el else tr.get_text(" ", strip=True)
        found_date = re.search(r"(\d{2}/\d{2}/20\d{2})", blob)
        if found_date:
            date = found_date.group(1)
        pid_i = int(pid) if pid else None
        mw_el = tr.select_one(".mw-transfer-cell")
        tm_val = parse_euro(mw_el.get_text(" ", strip=True)) if mw_el else None
        if tm_val is None:
            for td in tds[1:-1]:
                txt = td.get_text(" ", strip=True)
                if "€" not in txt:
                    continue
                parsed = parse_euro(txt)
                if parsed:
                    tm_val = parsed
                    break
        rows.append(
            {
                "player_id": pid_i,
                "name": name,
                "age": age,
                "club": club,
                "other": other,
                "side": side,
                "kind": kind,
                "fee": fee,
                "fee_label": format_eur(fee)
                if fee
                else ("Bedelsiz" if kind == "bedelsiz" else ("Kiralık" if kind == "kiralik" else "—")),
                "tm_value": tm_val,
                "tm_label": format_eur(tm_val) if tm_val else "—",
                "href": f"/oyuncu/{pid_i}" if pid_i else f"/ara?q={name}",
                "date": date,
            }
        )
    return rows


def _keep_season_moves(rows: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    keep: list[dict[str, Any]] = []
    for row in rows:
        date = str(row.get("date") or "")
        if date and not _in_season(date, season):
            continue
        keep.append(row)
    return keep


def club_squad(club_id: int, name: str = "") -> list[dict[str, Any]]:
    season = _season_id()
    key = f"clubsquadrows:{int(club_id)}:{season}:v2"
    cached = _get_cache(key)
    if isinstance(cached, list) and cached:
        return cached
    from app.slugs import slugify

    slug = slugify(name) or "club"
    paths = [
        f"/{slug}/kader/verein/{int(club_id)}/saison_id/{season}/plus/1",
        f"/{slug}/kader/verein/{int(club_id)}/saison_id/{season}",
        f"/kader/verein/{int(club_id)}/saison_id/{season}",
    ]
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for path in paths:
        try:
            html = _get_html(path)
            soup = BeautifulSoup(html, "lxml")
            table = soup.select_one("table.items")
            if table is None:
                continue
            for tr in table.select("tbody tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) < 5:
                    continue
                pname, href = _row_player(tr)
                pid = _player_id_from_href(href)
                if not pname or not pid:
                    continue
                num = int(pid)
                if num in seen:
                    continue
                seen.add(num)
                pos = ""
                box = tr.select_one(".inline-table") or tr.select_one(".posrela")
                if box is not None:
                    bits = [x.get_text(" ", strip=True) for x in box.select("td") if x.get_text(" ", strip=True)]
                    if len(bits) >= 2:
                        pos = bits[-1]
                age = None
                for cell in tr.select("td.zentriert"):
                    raw = re.sub(r"\D", "", cell.get_text() or "")
                    if not raw:
                        continue
                    try:
                        n = int(raw)
                    except ValueError:
                        continue
                    if 15 <= n <= 50:
                        age = n
                        break
                tm_val = None
                joined = ""
                for td in tds:
                    txt = td.get_text(" ", strip=True)
                    if "€" in txt:
                        parsed = parse_euro(txt)
                        if parsed:
                            tm_val = parsed
                    if joined or re.search(r"\(\d{1,2}\)", txt):
                        continue
                    found_join = re.search(
                        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2}|\d{2}/\d{2}/20\d{2})",
                        txt,
                        re.I,
                    )
                    if found_join:
                        joined = found_join.group(1)
                rows.append(
                    {
                        "player_id": num,
                        "name": pname,
                        "position": pos,
                        "age": age,
                        "tm_value": tm_val,
                        "joined": joined,
                    }
                )
            if len(rows) >= 8:
                break
        except Exception:
            continue
    if rows:
        _set_cache(key, rows, ttl=6 * 3600)
    return rows


def club_squad_ids(club_id: int, name: str = "") -> list[int]:
    return [int(r["player_id"]) for r in club_squad(club_id, name) if r.get("player_id")]


def club_moves(club_id: int, name: str = "") -> dict[str, Any]:
    season = _season_id()
    key = f"clubmoves:{int(club_id)}:{season}:v9"
    cached = _get_cache(key)
    if isinstance(cached, dict) and (cached.get("in") or cached.get("empty")):
        return cached
    from app.slugs import slugify

    slug = slugify(name) or "club"
    incoming: list[dict[str, Any]] = []
    outgoing: list[dict[str, Any]] = []
    paths = [
        f"/{slug}/transfers/verein/{int(club_id)}/saison_id/{season}/plus/1",
        f"/transfers/verein/{int(club_id)}/saison_id/{season}/plus/1",
        f"/{slug}/transfers/verein/{int(club_id)}/plus/1?saison_id={season}",
    ]
    for path in paths:
        try:
            html_key = f"clubmoves-html:{int(club_id)}:{season}:{path}:v5"
            html = _get_cache(html_key)
            if not isinstance(html, str) or len(html) < 400:
                html = _get_html(path)
                _set_cache(html_key, html, ttl=6 * 3600)
            soup = BeautifulSoup(html, "lxml")
            boxes = soup.select("div.box")
            for box in boxes:
                head = box.select_one("h2")
                title = head.get_text(" ", strip=True) if head else ""
                if not _season_in_title(title, season):
                    continue
                table = _main_move_table(box)
                if table is None:
                    continue
                if _is_arrivals(title):
                    incoming.extend(_parse_move_table(table, name, "in"))
                elif _is_departures(title):
                    outgoing.extend(_parse_move_table(table, name, "out"))
            if incoming or outgoing:
                break
        except Exception:
            incoming = []
            outgoing = []
    try:
        extra_dates = _scrape_latest_dates(season)
    except Exception:
        extra_dates = {}
    for row in incoming + outgoing:
        pid = row.get("player_id")
        if pid and not row.get("date") and int(pid) in extra_dates:
            row["date"] = extra_dates[int(pid)]
    incoming = _keep_season_moves(incoming, season)
    outgoing = _keep_season_moves(outgoing, season)
    judged_in = []
    for row in incoming[:40]:
        pid = row.get("player_id")
        if pid:
            club_overlay_put(pid, club_id=club_id, club_name=name)
            try:
                judged_in.append(_enrich(row, False))
                continue
            except Exception:
                pass
        judged_in.append(row)
    judged_out = []
    for row in outgoing[:40]:
        pid = row.get("player_id")
        if pid:
            club_overlay_put(pid, club_name=str(row.get("other") or ""))
        judged_out.append(row)
    payload = {
        "season": f"{season}/{str(season + 1)[2:]}",
        "in": judged_in,
        "out": judged_out,
        "empty": not judged_in,
    }
    _set_cache(key, payload, ttl=30 * 60 if payload["empty"] else 6 * 3600)
    return json_safe(payload)

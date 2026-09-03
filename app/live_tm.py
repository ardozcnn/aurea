"""Canlı Transfermarkt: arama, profil, piyasa eğrisi ve kariyer."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import CACHE_SQLITE, DATA_DIR, TM_WEB, USER_AGENT
from app.money import format_eur

_LOCK = threading.Lock()
_FLIGHT_LOCK = threading.Lock()
_FLIGHT: dict[str, dict[str, Any]] = {}
_TTL = 90
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE_SQLITE)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires REAL NOT NULL
        )
        """
    )
    return con


def _get_cache(key: str) -> Any | None:
    with _LOCK:
        con = _db()
        try:
            row = con.execute("SELECT payload, expires FROM kv WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            payload, expires = row
            if expires < time.time():
                return None
            return json.loads(payload)
        finally:
            con.close()


def _empty_career() -> dict[str, Any]:
    return {
        "current": [],
        "former": [],
        "youth": [],
        "fee_sum": None,
        "fee_sum_label": "",
    }


def _wait_fut(fut, fallback, timeout: float = 32.0):
    from concurrent.futures import TimeoutError as FuturesTimeout

    if fut is None:
        return fallback
    try:
        result = fut.result(timeout=timeout)
        return fallback if result is None else result
    except (httpx.HTTPError, TimeoutError, FuturesTimeout, ValueError, TypeError, json.JSONDecodeError):
        return fallback


def _bundle_has_body(bundle: dict[str, Any]) -> bool:
    if not isinstance(bundle, dict):
        return False
    profile = bundle.get("profile") or {}
    if profile.get("name") or profile.get("fullName"):
        return True
    career = bundle.get("career") or {}
    return bool(
        career.get("current")
        or career.get("former")
        or career.get("youth")
        or bundle.get("stats")
        or bundle.get("market_history")
    )


def _bundle_ready(bundle: dict[str, Any]) -> bool:
    return _bundle_has_body(bundle) and not bundle.get("partial")


def _career_has_wage(career: dict[str, Any]) -> bool:
    for section in ("current", "former"):
        for spell in career.get(section) or []:
            if spell.get("wage_annual"):
                return True
    return False


def _set_cache(key: str, payload: Any, ttl: float | None = None) -> None:
    with _LOCK:
        con = _db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO kv(key, payload, expires) VALUES (?, ?, ?)",
                (
                    key,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    time.time() + (ttl if ttl is not None else _TTL),
                ),
            )
            con.commit()
        finally:
            con.close()


def _client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=35.0, verify=False)


def _get_html(path: str) -> str:
    url = path if path.startswith("http") else f"{TM_WEB}{path}"
    with _client() as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _get_json(path: str, referer: str | None = None) -> dict:
    url = path if path.startswith("http") else f"{TM_WEB}{path}"
    headers = dict(_HEADERS)
    headers["Accept"] = "application/json"
    if referer:
        headers["Referer"] = referer if referer.startswith("http") else f"{TM_WEB}{referer}"
    for attempt in range(2):
        try:
            with _client() as client:
                response = client.get(url, headers=headers)
                if response.status_code >= 400:
                    if attempt == 0:
                        time.sleep(0.45)
                        continue
                    return {}
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            if attempt == 0:
                time.sleep(0.45)
                continue
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def parse_euro(text: str | None) -> int | None:
    if not text:
        return None
    raw = text.replace("\xa0", " ").strip()
    raw = re.split(r"Last update|Last Update|Son güncelleme", raw, maxsplit=1)[0]
    raw = raw.replace("€", "").strip().lower()
    if not raw or raw in {"-", "?"}:
        return None
    mult = 1.0
    if "bn" in raw or "mrd" in raw or "billion" in raw:
        mult = 1_000_000_000
        raw = re.sub(r"bn|mrd|billion", " ", raw, count=1)
    elif (
        "mio" in raw
        or "million" in raw
        or "mill" in raw
        or re.search(r"\bmil\.?\b", raw)
        or re.search(r"[\d.,]\s*m(?:\s|$)", raw)
    ):
        mult = 1_000_000
        raw = re.sub(r"mio|million|mill\.?|mil\.?|(?<=[\d.,])\s*m\b", " ", raw, count=1)
    elif (
        "thousand" in raw
        or re.search(r"\bth\.?\b", raw)
        or re.search(r"[\d.,]\s*k(?:\s|$)", raw)
        or (raw.endswith("k") and re.search(r"\d", raw))
    ):
        mult = 1_000
        raw = re.sub(r"thousand|th\.?|(?<=[\d.,])\s*k\b", " ", raw, count=1)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
        if mult == 1.0 and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
            raw = raw.replace(".", "")
    raw = raw.strip()
    raw = re.sub(r"[^0-9.]", "", raw)
    if not raw:
        return None
    try:
        return int(float(raw) * mult)
    except ValueError:
        return None


def _normal_market_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_euro(value)
        if parsed is not None:
            return parsed
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount <= 0:
        return None
    if amount < 1_000:
        return int(round(amount * 1_000_000))
    return int(round(amount))


_OVERLAY_MEM: dict[str, Any] | None = None
_OVERLAY_AT = 0.0
_OVERLAY_VER = 0


def club_overlay_stamp() -> float:
    return float(_OVERLAY_VER)


def club_overlay_get() -> dict[str, Any]:
    global _OVERLAY_MEM, _OVERLAY_AT, _OVERLAY_VER
    if _OVERLAY_MEM is not None and (time.time() - _OVERLAY_AT) < 45:
        return _OVERLAY_MEM
    raw = _get_cache("club-overlay:v1")
    new = raw if isinstance(raw, dict) else {}
    if _OVERLAY_MEM is None:
        _OVERLAY_MEM = new
    elif new != _OVERLAY_MEM:
        _OVERLAY_MEM = new
        _OVERLAY_VER += 1
    _OVERLAY_AT = time.time()
    return _OVERLAY_MEM


def club_overlay_put(
    player_id: Any,
    *,
    club_id: Any = None,
    club_name: str = "",
    league_id: str = "",
) -> None:
    global _OVERLAY_MEM, _OVERLAY_AT, _OVERLAY_VER
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return
    pack = dict(club_overlay_get())
    cid = None
    try:
        if club_id is not None and club_id == club_id:
            cid = int(float(club_id))
    except (TypeError, ValueError):
        cid = None
    pack[str(pid)] = {
        "club_id": cid,
        "club": str(club_name or "").strip(),
        "league_id": str(league_id or "").strip(),
    }
    _OVERLAY_MEM = pack
    _OVERLAY_AT = time.time()
    _OVERLAY_VER += 1
    _set_cache("club-overlay:v1", pack, ttl=30 * 24 * 3600)


def _player_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"/spieler/(\d+)", href)
    return match.group(1) if match else None


def search_players(query: str, page: int = 1) -> dict:
    q = (query or "").strip()
    if len(q) < 2:
        return {"results": []}
    key = f"search:{q.lower()}:{page}"
    cached = _get_cache(key)
    if cached is not None:
        return cached
    try:
        html = _get_html(f"/schnellsuche/ergebnis/schnellsuche?query={quote(q)}")
    except httpx.HTTPError:
        return {"results": []}
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("div.large-8 table.items") or soup.select_one("table.items")
    results = []
    seen = set()
    if table:
        for row in table.select("tbody tr"):
            link = row.select_one('a[href*="/profil/spieler/"]')
            if not link:
                continue
            pid = _player_id_from_href(link.get("href"))
            if not pid or pid in seen:
                continue
            seen.add(pid)
            cells = [td.get_text(" ", strip=True) for td in row.select("td")]
            club = ""
            position = ""
            age = None
            mv = None
            if len(cells) >= 5:
                club = cells[3] if len(cells) > 3 else ""
                position = cells[4] if len(cells) > 4 else ""
                try:
                    age = int(re.sub(r"\D", "", cells[6] or "") or 0) or None
                except (TypeError, ValueError):
                    age = None
                mv = parse_euro(cells[-1] if cells else "")
            results.append(
                {
                    "id": pid,
                    "name": link.get_text(" ", strip=True),
                    "position": position,
                    "club": {"id": None, "name": club},
                    "age": age,
                    "nationalities": [],
                    "marketValue": mv,
                }
            )
            if len(results) >= 12:
                break
    payload = {"query": q, "pageNumber": page, "results": results}
    _set_cache(key, payload)
    return payload


_YOUTH_CLUB = re.compile(
    r"yth\.?|u1[4-9]|u2[01]|jugend|youth|amateurs?|\bii\b|reserve|akademi|altyap",
    re.I,
)
_KIND_TR = {
    "bedel": "Satın alma",
    "kiralik": "Kiralık",
    "bedelsiz": "Bedelsiz",
    "belirsiz": "Bedel açıklanmadı",
    "donus": "Kiralık dönüş",
    "baslangic": "İlk kayıt",
}


def resolve_club_id(name: str) -> int | None:
    from app.slugs import club_query_hit, fold_tr

    q = str(name or "").strip()
    if len(q) < 2:
        return None
    key = f"clubid:{fold_tr(q)}:v1"
    cached = _get_cache(key)
    if isinstance(cached, int) and cached > 0:
        return cached
    try:
        html = _get_html(f"/schnellsuche/ergebnis/schnellsuche?query={quote(q)}")
    except Exception:
        return None
    soup = BeautifulSoup(html, "lxml")
    best: int | None = None
    best_rank = 9
    for link in soup.select("a[href*='/startseite/verein/']"):
        title = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
        folded = fold_tr(title)
        if _YOUTH_CLUB.search(folded):
            continue
        found = re.search(r"/verein/(\d+)", link.get("href") or "")
        if not found:
            continue
        rank = club_query_hit(title, q)
        if rank is None:
            continue
        cid = int(found.group(1))
        if rank < best_rank:
            best_rank = rank
            best = cid
        if rank == 0:
            break
    if best:
        _set_cache(key, best, ttl=14 * 24 * 3600)
    return best


def _info_map(soup: BeautifulSoup) -> dict[str, str]:
    mapping: dict[str, str] = {}
    cells = soup.select(".info-table .info-table__content")
    for i in range(0, len(cells) - 1, 2):
        key = cells[i].get_text(" ", strip=True).rstrip(":")
        val = cells[i + 1].get_text(" ", strip=True)
        mapping[key] = val
    return mapping


def _digits_shirt(text: str) -> str | None:
    found = re.search(r"#\s*(\d{1,3})\b", text or "")
    if found:
        return found.group(1)
    digits = re.sub(r"\D", "", text or "")
    if 1 <= len(digits) <= 3:
        n = int(digits)
        if 1 <= n <= 99:
            return str(n)
    return None


def _hash_shirt(text: str) -> str | None:
    found = re.search(r"#\s*(\d{1,2})\b", text or "")
    if not found:
        return None
    n = int(found.group(1))
    if 1 <= n <= 99:
        return str(n)
    return None


def _read_shirt_number(soup: BeautifulSoup, info: dict[str, str], raw_name: str) -> str | None:
    for sel in (
        ".data-header__shirt-number",
        ".tm-player-meta__number",
        "span[class*='shirt-number']",
        '[itemprop="jerseyNumber"]',
    ):
        el = soup.select_one(sel)
        if el is None:
            continue
        text = el.get_text(" ", strip=True) or el.get("content") or ""
        got = _digits_shirt(text) or _hash_shirt(text)
        if got:
            return got
    headline = soup.select_one(".data-header__headline-wrapper")
    if headline is not None:
        got = _hash_shirt(headline.get_text(" ", strip=True))
        if got:
            return got
    for key in (
        "Shirt number",
        "Player shirt number",
        "Forma numarası",
        "Forma no",
        "Rückennummer",
        "Number",
    ):
        got = _digits_shirt(str(info.get(key) or "")) or _hash_shirt(str(info.get(key) or ""))
        if got:
            return got
    got = _hash_shirt(raw_name)
    if got:
        return got
    for script in soup.select('script[type="application/ld+json"]'):
        blob = script.get_text() or ""
        found = re.search(r'"jersey(?:Number|No)"\s*:\s*"?(\d{1,3})"?', blob, re.I)
        if found:
            n = int(found.group(1))
            if 1 <= n <= 99:
                return str(n)
    return None


def _scrape_profile(player_id: str) -> dict:
    html = _get_html(f"/dummy/profil/spieler/{player_id}")
    soup = BeautifulSoup(html, "lxml")
    info = _info_map(soup)
    name_el = soup.select_one("h1.data-header__headline-wrapper")
    raw_name = name_el.get_text(" ", strip=True) if name_el else ""
    shirt = _read_shirt_number(soup, info, raw_name)
    name = re.sub(r"^#\s*\d+\s*", "", raw_name)
    img = soup.select_one("div.data-header__profile-container img")
    mv_el = soup.select_one("a.data-header__market-value-wrapper, div.data-header__market-value-wrapper")
    market_value = parse_euro(mv_el.get_text(" ", strip=True) if mv_el else None)
    height_raw = info.get("Height") or info.get("Boy")
    height = None
    if height_raw:
        cleaned = height_raw.replace(",", ".").replace("m", "").strip()
        try:
            height = int(round(float(re.sub(r"[^0-9.]", "", cleaned)) * 100)) if "." in cleaned else int(re.sub(r"\D", "", cleaned) or 0)
        except ValueError:
            height = None
    age = None
    birth = info.get("Date of birth/Age") or info.get("Doğum tarihi/Yaş") or ""
    age_match = re.search(r"\((\d+)\)", birth)
    if age_match:
        age = int(age_match.group(1))
    caps_txt = ""
    for item in soup.select(".data-header__details li"):
        text = item.get_text(" ", strip=True)
        if "Caps/Goals" in text or "Maç/Gol" in text:
            caps_txt = text
    caps, goals = 0, 0
    cap_match = re.search(r"(\d+)\s*/\s*(\d+)", caps_txt)
    if cap_match:
        caps, goals = int(cap_match.group(1)), int(cap_match.group(2))
    position = info.get("Position") or ""
    club_el = soup.select_one(".data-header__club a") or soup.select_one(".data-header__club")
    club_name = (club_el.get_text(" ", strip=True) if club_el else "") or info.get("Current club") or info.get("Güncel kulüp")
    club_href = ""
    if club_el and club_el.name == "a":
        club_href = club_el.get("href") or ""
    else:
        link = soup.select_one(".data-header__club a")
        club_href = (link.get("href") if link else "") or ""
    club_id = None
    found_club = re.search(r"/verein/(\d+)", club_href)
    if found_club:
        club_id = int(found_club.group(1))
    contract = info.get("Contract expires") or info.get("Sözleşme")
    league_el = soup.select_one("a.data-header__league-link") or soup.select_one(".data-header__league")
    league_name = league_el.get_text(" ", strip=True) if league_el else None
    og = soup.select_one('meta[property="og:image"]')
    image_url = (og.get("content") if og else None) or (img.get("src") if img else None)
    return {
        "id": player_id,
        "url": f"{TM_WEB}/-/profil/spieler/{player_id}",
        "name": name,
        "fullName": info.get("Name in home country") or name,
        "imageUrl": image_url,
        "age": age,
        "height": height,
        "citizenship": [info.get("Citizenship") or info.get("Uyruk") or ""],
        "position": {"main": position, "other": []},
        "foot": (info.get("Foot") or info.get("Ayak") or "").lower() or None,
        "club": {
            "id": club_id,
            "name": club_name,
            "contractExpires": contract,
        },
        "leagueName": league_name,
        "placeOfBirth": info.get("Place of birth") or info.get("Doğum yeri"),
        "marketValue": market_value,
        "shirtNumber": shirt,
        "dateOfBirth": birth,
        "joined": info.get("Joined") or info.get("Katılma"),
        "description": f"{name}, {club_name or ''}.".strip(),
        "internationalCaps": caps,
        "internationalGoals": goals,
    }


def _scrape_injuries(player_id: str) -> list[dict]:
    try:
        html = _get_html(f"/dummy/verletzungen/spieler/{player_id}")
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if not table:
        return []
    rows = []
    for tr in table.select("tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(tds) < 5:
            continue
        days = int(re.sub(r"\D", "", tds[4]) or 0)
        missed = int(re.sub(r"\D", "", tds[5]) or 0) if len(tds) > 5 else 0
        rows.append(
            {
                "season": tds[0],
                "injury": tds[1],
                "fromDate": tds[2],
                "untilDate": tds[3] or None,
                "days": days,
                "gamesMissed": missed,
                "gamesMissedClubs": [],
            }
        )
    return rows


def _int_cell(text: str | None) -> int:
    raw = (text or "").replace(".", " ").strip()
    if not raw or raw in {"-", "–", "?"}:
        return 0
    match = re.search(r"\d+", raw.replace(",", ""))
    return int(match.group(0)) if match else 0


def _cell(tds: list[str], idx: int | None, fallback: str = "0") -> str:
    if idx is None:
        return fallback
    if idx < 0:
        idx = len(tds) + idx
    if 0 <= idx < len(tds):
        return tds[idx]
    return fallback


def _scrape_stats(player_id: str) -> list[dict]:
    try:
        html = _get_html(f"/dummy/leistungsdaten/spieler/{player_id}")
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    tables = soup.select("div.box table.items") or soup.select("table.items")
    for table in tables[:3]:
        box = table.find_parent("div", class_="box")
        season_id = ""
        if box:
            box_h = box.select_one("h2, .content-box-headline")
            if box_h:
                found = re.search(r"(20\d{2}(?:/\d{2})?)", box_h.get_text(" ", strip=True))
                if found:
                    season_id = found.group(1)
        headers = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
        apps_i = next((i for i, h in enumerate(headers) if "app" in h or "maç" in h or "eins" in h), 2)
        gls_i = next((i for i, h in enumerate(headers) if "goal" in h or "gol" in h), 3)
        ast_i = next((i for i, h in enumerate(headers) if "assist" in h or "asit" in h or "vorlage" in h), 4)
        min_i = next((i for i, h in enumerate(headers) if "min" in h), -2)
        yel_i = next((i for i, h in enumerate(headers) if "yellow" in h or "sarı" in h or "gelb" in h), None)
        for tr in table.select("tbody tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(tds) < 4:
                continue
            comp_el = tr.select_one("a")
            competition = (comp_el.get_text(" ", strip=True) if comp_el else tds[1] if len(tds) > 1 else tds[0])
            if not competition or competition.lower() in {"total", "gesamt", "toplam"}:
                continue
            apps = _int_cell(_cell(tds, apps_i))
            if apps <= 0:
                continue
            rows.append(
                {
                    "competitionName": competition,
                    "seasonId": season_id,
                    "appearances": apps,
                    "goals": _int_cell(_cell(tds, gls_i)),
                    "assists": _int_cell(_cell(tds, ast_i)),
                    "minutesPlayed": _int_cell(_cell(tds, min_i)),
                    "yellowCards": _int_cell(_cell(tds, yel_i)),
                    "redCards": 0,
                }
            )
        if rows:
            break
    return rows[:16]


def _market_history(player_id: str) -> tuple[int | None, list[dict]]:
    url = f"{TM_WEB}/ceapi/marketValueDevelopment/graph/{player_id}"
    headers = dict(_HEADERS)
    headers["Accept"] = "application/json"
    headers["Referer"] = f"{TM_WEB}/-/marktwertverlauf/spieler/{player_id}"
    try:
        with _client() as client:
            response = client.get(url, headers=headers)
            if response.status_code >= 400:
                data = {}
            else:
                data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        data = {}
    series = data.get("list") or []
    history = []
    for point in series:
        value = _normal_market_value(point.get("y"))
        history.append(
            {
                "date": datetime.fromtimestamp(int(point.get("x", 0)) / 1000, tz=timezone.utc).date().isoformat() if point.get("x") else None,
                "marketValue": value,
                "clubName": point.get("verein"),
                "age": int(point["age"]) if str(point.get("age") or "").isdigit() else None,
            }
        )
    current = history[-1]["marketValue"] if history else None
    if len(history) < 2:
        scraped = _scrape_value_curve(player_id)
        if scraped:
            history = scraped
            current = history[-1]["marketValue"] if history else current
    return current, history


def _scrape_value_curve(player_id: str) -> list[dict]:
    try:
        html = _get_html(f"/x/marktwertverlauf/spieler/{player_id}")
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    table = soup.select_one("table.items")
    if table is None:
        return []
    for tr in table.select("tbody tr"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        date_raw = tds[0].get_text(" ", strip=True)
        value = None
        for td in reversed(tds):
            value = parse_euro(td.get_text(" ", strip=True))
            if value:
                break
        if not value:
            continue
        iso = None
        found = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", date_raw)
        if found:
            iso = f"{found.group(3)}-{found.group(2)}-{found.group(1)}"
        rows.append({"date": iso, "marketValue": value, "clubName": "", "age": None})
    rows.reverse()
    return rows[-24:]


def _iso_day(value: Any):
    return _parse_tm_date(value)


def _parse_tm_date(value: Any):
    raw = str(value or "").replace("\xa0", " ").strip()
    if not raw or raw in {"-", "–", "—", "None"}:
        return None
    iso = raw[:10]
    if len(iso) == 10 and iso[4] == "-" and iso[7] == "-":
        try:
            return datetime.strptime(iso, "%Y-%m-%d").date()
        except ValueError:
            pass
    found = re.search(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", raw)
    if found:
        try:
            return datetime(int(found.group(3)), int(found.group(2)), int(found.group(1))).date()
        except ValueError:
            pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(re.sub(r"\s+", " ", raw)[:32], fmt).date()
        except ValueError:
            continue
    return None


def _transfer_kind(text: str) -> tuple[str, int | None]:
    raw = (text or "").replace("\xa0", " ").strip()
    low = raw.lower()
    if not raw or raw in {"-", "–"}:
        return "belirsiz", None
    if "end of loan" in low or "leihende" in low or "kiralık sonu" in low:
        return "donus", None
    if "loan fee" in low or "leihgebühr" in low:
        return "kiralik", parse_euro(raw)
    if "loan" in low or "leihe" in low or "kiralık" in low:
        return "kiralik", parse_euro(raw)
    if any(w in low for w in ("free", "ablösefrei", "bedelsiz", "ücretsiz")):
        return "bedelsiz", 0
    fee = parse_euro(raw)
    if fee is None:
        return "belirsiz", None
    return "bedel", fee


def _club_side(pack: Any) -> dict[str, Any]:
    if not isinstance(pack, dict):
        pack = {}
    href = str(pack.get("href") or "")
    found = re.search(r"/verein/(\d+)", href)
    name = str(pack.get("clubName") or "").strip()
    return {
        "name": name,
        "id": int(found.group(1)) if found else None,
        "crest": str(pack.get("clubEmblem-1x") or pack.get("clubEmblem-2x") or ""),
    }


def _club_key(side: dict[str, Any]) -> str:
    if side.get("id"):
        return f"id:{side['id']}"
    return "n:" + re.sub(r"\s+", " ", str(side.get("name") or "").strip().lower())


def _youth_club(name: str) -> bool:
    return bool(name and _YOUTH_CLUB.search(name))


def _duration_label(days: int | None) -> str:
    if days is None:
        return ""
    if days < 20:
        return f"{max(days, 1)} gün"
    years, rem = divmod(days, 365)
    months = rem // 30
    if years and months:
        return f"{years} yıl {months} ay"
    if years:
        return f"{years} yıl"
    if months:
        return f"{months} ay"
    return f"{days} gün"


def _fee_label(kind: str, fee: int | None) -> str:
    if kind == "bedelsiz":
        return "Bedelsiz"
    if kind == "kiralik" and not fee:
        return "Kiralık"
    if kind in {"donus", "baslangic"}:
        return "—"
    if kind == "belirsiz" or fee is None:
        return "Açıklanmadı"
    return format_eur(fee)


def _total_pack(kind: str, fee: int | None) -> tuple[int | None, str]:
    if kind in {"donus", "baslangic"}:
        return None, "—"
    if kind == "bedelsiz":
        return 0, "Bedelsiz"
    if fee is None:
        return None, "Açıklanmadı"
    return fee, format_eur(fee)


def _spell_window(spell: dict[str, Any], today):
    start = _parse_tm_date(spell.get("arrived"))
    departed = _parse_tm_date(spell.get("departed"))
    end = departed or today
    return start, end


def _wage_window(spell: dict[str, Any], today):
    start = _parse_tm_date(spell.get("arrived"))
    departed = _parse_tm_date(spell.get("departed"))
    until = _parse_tm_date(spell.get("contract_until"))
    loan = bool(spell.get("loan") or spell.get("kind") == "kiralik")
    if departed:
        end = departed
    elif loan:
        year = today.year + (1 if today.month >= 7 else 0)
        end = datetime(year, 6, 30).date()
        if end < today:
            end = datetime(today.year + 1, 6, 30).date()
    elif until:
        end = until
    else:
        end = today
    return start, end


def _finish_spell(spell: dict[str, Any], today) -> dict[str, Any]:
    from app.slugs import club_display, club_path, is_free_agent

    start, end = _spell_window(spell, today)
    days = None
    if start is not None and end is not None:
        days = max((end - start).days, 0)
    kind = str(spell.get("kind") or "belirsiz")
    fee = spell.get("fee")
    total, total_label = _total_pack(kind, fee if isinstance(fee, int) else None)
    club_name = club_display(str(spell.get("club") or ""))
    from_name = club_display(str(spell.get("from_club") or ""))
    youth = bool(spell.get("youth"))
    href = None
    cid = spell.get("club_id")
    if cid and not youth and not is_free_agent(club_name):
        href = club_path(cid, club_name)
    mv = spell.get("market_value")
    spell.update(
        {
            "club": club_name,
            "from_club": from_name,
            "days": days,
            "duration_label": _duration_label(days),
            "kind_label": _KIND_TR.get(kind, "Bedel açıklanmadı"),
            "fee_label": _fee_label(kind, fee if isinstance(fee, int) else None),
            "market_label": format_eur(mv) if mv else "",
            "wage_label": "Açıklanmadı",
            "wage_total_label": "Açıklanmadı",
            "total": total,
            "total_label": total_label,
            "total_scope": "bonservis",
            "href": href,
        }
    )
    return spell


def _stamp_contract(career: dict[str, Any], profile: dict[str, Any] | None) -> None:
    from app.slugs import club_names_match

    profile = profile or {}
    club = profile.get("club") if isinstance(profile.get("club"), dict) else {}
    until = _parse_tm_date((club or {}).get("contractExpires"))
    joined = _parse_tm_date(profile.get("joined"))
    today = datetime.now(timezone.utc).date()
    club_name = str((club or {}).get("name") or "")
    for spell in career.get("current") or []:
        if not isinstance(spell, dict):
            continue
        loan = bool(spell.get("loan") or spell.get("kind") == "kiralik")
        same = bool(club_name) and club_names_match(str(spell.get("club") or ""), club_name)
        if same and not loan:
            if joined and not _parse_tm_date(spell.get("arrived")):
                spell["arrived"] = joined.isoformat()
            if until:
                spell["contract_until"] = until.isoformat()
        _finish_spell(spell, today)


def _club_core(name: str) -> str:
    from app.slugs import fold_tr

    n = fold_tr(name)
    n = re.sub(
        r"\b(fk|jk|sk|fc|cf|ac|as|afc|istanbul|spor|sportif|faaliyetler|club|kulubu|kulup)\b",
        " ",
        n,
    )
    return re.sub(r"[^a-z0-9]+", "", n)


def _club_wage_hit(spell_club: str, wage_club: str) -> bool:
    from app.slugs import club_names_match, club_query_hit

    if club_names_match(spell_club, wage_club):
        return True
    left = club_query_hit(spell_club, wage_club)
    right = club_query_hit(wage_club, spell_club)
    if (left is not None and left <= 1) or (right is not None and right <= 1):
        return True
    a, b = _club_core(spell_club), _club_core(wage_club)
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) >= 6 and (a in b or b in a):
        return True
    return False


def _apply_wage_pack(career: dict[str, Any], pack: dict[str, Any] | None) -> None:
    pack = pack or {}
    rows = [row for row in (pack.get("rows") or []) if isinstance(row, dict) and row.get("annual_eur")]
    if not rows:
        return
    bonus = pack.get("bonus_annual_eur")
    today = datetime.now(timezone.utc).date()
    latest = sorted(rows, key=lambda row: int(row.get("year") or 0))[-1]
    for section in ("current", "former"):
        for spell in career.get(section) or []:
            if spell.get("kind") in {"donus", "baslangic"}:
                continue
            hits = [row for row in rows if _club_wage_hit(str(spell.get("club") or ""), str(row.get("club") or ""))]
            if not hits and section == "current" and spell.get("ongoing"):
                hits = [latest]
            if not hits:
                continue
            start, end = _wage_window(spell, today)
            if start is None:
                annual = int(hits[-1].get("annual_eur") or 0)
                if annual <= 0:
                    continue
                if end is not None and end > today:
                    bill = int(round(annual * max((end - today).days, 30) / 365.25))
                else:
                    bill = annual
                _write_wage_spell(spell, hits, bill, bonus, section, today)
                continue
            if end is None or end < start:
                annual = int(hits[-1].get("annual_eur") or 0)
                if annual <= 0:
                    continue
                _write_wage_spell(spell, hits, annual, bonus, section, today)
                continue
            hits = sorted(hits, key=lambda row: int(row.get("year") or 0))
            bill = 0
            used_rows: list[dict[str, Any]] = []
            for i, row in enumerate(hits):
                year = int(row.get("year") or 0)
                if year < 1990:
                    continue
                period_start = datetime(year, 7, 1).date()
                if i + 1 < len(hits):
                    nxt = int(hits[i + 1].get("year") or year + 1)
                    period_end = datetime(nxt, 7, 1).date()
                else:
                    period_end = datetime(year + 12, 7, 1).date()
                left = max(start, period_start)
                right = min(end, period_end)
                overlap = (right - left).days
                if overlap <= 0:
                    continue
                annual = int(row.get("annual_eur") or 0)
                bill += int(round(annual * overlap / 365.25))
                used_rows.append(row)
            if not used_rows:
                used_rows = [hits[-1]]
                days = max(int(spell.get("days") or 0), (end - start).days)
                bill = int(round(int(used_rows[0].get("annual_eur") or 0) * max(days, 1) / 365.25))
            if not bill:
                continue
            _write_wage_spell(spell, used_rows, bill, bonus, section, today)


def _write_wage_spell(
    spell: dict[str, Any],
    used_rows: list[dict[str, Any]],
    bill: int,
    bonus: Any,
    section: str,
    today=None,
) -> None:
    annuals = [int(row.get("annual_eur") or 0) for row in used_rows if row.get("annual_eur")]
    last = used_rows[-1]
    weekly = last.get("weekly_eur")
    base_annual = int(last.get("annual_eur") or (annuals[-1] if annuals else 0) or 0)
    bonus_n = 0
    if bonus and section == "current" and spell.get("ongoing"):
        try:
            bonus_n = int(bonus)
        except (TypeError, ValueError):
            bonus_n = 0
        if bonus_n < 0:
            bonus_n = 0
    shown_annual = base_annual + bonus_n
    spell["wage_annual"] = shown_annual if shown_annual else last.get("annual_eur")
    spell["wage_weekly"] = weekly
    if bonus_n:
        spell["wage_bonus"] = bonus_n
        spell["wage_bonus_label"] = format_eur(bonus_n)
        spell["wage_label"] = f"{format_eur(shown_annual)} / yıl"
    elif len(set(annuals)) > 1:
        spell["wage_label"] = f"{format_eur(min(annuals))}–{format_eur(max(annuals))} / yıl"
    elif annuals:
        spell["wage_label"] = f"{format_eur(annuals[0])} / yıl"
    else:
        spell["wage_label"] = "Açıklanmadı"
    spell["wage_weekly_label"] = f"{format_eur(weekly)} / hafta" if weekly else ""
    if bonus_n:
        now = today or datetime.now(timezone.utc).date()
        _start, end = _wage_window(spell, now)
        if end and end > now:
            days = max((end - now).days, 1)
        else:
            days = 365
        bill = int(bill) + int(round(bonus_n * days / 365.25))
    spell["wage_total"] = bill
    spell["wage_total_label"] = format_eur(bill)
    fee = spell.get("fee")
    kind = str(spell.get("kind") or "")
    fee_part = None
    if kind == "bedelsiz":
        fee_part = 0
    elif isinstance(fee, int):
        fee_part = fee
    if fee_part is None:
        spell["total"] = bill
        spell["total_label"] = format_eur(bill)
        spell["total_scope"] = "maas"
    else:
        spell["total"] = fee_part + bill
        spell["total_label"] = format_eur(fee_part + bill)
        spell["total_scope"] = "tam"


def _attach_wages(career: dict[str, Any], name: str, pack: dict[str, Any] | None = None) -> dict[str, Any]:
    if pack is None:
        from app.wages import fetch_player_wages

        pack = fetch_player_wages(name) or {}
    _apply_wage_pack(career, pack)
    return pack


def _fetch_wages_safe(name: str) -> dict[str, Any] | None:
    try:
        from app.wages import fetch_player_wages

        return fetch_player_wages(name)
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _fetch_fotmob_safe(name: str, club: str) -> dict[str, Any] | None:
    try:
        from app.live_fotmob import player_dossier

        return player_dossier(name, club)
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _player_career(player_id: str) -> dict:
    empty: dict[str, Any] = {
        "current": [],
        "former": [],
        "youth": [],
        "fee_sum": None,
        "fee_sum_label": "",
    }
    data = _get_json(
        f"/ceapi/transferHistory/list/{player_id}",
        referer=f"/dummy/transfers/spieler/{player_id}",
    )
    raw = data.get("transfers")
    if not isinstance(raw, list) or not raw:
        return empty
    today = datetime.now(timezone.utc).date()
    career = _career_from_transfer_list(raw, today)
    fee_sum = data.get("feeSum")
    parsed_sum = None
    try:
        if fee_sum is not None and fee_sum == fee_sum:
            parsed_sum = int(fee_sum)
    except (TypeError, ValueError):
        parsed_sum = parse_euro(str(data.get("formattedFeeSum") or ""))
    career["fee_sum"] = parsed_sum
    career["fee_sum_label"] = format_eur(parsed_sum) if parsed_sum else ""
    return career


def _career_from_transfer_list(raw: list, today) -> dict[str, Any]:
    spells: list[dict[str, Any]] = []
    open_map: dict[str, dict[str, Any]] = {}
    for item in reversed(raw):
        if not isinstance(item, dict):
            continue
        arrived = str(item.get("dateUnformatted") or "")[:10] or None
        arrived_date = _parse_tm_date(arrived)
        if arrived_date and arrived_date > today:
            continue
        src = _club_side(item.get("from"))
        dst = _club_side(item.get("to"))
        kind, fee = _transfer_kind(str(item.get("fee") or ""))
        src_key = _club_key(src)
        dst_key = _club_key(dst)
        if src.get("name") and src_key in open_map:
            prev = open_map.pop(src_key)
            prev["departed"] = arrived
            prev["ongoing"] = False
        if not dst.get("name") and not dst.get("id"):
            continue
        if dst_key in open_map:
            stuck = open_map.pop(dst_key)
            stuck["departed"] = arrived
            stuck["ongoing"] = False
        youth = _youth_club(dst.get("name") or "")
        spell = {
            "club": dst.get("name") or "",
            "club_id": dst.get("id"),
            "crest": dst.get("crest") or "",
            "from_club": src.get("name") or "",
            "from_club_id": src.get("id"),
            "arrived": arrived,
            "departed": None,
            "ongoing": True,
            "season": item.get("season"),
            "kind": kind,
            "fee": fee,
            "market_value": parse_euro(str(item.get("marketValue") or "")),
            "youth": youth,
            "loan": kind == "kiralik",
        }
        spells.append(spell)
        open_map[dst_key] = spell
    if spells:
        origin_name = str(spells[0].get("from_club") or "").strip()
        origin_id = spells[0].get("from_club_id")
        seen = any(
            (origin_id and s.get("club_id") == origin_id)
            or (origin_name and str(s.get("club") or "") == origin_name)
            for s in spells
        )
        if origin_name and not seen:
            spells.insert(
                0,
                {
                    "club": origin_name,
                    "club_id": origin_id,
                    "crest": "",
                    "from_club": "",
                    "from_club_id": None,
                    "arrived": None,
                    "departed": spells[0].get("arrived"),
                    "ongoing": False,
                    "season": spells[0].get("season"),
                    "kind": "baslangic",
                    "fee": None,
                    "market_value": None,
                    "youth": _youth_club(origin_name),
                    "loan": False,
                },
            )
    current: list[dict[str, Any]] = []
    former: list[dict[str, Any]] = []
    youth_rows: list[dict[str, Any]] = []
    for spell in reversed(spells):
        _finish_spell(spell, today)
        if spell.get("youth") and not spell.get("ongoing"):
            youth_rows.append(spell)
        elif spell.get("ongoing"):
            current.append(spell)
        else:
            former.append(spell)
    loans = [s for s in current if s.get("loan") or s.get("kind") == "kiralik"]
    if loans and len(current) > 1:
        keep = loans[0]
        rest = [s for s in current if s is not keep]
        for extra in rest:
            extra["ongoing"] = False
            _finish_spell(extra, today)
            former.insert(0, extra)
        current = [keep]
    return {
        "current": current,
        "former": former,
        "youth": youth_rows,
        "fee_sum": None,
        "fee_sum_label": "",
    }


def playing_club_from_career(career: dict[str, Any] | None) -> dict[str, Any] | None:
    current = [s for s in ((career or {}).get("current") or []) if isinstance(s, dict)]
    if not current:
        return None
    loan = next((s for s in current if s.get("loan") or s.get("kind") == "kiralik"), None)
    return loan or current[0]


def _skeleton_bundle() -> dict[str, Any]:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "profile": {},
        "stats": [],
        "market_value": None,
        "market_history": [],
        "ranking": {},
        "injuries": [],
        "career": _empty_career(),
        "transfers": [],
        "fotmob": None,
        "partial": True,
        "source": TM_WEB,
    }


def _player_bundle_fetch(pid: str, name: str = "", club: str = "") -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    career = _empty_career()
    injuries: list = []
    stats: list = []
    profile: dict = {}
    market_value = None
    history: list = []
    fotmob = None
    wages_complete = True
    career_ok = True
    hint_name = str(name or "").strip()
    hint_club = str(club or "").strip()
    with ThreadPoolExecutor(max_workers=7) as pool:
        fut_profile = pool.submit(_scrape_profile, pid)
        fut_market = pool.submit(_market_history, pid)
        fut_stats = pool.submit(_scrape_stats, pid)
        fut_career = pool.submit(_player_career, pid)
        fut_inj = pool.submit(_scrape_injuries, pid)
        fut_wages = pool.submit(_fetch_wages_safe, hint_name) if hint_name else None
        fut_fm = pool.submit(_fetch_fotmob_safe, hint_name, hint_club) if hint_name else None
        profile = _wait_fut(fut_profile, {}) or {}
        player_name = str(profile.get("name") or profile.get("fullName") or hint_name or "").strip()
        club_name = str((profile.get("club") or {}).get("name") or hint_club or "").strip()
        if fut_wages is None and player_name:
            fut_wages = pool.submit(_fetch_wages_safe, player_name)
        if fut_fm is None and player_name:
            fut_fm = pool.submit(_fetch_fotmob_safe, player_name, club_name)
        try:
            mv, hist = fut_market.result(timeout=32)
            market_value = mv
            history = hist or []
        except (httpx.HTTPError, TimeoutError, FuturesTimeout, TypeError, ValueError):
            market_value, history = None, []
        stats = _wait_fut(fut_stats, []) or []
        try:
            career = fut_career.result(timeout=32) or career
        except (httpx.HTTPError, TimeoutError, FuturesTimeout, ValueError, TypeError, json.JSONDecodeError):
            career_ok = False
        if not (career.get("current") or career.get("former") or career.get("youth")):
            time.sleep(0.55)
            try:
                retry = _player_career(pid) or _empty_career()
            except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
                retry = _empty_career()
                career_ok = False
            if retry.get("current") or retry.get("former") or retry.get("youth"):
                career = retry
                career_ok = True
            else:
                career_ok = False
        _stamp_contract(career, profile)
        injuries = _wait_fut(fut_inj, []) or []
        pack = _wait_fut(fut_wages, None, timeout=28)
        if (not isinstance(pack, dict) or not (pack.get("rows") or [])) and player_name:
            alt = str(profile.get("fullName") or "").strip()
            if alt and alt.casefold() != player_name.casefold():
                extra = _fetch_wages_safe(alt)
                if isinstance(extra, dict) and extra.get("rows"):
                    pack = extra
        if isinstance(pack, dict):
            _apply_wage_pack(career, pack)
            wages_complete = bool(pack.get("complete", True))
        elif player_name:
            wages_complete = False
        fotmob = _wait_fut(fut_fm, None, timeout=16)
    if market_value is None:
        market_value = profile.get("marketValue")
    else:
        profile["marketValue"] = market_value
    partial = (not career_ok) or (bool(player_name) and not wages_complete and not _career_has_wage(career))
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "stats": stats,
        "market_value": market_value,
        "market_history": history,
        "ranking": {},
        "injuries": injuries,
        "career": career,
        "transfers": [],
        "fotmob": fotmob,
        "partial": partial,
        "source": TM_WEB,
    }


def player_bundle(
    player_id: int | str,
    fresh: bool = True,
    name: str | None = None,
    club: str | None = None,
) -> dict:
    pid = str(player_id)
    key = f"bundle:v8:{pid}"
    cached = _get_cache(key)
    if cached and _bundle_ready(cached):
        return cached
    if cached and _bundle_has_body(cached) and not fresh:
        return cached
    with _FLIGHT_LOCK:
        holder = _FLIGHT.get(pid)
        if holder is None:
            holder = {"event": threading.Event(), "bundle": None}
            _FLIGHT[pid] = holder
            leader = True
        else:
            leader = False
    if not leader:
        holder["event"].wait(timeout=70)
        got = holder.get("bundle")
        if isinstance(got, dict) and _bundle_has_body(got):
            return got
        cached = _get_cache(key)
        if cached:
            return cached
        return got if isinstance(got, dict) else _skeleton_bundle()
    try:
        try:
            bundle = _player_bundle_fetch(pid, name=str(name or ""), club=str(club or ""))
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError, TimeoutError):
            bundle = cached if isinstance(cached, dict) else _skeleton_bundle()
        holder["bundle"] = bundle
        if _bundle_has_body(bundle):
            ttl = 25 if bundle.get("partial") else _TTL
            _set_cache(key, bundle, ttl=ttl)
        return bundle
    finally:
        holder["event"].set()
        with _FLIGHT_LOCK:
            if _FLIGHT.get(pid) is holder:
                del _FLIGHT[pid]


def current_season_totals(stats: list[dict]) -> dict:
    if not stats:
        return {
            "apps": 0,
            "goals": 0,
            "assists": 0,
            "minutes": 0,
            "yellow": 0,
            "red": 0,
            "rows": [],
        }
    seasons = [str(row.get("seasonId") or "") for row in stats]
    current = max(seasons) if seasons else ""
    rows = [row for row in stats if str(row.get("seasonId") or "") == current]
    return {
        "season": current,
        "apps": int(sum(row.get("appearances") or 0 for row in rows)),
        "goals": int(sum(row.get("goals") or 0 for row in rows)),
        "assists": int(sum(row.get("assists") or 0 for row in rows)),
        "minutes": int(sum(row.get("minutesPlayed") or 0 for row in rows)),
        "yellow": int(sum(row.get("yellowCards") or 0 for row in rows)),
        "red": int(sum(row.get("redCards") or 0 for row in rows)),
        "rows": rows,
    }


def open_injury_days(injuries: list[dict]) -> int:
    today = datetime.now(timezone.utc).date()
    total = 0
    for item in injuries[:12]:
        until = item.get("untilDate")
        days = int(item.get("days") or 0)
        if until in (None, "", "None", "-"):
            total += max(days, 7)
            continue
        parsed = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(str(until), fmt).date()
                break
            except ValueError:
                continue
        if parsed and parsed >= today:
            total += max(days, 7)
    return total

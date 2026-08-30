"""Canlı Transfermarkt: arama, profil, piyasa eğrisi ve sakatlık."""

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

_LOCK = threading.Lock()
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


def club_overlay_get() -> dict[str, Any]:
    global _OVERLAY_MEM, _OVERLAY_AT
    if _OVERLAY_MEM is not None and (time.time() - _OVERLAY_AT) < 45:
        return _OVERLAY_MEM
    raw = _get_cache("club-overlay:v1")
    _OVERLAY_MEM = raw if isinstance(raw, dict) else {}
    _OVERLAY_AT = time.time()
    return _OVERLAY_MEM


def club_overlay_put(
    player_id: Any,
    *,
    club_id: Any = None,
    club_name: str = "",
    league_id: str = "",
) -> None:
    global _OVERLAY_MEM, _OVERLAY_AT
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


_YOUTH_CLUB = re.compile(r"u1[789]|u2[01]|jugend|youth|amateurs|\bii\b|reserve")


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


def _scrape_profile(player_id: str) -> dict:
    html = _get_html(f"/dummy/profil/spieler/{player_id}")
    soup = BeautifulSoup(html, "lxml")
    info = _info_map(soup)
    name_el = soup.select_one("h1.data-header__headline-wrapper")
    raw_name = name_el.get_text(" ", strip=True) if name_el else ""
    shirt_match = re.search(r"#(\d+)", raw_name)
    shirt = shirt_match.group(1) if shirt_match else None
    name = re.sub(r"^#\d+\s*", "", raw_name)
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
    shirt_el = soup.select_one(".data-header__shirt-number")
    if shirt_el:
        shirt = re.sub(r"\D", "", shirt_el.get_text(" ", strip=True)) or shirt
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


def player_bundle(player_id: int | str, fresh: bool = True) -> dict:
    pid = str(player_id)
    key = f"bundle:{pid}"
    if not fresh:
        cached = _get_cache(key)
        if cached is not None:
            return cached
    profile: dict = {}
    injuries: list = []
    stats: list = []
    market_value = None
    history: list = []
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_profile = pool.submit(_scrape_profile, pid)
            fut_market = pool.submit(_market_history, pid)
            fut_stats = pool.submit(_scrape_stats, pid)
            profile = fut_profile.result() or {}
            market_value, history = fut_market.result()
            stats = fut_stats.result() or []
        if market_value is None:
            market_value = profile.get("marketValue")
        else:
            profile["marketValue"] = market_value
    except httpx.HTTPError:
        profile = profile or {}
    bundle = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "stats": stats,
        "market_value": market_value,
        "market_history": history,
        "ranking": {},
        "injuries": injuries,
        "transfers": [],
        "source": TM_WEB,
    }
    if profile or history:
        _set_cache(key, bundle)
    return bundle


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

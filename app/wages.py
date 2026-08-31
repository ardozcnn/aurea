"""Açık maaş raporları: yıllık taban, kulüp ve dönem."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import USER_AGENT
from app.slugs import fold_tr, slugify

_WAGE_TTL = 12 * 3600
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
}
_FALLBACK_FX = {"GBP": 1.16, "USD": 0.86}


def _parse_wage_number(text: str) -> int | None:
    from app.live_tm import parse_euro

    raw = (text or "").replace("\xa0", " ").strip()
    if not raw or raw in {"-", "–", "—"}:
        return None
    low = raw.lower()
    if re.search(r"\d", raw) and re.search(r"mio|million|bn|mrd|bin|(?:\d(?:[.,]\d+)?)\s*m\b|(?:\d+(?:[.,]\d+)?)\s*k\b", low):
        return parse_euro(raw.replace("£", "€").replace("$", "€"))
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) >= 4:
        if len(digits) == 4 and not re.search(r"[€£$]|,\d{3}", raw):
            return None
        try:
            return int(digits)
        except ValueError:
            return None
    return parse_euro(raw.replace("£", "€").replace("$", "€"))


def _currency_of(text: str) -> str:
    raw = text or ""
    if "£" in raw or "gbp" in raw.lower():
        return "GBP"
    if "$" in raw and "€" not in raw and "eur" not in raw.lower():
        return "USD"
    return "EUR"


def _fx_to_eur(amount: int | None, currency: str) -> int | None:
    from app.live_tm import _get_cache, _set_cache

    if not amount:
        return None
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return int(amount)
    key = f"fx:{cur}:EUR:v1"
    cached = _get_cache(key)
    rate = None
    if isinstance(cached, (int, float)) and float(cached) > 0:
        rate = float(cached)
    else:
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=8.0, verify=False) as client:
                response = client.get(f"https://api.frankfurter.app/latest?from={cur}&to=EUR")
                payload = response.json() if response.status_code < 400 else {}
            rate = float((payload.get("rates") or {}).get("EUR") or 0)
        except (httpx.HTTPError, ValueError, TypeError):
            rate = 0.0
        if rate <= 0:
            rate = float(_FALLBACK_FX.get(cur) or 0)
        if rate > 0:
            _set_cache(key, rate, ttl=24 * 3600)
    if not rate:
        return None
    return int(round(amount * rate))


def _get(url: str) -> tuple[int, str]:
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=14.0, verify=False) as client:
        response = client.get(url)
        return response.status_code, response.text


def _name_hit(query: str, candidate: str) -> bool:
    q = fold_tr(query)
    c = fold_tr(candidate)
    if not q or not c:
        return False
    if q == c or q in c:
        return True
    qw = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) >= 3]
    cw = [w for w in re.split(r"[^a-z0-9]+", c) if len(w) >= 3]
    if len(qw) < 2 or len(cw) < 2:
        return False
    return qw[-1] == cw[-1] and qw[0][:4] == cw[0][:4]


def _merge_row(rows: list[dict[str, Any]], year: int | None, club: str, annual: int | None, weekly: int | None, currency: str) -> None:
    if year is None or not club or not annual:
        return
    annual_eur = _fx_to_eur(annual, currency)
    weekly_eur = _fx_to_eur(weekly, currency) if weekly else None
    if annual_eur and not weekly_eur:
        weekly_eur = int(round(annual_eur / 52))
    for row in rows:
        if row.get("year") == year and fold_tr(row.get("club") or "") == fold_tr(club):
            if annual_eur and not row.get("annual_eur"):
                row["annual"] = annual
                row["annual_eur"] = annual_eur
            if weekly_eur and not row.get("weekly_eur"):
                row["weekly"] = weekly
                row["weekly_eur"] = weekly_eur
            return
    rows.append(
        {
            "year": year,
            "club": club,
            "annual": annual,
            "weekly": weekly,
            "currency": currency,
            "annual_eur": annual_eur,
            "weekly_eur": weekly_eur,
        }
    )


def _parse_chart(html: str, rows: list[dict[str, Any]]) -> None:
    found = re.search(r"const data = (\[{.*?}\]);", html, re.S)
    if not found:
        return
    try:
        data = json.loads(found.group(1))
    except json.JSONDecodeError:
        return
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            continue
        club = str(item.get("team") or "").strip()
        try:
            annual = int(item.get("salary"))
        except (TypeError, ValueError):
            continue
        symbol = str(item.get("symbol") or "€")
        _merge_row(rows, year, club, annual, None, _currency_of(symbol))


def _parse_tables(soup: BeautifulSoup, rows: list[dict[str, Any]]) -> None:
    for table in soup.select("table"):
        heads = [th.get_text(" ", strip=True).lower() for th in table.select("thead th, tr th")]
        blob = " ".join(heads)
        if "yearly" not in blob and "yıllık" not in blob:
            continue
        if "team" not in blob and "kulüp" not in blob and "club" not in blob:
            continue
        body_rows = table.select("tbody tr") or table.select("tr")[1:]
        for tr in body_rows:
            cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cells) < 3:
                continue
            year = None
            for cell in cells:
                found = re.search(r"(20\d{2})", cell)
                if found:
                    year = int(found.group(1))
                    break
            weekly = None
            annual = None
            club = ""
            currency = "EUR"
            for cell in cells:
                cur = _currency_of(cell)
                if cur != "EUR":
                    currency = cur
                amount = _parse_wage_number(cell)
                low = cell.lower()
                if amount and re.search(r"m\b|mio|million|€|£|\$", low) and amount >= 50_000:
                    if annual is None or amount > annual:
                        annual = amount
                elif amount and 5_000 <= amount < 400_000 and weekly is None and re.search(r"[€£$]", low):
                    weekly = amount
                if not club and re.search(r"[A-Za-zçğıöşüÇĞİÖŞÜ]{3,}", cell) and not re.search(r"20\d{2}|€|£|\$|verified|source", low):
                    if "week" not in low and "year" not in low:
                        club = cell
            if not club:
                for cell in cells:
                    if re.search(r"[A-Za-zçğıöşüÇĞİÖŞÜ]{4,}", cell) and not re.search(r"20\d{2}|€|£", cell):
                        club = cell
                        break
            _merge_row(rows, year, club, annual, weekly, currency)


def _parse_bonus(soup: BeautifulSoup) -> tuple[int | None, str]:
    for table in soup.select("table"):
        heads = [th.get_text(" ", strip=True).lower() for th in table.select("th")]
        blob = " ".join(heads)
        if "bonus" not in blob or "base" not in blob:
            continue
        tr = table.select_one("tbody tr") or (table.select("tr")[1] if len(table.select("tr")) > 1 else None)
        if tr is None:
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        bonus = None
        for i, head in enumerate(heads):
            if "bonus" in head and "total" not in head and i < len(cells):
                bonus = _parse_wage_number(cells[i])
        return bonus, _currency_of(" ".join(cells))
    return None, "EUR"


def _js_array(source: str, name: str) -> str:
    token = f"var {name} = ["
    start = source.find(token)
    if start < 0:
        return ""
    start = start + len(token) - 1
    depth = 0
    in_str = None
    escape = False
    for i, ch in enumerate(source[start:]):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in {'"', "'"}:
            in_str = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return source[start : start + i + 1]
    return ""


def _parse_capology_array(blob: str, rows: list[dict[str, Any]]) -> None:
    if not blob:
        return
    chunks = re.split(r"\},\s*\{", blob)
    for chunk in chunks:
        season = re.search(r">(\d{4}-\d{4})</a>", chunk)
        club = re.search(r"/club/([^/]+)/salaries/[^'\"]*['\"]>([^<]+)</a>", chunk)
        annual = re.search(r'"annual_gross_eur"\s*:\s*accounting\.formatMoney\("(\d+)"', chunk)
        if not season or not club or not annual:
            continue
        try:
            year = int(season.group(1)[:4])
            amount = int(annual.group(1))
        except (TypeError, ValueError):
            continue
        club_name = club.group(2).strip()
        if year < 1990 or amount < 1000 or not club_name:
            continue
        _merge_row(rows, year, club_name, amount, None, "EUR")


def _collapse_same_deal(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (fold_tr(str(row.get("club") or "")), int(row.get("year") or 0)))
    out: list[dict[str, Any]] = []
    for row in ordered:
        if (
            out
            and fold_tr(str(out[-1].get("club") or "")) == fold_tr(str(row.get("club") or ""))
            and out[-1].get("annual_eur") == row.get("annual_eur")
        ):
            continue
        out.append(row)
    return out


def _capology_snapshot(name: str) -> str:
    slug = slugify(name)
    if not slug:
        return ""
    cdx = (
        "https://web.archive.org/cdx/search/cdx?url="
        + quote(f"capology.com/player/{slug}*")
        + "&output=json&fl=timestamp,original&filter=statuscode:200&limit=40"
    )
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0, verify=False) as client:
            response = client.get(cdx)
            if response.status_code >= 400:
                return ""
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(payload, list) or len(payload) < 2:
        return ""
    best_ts = ""
    best_url = ""
    for item in payload[1:]:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts, original = str(item[0]), str(item[1])
        low = original.lower()
        if f"/player/{slug}" not in low:
            continue
        if ts > best_ts:
            best_ts = ts
            best_url = original
    if not best_ts or not best_url:
        return ""
    if best_url.startswith("http://"):
        best_url = "https://" + best_url[len("http://") :]
    archived = f"https://web.archive.org/web/{best_ts}id_/{best_url}"
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=35.0, verify=False) as client:
            response = client.get(archived)
            html = response.text if response.status_code < 400 else ""
    except httpx.HTTPError:
        return ""
    if len(html) < 2000:
        return ""
    return html


def _fetch_capology(name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    html = _capology_snapshot(name)
    if not html:
        return [], []
    soup = BeautifulSoup(html, "lxml")
    heading = soup.title.get_text(" ", strip=True) if soup.title else ""
    if heading and not _name_hit(name, heading.split("|")[0]):
        return [], []
    big = max((script.get_text() or "" for script in soup.select("script")), key=len, default="")
    if "data_archive" not in big and "data_active" not in big:
        return [], []
    archive: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    _parse_capology_array(_js_array(big, "data_archive"), archive)
    _parse_capology_array(_js_array(big, "data_active"), active)
    return archive, _collapse_same_deal(active)


def _search_slug(name: str) -> str | None:
    status, html = _get(f"https://www.salaryleaks.com/search?q={quote(name)}")
    if status >= 400 or not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for link in soup.select("a[href*='/football/']"):
        href = str(link.get("href") or "")
        label = link.get_text(" ", strip=True)
        path = re.sub(r"https://www\.salaryleaks\.com", "", href)
        if not re.fullmatch(r"/football/[a-z0-9-]+/?", path.split("?")[0]):
            continue
        if _name_hit(name, label) or _name_hit(name, path.split("/")[-1].replace("-", " ")):
            slug = path.strip("/").split("/")[-1]
            if slug:
                return slug
    return None


def _salaryleaks_pack(query: str) -> dict[str, Any]:
    empty: dict[str, Any] = {"rows": [], "bonus_annual_eur": None}
    slug = slugify(query)
    html = ""
    if slug:
        status, html = _get(f"https://www.salaryleaks.com/football/{slug}")
        if status >= 400:
            html = ""
    soup = BeautifulSoup(html, "lxml") if html else None
    heading = soup.select_one("h1").get_text(" ", strip=True) if soup and soup.select_one("h1") else ""
    if not html or (heading and not _name_hit(query, heading)):
        html = ""
        soup = None
        found = _search_slug(query)
        if found:
            status, html = _get(f"https://www.salaryleaks.com/football/{found}")
            if status >= 400:
                html = ""
            soup = BeautifulSoup(html, "lxml") if html else None
            heading = soup.select_one("h1").get_text(" ", strip=True) if soup and soup.select_one("h1") else ""
            if heading and not _name_hit(query, heading):
                html = ""
                soup = None
    if not html or soup is None:
        return empty
    rows: list[dict[str, Any]] = []
    _parse_tables(soup, rows)
    _parse_chart(html, rows)
    bonus, bonus_cur = _parse_bonus(soup)
    return {
        "rows": rows,
        "bonus_annual_eur": _fx_to_eur(bonus, bonus_cur) if bonus else None,
    }


def fetch_player_wages(name: str) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor

    from app.live_tm import _get_cache, _set_cache

    empty: dict[str, Any] = {"rows": [], "bonus_annual_eur": None}
    query = str(name or "").strip()
    if len(query) < 4:
        return empty
    key = f"wages:v5:{fold_tr(query)}"
    cached = _get_cache(key)
    if isinstance(cached, dict) and "rows" in cached:
        return cached
    leaks: dict[str, Any] = empty
    archive: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_leaks = pool.submit(_salaryleaks_pack, query)
            fut_cap = pool.submit(_fetch_capology, query)
            leaks = fut_leaks.result() or empty
            archive, active = fut_cap.result() or ([], [])
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
        leaks = leaks or empty
    rows: list[dict[str, Any]] = list(leaks.get("rows") or [])
    had_leaks = bool(rows)
    for row in archive:
        _merge_row(
            rows,
            row.get("year"),
            str(row.get("club") or ""),
            row.get("annual") or row.get("annual_eur"),
            row.get("weekly") or row.get("weekly_eur"),
            str(row.get("currency") or "EUR"),
        )
    if not had_leaks:
        for row in active:
            _merge_row(
                rows,
                row.get("year"),
                str(row.get("club") or ""),
                row.get("annual") or row.get("annual_eur"),
                row.get("weekly") or row.get("weekly_eur"),
                str(row.get("currency") or "EUR"),
            )
    pack = {
        "rows": rows,
        "bonus_annual_eur": leaks.get("bonus_annual_eur"),
        "source": "SalaryLeaks+Capology",
    }
    _set_cache(key, pack, ttl=_WAGE_TTL if rows else 3 * 3600)
    return pack

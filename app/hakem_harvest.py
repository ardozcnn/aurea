"""Süper Lig hakem masası: bitmiş maç ve eski hakem köşesi hasadı."""

from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.config import DATA_DIR, USER_AGENT

IST = ZoneInfo("Europe/Istanbul")
SEASON = "2026/27"
FOTMOB_SEASON = "2026/2027"
FOTMOB_LEAGUE = 71
HARVEST_PATH = DATA_DIR / "hakem_notu_harvest.json"
STATUS_PATH = DATA_DIR / "hakem_harvest_status.json"
CACHE_PATH = DATA_DIR / "hakem_harvest_cache.json"
EDITORIAL_PATH = DATA_DIR / "hakem_notu.json"
INTERVAL_SEC = 6 * 3600

EDITORIAL_SLUGS = {
    "genclerbirligi-fenerbahce-2026-1",
    "galatasaray-goztepe-2026-3",
    "samsunspor-fenerbahce-2026-3",
    "basaksehir-galatasaray-2026-4",
    "fenerbahce-besiktas-2026-4",
}

TR_MAP = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
        "â": "a",
        "î": "i",
        "û": "u",
    }
)

TEAM_META = {
    "galatasaray": {"id": "gs", "shortName": "GS", "name": "Galatasaray", "aliases": ("galatasaray", "g.saray")},
    "fenerbahce": {"id": "fb", "shortName": "FB", "name": "Fenerbahçe", "aliases": ("fenerbahce", "fenerbahçe", "fener")},
    "besiktas": {"id": "bjk", "shortName": "BJK", "name": "Beşiktaş", "aliases": ("besiktas", "beşiktaş")},
    "trabzonspor": {"id": "ts", "shortName": "TS", "name": "Trabzonspor", "aliases": ("trabzonspor", "trabzon")},
    "basaksehir": {"id": "basaksehir", "shortName": "BŞH", "name": "İstanbul Başakşehir", "aliases": ("basaksehir", "başakşehir")},
    "goztepe": {"id": "goztepe", "shortName": "GÖZ", "name": "Göztepe", "aliases": ("goztepe", "göztepe")},
    "samsunspor": {"id": "samsunspor", "shortName": "SAM", "name": "Samsunspor", "aliases": ("samsunspor", "samsun")},
    "genclerbirligi": {"id": "genclerbirligi", "shortName": "GEN", "name": "Gençlerbirliği", "aliases": ("genclerbirligi", "gençlerbirliği")},
    "konyaspor": {"id": "konyaspor", "shortName": "KON", "name": "Konyaspor", "aliases": ("konyaspor",)},
    "alanyaspor": {"id": "alanyaspor", "shortName": "ALA", "name": "Alanyaspor", "aliases": ("alanyaspor",)},
    "gaziantep-fk": {"id": "gaziantep", "shortName": "GZT", "name": "Gaziantep FK", "aliases": ("gaziantep",)},
    "kasimpasa": {"id": "kasimpasa", "shortName": "KAS", "name": "Kasımpaşa", "aliases": ("kasimpasa", "kasımpaşa")},
    "rizespor": {"id": "rizespor", "shortName": "RIZ", "name": "Rizespor", "aliases": ("rizespor", "çaykur rizespor")},
    "eyupspor": {"id": "eyupspor", "shortName": "EYÜ", "name": "Eyüpspor", "aliases": ("eyupspor", "eyüpspor")},
    "kocaelispor": {"id": "kocaelispor", "shortName": "KOC", "name": "Kocaelispor", "aliases": ("kocaelispor",)},
    "corum-fk": {"id": "corum", "shortName": "ÇOR", "name": "Çorum FK", "aliases": ("corum", "çorum")},
    "erzurumspor-fk": {"id": "erzurumspor", "shortName": "ERZ", "name": "Erzurumspor FK", "aliases": ("erzurumspor", "erzurum")},
    "amed-sportif": {"id": "amed", "shortName": "AMD", "name": "Amed Sportif", "aliases": ("amed sportif", "amed")},
}

EXPERTS = (
    ("Fırat Aydınus", ("fırat aydınus", "aydinus")),
    ("Mustafa Çulcu", ("mustafa çulcu", "çulcu")),
    ("Ahmet Çakar", ("ahmet çakar", "çakar")),
    ("Deniz Ateş Bitnel", ("deniz ateş bitnel", "bitnel")),
    ("Serdar Akçer", ("serdar akçer", "akçer")),
    ("Erman Toroğlu", ("erman toroğlu", "toroğlu")),
    ("Deniz Çoban", ("deniz çoban",)),
    ("Bülent Yıldırım", ("bülent yıldırım",)),
    ("Seçim Demirel", ("seçim demirel",)),
    ("Aleks Taşçıoğlu", ("aleks taşçıoğlu", "taşçıoğlu")),
)

NEWS_QUERIES = (
    "Fırat Aydınus hakem Süper Lig",
    "Mustafa Çulcu hakem",
    "Ahmet Çakar hakem Süper Lig",
    "Deniz Ateş Bitnel hakem",
    "Trio hakem Süper Lig 2026",
    "Serdar Akçer hakem",
    "Erman Toroğlu hakem Süper Lig",
)

WRONG_RE = re.compile(
    r"görmeliydi|verilmeliydi|hatalı|kaçırıl|güme|olmalıydı|yanlış karar|penaltı yok|kırmızı yok|"
    r"verilmedi|ihraç olmalı|net penaltı|net kırmızı|kaçırılmış",
    re.I,
)
RIGHT_RE = re.compile(
    r"doğru karar|devam (doğru|kararı)|penaltı değil|kırmızı doğru|tartışmaya kapalı|yerinde (karar|iptal)",
    re.I,
)
MINUTE_RE = re.compile(r"(\d{1,3})\s*(?:['′.]|dk|dakika)", re.I)
EVENT_PATTERNS = (
    ("RED_CARD", re.compile(r"kırmızı")),
    ("PENALTY", re.compile(r"penaltı")),
    ("OFFSIDE", re.compile(r"ofsayt")),
    ("YELLOW_CARD", re.compile(r"sarı kart|sarı")),
    ("GOAL", re.compile(r"gol")),
)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,application/rss+xml,application/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_SCHEDULER: threading.Thread | None = None

FetchMatches = Callable[[], list[dict[str, Any]]]
FetchNews = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
FetchDetail = Callable[[str], dict[str, Any] | None]


def fold(value: str) -> str:
    return (value or "").translate(TR_MAP).casefold()


def slugify(value: str) -> str:
    text = fold(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:72]


def team_key(name: str) -> str:
    return slugify(name)


def team_side(name: str) -> dict[str, str]:
    meta = TEAM_META.get(team_key(name))
    if meta:
        return {"id": meta["id"], "name": meta["name"], "shortName": meta["shortName"]}
    key = team_key(name) or "takim"
    return {"id": key, "name": name, "shortName": (name[:3] or "???").upper()}


def split_person(full: str) -> tuple[str, str]:
    parts = [bit for bit in re.split(r"\s+", (full or "").strip()) if bit]
    if not parts:
        return "?", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def person_slug(full: str) -> str:
    return slugify(full) or "hakem"


def referee_row(full: str, role: str = "CENTER") -> dict[str, Any]:
    first, last = split_person(full)
    bio = {
        "CENTER": "Süper Lig orta hakemi.",
        "ASSISTANT": "Yardımcı hakem.",
        "FOURTH": "Dördüncü hakem.",
        "VAR": "VAR. Maç notuna dahil edilmez.",
        "AVAR": "AVAR. Maç notuna dahil edilmez.",
    }.get(role, "Hakem.")
    return {
        "firstName": first,
        "lastName": last,
        "slug": person_slug(full),
        "bio": bio,
        "isDemo": False,
    }


def parse_score(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    match = re.search(r"(\d+)\s*[-–]\s*(\d+)", text)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def to_istanbul(utc_text: str) -> str:
    raw = (utc_text or "").replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return utc_text
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(IST).isoformat()


def expert_in_text(text: str) -> str | None:
    folded = fold(text)
    for name, aliases in EXPERTS:
        if any(fold(alias) in folded for alias in aliases):
            return name
    if "trio" in folded:
        return "beIN Trio"
    return None


def claims_from_text(text: str, expert: str | None = None) -> list[dict[str, Any]]:
    blob = text or ""
    event_type = next((key for key, pattern in EVENT_PATTERNS if pattern.search(blob)), None)
    if not event_type:
        return []
    stance = "UNCLEAR"
    if WRONG_RE.search(blob) and not RIGHT_RE.search(blob):
        stance = "WRONG"
    elif RIGHT_RE.search(blob) and not WRONG_RE.search(blob):
        stance = "RIGHT"
    elif WRONG_RE.search(blob) and RIGHT_RE.search(blob):
        stance = "UNCLEAR"
    minute = None
    found = MINUTE_RE.search(blob)
    if found:
        minute = int(found.group(1))
        if minute > 120:
            minute = None
    return [
        {
            "expert": expert or expert_in_text(blob),
            "eventType": event_type,
            "stance": stance,
            "minute": minute,
            "excerpt": re.sub(r"\s+", " ", blob).strip()[:280],
        }
    ]


def _impact(event_type: str) -> str:
    if event_type in {"PENALTY", "RED_CARD", "GOAL", "OFFSIDE"}:
        return "CRITICAL"
    if event_type == "YELLOW_CARD":
        return "LOW"
    return "MEDIUM"


def incidents_from_claims(claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for claim in claims:
        if claim.get("stance") == "UNCLEAR" or claim.get("minute") is None:
            continue
        key = (claim.get("eventType"), claim.get("minute"))
        buckets.setdefault(key, []).append(claim)
    out = []
    for (event_type, minute), rows in sorted(buckets.items(), key=lambda item: item[0][1] or 0):
        experts = [row.get("expert") for row in rows if row.get("expert")]
        unique = list(dict.fromkeys(experts))
        wrong = sum(1 for row in rows if row["stance"] == "WRONG")
        right = sum(1 for row in rows if row["stance"] == "RIGHT")
        excerpts = [row["excerpt"] for row in rows if row.get("excerpt")]
        if wrong and right:
            verdict, confidence = "DEBATABLE", "SPLIT"
        elif wrong and len(unique) >= 2:
            verdict, confidence = "INCORRECT", "HIGH_CONFIDENCE_WRONG"
        elif wrong:
            verdict, confidence = "OPEN_REVIEW", "INSUFFICIENT"
        elif right and len(unique) >= 2:
            verdict, confidence = "CORRECT", "HIGH_CONFIDENCE"
        else:
            continue
        on_field = "Devam" if verdict in {"INCORRECT", "OPEN_REVIEW"} else "Saha kararı"
        out.append(
            {
                "minute": minute,
                "eventType": event_type,
                "onFieldDecision": on_field,
                "editorialVerdict": verdict,
                "impactLevel": _impact(event_type),
                "confidence": confidence,
                "description": " ".join(excerpts)[:420],
                "ifabRule": "IFAB 12" if event_type != "OFFSIDE" else "IFAB 11",
                "ifabUrl": (
                    "https://www.theifab.com/laws/latest/offside/"
                    if event_type == "OFFSIDE"
                    else "https://www.theifab.com/laws/latest/fouls-and-misconduct/"
                ),
                "sourceConfidence": 62 if verdict == "INCORRECT" else 48,
                "origin": "harvest",
                "sources": sources[:6],
            }
        )
    return out


def news_is_useful(title: str) -> bool:
    if expert_in_text(title):
        return True
    folded = fold(title)
    return any(bit in folded for bit in ("hakem", "trio", "penalti", "kirmizi", "ofsayt", "var "))


def match_article_to_slug(title: str, matches: list[dict[str, Any]]) -> str | None:
    folded = fold(title)
    hits = []
    for match in matches:
        home = fold(match["home"]["name"])
        away = fold(match["away"]["name"])
        home_aliases = TEAM_META.get(team_key(match["home"]["name"]), {}).get("aliases") or (home,)
        away_aliases = TEAM_META.get(team_key(match["away"]["name"]), {}).get("aliases") or (away,)
        if any(alias in folded for alias in home_aliases) and any(alias in folded for alias in away_aliases):
            hits.append(match)
    if not hits:
        return None
    hits.sort(key=lambda row: row.get("playedAt") or "", reverse=True)
    return hits[0]["slug"]


def _client() -> httpx.Client:
    return httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=28.0, verify=False)


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def harvest_status() -> dict[str, Any]:
    row = _load_json(STATUS_PATH, {})
    if not isinstance(row, dict):
        row = {}
    row.setdefault("state", "idle")
    row.setdefault("message", "Tarama henüz çalışmadı. Bitmiş maçlar birkaç dakika içinde eklenir.")
    return row


def _set_status(**kwargs: Any) -> dict[str, Any]:
    row = harvest_status()
    row.update(kwargs)
    _write_json(STATUS_PATH, row)
    return row


def _cache_get(bucket: str, key: str, ttl: float) -> Any | None:
    cache = _load_json(CACHE_PATH, {})
    row = ((cache.get(bucket) or {}).get(key)) if isinstance(cache, dict) else None
    if not isinstance(row, dict):
        return None
    if time.time() - float(row.get("t") or 0) > ttl:
        return None
    return row.get("v")


def _cache_set(bucket: str, key: str, value: Any) -> None:
    cache = _load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}
    cache.setdefault(bucket, {})
    cache[bucket][key] = {"t": time.time(), "v": value}
    _write_json(CACHE_PATH, cache)


def fetch_fotmob_matches() -> list[dict[str, Any]]:
    cached = _cache_get("league", FOTMOB_SEASON, 3 * 3600)
    if cached:
        return cached
    with _client() as client:
        response = client.get(
            f"https://www.fotmob.com/api/data/leagues?id={FOTMOB_LEAGUE}&season={FOTMOB_SEASON}"
        )
        response.raise_for_status()
        payload = response.json()
    rows = ((payload.get("fixtures") or {}).get("allMatches")) or []
    out = []
    for row in rows:
        status = row.get("status") or {}
        if not status.get("finished") or status.get("cancelled"):
            continue
        home = (row.get("home") or {}).get("name") or ""
        away = (row.get("away") or {}).get("name") or ""
        if not home or not away:
            continue
        home_score, away_score = parse_score(status.get("scoreStr"))
        if home_score is None:
            continue
        week = int(row.get("round") or row.get("roundName") or 0)
        played = to_istanbul(status.get("utcTime") or "")
        year = played[:4] if played else "2026"
        slug = f"{slugify(home)}-{slugify(away)}-{year}-{week}"
        out.append(
            {
                "slug": slug,
                "fotmobId": str(row.get("id") or ""),
                "season": SEASON,
                "week": week,
                "playedAt": played,
                "home": team_side(home),
                "away": team_side(away),
                "homeScore": home_score,
                "awayScore": away_score,
            }
        )
    _cache_set("league", FOTMOB_SEASON, out)
    return out


def fetch_fotmob_detail(match_id: str) -> dict[str, Any] | None:
    if not match_id:
        return None
    cached = _cache_get("detail", match_id, 7 * 24 * 3600)
    if cached is not None:
        return cached
    try:
        with _client() as client:
            response = client.get(f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError:
        return None
    facts = ((payload.get("content") or {}).get("matchFacts") or {})
    info = facts.get("infoBox") or {}
    referee = ((info.get("Referee") or {}).get("text") or "").strip()
    stadium = ((info.get("Stadium") or {}).get("name") or "").strip()
    row = {"referee": referee, "stadium": stadium or "—"}
    _cache_set("detail", match_id, row)
    time.sleep(0.12)
    return row


def fetch_news_items(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries = list(NEWS_QUERIES)
    recent = sorted(matches, key=lambda row: row.get("playedAt") or "", reverse=True)[:12]
    for match in recent:
        queries.append(f"{match['home']['name']} {match['away']['name']} hakem Trio")
        queries.append(f"{match['home']['name']} {match['away']['name']} Fırat Aydınus")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    with _client() as client:
        for query in queries:
            cached = _cache_get("rss", query, 4 * 3600)
            rows = cached
            if rows is None:
                url = (
                    "https://news.google.com/rss/search?q="
                    + quote(query)
                    + "&hl=tr&gl=TR&ceid=TR:tr"
                )
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    root = ET.fromstring(response.text)
                except (httpx.HTTPError, ET.ParseError):
                    continue
                rows = []
                for item in root.findall(".//item"):
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    source_el = item.find("source")
                    publisher = (source_el.text or "").strip() if source_el is not None else ""
                    published = item.findtext("pubDate") or ""
                    if not title or not link:
                        continue
                    rows.append(
                        {
                            "title": title,
                            "url": link,
                            "publisher": publisher or "Google Haberler",
                            "publishedAt": published,
                        }
                    )
                _cache_set("rss", query, rows)
                time.sleep(0.2)
            for row in rows or []:
                key = row.get("url") or row.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(row)
    return items


def attach_news(matches: list[dict[str, Any]], news: list[dict[str, Any]]) -> None:
    by_slug = {row["slug"]: row for row in matches}
    for item in news:
        if not news_is_useful(item["title"]):
            continue
        slug = match_article_to_slug(item["title"], matches)
        if not slug:
            continue
        match = by_slug[slug]
        published = ""
        try:
            published = parsedate_to_datetime(item.get("publishedAt") or "").date().isoformat()
        except (TypeError, ValueError):
            published = (match.get("playedAt") or "")[:10]
        expert = expert_in_text(item["title"])
        source = {
            "title": item["title"][:160],
            "publisher": expert or item.get("publisher") or "Haber",
            "url": item["url"],
            "sourceType": "EXPERT_COMMENTARY" if expert else "NEWS",
            "publishedAt": published,
            "excerpt": item["title"][:280],
            "approved": True,
            "origin": "harvest",
        }
        sources = match.setdefault("sources", [])
        harvest_count = sum(1 for row in sources if row.get("origin") == "harvest")
        if harvest_count >= 8:
            continue
        if any(row.get("url") == source["url"] for row in sources):
            continue
        sources.append(source)
        for claim in claims_from_text(item["title"], expert):
            match.setdefault("claims", []).append(claim)


def build_harvest_catalog(
    fixtures: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    referees: dict[str, dict[str, Any]] = {}
    matches = []
    fotmob_source = {
        "title": "Süper Lig fikstür ve maç kaydı",
        "publisher": "FotMob",
        "url": "https://www.fotmob.com/leagues/71/overview/super-lig",
        "sourceType": "NEWS",
        "publishedAt": datetime.now(IST).date().isoformat(),
        "excerpt": "Bitmiş 2026/27 Süper Lig maçları, skor ve orta hakem kaydı.",
        "approved": True,
        "origin": "harvest",
    }
    for row in fixtures:
        detail = details.get(row.get("fotmobId") or "") or {}
        referee_name = (detail.get("referee") or "").strip()
        officials = []
        if referee_name:
            ref = referee_row(referee_name, "CENTER")
            referees[ref["slug"]] = ref
            officials.append({"role": "CENTER", "refereeSlug": ref["slug"]})
        sources = [fotmob_source, *(row.get("sources") or [])]
        claims = row.get("claims") or []
        incidents = []
        if row["slug"] not in EDITORIAL_SLUGS:
            incidents = incidents_from_claims(claims, [src for src in sources if src.get("sourceType") == "EXPERT_COMMENTARY"] or sources)
        matches.append(
            {
                "slug": row["slug"],
                "season": SEASON,
                "week": row["week"],
                "playedAt": row["playedAt"],
                "stadium": detail.get("stadium") or "—",
                "fotmobId": row.get("fotmobId"),
                "home": row["home"],
                "away": row["away"],
                "homeScore": row["homeScore"],
                "awayScore": row["awayScore"],
                "isDemo": False,
                "origin": "harvest",
                "officials": officials,
                "sources": sources,
                "incidents": incidents,
            }
        )
    return {
        "season": SEASON,
        "harvestedAt": datetime.now(IST).isoformat(),
        "referees": list(referees.values()),
        "matches": matches,
    }


def merge_editorial(editorial: dict[str, Any], harvested: dict[str, Any]) -> dict[str, Any]:
    refs = {row["slug"]: row for row in harvested.get("referees") or []}
    for row in editorial.get("referees") or []:
        refs[row["slug"]] = row
    matches = {row["slug"]: row for row in harvested.get("matches") or []}
    for row in editorial.get("matches") or []:
        extra = matches.get(row["slug"]) or {}
        merged = dict(row)
        merged["lock"] = True
        if extra.get("fotmobId"):
            merged["fotmobId"] = merged.get("fotmobId") or extra["fotmobId"]
        seen = {src.get("url") for src in merged.get("sources") or []}
        sources = list(merged.get("sources") or [])
        extra_sources = [
            src
            for src in extra.get("sources") or []
            if src.get("origin") == "harvest" and src.get("sourceType") == "EXPERT_COMMENTARY"
        ]
        for src in extra_sources[:8]:
            if src.get("url") and src["url"] not in seen:
                sources.append(src)
                seen.add(src["url"])
        merged["sources"] = sources
        matches[row["slug"]] = merged
    return {
        "season": editorial.get("season") or harvested.get("season") or SEASON,
        "harvestedAt": harvested.get("harvestedAt") or editorial.get("harvestedAt"),
        "note": editorial.get("note") or "",
        "referees": list(refs.values()),
        "matches": list(matches.values()),
    }


def load_merged_catalog() -> dict[str, Any]:
    editorial = _load_json(EDITORIAL_PATH, {"referees": [], "matches": []})
    harvested = _load_json(HARVEST_PATH, {"referees": [], "matches": []})
    return merge_editorial(editorial, harvested)


def harvest(
    *,
    fetch_matches: FetchMatches | None = None,
    fetch_news: FetchNews | None = None,
    fetch_detail: FetchDetail | None = None,
) -> dict[str, Any]:
    if not _LOCK.acquire(blocking=False):
        status = harvest_status()
        status["message"] = "Tarama zaten sürüyor."
        return status
    started = datetime.now(IST).isoformat()
    _set_status(state="running", startedAt=started, message="Bitmiş maçlar ve köşe haberleri taranıyor.")
    try:
        fixtures = (fetch_matches or fetch_fotmob_matches)()
        details: dict[str, dict[str, Any]] = {}
        detail_fn = fetch_detail or fetch_fotmob_detail
        for row in fixtures:
            mid = row.get("fotmobId") or ""
            info = detail_fn(mid)
            if info:
                details[mid] = info
        news = (fetch_news or fetch_news_items)(fixtures)
        attach_news(fixtures, news)
        catalog = build_harvest_catalog(fixtures, details)
        _write_json(HARVEST_PATH, catalog)
        added = sum(1 for row in catalog["matches"] if row["slug"] not in EDITORIAL_SLUGS)
        status = _set_status(
            state="idle",
            startedAt=started,
            finishedAt=datetime.now(IST).isoformat(),
            added=added,
            total=len(catalog["matches"]),
            sources=sum(len(row.get("sources") or []) for row in catalog["matches"]),
            message=(
                f"{len(catalog['matches'])} bitmiş maç okundu, {added} yeni maç masaya eklendi. "
                "Kilitli maçların el ile işlenmiş notları duruyor."
            ),
        )
        return status
    except Exception as extra:
        return _set_status(
            state="error",
            startedAt=started,
            finishedAt=datetime.now(IST).isoformat(),
            message=f"Tarama başarısız: {extra}",
        )
    finally:
        _LOCK.release()


def start_harvest_async() -> dict[str, Any]:
    global _THREAD
    status = harvest_status()
    if _LOCK.locked() or status.get("state") == "running":
        return {**status, "message": "Tarama zaten sürüyor."}

    def run() -> None:
        harvest()

    _THREAD = threading.Thread(target=run, daemon=True, name="hakem-harvest")
    _THREAD.start()
    return _set_status(state="running", message="Tarama başladı.")


def start_scheduler() -> None:
    global _SCHEDULER
    if _SCHEDULER and _SCHEDULER.is_alive():
        return

    def loop() -> None:
        time.sleep(2)
        while True:
            try:
                harvest()
            except Exception:
                pass
            time.sleep(INTERVAL_SEC)

    _SCHEDULER = threading.Thread(target=loop, daemon=True, name="hakem-harvest-loop")
    _SCHEDULER.start()

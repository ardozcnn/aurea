"""FotMob lig üretimi: şut, beklenen gol, son maçlar. Puan göstermez."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.config import CACHE_SQLITE, DATA_DIR, USER_AGENT
from app.slugs import fold_tr

_LOCK = threading.Lock()
_TTL = 6 * 3600
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Origin": "https://www.fotmob.com",
    "Referer": "https://www.fotmob.com/",
}
_BASE = "https://www.fotmob.com/api/data"


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


def _set_cache(key: str, payload: Any, ttl: float = _TTL) -> None:
    with _LOCK:
        con = _db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO kv(key, payload, expires) VALUES (?, ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False, default=str), time.time() + ttl),
            )
            con.commit()
        finally:
            con.close()


def _get_json(path: str) -> Any | None:
    url = f"{_BASE}/{path.lstrip('/')}"
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=12.0, verify=False) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.json()
    except Exception:
        return None


def _same_team(left: str, right: str) -> bool:
    a, b = fold_tr(left), fold_tr(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    generic = {"fk", "jk", "spor", "sportif", "faaliyetler", "istanbul", "as", "fc", "cf"}
    at, bt = set(a.split()) - generic, set(b.split()) - generic
    return bool(at and bt and len(at & bt) / len(at | bt) >= 0.45)


def _score_name(query: str, candidate: str) -> int:
    q, c = fold_tr(query), fold_tr(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.endswith(q) or q.endswith(c):
        return 86
    qt, ct = set(q.split()), set(c.split())
    if qt and qt <= ct:
        return 80
    last_q = q.split()[-1]
    last_c = c.split()[-1]
    if last_q and last_q == last_c and len(last_q) >= 4:
        return 74
    try:
        from rapidfuzz import fuzz

        return int(fuzz.token_sort_ratio(q, c))
    except Exception:
        return 40 if q in c or c in q else 0


def _pick_player(name: str, club: str | None, payload: Any) -> dict[str, Any] | None:
    hits: list[dict[str, Any]] = []
    groups = payload if isinstance(payload, list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hit in group.get("suggestions") or []:
            if not isinstance(hit, dict):
                continue
            if str(hit.get("type") or "") != "player" or not hit.get("id"):
                continue
            hits.append(hit)
    if not hits:
        return None
    best = None
    best_score = 0
    for hit in hits:
        score = _score_name(name, str(hit.get("name") or ""))
        team = str(hit.get("teamName") or "")
        if club and _same_team(club, team):
            score += 12
        if score > best_score:
            best_score = score
            best = hit
    if best_score < 62:
        return None
    return best


def _num(item: dict, *keys: str) -> float:
    for key in keys:
        raw = item.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _deep_map(payload: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    section = (payload.get("firstSeasonStats") or {}).get("statsSection") or {}
    for group in section.get("items") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip().lower()
            raw = str(item.get("statValue") or "").replace(",", "")
            try:
                out[title] = float(raw)
            except ValueError:
                continue
    return out


def _league_stats(payload: dict[str, Any], player_id: str) -> dict[str, float]:
    main = payload.get("mainLeague") or {}
    season_name = str(main.get("season") or "")
    league_id = int(main.get("leagueId") or 0)
    entry_id = ""
    for season in payload.get("statSeasons") or []:
        if str(season.get("seasonName") or "") != season_name:
            continue
        for tournament in season.get("tournaments") or []:
            if int(tournament.get("tournamentId") or 0) == league_id:
                entry_id = str(tournament.get("entryId") or "")
                break
    if not entry_id:
        return {}
    stats = _get_json(f"playerStats?playerId={player_id}&seasonId={quote(entry_id)}&isFirstSeason=false")
    if not isinstance(stats, dict):
        return {}
    return _deep_map({"firstSeasonStats": stats})


def player_dossier(name: str, club: str | None = None) -> dict[str, Any] | None:
    q = (name or "").strip()
    if len(q) < 3:
        return None
    key = f"fotmob:{fold_tr(q)}:{fold_tr(club or '')}"
    cached = _get_cache(key)
    if isinstance(cached, dict):
        if cached.get("empty"):
            return None
        return cached
    search = _get_json(f"search/suggest?term={quote(q)}")
    if search is None:
        return None
    hit = _pick_player(q, club, search)
    if not hit:
        _set_cache(key, {"empty": True}, ttl=20 * 60)
        return None
    player_id = str(hit.get("id") or "")
    payload = _get_json(f"playerData?id={player_id}")
    if not isinstance(payload, dict):
        return None
    main = payload.get("mainLeague") or {}
    totals: dict[str, float] = {}
    for item in main.get("stats") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("localizedTitleId") or item.get("title") or "").lower()
        try:
            totals[label] = float(item.get("value") or 0)
        except (TypeError, ValueError):
            continue
    deep = _league_stats(payload, player_id)
    raw_matches = (
        payload.get("recentMatches")
        or payload.get("lastMatches")
        or payload.get("recent")
        or []
    )
    collected = []
    for match in raw_matches:
        if not isinstance(match, dict):
            continue
        if match.get("playedInMatch") is False:
            continue
        minutes = _num(match, "minutesPlayed") or _num(match, "minutes")
        if minutes <= 0:
            continue
        collected.append(
            {
                "opponent": match.get("opponentName") or match.get("opponent") or "",
                "minutes": int(minutes),
                "goals": int(_num(match, "goals")),
                "assists": int(_num(match, "assists")),
                "started": not bool(match.get("onBench")),
                "when": ((match.get("matchDate") or {}).get("utcTime") if isinstance(match.get("matchDate"), dict) else None),
                "league": match.get("leagueName") or "",
                "team": str(match.get("teamName") or ""),
            }
        )
    recent = [m for m in collected if club and _same_team(club, m.get("team") or "")]
    if not recent:
        recent = collected
    recent = recent[:6]
    apps = totals.get("matches_uppercase") or totals.get("matches") or 0.0
    minutes = totals.get("minutes_played") or 0.0
    goals = totals.get("goals") or 0.0
    assists = totals.get("assists") or 0.0
    xg = deep.get("xg") or deep.get("expected goals") or 0.0
    xa = deep.get("expected assists") or deep.get("xa") or 0.0
    shots = deep.get("shots") or 0.0
    sot = deep.get("shots on target") or 0.0
    key_passes = deep.get("key passes") or deep.get("chances created") or 0.0
    tackles = deep.get("tackles") or deep.get("tackles won") or 0.0
    interceptions = deep.get("interceptions") or 0.0
    recoveries = deep.get("recoveries") or deep.get("possession won") or 0.0
    clean_sheets = deep.get("clean sheets") or deep.get("clean sheet") or 0.0
    pass_pct = deep.get("accurate passes %") or deep.get("pass accuracy") or deep.get("accurate passes percentage") or 0.0
    dribbles = deep.get("successful dribbles") or deep.get("dribbles") or 0.0
    n90 = minutes / 90.0 if minutes else 0.0
    dossier = {
        "source": "FotMob",
        "player_id": player_id,
        "name": payload.get("name") or hit.get("name") or q,
        "team": str((payload.get("primaryTeam") or {}).get("teamName") or hit.get("teamName") or club or ""),
        "league": main.get("leagueName") or "",
        "season": main.get("season") or "",
        "apps": int(apps) if apps else 0,
        "starts": int(totals.get("started") or 0),
        "minutes": int(minutes) if minutes else 0,
        "goals": int(goals) if goals else 0,
        "assists": int(assists) if assists else 0,
        "xg": round(float(xg), 2) if xg else 0.0,
        "xa": round(float(xa), 2) if xa else 0.0,
        "shots": int(shots) if shots else 0,
        "sot": int(sot) if sot else 0,
        "key_passes": round(float(key_passes), 1) if key_passes else 0.0,
        "tackles": int(tackles) if tackles else 0,
        "interceptions": int(interceptions) if interceptions else 0,
        "recoveries": int(recoveries) if recoveries else 0,
        "clean_sheets": int(clean_sheets) if clean_sheets else 0,
        "pass_pct": round(float(pass_pct), 1) if pass_pct else 0.0,
        "dribbles": int(dribbles) if dribbles else 0,
        "goals_p90": round(goals / n90, 2) if n90 else 0.0,
        "assists_p90": round(assists / n90, 2) if n90 else 0.0,
        "xg_p90": round(xg / n90, 2) if n90 and xg else 0.0,
        "xa_p90": round(xa / n90, 2) if n90 and xa else 0.0,
        "injured": bool(payload.get("injuryInformation")),
        "recent": recent,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if dossier["apps"] <= 0 and not recent:
        _set_cache(key, {"empty": True}, ttl=90 * 60)
        return None
    _set_cache(key, dossier)
    return dossier

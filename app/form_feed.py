"""Sofascore oyuncu formu: puan ve maç notu. Transfermarkt etiketini değiştirmez."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import quote

from app.config import CACHE_SQLITE, DATA_DIR, USER_AGENT

_LOCK = threading.Lock()
_TTL = 6 * 3600
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/",
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


def _set_cache(key: str, payload: Any) -> None:
    with _LOCK:
        con = _db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO kv(key, payload, expires) VALUES (?, ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False, default=str), time.time() + _TTL),
            )
            con.commit()
        finally:
            con.close()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _score_name(query: str, candidate: str) -> int:
    q = _norm(query)
    c = _norm(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.endswith(q) or q.endswith(c):
        return 88
    qt = set(q.split())
    ct = set(c.split())
    if qt and qt <= ct:
        return 82
    last_q = q.split()[-1]
    last_c = c.split()[-1]
    if last_q and last_q == last_c and len(last_q) >= 4:
        return 74
    if q in c or c in q:
        return 62
    try:
        from rapidfuzz import fuzz

        return int(fuzz.token_sort_ratio(q, c))
    except Exception:
        return 0


def _get_json(url: str) -> Any | None:
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate="chrome")
        response = session.get(url, headers=_HEADERS, timeout=8, verify=False)
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception:
        pass
    try:
        import httpx

        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=8.0, verify=False) as client:
            response = client.get(url)
            if response.status_code >= 400:
                return None
            return response.json()
    except Exception:
        return None


def _pick_player(query: str, club: str | None, results: list) -> dict | None:
    best = None
    best_score = 0
    club_n = _norm(club or "")
    for item in results:
        if not isinstance(item, dict):
            continue
        entity = item.get("entity") if item.get("type") in (None, "player") else None
        if entity is None and "name" in item and "id" in item:
            entity = item
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or entity.get("shortName") or "")
        team = ""
        team_obj = entity.get("team") or entity.get("teamName")
        if isinstance(team_obj, dict):
            team = str(team_obj.get("name") or "")
        elif team_obj:
            team = str(team_obj)
        score = _score_name(query, name)
        if club_n and club_n in _norm(team):
            score += 8
        if score > best_score:
            best_score = score
            best = entity
    if best_score < 58:
        return None
    return best


def player_form(name: str, club: str | None = None) -> dict[str, Any] | None:
    q = (name or "").strip()
    if len(q) < 3:
        return None
    key = f"sofa:{_norm(q)}:{_norm(club or '')}"
    cached = _get_cache(key)
    if isinstance(cached, dict) and cached.get("empty"):
        return None
    if cached is not None:
        return cached
    data = _get_json(f"https://www.sofascore.com/api/v1/search/all?q={quote(q)}")
    results = []
    if isinstance(data, dict):
        results = data.get("results") or data.get("players") or []
        if isinstance(data.get("results"), dict):
            results = (data["results"].get("players") or []) + (data["results"].get("all") or [])
    if not isinstance(results, list) or not results:
        _set_cache(key, {"empty": True})
        return None
    entity = _pick_player(q, club, results)
    if not entity:
        _set_cache(key, {"empty": True})
        return None
    pid = entity.get("id")
    rating = entity.get("rating") or entity.get("averageRating")
    matches = entity.get("appearances") or entity.get("matches")
    team = ""
    team_obj = entity.get("team")
    if isinstance(team_obj, dict):
        team = str(team_obj.get("name") or "")
    if pid:
        detail = _get_json(f"https://www.sofascore.com/api/v1/player/{pid}")
        player = (detail or {}).get("player") if isinstance(detail, dict) else None
        if isinstance(player, dict):
            team = str((player.get("team") or {}).get("name") or team)
            rating = rating or player.get("rating") or player.get("averageRating")
        seasons = _get_json(f"https://www.sofascore.com/api/v1/player/{pid}/statistics/seasons")
        blocks = []
        if isinstance(seasons, dict):
            blocks = seasons.get("uniqueTournamentSeasons") or []
        if isinstance(blocks, list) and blocks:
            first = blocks[0] if isinstance(blocks[0], dict) else {}
            tid = (first.get("uniqueTournament") or {}).get("id")
            season_list = first.get("seasons") or []
            sid = season_list[0].get("id") if season_list and isinstance(season_list[0], dict) else None
            if tid and sid:
                overall = _get_json(
                    f"https://www.sofascore.com/api/v1/player/{pid}/unique-tournament/{tid}/season/{sid}/statistics/overall"
                )
                stats_obj = (overall or {}).get("statistics") if isinstance(overall, dict) else None
                if isinstance(stats_obj, dict):
                    rating = stats_obj.get("rating") or stats_obj.get("averageRating") or rating
                    matches = stats_obj.get("appearances") or stats_obj.get("matches") or stats_obj.get("countRating") or matches
    payload = {
        "source": "Sofascore",
        "player_id": pid,
        "name": entity.get("name"),
        "team": team,
        "rating": float(rating) if rating is not None else None,
        "matches": int(matches) if matches is not None else None,
    }
    if payload["rating"] is None and payload["matches"] is None:
        _set_cache(key, {"empty": True})
        return None
    _set_cache(key, payload)
    return payload

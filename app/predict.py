"""Süper Lig haftalık skor tahmini: Poisson–Dixon–Coles, bitmiş maçta gerçek skor."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.form_feed import _get_json
from app.live_tm import _get_cache, _set_cache
from app.store import json_safe

_TTL = 8 * 60
_TOURNAMENT = 52
_HOME_AVG = 1.28
_AWAY_AVG = 1.05
_RHO = 0.04
_PRIOR_GAMES = 14.0
_CAP = 6

_FOLD = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


def _fold(text: str) -> str:
    return (
        str(text or "")
        .translate(_FOLD)
        .casefold()
        .replace(".", "")
        .replace("fk", "")
        .replace("sk", "")
        .replace("jk", "")
        .replace("  ", " ")
        .strip()
    )


def _tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Istanbul")
    except Exception:
        return timezone(timedelta(hours=3))


def _poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))


def _tau(i: int, j: int, lh: float, la: float, rho: float) -> float:
    if i == 0 and j == 0:
        return 1.0 - lh * la * rho
    if i == 0 and j == 1:
        return 1.0 + lh * rho
    if i == 1 and j == 0:
        return 1.0 + la * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def _most_likely(lh: float, la: float) -> tuple[int, int, float]:
    best_i, best_j, best_p = 1, 0, -1.0
    for i in range(_CAP + 1):
        pi = _poisson(i, lh)
        for j in range(_CAP + 1):
            p = pi * _poisson(j, la) * max(0.02, _tau(i, j, lh, la, _RHO))
            if p > best_p:
                best_i, best_j, best_p = i, j, p
    return best_i, best_j, best_p


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _goals(event: dict[str, Any]) -> tuple[int, int] | None:
    home = event.get("homeScore") or {}
    away = event.get("awayScore") or {}
    hs = home.get("current")
    ag = away.get("current")
    if hs is None:
        hs = home.get("display")
    if ag is None:
        ag = away.get("display")
    try:
        if hs is None or ag is None:
            return None
        return int(hs), int(ag)
    except (TypeError, ValueError):
        return None


def _team_name(event: dict[str, Any], side: str) -> str:
    blob = event.get(side) or {}
    return str(blob.get("name") or blob.get("shortName") or "").strip()


def _status_type(event: dict[str, Any]) -> str:
    st = event.get("status") or {}
    return str(st.get("type") or "").lower()


def _collect_events(season_id: int, kind: str, pages: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(pages):
        data = _get_json(
            f"https://www.sofascore.com/api/v1/unique-tournament/{_TOURNAMENT}/season/{season_id}/events/{kind}/{page}"
        )
        if not isinstance(data, dict):
            break
        rows = data.get("events") or []
        if isinstance(rows, list):
            out.extend(row for row in rows if isinstance(row, dict))
        if not data.get("hasNextPage"):
            break
    return out


def _seasons() -> list[dict[str, Any]]:
    data = _get_json(f"https://www.sofascore.com/api/v1/unique-tournament/{_TOURNAMENT}/seasons")
    rows = (data or {}).get("seasons") if isinstance(data, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _club_priors() -> dict[str, float]:
    try:
        from app.store import universe

        df = universe()
        part = df[df["league_id"].astype("string") == "TR1"]
        if part.empty:
            return {}
        grouped = part.groupby(part["current_club_name"].astype("string"), dropna=False)
        raw: dict[str, float] = {}
        for name, chunk in grouped:
            key = _fold(str(name or ""))
            if not key:
                continue
            if float(chunk["minutes_365"].fillna(0).sum()) < 2500 and len(chunk) < 10:
                continue
            value = float(chunk["true_value"].fillna(0).sum())
            if value <= 0:
                value = float(chunk["market_value_in_eur"].fillna(0).sum())
            raw[key] = max(raw.get(key, 0.0), value)
        if not raw:
            return {}
        logs = {k: math.log1p(v) for k, v in raw.items()}
        vals = list(logs.values())
        mid = sorted(vals)[len(vals) // 2]
        spread = max(0.35, (max(vals) - min(vals)) / 2.0)
        return {k: _clip(1.0 + 0.22 * ((v - mid) / spread), 0.78, 1.28) for k, v in logs.items()}
    except Exception:
        return {}


def _prior_of(name: str, priors: dict[str, float]) -> float:
    key = _fold(name)
    if key in priors:
        return priors[key]
    for other, value in priors.items():
        if key and other and (key in other or other in key):
            return value
    return 1.0


def _ingest(events: list[dict[str, Any]], weight: float, acc: dict[str, dict[str, float]]) -> None:
    for event in events:
        if _status_type(event) not in {"finished", "ended"}:
            continue
        goals = _goals(event)
        if goals is None:
            continue
        home = _team_name(event, "homeTeam")
        away = _team_name(event, "awayTeam")
        if not home or not away:
            continue
        hg, ag = goals
        hk, ak = _fold(home), _fold(away)
        w = float(weight)
        for key, gf, ga in ((hk, hg, ag), (ak, ag, hg)):
            row = acc[key]
            row["name"] = home if key == hk else away
            row["gf"] += gf * w
            row["ga"] += ga * w
            row["n"] += w
        row_h = acc[hk]
        row_a = acc[ak]
        row_h["results"].append("G" if hg > ag else ("B" if hg == ag else "M"))
        row_a["results"].append("G" if ag > hg else ("B" if ag == hg else "M"))
        row_h["meet"].append((ak, hg, ag, w))
        row_a["meet"].append((hk, ag, hg, w))


def _rates(acc: dict[str, dict[str, float]], priors: dict[str, float]) -> dict[str, dict[str, float]]:
    games = [row["n"] for row in acc.values() if row["n"] > 0]
    gf_pg = (
        sum(row["gf"] for row in acc.values()) / max(sum(games), 0.01)
        if games
        else (_HOME_AVG + _AWAY_AVG) / 2.0
    )
    ga_pg = (
        sum(row["ga"] for row in acc.values()) / max(sum(games), 0.01)
        if games
        else (_HOME_AVG + _AWAY_AVG) / 2.0
    )
    out: dict[str, dict[str, float]] = {}
    for key, row in acc.items():
        n = row["n"]
        prior = _prior_of(row.get("name") or key, priors)
        w = n / (n + _PRIOR_GAMES) if n else 0.0
        att_obs = (row["gf"] / n) / max(gf_pg, 0.35) if n else prior
        def_obs = (row["ga"] / n) / max(ga_pg, 0.35) if n else (2.0 - prior)
        att = w * att_obs + (1.0 - w) * prior
        deff = w * def_obs + (1.0 - w) * _clip(2.0 - prior, 0.78, 1.28)
        form = "".join((row.get("results") or [])[-5:])
        form_n = form.count("G") - form.count("M")
        tilt = 1.0 + 0.02 * math.tanh(form_n / 2.5)
        out[key] = {
            "att": _clip(att * tilt, 0.70, 1.45),
            "defn": _clip(deff / max(tilt, 0.85), 0.70, 1.45),
            "form": form,
            "name": row.get("name") or key,
            "n": n,
        }
    return out


def _h2h(acc: dict[str, dict[str, float]], home: str, away: str) -> tuple[float, float]:
    hk, ak = _fold(home), _fold(away)
    meets = (acc.get(hk) or {}).get("meet") or []
    recent = [row for row in meets if row[0] == ak][-4:]
    if not recent:
        return 0.0, 0.0
    gf = sum(row[1] * row[3] for row in recent) / max(sum(row[3] for row in recent), 0.01)
    ga = sum(row[2] * row[3] for row in recent) / max(sum(row[3] for row in recent), 0.01)
    return _clip((gf - _HOME_AVG) * 0.12, -0.18, 0.18), _clip((ga - _AWAY_AVG) * 0.12, -0.18, 0.18)


def _kick_label(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        moment = datetime.fromtimestamp(int(ts), timezone.utc).astimezone(_tz())
        weekdays = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
        return f"{weekdays[moment.weekday()]} {moment.strftime('%d.%m %H:%M')}"
    except (OSError, OverflowError, ValueError, TypeError):
        return ""


def _lambda(
    home: str,
    away: str,
    rates: dict[str, dict[str, float]],
    acc: dict[str, dict[str, float]],
    priors: dict[str, float],
) -> tuple[float, float]:
    hk, ak = _fold(home), _fold(away)
    ph = _prior_of(home, priors)
    pa = _prior_of(away, priors)
    rh = rates.get(hk) or {"att": ph, "defn": _clip(2.0 - ph, 0.78, 1.28)}
    ra = rates.get(ak) or {"att": pa, "defn": _clip(2.0 - pa, 0.78, 1.28)}
    att_h = float(rh["att"])
    def_h = float(rh["defn"])
    att_a = float(ra["att"])
    def_a = float(ra["defn"])
    if ph >= 1.16:
        att_h = max(att_h, 1.10)
        def_h = min(def_h, 0.94)
    if pa >= 1.16:
        att_a = max(att_a, 1.10)
        def_a = min(def_a, 0.94)
    lh = _HOME_AVG * att_h * def_a
    la = _AWAY_AVG * att_a * def_h
    if pa > ph + 0.06:
        la = max(la, lh * 0.96)
        lh *= 0.92
    dh, da = _h2h(acc, home, away)
    return _clip(lh + dh, 0.40, 3.35), _clip(la + da, 0.35, 3.10)


def _form_of(name: str, rates: dict[str, dict[str, float]]) -> str:
    row = rates.get(_fold(name)) or {}
    letters = str(row.get("form") or "")
    if not letters:
        return ""
    return " ".join(letters[-5:])


def week(*, refresh: bool = False) -> dict[str, Any]:
    key = "superlig:week:v2"
    if not refresh:
        cached = _get_cache(key)
        if isinstance(cached, dict) and cached.get("matches"):
            return cached
    seasons = _seasons()
    if not seasons:
        return {"ok": False, "matches": [], "round": None}
    current_id = int(seasons[0].get("id") or 0)
    rounds = _get_json(
        f"https://www.sofascore.com/api/v1/unique-tournament/{_TOURNAMENT}/season/{current_id}/rounds"
    )
    round_n = None
    if isinstance(rounds, dict):
        round_n = (rounds.get("currentRound") or {}).get("round")
    try:
        round_n = int(round_n)
    except (TypeError, ValueError):
        round_n = 1
    bundle = _get_json(
        f"https://www.sofascore.com/api/v1/unique-tournament/{_TOURNAMENT}/season/{current_id}/events/round/{round_n}"
    )
    events = [row for row in ((bundle or {}).get("events") or []) if isinstance(row, dict)]
    if events and all(_status_type(row) in {"finished", "ended"} for row in events):
        nxt = _get_json(
            f"https://www.sofascore.com/api/v1/unique-tournament/{_TOURNAMENT}/season/{current_id}/events/round/{round_n + 1}"
        )
        extra = [row for row in ((nxt or {}).get("events") or []) if isinstance(row, dict)]
        if extra:
            round_n += 1
            events = extra
    acc: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"gf": 0.0, "ga": 0.0, "n": 0.0, "results": [], "meet": [], "name": ""}
    )
    current_last = sorted(
        _collect_events(current_id, "last", pages=3),
        key=lambda row: int(row.get("startTimestamp") or 0),
    )
    _ingest(current_last, 1.0, acc)
    priors = _club_priors()
    rates = _rates(acc, priors)
    matches: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda row: int(row.get("startTimestamp") or 0)):
        home = _team_name(event, "homeTeam")
        away = _team_name(event, "awayTeam")
        if not home or not away:
            continue
        kind = _status_type(event)
        actual = _goals(event) if kind in {"finished", "ended", "inprogress"} else None
        lh, la = _lambda(home, away, rates, acc, priors)
        ph, pa, _prob = _most_likely(lh, la)
        if kind in {"finished", "ended"} and actual:
            display_h, display_a = actual
            state = "skor"
        elif kind == "inprogress" and actual:
            display_h, display_a = actual
            state = "canli"
        else:
            display_h, display_a = ph, pa
            state = "tahmin"
        matches.append(
            {
                "home": home,
                "away": away,
                "home_form": _form_of(home, rates),
                "away_form": _form_of(away, rates),
                "kickoff": _kick_label(event.get("startTimestamp")),
                "ts": event.get("startTimestamp"),
                "state": state,
                "home_goals": display_h,
                "away_goals": display_a,
                "score": f"{display_h}–{display_a}",
                "pred_score": f"{ph}–{pa}",
                "pred_home": ph,
                "pred_away": pa,
            }
        )
    payload = {
        "ok": True,
        "round": round_n,
        "season": str(seasons[0].get("year") or ""),
        "matches": matches,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _set_cache(key, payload, ttl=_TTL)
    return json_safe(payload)

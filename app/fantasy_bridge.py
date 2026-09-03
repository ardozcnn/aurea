"""TFF Fantezi Lig motorunu web API’ye bağlar. PNG üretmez."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from app.config import DATA_DIR, FANTASY_CACHE, FANTASY_ROOT
from app.store import json_safe

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATE: dict[str, Any] = {
    "phase": "idle",
    "message": "Kadro henüz hesaplanmadı.",
    "progress": 0.0,
    "error": None,
    "updated_at": None,
}
_LAST: dict[str, Any] | None = None
_SESSION: dict[str, Any] | None = None
_HAUL_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_PLAYER_KEYS = (
    "player",
    "display_name",
    "team",
    "position",
    "price_m",
    "projected_pts",
    "pts_if_plays",
    "play_probability",
    "fixture_opponent",
    "fixture_home",
    "fixture_attack_mult",
    "fixture_cs_mult",
    "fixture_band",
    "fixture_p_cs",
    "fixture_lambda_for",
    "fixture_lambda_against",
    "fixture_match_kind",
    "cs_after_fixture",
    "reason",
    "form_apps",
    "current_apps",
    "prev_apps",
    "gls_pa",
    "ast_pa",
    "xg_pa",
    "current_minutes",
    "tff_minutes",
    "fotmob_recent_starts",
    "fotmob_recent_played",
    "availability",
    "avail_news",
    "avail_pct",
    "data_src",
    "tff_points",
    "tff_round_points",
    "tff_goals",
    "tff_assists",
    "tff_form",
    "selected_by",
    "rating",
    "ppm",
    "tff_ppm",
    "selection_pts",
    "bench_rank",
    "table_pos",
    "opp_table_pos",
    "table_n",
    "team_gf_pg",
    "team_ga_pg",
    "opp_gf_pg",
    "opp_ga_pg",
    "odds_favorite",
    "odds_p_win",
    "odds_p_over_25",
    "odds_p_btts",
    "odds_p_first",
    "odds_corner_line",
    "odds_expected_corners",
    "odds_gs_override",
    "odds_source",
)

def _league_id() -> str:
    return (os.environ.get("TFF_LEAGUE_ID") or "1").strip() or "1"


def _account_paths(league_id: str) -> list[str]:
    q = "league-id=" + league_id
    return [
        f"users/me?{q}",
        "users/me",
        f"fantasy-team?{q}",
        f"fantasy-team?{q}&mode=editable",
        f"fantasy-team?{q}&view=editable",
        f"fantasy-team/chips?{q}",
        f"fantasy-team/history?{q}",
        f"fantasy-team/points?{q}",
        f"leagues/mine-v2?{q}",
        "leagues/mine-v2",
        f"leagues/dashboard?{q}",
        f"leagues/standings?{q}",
        f"leagues/detail?{q}",
        f"projection/fantasy-team?{q}",
        f"projection/stats/my-team?{q}",
        f"projection/stats/dashboard?{q}",
        f"projection/stats/gameweek-history?{q}",
        f"projection/stats/points?{q}",
        f"projection/stats/entry?{q}",
        f"projection/stats/user?{q}",
        f"users/me/fantasy-team?{q}",
        f"users/me/history?{q}",
        f"me/team?{q}",
    ]

_CARD_EXPLAIN = {
    "Dört Dörtlük Kaptan": "Kaptanın haftalık puanı dört katına çıkar.",
    "Tripleks Kaptan": "Kaptanın haftalık puanı üç katına çıkar.",
    "Tüm Takım Sahaya": "Yedek kulübesindeki oyuncular da bu hafta puan alır.",
    "Hücum": "Hücum kartı, bütçe ve diziliş kısıtlarını gevşetir.",
    "Limitsiz Bütçe": "Transferde bütçe tavanı kalkar.",
}

_KNOWN_CHIPS = (
    "Tripleks Kaptan",
    "Dört Dörtlük Kaptan",
    "Tüm Takım Sahaya",
    "Hücum",
    "Limitsiz Bütçe",
)
_CHIP_ALIAS = {
    "triplecaptain": "Tripleks Kaptan",
    "triplekskaptan": "Tripleks Kaptan",
    "tripleks": "Tripleks Kaptan",
    "3c": "Tripleks Kaptan",
    "3xc": "Tripleks Kaptan",
    "quadcaptain": "Dört Dörtlük Kaptan",
    "dortdortlukkaptan": "Dört Dörtlük Kaptan",
    "skipperup": "Dört Dörtlük Kaptan",
    "4c": "Dört Dörtlük Kaptan",
    "teamboost": "Tüm Takım Sahaya",
    "tumtakimsahaya": "Tüm Takım Sahaya",
    "benchboost": "Tüm Takım Sahaya",
    "bboost": "Tüm Takım Sahaya",
    "attackchip": "Hücum",
    "attack": "Hücum",
    "hücum": "Hücum",
    "hucum": "Hücum",
    "unlimitedbudget": "Limitsiz Bütçe",
    "limitsizbutce": "Limitsiz Bütçe",
    "limitless": "Limitsiz Bütçe",
}
_SKIP_WALK = {
    "players",
    "picks",
    "elements",
    "squad",
    "fixtures",
    "clubs",
    "sponsors",
    "predictions",
}
_POINT_KEYS = (
    "overallpoints",
    "totalpoints",
    "seasonpoints",
    "activepoints",
    "aktifpuan",
    "aktifpuani",
    "currentpoints",
    "seasonscore",
    "overallscore",
    "totalscores",
    "pointstotal",
)
_GW_KEYS = (
    "gameweekpoints",
    "matchweekpoints",
    "eventpoints",
    "roundpoints",
    "gwpoints",
    "weekpoints",
    "currenteventpoints",
    "thisweekpoints",
    "latestpoints",
    "lastgameweekpoints",
)
_RANK_KEYS = (
    "overallrank",
    "globalrank",
    "generalranking",
    "overallranking",
    "seasonrank",
    "activerank",
    "totalrank",
)
_FOLD_MAP = str.maketrans(
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
_RATIO_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$")


def _fold_token(word: str) -> str:
    return str(word or "").translate(_FOLD_MAP).casefold()


def _tidy_name(text: str) -> str:
    words = [w for w in re.split(r"\s+", str(text or "").strip()) if w]
    if not words:
        return ""
    n = len(words)
    for length in range(n // 2, 0, -1):
        left = [_fold_token(w) for w in words[:length]]
        mid = [_fold_token(w) for w in words[length : 2 * length]]
        if left == mid:
            chosen = []
            for a, b in zip(words[:length], words[length : 2 * length]):
                if sum(ord(ch) > 127 for ch in b) > sum(ord(ch) > 127 for ch in a):
                    chosen.append(b)
                else:
                    chosen.append(a)
            return _tidy_name(" ".join(chosen + words[2 * length :]))
    kept: list[str] = []
    for word in words:
        if kept:
            fa = _fold_token(kept[-1])
            fb = _fold_token(word)
            same = fa == fb
            short_dup = (
                fa
                and fb
                and (fa.startswith(fb) or fb.startswith(fa))
                and abs(len(fa) - len(fb)) <= 2
                and min(len(fa), len(fb)) >= 3
            )
            if same or short_dup:
                richer = sum(ord(ch) > 127 for ch in word) > sum(ord(ch) > 127 for ch in kept[-1])
                longer = len(fb) > len(fa)
                if richer or longer:
                    kept[-1] = word
                continue
        kept.append(word)
    return " ".join(kept)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set(*, phase: str | None = None, message: str | None = None, progress: float | None = None, error: Any = False) -> None:
    with _LOCK:
        if phase is not None:
            _STATE["phase"] = phase
        if message is not None:
            _STATE["message"] = message
        if progress is not None:
            _STATE["progress"] = float(max(0.0, min(1.0, progress)))
        if error is not False:
            _STATE["error"] = error
        _STATE["updated_at"] = _stamp()


def _ensure_path() -> None:
    if not FANTASY_ROOT.exists():
        raise FileNotFoundError(f"Fantezi Lig klasörü yok: {FANTASY_ROOT}")
    root = str(FANTASY_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def status() -> dict[str, Any]:
    with _LOCK:
        snap = dict(_STATE)
        snap["available"] = FANTASY_ROOT.exists()
        snap["has_squad"] = _LAST is not None
        snap["running"] = bool(_THREAD and _THREAD.is_alive())
        snap["logged_in"] = bool(_SESSION and _SESSION.get("ok"))
        return snap


def last_payload() -> dict[str, Any] | None:
    with _LOCK:
        if not _LAST:
            return None
        payload = json_safe(_LAST)
    result = payload.get("result")
    if isinstance(result, dict):
        result["bench"] = _stamp_bench_ranks(_player_rows(result.get("bench")))
        payload["result"] = result
    return _sanitize_payload(_with_formation_xi(payload))


def _tidy_player_dict(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    for key in ("display_name", "player"):
        if row.get(key):
            row[key] = _tidy_name(str(row[key]))
    return row


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("squad", "xi", "bench"):
            rows = result.get(key) or []
            result[key] = [_tidy_player_dict(row) for row in rows]
        if isinstance(result.get("captain"), dict):
            result["captain"] = _tidy_player_dict(result["captain"])
        payload["result"] = result
    leaders = payload.get("leaders")
    if isinstance(leaders, dict):
        payload["leaders"] = {
            pos: [_tidy_player_dict(row) for row in (rows or [])]
            for pos, rows in leaders.items()
        }
    watch = payload.get("watch")
    if isinstance(watch, list) and watch:
        payload["watch"] = [_tidy_player_dict(row) for row in watch]
    else:
        squad_names = set()
        if isinstance(result, dict):
            for row in (result.get("squad") or []) + (result.get("xi") or []):
                if isinstance(row, dict):
                    squad_names.add(_tidy_name(str(row.get("display_name") or row.get("player") or "")))
        filled = []
        for pos in ("FW", "MF", "DF", "GK"):
            for row in (payload.get("leaders") or {}).get(pos) or []:
                name = _tidy_name(str(row.get("display_name") or row.get("player") or ""))
                if name and name not in squad_names:
                    filled.append(row)
                if len(filled) >= 6:
                    break
            if len(filled) >= 6:
                break
        payload["watch"] = filled
    card = dict(payload.get("manager_card") or {})
    card["why"] = _card_sentence(card)
    card.pop("remaining", None)
    card.pop("threshold", None)
    card.pop("card_state", None)
    payload["manager_card"] = card
    payload["account"] = account_public() or {}
    payload["xi_table"] = _xi_table(result if isinstance(result, dict) else {})
    try:
        _blend_watch_with_hauls(payload)
    except Exception:
        pass
    payload["analysis"] = _analysis({}, payload)
    return payload


def _xi_table(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for kind, group in (("XI", result.get("xi") or []), ("Yedek", result.get("bench") or [])):
        for player in group:
            if not isinstance(player, dict):
                continue
            opp = player.get("fixture_opponent") or ""
            venue = ""
            if opp:
                fx_kind = str(player.get("fixture_match_kind") or "").strip()
                if fx_kind == "derbi":
                    venue = "vs " + str(opp) + " · derbi"
                elif fx_kind == "kolay":
                    venue = "vs " + str(opp) + " · rakip zayıf"
                elif fx_kind == "zor":
                    venue = "vs " + str(opp) + " · rakip sert"
                else:
                    venue = "vs " + str(opp)
            rows.append(
                {
                    "role": kind,
                    "name": _tidy_name(str(player.get("display_name") or player.get("player") or "")),
                    "team": player.get("team") or "",
                    "position": player.get("position") or "",
                    "pts": player.get("projected_pts"),
                    "pts_if_plays": player.get("pts_if_plays"),
                    "fixture": venue,
                    "price_m": player.get("price_m"),
                }
            )
    return rows


def account_public() -> dict[str, Any] | None:
    with _LOCK:
        if not _SESSION:
            return None
        out = {k: v for k, v in _SESSION.items() if k not in {"tokens", "password"}}
        return json_safe(out)


def _slim_player(row: dict[str, Any]) -> dict[str, Any]:
    out = {key: row.get(key) for key in _PLAYER_KEYS if key in row}
    for key in ("display_name", "player"):
        if key in out and out[key]:
            out[key] = _tidy_name(str(out[key]))
    return out


def _tff_week_hauls() -> list[dict[str, Any]]:
    global _HAUL_CACHE
    path = DATA_DIR / "tff_raw.json"
    if not path.exists():
        return []
    stamp = float(path.stat().st_mtime)
    prices_path = DATA_DIR / "prices.csv"
    if prices_path.exists():
        stamp += float(prices_path.stat().st_mtime)
    if _HAUL_CACHE is not None and _HAUL_CACHE[0] == stamp:
        return _HAUL_CACHE[1]
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    inner: Any = blob
    if isinstance(blob, dict) and blob:
        inner = next(iter(blob.values()))
    try:
        from src.tff_client import parse_tff_official_players

        frame = parse_tff_official_players(inner)
    except Exception:
        _HAUL_CACHE = (stamp, [])
        return []
    teams: dict[str, str] = {}
    if prices_path.exists():
        try:
            import pandas as pd

            prices = pd.read_csv(prices_path)
            for _, row in prices.iterrows():
                label = str(row.get("display_name") or row.get("player_name") or "").strip()
                club = str(row.get("team") or "").strip()
                if label and club and not club.isdigit():
                    teams[label] = club
        except Exception:
            teams = {}
    rows: list[dict[str, Any]] = []
    for rec in frame.to_dict(orient="records"):
        name = str(rec.get("display_name") or rec.get("player_name") or "").strip()
        if not name:
            continue
        team = str(rec.get("team") or "").strip()
        if not team or team.isdigit():
            team = teams.get(name, team)
        rows.append(
            {
                "player": name,
                "display_name": name,
                "team": team,
                "position": rec.get("position"),
                "price_m": rec.get("price_m"),
                "tff_points": rec.get("tff_points") or 0,
                "tff_round_points": rec.get("tff_round_points") or 0,
                "tff_goals": rec.get("tff_goals") or 0,
            }
        )
    rows.sort(
        key=lambda item: (
            -float(item.get("tff_round_points") or 0),
            -float(item.get("tff_points") or 0),
            -float(item.get("tff_goals") or 0),
        )
    )
    _HAUL_CACHE = (stamp, rows)
    return rows


def _blend_watch_with_hauls(payload: dict[str, Any]) -> None:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    squad_names = set()
    for row in (result.get("squad") or []) + (result.get("xi") or []):
        if isinstance(row, dict):
            name = _tidy_name(str(row.get("display_name") or row.get("player") or ""))
            if name:
                squad_names.add(name)
    watch = [row for row in (payload.get("watch") or []) if isinstance(row, dict)]
    extra = []
    for row in _tff_week_hauls()[:10]:
        name = _tidy_name(str(row.get("display_name") or row.get("player") or ""))
        if name and name not in squad_names:
            extra.append(_slim_player(row))
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in extra + watch:
        name = _tidy_name(str(row.get("display_name") or row.get("player") or ""))
        if not name or name in seen or name in squad_names:
            continue
        merged.append(row)
        seen.add(name)
        if len(merged) >= 6:
            break
    if merged:
        payload["watch"] = merged


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return float(text)
    return None


def _norm_key(text: str) -> str:
    return _fold_token(text).replace(" ", "").replace("-", "").replace("_", "")


def _unwrap(obj: Any) -> Any:
    if not isinstance(obj, dict):
        return obj
    inner = obj.get("data")
    status = obj.get("status")
    keys = set(obj.keys())
    envelope = keys <= {"status", "data", "errors", "error", "message", "meta", "ok"}
    if inner is not None and (status in (True, "ok", "success", 1, "OK") or envelope):
        if isinstance(inner, dict):
            return _unwrap(inner)
        return inner
    return obj


def _looks_player(obj: dict[str, Any]) -> bool:
    keys = {_norm_key(str(k)) for k in obj}
    priced = bool({"cost", "price", "nowcost", "sellingprice"} & keys)
    placed = bool({"position", "elementtype", "positionid"} & keys)
    return (priced and placed) or ("webname" in keys and placed)


def _deep_num(obj: Any, names: tuple[str, ...], *, cap: float | None = None) -> float | None:
    hits: list[tuple[int, float]] = []
    want = {_norm_key(n) for n in names}

    def walk(node: Any, depth: int) -> None:
        if depth > 8 or node is None:
            return
        if isinstance(node, dict):
            if _looks_player(node):
                return
            for key, value in node.items():
                lk = _norm_key(str(key))
                if lk in _SKIP_WALK:
                    continue
                if lk in want:
                    n = _num(value)
                    if n is not None and (cap is None or n <= cap):
                        hits.append((depth, n))
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:28]:
                walk(item, depth + 1)

    walk(obj, 0)
    if not hits:
        return None
    hits.sort(key=lambda row: row[0])
    return hits[0][1]


def _map_chip_name(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    aliased = _CHIP_ALIAS.get(_norm_key(text))
    if aliased:
        return aliased
    return text


def _chip_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = _map_chip_name(
        raw.get("name")
        or raw.get("card")
        or raw.get("title")
        or raw.get("type")
        or raw.get("chipType")
        or raw.get("chip_type")
        or raw.get("label")
        or raw.get("chip")
        or raw.get("joker")
        or raw.get("code")
        or raw.get("id")
    )
    played_list = raw.get("played_by_entry") or raw.get("playedByEntry") or raw.get("usageHistory")
    used = _num(
        raw.get("used")
        or raw.get("usedCount")
        or raw.get("timesUsed")
        or raw.get("usageCount")
        or raw.get("playedCount")
        or raw.get("numberOfTimesPlayed")
        or raw.get("uses")
        or raw.get("playCount")
        or raw.get("consumed")
    )
    if used is None and isinstance(played_list, list):
        used = float(len(played_list))
    played_flag = raw.get("played")
    if used is None and isinstance(played_flag, bool) and played_flag:
        used = 1.0
    elif used is None:
        used = _num(played_flag)
    limit = _num(
        raw.get("limit")
        or raw.get("max")
        or raw.get("quota")
        or raw.get("maxCount")
        or raw.get("maxUses")
        or raw.get("allowed")
        or raw.get("allowedUses")
        or raw.get("number")
        or raw.get("limitPerHalf")
    )
    remaining = _num(
        raw.get("remaining")
        or raw.get("left")
        or raw.get("remainingCount")
        or raw.get("remainingUses")
        or raw.get("availableUses")
        or raw.get("leftover")
    )
    status = _norm_key(
        str(
            raw.get("status_for_entry")
            or raw.get("statusForEntry")
            or raw.get("chipStatus")
            or raw.get("state")
            or ""
        )
    )
    status_map = {
        "available": (0, 2),
        "availabletoplay": (0, 2),
        "playable": (0, 2),
        "active": (0, 2),
        "played": (1, 2),
        "used": (1, 2),
        "unavailable": (2, 2),
        "spent": (2, 2),
    }
    if status in status_map and used is None and remaining is None:
        used, limit = (float(status_map[status][0]), float(limit if limit is not None else status_map[status][1]))
        remaining = max(0.0, (limit or 2) - used)
    for value in raw.values():
        if isinstance(value, str):
            match = _RATIO_RE.match(value.strip())
            if match:
                used = float(match.group(1)) if used is None else used
                limit = float(match.group(2)) if limit is None else limit
    if remaining is not None and remaining > 5:
        remaining = None
    if limit is None and remaining is not None and 0 <= remaining <= 2:
        limit = 2.0
    if remaining is None and used is not None and limit is not None:
        remaining = max(0.0, limit - used)
    if used is None and remaining is not None and limit is not None:
        used = max(0.0, limit - remaining)
    if limit is not None and (limit < 1 or limit > 5):
        return None
    if used is None and limit is None:
        return None
    label = str(name or "").strip()
    if label.isdigit():
        label = ""
    low = label.lower()
    if label and label not in _KNOWN_CHIPS and len(label.split()) >= 3 and not any(
        w in low for w in ("kaptan", "kart", "hücum", "hucum", "bütçe", "butce", "triple", "sahaya")
    ):
        return None
    return {
        "name": label or "Kart",
        "used": int(used or 0),
        "limit": int(limit or 0),
        "remaining": int(remaining if remaining is not None else max(0, int(limit or 0) - int(used or 0))),
    }


def _extract_chips(obj: Any, depth: int = 0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if depth > 8 or obj is None:
        return found
    if isinstance(obj, dict):
        if _looks_player(obj):
            return found
        for key, value in obj.items():
            mapped = _CHIP_ALIAS.get(_norm_key(str(key)))
            if mapped:
                if isinstance(value, dict):
                    item = _chip_item({**value, "name": mapped})
                    if item:
                        found.append(item)
                elif isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 2:
                    found.append(
                        {
                            "name": mapped,
                            "used": int(2 - float(value)),
                            "limit": 2,
                            "remaining": int(value),
                        }
                    )
                elif isinstance(value, str):
                    item = _chip_item({"name": mapped, "status_for_entry": value})
                    if item:
                        found.append(item)
        item = _chip_item(obj)
        looks_chip = any(
            _norm_key(str(k)) in {"chip", "card", "joker", "booster", "used", "remaining", "quota", "chiptype"}
            for k in obj.keys()
        )
        if item and (looks_chip or item.get("name") in _KNOWN_CHIPS or item.get("name") not in {"Kart"}):
            if item.get("limit") or item.get("name") != "Kart":
                found.append(item)
        for key, value in obj.items():
            lk = _norm_key(str(key))
            if lk in _SKIP_WALK:
                continue
            if isinstance(value, (dict, list)):
                found.extend(_extract_chips(value, depth + 1))
    elif isinstance(obj, list):
        for entry in obj[:40]:
            if isinstance(entry, dict):
                found.extend(_extract_chips(entry, depth + 1))
            elif isinstance(entry, str) and _RATIO_RE.match(entry.strip()):
                match = _RATIO_RE.match(entry.strip())
                found.append(
                    {
                        "name": "Kart",
                        "used": int(match.group(1)),
                        "limit": int(match.group(2)),
                        "remaining": max(0, int(match.group(2)) - int(match.group(1))),
                    }
                )
    return found


def _dedupe_chips(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    unnamed = []
    for row in rows:
        name = str(row.get("name") or "Kart").strip()
        if name in {"Kart", ""}:
            unnamed.append(row)
            continue
        prev = by_name.get(name)
        if prev is None or int(row.get("limit") or 0) >= int(prev.get("limit") or 0):
            by_name[name] = row
    out = list(by_name.values())
    if not out:
        out = unnamed
    return _label_chips(out)


def _label_chips(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    mapped = []
    for row in rows:
        item = dict(row)
        item["name"] = _map_chip_name(item.get("name")) or item.get("name") or "Kart"
        mapped.append(item)
    named = [row for row in mapped if str(row.get("name") or "") not in {"Kart", ""}]
    if named:
        return named[:8]
    if len(mapped) == len(_KNOWN_CHIPS) and all(int(r.get("limit") or 0) in {1, 2} for r in mapped):
        labelled = []
        for name, row in zip(_KNOWN_CHIPS, mapped):
            item = dict(row)
            item["name"] = name
            labelled.append(item)
        return labelled
    return mapped[:8]


def _chip_catalog(chips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {_map_chip_name(row.get("name")): row for row in chips}
    out = []
    for name in _KNOWN_CHIPS:
        hit = by_name.get(name)
        if hit:
            out.append(
                {
                    "name": name,
                    "used": int(hit.get("used") or 0),
                    "limit": int(hit.get("limit") or 2),
                    "remaining": int(
                        hit.get("remaining")
                        if hit.get("remaining") is not None
                        else max(0, int(hit.get("limit") or 2) - int(hit.get("used") or 0))
                    ),
                    "known": True,
                }
            )
        else:
            out.append({"name": name, "used": None, "limit": 2, "remaining": None, "known": False})
    return out


def _used_from_chips(chips: list[dict[str, Any]], blobs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    used = []
    for chip in chips:
        n = int(chip.get("used") or 0)
        if n > 0:
            used.append({"name": chip.get("name"), "count": n})
    for _, data in blobs:
        hist = _walk_history(data) if isinstance(data, (dict, list)) else []
        for row in hist:
            if row.get("card") or row.get("chip"):
                used.append({"name": row.get("card") or row.get("chip"), "week": row.get("week"), "points": row.get("points")})
    seen = set()
    clean = []
    for row in used:
        key = (str(row.get("name")), row.get("week"), row.get("count"))
        if key in seen:
            continue
        seen.add(key)
        clean.append(row)
    return clean[:24]


def _walk_str(obj: Any, names: tuple[str, ...], depth: int = 0) -> str | None:
    if depth > 6 or obj is None:
        return None
    want = {_norm_key(n) for n in names}
    if isinstance(obj, dict):
        if _looks_player(obj):
            return None
        for key, value in obj.items():
            lk = _norm_key(str(key))
            if lk in _SKIP_WALK:
                continue
            if lk in want and isinstance(value, str) and value.strip():
                return value.strip()
        for key, value in obj.items():
            if _norm_key(str(key)) in _SKIP_WALK:
                continue
            hit = _walk_str(value, names, depth + 1)
            if hit:
                return hit
    elif isinstance(obj, list):
        for item in obj[:8]:
            hit = _walk_str(item, names, depth + 1)
            if hit:
                return hit
    return None


def _walk_history(obj: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6 or obj is None:
        return []
    rows: list[dict[str, Any]] = []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if _looks_player(obj[0]):
            return []
        for item in obj[:38]:
            week = (
                item.get("gameweek")
                or item.get("matchweek")
                or item.get("round")
                or item.get("week")
                or item.get("gw")
                or item.get("event")
            )
            pts = (
                item.get("points")
                or item.get("totalPoints")
                or item.get("gameweekPoints")
                or item.get("matchweekPoints")
                or item.get("score")
                or item.get("gwPoints")
                or item.get("eventPoints")
            )
            n = _num(pts)
            if n is None:
                continue
            rows.append(
                {
                    "week": week,
                    "points": n,
                    "earned": _num(item.get("earned") or item.get("winnings")),
                    "card": item.get("card") or item.get("chip") or item.get("activeChip"),
                    "rank": _num(item.get("overallRank") or item.get("rank")),
                }
            )
        if rows:
            return rows
    if isinstance(obj, dict):
        if _looks_player(obj):
            return []
        for key, value in obj.items():
            lk = _norm_key(str(key))
            if lk in _SKIP_WALK:
                continue
            if "histor" in lk or lk in {"gameweeks", "weeks", "rounds", "events", "current", "past"}:
                rows = _walk_history(value, depth + 1)
                if rows:
                    return rows
        for key, value in obj.items():
            if _norm_key(str(key)) in _SKIP_WALK:
                continue
            rows = _walk_history(value, depth + 1)
            if rows:
                return rows
    return []


def _person_name(blobs: list[tuple[str, Any]]) -> str | None:
    for _, data in blobs:
        name = _walk_str(data, ("teamname", "squadname", "entryname", "teamName"))
        if name:
            return name
    for _, data in blobs:
        if not isinstance(data, dict):
            continue
        first = data.get("name") or data.get("firstName") or data.get("first_name")
        last = data.get("lastName") or data.get("surname") or data.get("last_name")
        if isinstance(first, str) and first.strip() and isinstance(last, str) and last.strip():
            joined = f"{first.strip()} {last.strip()}".strip()
            if joined:
                return joined
        name = _walk_str(data, ("managername", "displayname", "fullName"))
        if name:
            return name
    return None


def _find_team_id(blobs: list[tuple[str, Any]]) -> str | None:
    for _, data in blobs:
        if not isinstance(data, dict):
            continue
        for key in ("fantasyTeamId", "fantasy_team_id", "teamId", "entryId", "entry"):
            value = data.get(key)
            if value is not None and str(value).strip() and str(value).lower() not in {"true", "false"}:
                return str(value).strip()
        nested = data.get("fantasyTeam") or data.get("team")
        if isinstance(nested, dict):
            for key in ("id", "teamId", "fantasyTeamId"):
                value = nested.get(key)
                if value is not None:
                    return str(value).strip()
    return None


def _summarize_account(blobs: list[tuple[str, Any]], email: str) -> dict[str, Any]:
    points = None
    gw_points = None
    rank = None
    chip_rows: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    top_keys: list[str] = []
    for path, data in blobs:
        if isinstance(data, dict):
            top_keys.append(f"{path}: {', '.join(list(data.keys())[:18])}")
        if points is None:
            points = _deep_num(data, _POINT_KEYS, cap=4000.0)
        if gw_points is None:
            gw_points = _deep_num(data, _GW_KEYS, cap=400.0)
        if rank is None:
            rank = _deep_num(data, _RANK_KEYS, cap=5_000_000.0)
        chip_rows.extend(_extract_chips(data))
        if not history:
            history = _walk_history(data)
    if history:
        vals = [_num(row.get("points")) or 0 for row in history]
        if points is None and vals:
            points = vals[-1] if any(v > 180 for v in vals) else sum(vals)
        if gw_points is None:
            gw_points = _num(history[-1].get("points"))
        if rank is None:
            rank = _num(history[-1].get("rank"))
    chips = _dedupe_chips(chip_rows)
    catalog = _chip_catalog(chips)
    known = [row for row in catalog if row.get("known")]
    used_list = _used_from_chips(known or chips, blobs)
    earned = None
    if history:
        earned_vals = [row["earned"] for row in history if row.get("earned") is not None]
        if earned_vals:
            earned = sum(earned_vals)
    note = None
    chip_note = None
    return {
        "ok": True,
        "email": email,
        "name": _person_name(blobs),
        "points": points,
        "gameweek_points": gw_points,
        "rank": rank,
        "chips": known or chips,
        "chip_catalog": catalog,
        "chip_note": chip_note,
        "cards_remaining": None,
        "cards_used": used_list,
        "earned": earned,
        "history": history[:34],
        "sources": [p for p, _ in blobs],
        "source_keys": top_keys[:12],
        "note": note,
        "updated_at": _stamp(),
    }


def login_account(email: str, password: str) -> dict[str, Any]:
    global _SESSION
    _ensure_path()
    from src.tff_client import TFFAuthError, TFFHttpError, backend_get, login, login_with_password, network_message
    from src.tff_client import _session as tff_session

    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        raise ValueError("E-posta ve şifre gerekli.")
    session = None
    try:
        login_with_password(email, password)
    except TFFAuthError:
        session = login(email, password)
    except Exception as first:
        try:
            session = login(email, password)
        except Exception as second:
            raise RuntimeError(network_message(second)) from second
    session = session or tff_session()
    league_id = _league_id()
    blobs: list[tuple[str, Any]] = []
    seen: set[str] = set()
    paths = _account_paths(league_id)
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            data = backend_get(path, session=session, timeout=8.0)
            blobs.append((path, _unwrap(data)))
        except (TFFAuthError, TFFHttpError, Exception):
            continue
        draft = _summarize_account(blobs, email)
        if draft.get("points") is not None and any(row.get("known") for row in draft.get("chip_catalog") or []):
            break
    team_id = _find_team_id(blobs)
    extra = []
    if team_id:
        extra = [
            f"fantasy-team/{team_id}",
            f"fantasy-teams/{team_id}",
            f"entry/{team_id}",
            f"fantasy-team/{team_id}/history",
            f"users/me?league-id={league_id}",
        ]
    for path in extra:
        if path in seen:
            continue
        seen.add(path)
        try:
            data = backend_get(path, session=session, timeout=8.0)
            blobs.append((path, _unwrap(data)))
        except (TFFAuthError, TFFHttpError, Exception):
            continue
    summary = _summarize_account(blobs, email)
    if team_id:
        summary["team_id"] = team_id
    try:
        from src.manager_cards import load_card_state

        state = load_card_state()
        summary["weeks_left"] = state.get("weeks_left")
        if not summary.get("history") and isinstance(state.get("history"), list):
            summary["history"] = [
                {"week": row.get("week") or row.get("matchweek"), "points": row.get("points"), "card": row.get("card")}
                for row in state.get("history") or []
                if isinstance(row, dict)
            ]
    except Exception:
        pass
    with _LOCK:
        _SESSION = summary
    return json_safe(summary)


def logout_account() -> None:
    global _SESSION
    with _LOCK:
        _SESSION = None


def _player_key(row: dict[str, Any]) -> str:
    return _fold_token(str(row.get("player") or row.get("display_name") or ""))


def _shape_of(formation: str) -> dict[str, int]:
    parts: list[int] = []
    for bit in str(formation or "").replace("–", "-").split("-"):
        bit = bit.strip()
        if bit.isdigit():
            parts.append(int(bit))
    if len(parts) == 3:
        df, mf, fw = parts
    elif len(parts) >= 4:
        df, fw = parts[0], parts[-1]
        mf = sum(parts[1:-1])
    else:
        df, mf, fw = 4, 3, 3
    return {"GK": 1, "DF": df, "MF": mf, "FW": fw}


def _layout_xi(squad: list[Any], formation: str) -> dict[str, list[dict[str, Any]]]:
    need = _shape_of(formation)
    pool = [row for row in squad if isinstance(row, dict)]
    pool.sort(key=lambda row: float(row.get("projected_pts") or 0), reverse=True)
    used: set[str] = set()
    xi: list[dict[str, Any]] = []

    def take(pos: str, count: int) -> None:
        got = 0
        for row in pool:
            if got >= count:
                return
            key = _player_key(row)
            if not key or key in used:
                continue
            if str(row.get("position") or "") == pos:
                xi.append(row)
                used.add(key)
                got += 1

    take("GK", need["GK"])
    take("DF", need["DF"])
    take("MF", need["MF"])
    take("FW", need["FW"])
    slots = need["GK"] + need["DF"] + need["MF"] + need["FW"]
    for row in pool:
        if len(xi) >= slots:
            break
        key = _player_key(row)
        if key and key not in used:
            xi.append(row)
            used.add(key)
    bench = [row for row in pool if _player_key(row) not in used]
    return {"xi": xi, "bench": _stamp_bench_ranks(bench)}


def _stamp_bench_ranks(bench: list[Any]) -> list[dict[str, Any]]:
    rows = [row for row in bench if isinstance(row, dict)]
    gk = [row for row in rows if str(row.get("position") or "").upper() == "GK"]
    field = [row for row in rows if str(row.get("position") or "").upper() != "GK"]
    field.sort(
        key=lambda row: (
            -float(row.get("play_probability") or 0.85),
            -float(row.get("pts_if_plays") or row.get("projected_pts") or 0),
        )
    )
    ordered = gk + field
    field_n = 0
    for row in ordered:
        if str(row.get("position") or "").upper() == "GK":
            row["bench_rank"] = 0
        else:
            field_n += 1
            row["bench_rank"] = field_n
    return ordered


def _bench_sort_key(player: dict[str, Any]) -> tuple:
    gk = 0 if str(player.get("position") or "").upper() == "GK" else 1
    rank = player.get("bench_rank")
    rank_n = int(rank) if rank is not None else 99
    return (gk, rank_n, -_if_plays(player))


def _player_rows(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return []
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        return []
    if getattr(value, "empty", False):
        return []
    try:
        records = to_dict(orient="records")
    except TypeError:
        records = to_dict("records")
    if not isinstance(records, list):
        return []
    return records


def _with_formation_xi(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    squad = _player_rows(result.get("squad"))
    if not squad:
        squad = _player_rows(result.get("xi")) + _player_rows(result.get("bench"))
    comps = []
    for row in payload.get("formation_comparisons") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        has = item.get("xi_players")
        solid = (
            isinstance(has, list)
            and has
            and isinstance(has[0], dict)
            and (has[0].get("position") or has[0].get("player") or has[0].get("display_name"))
        )
        if not solid:
            laid = _layout_xi(squad, str(item.get("formation") or ""))
            item["xi_players"] = laid["xi"]
            item["bench_players"] = laid["bench"]
        comps.append(item)
    out = dict(payload)
    out["formation_comparisons"] = comps
    return out


def _formation_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    cooked = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    native = raw.get("raw_result") if isinstance(raw.get("raw_result"), dict) else {}
    rows = (
        cooked.get("formation_comparisons")
        or native.get("formation_comparisons")
        or raw.get("formation_comparisons")
        or []
    )
    squad = _player_rows(cooked.get("squad")) or _player_rows(native.get("squad"))
    if not squad:
        squad = _player_rows(cooked.get("xi")) + _player_rows(cooked.get("bench"))
    if not squad:
        squad = _player_rows(native.get("xi")) + _player_rows(native.get("bench"))
    out = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("formation") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        xi_players = row.get("xi_players") or []
        bench_players = row.get("bench_players") or []
        if not (isinstance(xi_players, list) and xi_players and isinstance(xi_players[0], dict)):
            laid = _layout_xi(squad, name)
            xi_players = laid["xi"]
            bench_players = laid["bench"]
        out.append(
            {
                "formation": name,
                "expected_pts": row.get("expected_pts"),
                "xi_players": xi_players,
                "bench_players": bench_players,
            }
        )
    out.sort(key=lambda r: float(r.get("expected_pts") or 0), reverse=True)
    return out[:8]


def _pts(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n != n:
        return "—"
    return f"{n:.1f}".replace(".", ",")


def _mn(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n != n:
        return "—"
    return f"{n:.1f}".replace(".", ",")


def _card_sentence(card: dict[str, Any]) -> str:
    use = bool(card.get("use"))
    name = str(card.get("card") or "").strip()
    if name in {"Kart kullanma", "Kart kullanmayın", ""}:
        name = str(card.get("candidate") or "").strip()
    extra = card.get("extra_pts")
    explain = _CARD_EXPLAIN.get(name, "")
    extra_n = None
    try:
        extra_n = float(extra) if extra is not None else None
    except (TypeError, ValueError):
        extra_n = None
    extra_txt = f" Beklenen ek puan {_pts(extra_n)}." if extra_n is not None and extra_n > 0 else ""
    left = card.get("remaining")
    hak = ""
    try:
        if left is not None:
            hak = f" Kalan hak {int(left)}."
    except (TypeError, ValueError):
        hak = ""
    if use and name:
        return f"Bu hafta {name} kartını kullanın.{extra_txt}{hak} {explain}".strip()
    if name and extra_n is not None and extra_n > 0:
        return (
            f"Bu hafta menajer kartı kullanmayın. En yakın aday {name}; "
            f"beklenen ek puan {_pts(extra_n)}. Hakkı harcamaya yetmez.{hak}"
        ).strip()
    return f"Bu hafta menajer kartı kullanmayın.{hak}".strip()


def _pname(player: dict[str, Any]) -> str:
    return _tidy_name(str(player.get("display_name") or player.get("player") or ""))


def _if_plays(player: dict[str, Any]) -> float:
    return float(player.get("pts_if_plays") or player.get("projected_pts") or 0)


def _ppm(player: dict[str, Any]) -> float | None:
    n = _num(player.get("ppm") or player.get("tff_ppm"))
    if n is not None:
        return n
    pts = _if_plays(player)
    price = _num(player.get("price_m"))
    if pts is None or not price:
        return None
    return pts / price


def _side_word(player: dict[str, Any]) -> str:
    if player.get("fixture_home") is True:
        return "iç sahada"
    if player.get("fixture_home") is False:
        return "deplasmanda"
    return "karşısında"


def _band_word(player: dict[str, Any]) -> str:
    kind = str(player.get("fixture_match_kind") or "").strip()
    if kind == "derbi":
        return "dengeli"
    if kind == "kolay":
        return "rahat"
    if kind == "zor":
        return "sert"
    raw = str(player.get("fixture_band") or "").strip()
    if raw in {"rahat", "sert", "dengeli"}:
        return raw
    att = _num(player.get("fixture_attack_mult")) or 1.0
    cs = _num(player.get("fixture_cs_mult")) or 1.0
    pos = str(player.get("position") or "").upper()
    if pos in {"GK", "DF"}:
        if cs >= 1.12:
            return "rahat"
        if cs <= 0.90:
            return "sert"
        return "dengeli"
    if att >= 1.14:
        return "rahat"
    if att <= 0.88:
        return "sert"
    return "dengeli"


def _table_blocks_easy(player: dict[str, Any]) -> bool:
    """Üst sıra rakibe 'kolay/zayıf' yazılmaz; 2026/27 tablosu esas."""
    opp_pos = _num(player.get("opp_table_pos"))
    if opp_pos is not None and opp_pos <= 6:
        return True
    own = _num(player.get("table_pos"))
    n_teams = _num(player.get("table_n")) or 18.0
    if own is not None and opp_pos is not None and own >= (n_teams - 4) and opp_pos <= 8:
        return True
    return False


def _kind_from_clubs(team: str, opponent: str) -> str:
    if not str(team or "").strip() or not str(opponent or "").strip():
        return ""
    t_big = _is_big_club(team)
    o_big = _is_big_club(opponent)
    # Derbi yalnızca Galatasaray, Fenerbahçe, Beşiktaş kendi aralarında oynarsa.
    if _is_core_club(team) and _is_core_club(opponent):
        return "derbi"
    if t_big and o_big:
        return ""
    if t_big and not o_big:
        return "kolay"
    if o_big and not t_big:
        return "zor"
    return ""


def _match_kind(player: dict[str, Any]) -> str:
    team = str(player.get("team") or "").strip()
    opp = str(player.get("fixture_opponent") or "").strip()
    raw = str(player.get("fixture_match_kind") or "").strip()
    club_kind = _kind_from_clubs(team, opp)
    if club_kind == "derbi":
        return "derbi"
    if raw == "derbi":
        return "denk"
    blocked = _table_blocks_easy(player)

    def _soft(kind: str) -> str:
        if kind == "kolay" and blocked:
            return "denk"
        return kind

    if raw in {"kolay", "zor", "denk"}:
        return _soft(raw)
    if club_kind:
        return _soft(club_kind)
    band = _band_word(player)
    if band == "rahat":
        return _soft("kolay")
    if band == "sert":
        return "zor"
    return "denk"


_CLUB_GENERIC = frozenset(
    {
        "fk",
        "jk",
        "sk",
        "as",
        "spor",
        "sportif",
        "faaliyetler",
        "istanbul",
        "kulubu",
        "kulup",
    }
)


def _club_tokens(name: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", _fold_token(name)))
    return {tok for tok in tokens if tok not in _CLUB_GENERIC and len(tok) >= 3}


def _same_club(left: str, right: str) -> bool:
    a, b = _club_fold(left), _club_fold(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = _club_tokens(left), _club_tokens(right)
    if not ta or not tb:
        return False
    return ta == tb or ta <= tb or tb <= ta


def _club_label(team: str) -> str:
    folded = _club_fold(team)
    for key, label in _BIG_CLUBS:
        if key in folded or folded in key:
            return label
    return str(team or "").strip() or "—"


def _xi_matches(xi: list[dict[str, Any]], fixtures: list[Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    used: set[int] = set()
    rows = [p for p in xi if isinstance(p, dict)]
    for fx in fixtures or []:
        if not isinstance(fx, dict):
            continue
        home = str(fx.get("home") or "")
        away = str(fx.get("away") or "")
        if not home or not away:
            continue
        members: list[dict[str, Any]] = []
        for idx, player in enumerate(rows):
            if idx in used:
                continue
            team = str(player.get("team") or "")
            if _same_club(team, home) or _same_club(team, away):
                members.append(player)
                used.add(idx)
        if members:
            groups.append(
                {
                    "home": home,
                    "away": away,
                    "kickoff": str(fx.get("kickoff") or ""),
                    "players": members,
                }
            )
    leftover = [player for idx, player in enumerate(rows) if idx not in used]
    if leftover:
        groups.append({"home": "", "away": "", "kickoff": "", "players": leftover})
    return groups


def _club_fold(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold_token(name))


_CORE_CLUBS = (
    ("galatasaray", "Galatasaray"),
    ("fenerbahce", "Fenerbahçe"),
    ("besiktas", "Beşiktaş"),
)
_BIG_CLUBS = (
    ("fenerbahce", "Fenerbahçe"),
    ("galatasaray", "Galatasaray"),
    ("besiktas", "Beşiktaş"),
    ("trabzonspor", "Trabzonspor"),
)


def _is_core_club(team: str) -> bool:
    folded = _club_fold(team)
    if len(folded) < 4:
        return False
    return any(key in folded or folded in key for key, _label in _CORE_CLUBS)


def _pos_tr(pos: str) -> str:
    return {
        "GK": "kaleci",
        "DF": "defans",
        "MF": "orta saha",
        "FW": "forvet",
    }.get(str(pos or "").upper(), "oyuncu")


def _rotation_note(name: str) -> str:
    key = _fold_token(name)
    if "osimhen" in key:
        return "Ligdeki net forvet; her kadronun sabit ismi."
    if "talisca" in key:
        return (
            "Fenerbahçe hücumunda son dönem forma Muriqi’de. "
            "Talisca kadroda beklenen puanı şişirir; sahaya çıkmazsa koltuk boş kalır."
        )
    if "vlahovic" in key:
        return (
            "Beşiktaş hücumunda ilk 11’de üretti. "
            "TFF haftalık puanı yüksek; bütçe uyarsa kadroda aranır."
        )
    if "muriqi" in key:
        return "Fenerbahçe hücumunda güncel forma burada; Talisca yerine bu koltuk okunur."
    if "bouchouari" in key:
        return (
            "Son iki sezonda gol ve asist tabanı yok. "
            "Kolay fikstür, üretim getirmeyen orta sahayı taşımaz."
        )
    if "joemendes" in key.replace(" ", "") or "joe mendes" in key:
        return (
            "Bu sezon defans performansı zayıf. Üç büyük dışında bu koltuk gerekçesiz kalır."
        )
    return ""


def _player_case(player: dict[str, Any], *, slot: str) -> str:
    name = _pname(player)
    if not name:
        return ""
    team = _club_label(str(player.get("team") or ""))
    pos = _pos_tr(str(player.get("position") or ""))
    kind = _match_kind(player)
    opp = str(player.get("fixture_opponent") or "").strip()
    bits = [f"{name}, {team} {pos}, {slot}."]
    note = _rotation_note(name)
    folded = _fold_token(name)
    if note:
        bits.append(note)
    if "osimhen" not in folded:
        if note and opp:
            bits.append(f"Bu hafta {_side_word(player)} {opp}.")
        elif kind == "kolay" and opp:
            if _is_core_club(str(player.get("team") or "")):
                bits.append(
                    f"Bu hafta {_side_word(player)} {opp}; rakip zayıf, üç büyük üretim burada aranır."
                )
            elif _is_big_club(str(player.get("team") or "")):
                bits.append(
                    f"Bu hafta {_side_word(player)} {opp}; üst sıra, alt sıra rakibe karşı. "
                    "Yalnızca üretim tabanı olan isim tutulur."
                )
            else:
                bits.append(
                    f"Bu hafta {_side_word(player)} {opp}. Kolay fikstür tek başına yolcu ismi taşımaz."
                )
        elif kind == "derbi" and opp:
            bits.append(
                f"Bu hafta {_side_word(player)} {opp}; denk derbi. "
                "Kalite tutulur, kaptan bu maça bağlanmaz."
            )
        elif kind == "zor" and opp:
            bits.append(
                f"Bu hafta {_side_word(player)} {opp}; rakip sert. "
                "Zayıf tarafın kalecisi veya defansı bu koltuğu doldurmaz."
            )
        elif opp:
            bits.append(f"Bu hafta {_side_word(player)} {opp}.")
    own_pos = _num(player.get("table_pos"))
    opp_pos = _num(player.get("opp_table_pos"))
    n_teams = _num(player.get("table_n")) or 18.0
    if own_pos and opp_pos:
        if own_pos <= 6 and opp_pos >= n_teams - 4:
            bits.append("Puan durumunda üst sıra, alt sıra rakibe karşı.")
        elif own_pos >= n_teams - 3 and opp_pos <= 6:
            bits.append("Bu sezon alt sıra; üst sıra rakibe karşı bu koltuk zayıf kalır.")
    ga = _num(player.get("team_ga_pg"))
    if (
        str(player.get("position") or "").upper() in {"GK", "DF"}
        and ga is not None
        and ga >= 1.55
    ):
        bits.append("Bu sezon çok gol yiyor; temiz sayfa beklenmez.")
    gf = _num(player.get("team_gf_pg"))
    if (
        str(player.get("position") or "").upper() in {"MF", "FW"}
        and gf is not None
        and gf >= 1.70
        and own_pos is not None
        and own_pos <= 6
    ):
        bits.append("Takım ligde gol atıyor; hücum burada aranır.")
    gls = _num(player.get("gls_pa"))
    ast = _num(player.get("ast_pa"))
    if (
        str(player.get("position") or "").upper() in {"MF", "FW"}
        and gls is not None
        and ast is not None
        and (gls + ast) < 0.08
        and "osimhen" not in folded
        and "bouchouari" not in folded
        and "talisca" not in folded
    ):
        bits.append("Geçen sezon gol ve asist tabanı zayıf.")
    play = _num(player.get("play_probability"))
    if play is not None and play < 0.45:
        bits.append("Güncel forma kaydı zayıf; ilk 11’de tutulması doğru değil.")
    return " ".join(bits)


def _is_big_club(team: str) -> bool:
    folded = _club_fold(team)
    if len(folded) < 4:
        return False
    return any(key in folded or folded in key for key, _label in _BIG_CLUBS)


def _fixture_line(player: dict[str, Any]) -> str:
    opp = str(player.get("fixture_opponent") or "").strip()
    name = _pname(player)
    if not name:
        return ""
    team = str(player.get("team") or "").strip()
    kind = _match_kind(player)
    if not opp:
        return f"{name} ({team}), fikstür belirsiz"
    if kind == "derbi":
        return f"{name} ({team}), {_side_word(player)} {opp}, denk derbi"
    if kind == "kolay":
        return f"{name} ({team}), {_side_word(player)} {opp}, rakip zayıf"
    if kind == "zor":
        return f"{name} ({team}), {_side_word(player)} {opp}, rakip sert"
    return f"{name} ({team}), {_side_word(player)} {opp}, denk maç"


def _match_rank_note(players: list[dict[str, Any]]) -> str:
    for player in players:
        own = _num(player.get("table_pos"))
        opp = _num(player.get("opp_table_pos"))
        if own is None or opp is None:
            continue
        team = _club_label(str(player.get("team") or ""))
        rival = str(player.get("fixture_opponent") or "").strip()
        if not team or not rival:
            continue
        return (
            f" Puan durumu: {team} {int(own)}., "
            f"{_club_label(rival)} {int(opp)}."
        )
    return ""


def _describe_match(group: dict[str, Any]) -> str:
    home = str(group.get("home") or "")
    away = str(group.get("away") or "")
    players = [p for p in (group.get("players") or []) if isinstance(p, dict)]
    if not players:
        return ""
    names = ", ".join(_pname(p) for p in players if _pname(p))
    if not home or not away:
        return f"{names}: fikstür bu hafta net değil."
    title = f"{home}–{away}"
    home_side = [p for p in players if _same_club(str(p.get("team") or ""), home)]
    away_side = [p for p in players if _same_club(str(p.get("team") or ""), away)]
    kinds = [_match_kind(p) for p in players]
    derby_clubs = _is_core_club(home) and _is_core_club(away)
    if "derbi" in kinds or derby_clubs:
        both = []
        if home_side:
            both.append(", ".join(_pname(p) for p in home_side if _pname(p)))
        if away_side:
            both.append(", ".join(_pname(p) for p in away_side if _pname(p)))
        sides = " ve ".join(bit for bit in both if bit)
        who = f" {sides} aynı maçta." if sides else ""
        if home_side and away_side:
            return f"{title}: denk derbi.{who}"
        return f"{title}: denk derbi.{who} Kalite tutulur."
    kolay = [p for p in players if _match_kind(p) == "kolay"]
    zor = [p for p in players if _match_kind(p) == "zor"]
    rank = _match_rank_note(players)
    if kolay and not zor:
        strong = _club_label(str(kolay[0].get("team") or ""))
        sample = kolay[0]
        opp_pos = _num(sample.get("opp_table_pos"))
        n_teams = _num(sample.get("table_n")) or 18.0
        if opp_pos is not None and opp_pos >= n_teams - 4:
            tail = " Alt sıra rakibe karşı üretim ve temiz sayfa burada aranır."
        else:
            tail = ""
        return (
            f"{title}: {strong} tarafı tutulur.{rank} "
            f"Kadrodaki isimler: {names}.{tail}"
        )
    if zor and not kolay:
        return (
            f"{title}: sert rakip. {names} üretim tabanı ile tutulur; "
            "bu maçtan yüksek TFF puanı beklenmez."
        )
    if home_side and away_side:
        h_kind = _match_kind(home_side[0])
        if h_kind == "kolay":
            return (
                f"{title}: {_club_label(home)} önde. "
                f"{', '.join(_pname(p) for p in home_side if _pname(p))} önce okunur; "
                f"{', '.join(_pname(p) for p in away_side if _pname(p))} aynı maçta geride kalır."
            )
        if h_kind == "zor":
            return (
                f"{title}: {_club_label(away)} önde. "
                f"{', '.join(_pname(p) for p in away_side if _pname(p))} önce okunur; "
                f"{', '.join(_pname(p) for p in home_side if _pname(p))} aynı maçta geride kalır."
            )
    return f"{title}: denk maç.{rank} {names}."


def _avail_tr(code: str, news: str = "") -> str:
    key = str(code or "").upper()
    labels = {
        "INJURED": "sakatlık kaydı var",
        "INJURY": "sakatlık kaydı var",
        "SUSPENDED": "ceza kaydı var",
        "DOUBTFUL": "forma durumu şüpheli",
        "QUESTIONABLE": "forma durumu şüpheli",
        "UNAVAILABLE": "kullanılamıyor",
        "OUT": "dışarıda",
    }
    word = labels.get(key)
    if not word:
        return ""
    extra = f" ({news})" if news else ""
    return word + extra


def _sec(title: str, paras: list[str]) -> dict[str, Any]:
    clean = [str(p).strip() for p in paras if str(p or "").strip()]
    return {"title": title, "paragraphs": clean, "body": " ".join(clean)}


def _analysis(raw: dict[str, Any], public: dict[str, Any]) -> list[dict[str, Any]]:
    result = public.get("result") or {}
    xi = [p for p in (result.get("xi") or []) if isinstance(p, dict)]
    bench = [p for p in (result.get("bench") or []) if isinstance(p, dict)]
    squad = [p for p in (result.get("squad") or []) if isinstance(p, dict)] or (xi + bench)
    cap = result.get("captain") or {}
    if isinstance(cap, dict) and xi:
        cap_name = _pname(cap)
        src = next((p for p in xi if _pname(p) == cap_name), None)
        if src:
            cap = {**src, **cap}
    vice = result.get("vice_captain") or {}
    if isinstance(vice, dict) and xi:
        vice_name = _pname(vice)
        src = next((p for p in xi if _pname(p) == vice_name), None)
        if src:
            vice = {**src, **vice}
    card = dict(public.get("manager_card") or {})
    card["why"] = _card_sentence(card)
    public["manager_card"] = card
    comps = public.get("formation_comparisons") or []
    sections: list[dict[str, Any]] = []
    fixtures = public.get("fixtures") or raw.get("fixtures") or []
    match_pool = squad or xi
    matches = _xi_matches(match_pool, fixtures if isinstance(fixtures, list) else [])
    total = result.get("xi_if_plays") or result.get("total_projected")
    bank = _num(result.get("bank"))
    if matches:
        paras = [_describe_match(group) for group in matches]
        paras = [p for p in paras if p]
        if paras:
            sections.append(_sec("Maçlar", paras))
    if total is not None:
        ev = float(result.get("total_projected") or 0)
        paras = [
            (
                f"İlk 11’in beklenen puanı {_pts(total)}. "
                f"Seçim değeri {_pts(ev)}; yedek kulübesi {_pts(result.get('bench_projected') or 0)}."
            ),
            (
                "Karttaki TFF puanı şans ve kırılma içerir. "
                "Bir maçlık yüksek skor, ayağı kayan bir vuruş veya sekme ile şişer; "
                "seçim takım gücü, rakip ve üretim tabanına bakılır."
            ),
        ]
        if bank is not None:
            if bank >= 2.5:
                paras.append(
                    f"Kasada {_mn(bank)} mn duruyor. Boş bütçe puan getirmez; "
                    "yedek yükseltmek veya fark yaratacak bir isim bakılır."
                )
            elif bank >= 0:
                paras.append(f"Kasa {_mn(bank)} mn.")
        club_n: dict[str, int] = {}
        club_name: dict[str, str] = {}
        club_kind: dict[str, str] = {}
        for p in squad:
            key = _club_fold(str(p.get("team") or ""))
            if not key:
                continue
            club_n[key] = club_n.get(key, 0) + 1
            club_name[key] = _club_label(str(p.get("team") or ""))
            kind = _match_kind(p)
            if key not in club_kind or kind == "kolay":
                club_kind[key] = kind
        stacked = [
            (club_name[key], n, club_kind.get(key) or "denk")
            for key, n in club_n.items()
            if n >= 3 and _is_big_club(club_name[key])
        ]
        if stacked:
            bits = []
            for label, n, kind in stacked[:3]:
                if kind == "kolay":
                    bits.append(
                        f"{label} kadrosundan {n} isim var. Kulüp tavanı üç; "
                        "rakip zayıfken bu yığılma doğru okunur."
                    )
                elif kind == "derbi":
                    bits.append(
                        f"{label} kadrosundan {n} isim var. Derbide yığılma risklidir; "
                        "üçüncü isim ancak üretim tabanı çok sağlamsa tutulur."
                    )
                else:
                    bits.append(
                        f"{label} kadrosundan {n} isim var. Kulüp tavanı üç; "
                        "iyi oyuncu ve uygun fikstür varsa yığılma serbesttir."
                    )
            paras.extend(bits)
        fav_bits = []
        for p in xi:
            fav = str(p.get("odds_favorite") or "").strip()
            team = str(p.get("team") or "")
            if not fav or not team:
                continue
            if _club_fold(fav) == _club_fold(team):
                win = _num(p.get("odds_p_win"))
                btts = _num(p.get("odds_p_btts"))
                name = _pname(p)
                if name:
                    extra = []
                    if win:
                        extra.append(f"galibiyet ~%{int(round(win * 100))}")
                    if btts is not None and btts >= 0.55:
                        extra.append("GG piyasası açık")
                    elif btts is not None and btts <= 0.45:
                        extra.append("GG hayır; CS aranır")
                    fav_bits.append(
                        name + (f" ({', '.join(extra)})" if extra else "")
                    )
        if fav_bits:
            paras.append(
                "İddia favori yakası tutulur: "
                + ", ".join(fav_bits[:6])
                + ". Rakip yaka (underdog) aynı maçta kadroya yığılmaz. "
                "GG, 2.5 üst/alt ve korner piyasası temiz sayfa ile kurtarışı kaydırır."
            )
        paras.append(
            "Kaleci ve defans, 2026/27 puan durumu, yenen gol ve maç bonusu için tutulur. "
            "Galatasaray, Fenerbahçe, Beşiktaş, Trabzonspor burada aranır."
        )
        backs = [
            p
            for p in xi
            if str(p.get("position") or "").upper() in {"GK", "DF"}
            and _is_big_club(str(p.get("team") or ""))
            and _match_kind(p) == "kolay"
        ]
        if backs:
            line = ", ".join(
                f"{_pname(p)} ({_club_label(str(p.get('team') or ''))})"
                for p in backs[:4]
                if _pname(p)
            )
            if line:
                paras.append(
                    f"Temiz sayfa ihtimali yüksek savunma: {line}. "
                    "Kaleci ve defans burada aranır; kart beklenen puanda geri planda tutulur."
                )
        ext = [p for p in xi if str(p.get("data_src") or "") == "external_prior"]
        if ext:
            line = ", ".join(_pname(p) for p in ext[:4] if _pname(p))
            paras.append(
                f"Dış ligden gelenler ({line}) Süper Lig fikstürüne çevrilerek okunur. "
                "Eski ligin puanı burada geçerli değildir; rakip ve takım gücü esas alınır."
            )
        paras.append(
            "Karttaki rakam beklenen puandır. Forma çıkmayan oyuncu bu tutarı getirmez."
        )
        sections.append(_sec("Haftalık okuma", paras))
    if xi or bench:
        paras = []
        for player in xi:
            line = _player_case(player, slot="ilk 11")
            if line:
                paras.append(line)
        ordered_b = sorted(bench, key=_bench_sort_key)
        for player in ordered_b:
            line = _player_case(player, slot="yedek")
            if line:
                paras.append(line)
        if paras:
            sections.append(_sec("Kadro", paras))
    haul_bits = []
    haul_seen: set[str] = set()
    haul_pool: list[dict[str, Any]] = []
    for row in _tff_week_hauls():
        haul_pool.append(row)
    for row in raw.get("new_signings") or []:
        if isinstance(row, dict):
            haul_pool.append(row)
    for pos in ("FW", "MF", "DF", "GK"):
        for row in (raw.get("leaders") or {}).get(pos) or []:
            if isinstance(row, dict):
                haul_pool.append(row)
    for pos in ("FW", "MF", "DF", "GK"):
        for row in (public.get("leaders") or {}).get(pos) or []:
            if isinstance(row, dict):
                haul_pool.append(row)
    for row in public.get("watch") or []:
        if isinstance(row, dict):
            haul_pool.append(row)
    haul_pool.extend(squad)
    in_squad = {_pname(p) for p in squad if _pname(p)}
    haul_pool.sort(
        key=lambda p: (
            -(_num(p.get("tff_round_points")) or 0),
            -(_num(p.get("tff_points")) or 0),
            -(_num(p.get("tff_goals")) or 0),
        )
    )
    for player in haul_pool:
        name = _pname(player)
        if not name or name in haul_seen:
            continue
        tff_n = _num(player.get("tff_points")) or 0
        round_n = _num(player.get("tff_round_points")) or 0
        gls_n = _num(player.get("tff_goals")) or 0
        if tff_n < 8 and round_n < 8 and gls_n < 2:
            continue
        haul_seen.add(name)
        line = f"{name} TFF {_pts(tff_n)}"
        if gls_n:
            line += f", {int(gls_n)} gol"
        if name in in_squad:
            line += ", kadroda"
        else:
            line += ", kadro dışı"
        haul_bits.append(line)
        if len(haul_bits) >= 5:
            break
    if haul_bits:
        sections.append(
            _sec(
                "Bu hafta TFF",
                [
                    "Resmî TFF puanı yüksek isimler: " + "; ".join(haul_bits) + ".",
                    "Bu okuma beklenen puandan ayrıdır. Haftalık üretim burada; "
                    "kadro dışı ismi bütçe, kulüp tavanı veya beklenen puan kesmiş olabilir.",
                ],
            )
        )
    if xi:
        ordered = sorted(xi, key=_if_plays, reverse=True)
        top = ", ".join(f"{_pname(p)} ({_pts(_if_plays(p))})" for p in ordered[:4])
        paras = [f"Yükü çekenler: {top}."]
        easy_names = [
            _pname(p)
            for p in ordered
            if _match_kind(p) == "kolay" and _pname(p)
        ]
        if easy_names:
            paras.append(
                "Rakibi zayıf olanlar önce okunur: "
                + ", ".join(easy_names[:5])
                + "."
            )
        derby_names = [
            _pname(p)
            for p in ordered
            if _match_kind(p) == "derbi" and _pname(p)
        ]
        if len(derby_names) >= 2:
            sides_by_fixture: dict[frozenset, set[str]] = {}
            for p in ordered:
                if _match_kind(p) != "derbi":
                    continue
                own = _club_fold(str(p.get("team") or ""))
                rival = _club_fold(str(p.get("fixture_opponent") or ""))
                if not own or not rival:
                    continue
                sides_by_fixture.setdefault(frozenset({own, rival}), set()).add(own)
            both_sides = any(len(v) >= 2 for v in sides_by_fixture.values())
            if both_sides:
                paras.append(
                    "Aynı derbide iki yaka birden duruyor. "
                    + ", ".join(derby_names[:4])
                    + ". Yeniden hesapta yalnızca üstün taraf kalır."
                )
            else:
                paras.append(
                    "Aynı derbide tutulanlar: "
                    + ", ".join(derby_names[:4])
                    + ". Karşı yakadan isim alınmaz; kaptan bu maça bağlanmaz."
                )
        tail = [p for p in ordered if _if_plays(p) < 3.6]
        if tail:
            weak = ", ".join(f"{_pname(p)} ({_pts(_if_plays(p))})" for p in tail[:3])
            paras.append(
                f"Zayıf halka: {weak}. Fikstür veya form düşerse bu koltuklar değişir."
            )
        fixtures_l = [_fixture_line(p) for p in ordered[:6]]
        fixtures_l = [line for line in fixtures_l if line]
        if fixtures_l:
            paras.append("Fikstür ve oyuncu: " + "; ".join(fixtures_l[:5]) + ".")
        sections.append(_sec("İlk 11", paras))
    if cap:
        raw_pts = _if_plays(cap)
        name = _pname(cap) or "—"
        xi_sorted = sorted(xi, key=_if_plays, reverse=True)
        alt = next((p for p in xi_sorted if _pname(p) != name), None)
        paras = [
            (
                f"{name} kaptan. Beklenen puan {_pts(raw_pts)}; "
                f"çift kaptan {_pts(raw_pts * 2)}, Tripleks {_pts(raw_pts * 3)}."
            )
        ]
        if not (isinstance(vice, dict) and _pname(vice)) and xi:
            vice = next((p for p in xi_sorted if _pname(p) != name), None)
        if isinstance(vice, dict) and _pname(vice):
            paras.append(f"Yedek kaptan {_pname(vice)}.")
        cap_kind = _match_kind(cap) if isinstance(cap, dict) else "denk"
        cap_fold = _fold_token(_pname(cap) if isinstance(cap, dict) else "")
        osi_locked = "osimhen" in cap_fold
        if cap.get("fixture_opponent"):
            paras.append(
                f"Bu hafta {_side_word(cap)} {cap.get('fixture_opponent')} var."
            )
        if cap_kind == "derbi":
            paras.append("Derbi; kaptan farkı küçük kalır.")
        elif cap_kind == "kolay":
            paras.append(
                "Rakip zayıf. Kaptan, takımın hücum üstünlüğüne bağlanır; "
                "geçmiş haftanın şişkin TFF puanına değil."
            )
        elif cap_kind == "zor":
            paras.append(
                "Sert rakip. Kaptan ancak üretim tabanı çok sağlamsa tutulur."
            )
        if alt and not osi_locked:
            gap = _if_plays(alt) - raw_pts
            alt_kind = _match_kind(alt)
            if alt_kind == "kolay" and cap_kind == "derbi":
                paras.append(
                    f"{_pname(alt)} ({alt.get('team') or '—'}) rakibi daha zayıf; "
                    f"beklenen {_pts(_if_plays(alt))}. Kaptan koltuğu bu isme daha yakın duruyor."
                )
            elif gap >= 0.8:
                paras.append(
                    f"{_pname(alt)} ({alt.get('team') or '—'}) beklenen {_pts(_if_plays(alt))}; "
                    "kaptan koltuğu bu isme daha yakın duruyor."
                )
            elif gap <= -0.8:
                paras.append(
                    f"İkinci aday {_pname(alt)}, {_pts(_if_plays(alt))}. "
                    "Fark belirgin; kaptan önde duruyor."
                )
            else:
                paras.append(
                    f"İkinci aday {_pname(alt)}, {_pts(_if_plays(alt))}. "
                    "Fark küçük; fikstür ve takım gücü netleşmeden kaptan tutulur."
                )
        sections.append(_sec("Kaptan", paras))
    sections.append(_sec("Menajer kartı", [_card_sentence(card)]))
    flags = []
    risky_xi = []
    for player in squad:
        label = _avail_tr(player.get("availability") or "", str(player.get("avail_news") or "").strip())
        if not label:
            continue
        flags.append(f"{_pname(player)}: {label}")
        if player in xi or _pname(player) in {_pname(p) for p in xi}:
            risky_xi.append(_pname(player))
    if flags:
        paras = ["Forma riski olanlar: " + "; ".join(flags[:6]) + "."]
        if risky_xi:
            paras.append(
                "Riskli ismi ilk 11’de tutmak, beklenen puanı düşürür. "
                "Yedek veya alınabilecekler arasında sağlam alternatif bakılır."
            )
        else:
            paras.append("Bu isimler şu anda ilk 11 dışında; yine de haber takip edilir.")
        sections.append(_sec("Hazırlık", paras))
    if comps:
        best = max(comps, key=lambda row: float(row.get("expected_pts") or 0), default=None)
        line = "; ".join(
            f"{row.get('formation')} {_pts(row.get('expected_pts') or 0)}"
            for row in comps[:5]
        )
        pick = result.get("formation")
        paras = [f"Seçilen diziliş {pick}. Karşılaştırma: {line}."]
        if best and pick and best.get("formation") != pick:
            delta = float(best.get("expected_pts") or 0) - float(
                next((r.get("expected_pts") or 0 for r in comps if r.get("formation") == pick), 0)
            )
            extra = (
                f"En yüksek okuma {best.get('formation')} ({_pts(best.get('expected_pts') or 0)})."
            )
            if delta >= 0.6:
                extra += f" Fark {_pts(delta)} puan."
            paras.append(extra)
        else:
            paras.append("Seçilen diziliş, beklenen puanda önde duruyor.")
        sections.append(_sec("Diziliş", paras))
    if bench:
        ordered_b = sorted(bench, key=_bench_sort_key)
        names = ", ".join(
            (
                f"KL {_pname(p)} ({_pts(_if_plays(p))})"
                if str(p.get("position") or "").upper() == "GK"
                else (
                    f"{int(p['bench_rank'])}. {_pname(p)} ({_pts(_if_plays(p))})"
                    if p.get("bench_rank")
                    else f"{_pname(p)} ({_pts(_if_plays(p))})"
                )
            )
            for p in ordered_b[:4]
            if _pname(p)
        )
        if names:
            sections.append(
                _sec(
                    "Yedekler",
                    [
                        f"Giriş sırası: {names}.",
                    ],
                )
            )
    watch = public.get("watch") or []
    if watch:
        bits = []
        for p in watch[:5]:
            line = f"{_pname(p)} {_mn(p.get('price_m') or 0)} mn"
            if _if_plays(p) > 0:
                line += f", beklenen {_pts(_if_plays(p))}"
            else:
                round_pts = _num(p.get("tff_round_points"))
                total_pts = _num(p.get("tff_points"))
                if round_pts is not None and round_pts > 0:
                    line += f", TFF haftalık {_pts(round_pts)}"
                elif total_pts is not None and total_pts > 0:
                    line += f", TFF toplam {_pts(total_pts)}"
            sel = _num(p.get("selected_by"))
            if sel is not None and sel <= 12:
                line += f", yüzde {int(round(sel))} seçilmiş"
            bits.append(line)
        sections.append(
            _sec(
                "Alınabilecekler",
                [
                    "Kadro dışında, fiyata göre beklenen puanı yüksek isimler: " + "; ".join(bits) + ".",
                    "Bu liste tavsiye değil; bütçe ve açık mevkie göre okunur.",
                ],
            )
        )
    return sections


def _public(raw: dict[str, Any]) -> dict[str, Any]:
    result = dict(raw.get("result") if isinstance(raw.get("result"), dict) else {})
    for key in ("squad", "xi", "bench"):
        rows = _player_rows(result.get(key))
        result[key] = [_slim_player(row) if isinstance(row, dict) else row for row in rows]
    xi_rows = [p for p in (result.get("xi") or []) if isinstance(p, dict)]
    result["xi_if_plays"] = round(sum(_if_plays(p) for p in xi_rows), 2)
    cap = result.get("captain")
    if isinstance(cap, dict):
        for key in ("display_name", "player"):
            if cap.get(key):
                cap[key] = _tidy_name(str(cap[key]))
        result["captain"] = cap
    vice = result.get("vice_captain")
    if isinstance(vice, dict):
        for key in ("display_name", "player"):
            if vice.get(key):
                vice[key] = _tidy_name(str(vice[key]))
        result["vice_captain"] = vice
    meta = dict(raw.get("meta") or {})
    meta.pop("fixture_context", None)
    leaders = {}
    for pos, rows in (raw.get("leaders") or {}).items():
        leaders[pos] = [_slim_player(row) for row in (rows or [])[:8]]
    card = dict(raw.get("manager_card") or {})
    card["why"] = _card_sentence(card)
    squad_names = {
        _pname(row)
        for row in (result.get("squad") or result.get("xi") or [])
        if isinstance(row, dict)
    }
    signed = [
        row for row in (raw.get("new_signings") or []) if isinstance(row, dict)
    ]
    signed.sort(
        key=lambda row: (
            -float(row.get("tff_round_points") or 0),
            -float(row.get("tff_points") or 0),
            -float(row.get("tff_goals") or 0),
            -float(row.get("pts_if_plays") or row.get("projected_pts") or 0),
        )
    )
    watch = []
    for row in signed:
        if not isinstance(row, dict):
            continue
        slim = _slim_player(row)
        if _pname(slim) and _pname(slim) not in squad_names:
            watch.append(slim)
        if len(watch) >= 6:
            break
    if len(watch) < 4:
        for pos in ("FW", "MF", "DF", "GK"):
            for row in leaders.get(pos) or []:
                if _pname(row) and _pname(row) not in squad_names:
                    watch.append(row)
                if len(watch) >= 6:
                    break
            if len(watch) >= 6:
                break
    payload = {
        "ok": True,
        "fetched_at": _stamp(),
        "meta": meta,
        "result": result,
        "fixtures": raw.get("fixtures") or [],
        "manager_card": card,
        "leaders": leaders,
        "watch": watch[:6],
        "formation_comparisons": _formation_rows(raw),
        "account": account_public(),
    }
    try:
        _blend_watch_with_hauls(payload)
    except Exception:
        pass
    payload["analysis"] = _analysis(raw, payload)
    return _sanitize_payload(_with_formation_xi(payload))


def _persist(payload: dict[str, Any]) -> None:
    FANTASY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FANTASY_CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_cached() -> None:
    global _LAST
    if not FANTASY_CACHE.exists():
        return
    try:
        data = json.loads(FANTASY_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict):
        try:
            _blend_watch_with_hauls(data)
            data["analysis"] = _analysis({}, data)
        except Exception:
            pass
    with _LOCK:
        _LAST = data
        _STATE["phase"] = "ready"
        _STATE["message"] = "Kayıtlı kadro yüklendi."
        _STATE["progress"] = 1.0
        _STATE["error"] = None
        _STATE["updated_at"] = _stamp()


def _pipeline():
    _ensure_path()
    from src.pipeline import run_pipeline

    return run_pipeline


def _run(fetch_prices: bool, refresh_cache: bool) -> None:
    global _LAST
    try:
        _set(phase="run", message="TFF Fantezi Lig oturumu doğrulanıyor.", progress=0.06, error=None)
        run_pipeline = _pipeline()

        def progress(msg: str) -> None:
            low = msg.lower()
            frac = 0.14
            if "fiyat" in low:
                frac = 0.28
                msg = "TFF Fantezi Lig fiyatları alınıyor."
            elif "sofascore" in low or "form" in low:
                frac = 0.52
                msg = "Süper Lig formu okunuyor."
            elif "fotmob" in low:
                frac = 0.70
                msg = "FotMob ile ilk 11 ve kulüp maçları doğrulanıyor."
            elif "optimize" in low or "diziliş" in low or "imza" in low:
                frac = 0.88
                msg = "Diziliş ve ilk 11 hesaplanıyor."
            _set(message=msg, progress=frac)

        raw = run_pipeline(
            fetch_prices=fetch_prices,
            refresh_cache=refresh_cache,
            report_png=None,
            progress=progress,
        )
        payload = json_safe(_public(raw))
        _persist(payload)
        with _LOCK:
            _LAST = payload
        _set(phase="ready", message="Kadro hazır.", progress=1.0, error=None)
    except Exception as exc:
        from src.tff_client import network_message

        _set(phase="error", message="Kadro hesaplanamadı.", error=network_message(exc))


def start(fetch_prices: bool = True, refresh_cache: bool = False) -> dict[str, Any]:
    global _THREAD
    with _LOCK:
        if not (_SESSION and _SESSION.get("ok")):
            return {
                **status(),
                "error": "Önce TFF Fantezi Lig hesabına girin.",
            }
        if _THREAD and _THREAD.is_alive():
            return status()
        _THREAD = threading.Thread(
            target=_run,
            kwargs={"fetch_prices": fetch_prices, "refresh_cache": refresh_cache},
            daemon=True,
        )
        _THREAD.start()
    return status()

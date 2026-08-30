"""Bellekteki oyuncu evreni, arama ve piyasa listeleri."""

from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np
import pandas as pd

from app.analysis import build_report, compare_verdict
from app.config import (
    ACTIVE_SEASON_FLOOR,
    CATALOG_LEAGUES,
    FEATURED_LEAGUES,
    LEAGUE_COUNTRY,
    LEAGUE_FLAG,
    LEAGUE_MARK,
    LEAGUE_NAMES,
    LEAGUE_REGION,
    POSITION_TR,
    SUB_POSITION_TR,
    TOP_LEAGUES,
    UNIVERSE_PARQUET,
)
from app.features import prepare_frame
from app.live_fotmob import player_dossier
from app.live_tm import (
    club_overlay_get,
    club_overlay_put,
    current_season_totals,
    open_injury_days,
    player_bundle,
    resolve_club_id,
    search_players,
)
from app.model import Engine, rescore_row, score_universe, similar_players
from app.money import GAP_CHEAP, GAP_RICH, format_eur, format_pct, gap_direction
from app.slugs import (
    club_display,
    club_names_match,
    club_path,
    club_query_hit,
    club_token,
    fold_tr,
    is_free_agent,
    parse_tm_id,
    player_path,
    player_slug,
    slugify,
)
from app.warehouse import warehouse_ready

_LOCK = threading.Lock()
_UNIVERSE: pd.DataFrame | None = None
_ENGINE: Engine | None = None
_OWNERS_MEM: dict[int, str] = {}


def set_store(frame: pd.DataFrame, engine: Engine) -> None:
    global _UNIVERSE, _ENGINE
    scored = score_universe(frame, engine)
    scored = _ranks(scored)
    with _LOCK:
        _UNIVERSE = scored
        _ENGINE = engine


def ready() -> bool:
    with _LOCK:
        return _UNIVERSE is not None and _ENGINE is not None


def engine() -> Engine | None:
    with _LOCK:
        return _ENGINE


def universe() -> pd.DataFrame:
    with _LOCK:
        if _UNIVERSE is None:
            raise RuntimeError("Evren yüklenmedi.")
        return _UNIVERSE


def try_load_existing() -> bool:
    from app.model import load_engine

    if not warehouse_ready():
        return False
    eng = load_engine()
    if eng is None:
        return False
    frame = pd.read_parquet(UNIVERSE_PARQUET)
    set_store(frame, eng)
    return True


def _ranks(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    group = out.groupby(["position", "league_id"], dropna=False)
    out["pct_minutes"] = group["minutes_2y"].rank(pct=True)
    out["pct_contrib"] = group["contrib_p90"].rank(pct=True)
    out["pct_value"] = group["market_value_in_eur"].rank(pct=True)
    out["pct_true"] = group["true_value"].rank(pct=True)
    return out


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return json_safe(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return json_safe(value.to_dict())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _clean(value):
    return json_safe(value)


def _club_id_owners(df: pd.DataFrame) -> dict[int, str]:
    if df.empty or "current_club_id" not in df.columns:
        return {}
    tmp = df[["current_club_id", "current_club_name"]].copy()
    tmp["cid"] = pd.to_numeric(tmp["current_club_id"], errors="coerce")
    tmp = tmp.dropna(subset=["cid"])
    if tmp.empty:
        return {}
    tmp["cid"] = tmp["cid"].astype(int)
    tmp["nm"] = tmp["current_club_name"].fillna("").map(lambda x: str(x).strip())
    tmp = tmp[tmp["nm"].ne("") & ~tmp["nm"].map(is_free_agent)]
    if tmp.empty:
        return {}
    tmp["_k"] = tmp["nm"].map(fold_tr)
    counts = tmp.groupby(["cid", "_k", "nm"], dropna=False).size().reset_index(name="n")
    owners: dict[int, str] = {}
    for cid, grp in counts.groupby("cid"):
        top = grp.sort_values("n", ascending=False).iloc[0]
        owners[int(cid)] = str(top["nm"])
    return owners


def _trusted_club_id(club_id: Any, club_name: str, owners: dict[int, str]) -> int | None:
    try:
        cid = int(float(club_id))
    except (TypeError, ValueError):
        return None
    if cid <= 0:
        return None
    owner = owners.get(cid)
    if not owner or club_names_match(club_name, owner):
        return cid
    return None


def _fix_club_ids(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "current_club_id" not in df.columns:
        return df
    global _OWNERS_MEM
    owners = _club_id_owners(df)
    _OWNERS_MEM = owners
    if not owners:
        return df
    cids = pd.to_numeric(df["current_club_id"], errors="coerce")
    names = df["current_club_name"].fillna("").astype(str)
    keep: list[bool] = []
    for cid, name in zip(cids.tolist(), names.tolist()):
        if cid is None:
            keep.append(True)
            continue
        try:
            if cid != cid:
                keep.append(True)
                continue
        except Exception:
            keep.append(True)
            continue
        keep.append(_trusted_club_id(cid, name, owners) is not None)
    if all(keep):
        return df
    out = df.copy()
    out.loc[[not ok for ok in keep], "current_club_id"] = pd.NA
    return out


def _apply_overlays(df: pd.DataFrame) -> pd.DataFrame:
    overlay = club_overlay_get()
    out = df
    if overlay and not df.empty and "player_id" in df.columns:
        out = df.copy()
        for key, meta in overlay.items():
            if not isinstance(meta, dict):
                continue
            try:
                pid = int(key)
            except (TypeError, ValueError):
                continue
            mask = pd.to_numeric(out["player_id"], errors="coerce") == pid
            if not mask.any():
                continue
            name = str(meta.get("club") or "").strip()
            if name:
                out.loc[mask, "current_club_name"] = name
            cid = meta.get("club_id")
            if cid:
                out.loc[mask, "current_club_id"] = cid
            lid = str(meta.get("league_id") or "").strip()
            if lid:
                out.loc[mask, "league_id"] = lid
    return _fix_club_ids(out)


def card(row: pd.Series) -> dict[str, Any]:
    pid = _clean(row.get("player_id"))
    gap = _clean(row.get("gap_pct"))
    overlay = {}
    if pid is not None:
        overlay = club_overlay_get().get(str(int(pid))) or {}
    club_name = str(overlay.get("club") or row.get("current_club_name") or "")
    club_id = overlay.get("club_id") if overlay.get("club_id") else row.get("current_club_id")
    owners = _OWNERS_MEM or {}
    if not owners and club_id is not None:
        try:
            owners = _club_id_owners(universe())
        except Exception:
            owners = {}
    trusted = _trusted_club_id(club_id, club_name, owners) if club_id is not None else None
    if club_id is not None and owners:
        club_id = trusted
    league_id = overlay.get("league_id") or row.get("league_id")
    payload = {
        "player_id": int(pid) if pid is not None else None,
        "name": row.get("name"),
        "image_url": _clean(row.get("image_url")),
        "club": club_display(club_name),
        "league_id": None if pd.isna(league_id) else str(league_id),
        "league": LEAGUE_NAMES.get(str(league_id or ""), str(league_id or "")),
        "position": POSITION_TR.get(str(row.get("position") or ""), row.get("position")),
        "sub_position": SUB_POSITION_TR.get(str(row.get("sub_position") or ""), row.get("sub_position")),
        "age": None if pd.isna(row.get("age")) else int(round(float(row.get("age")))),
        "tm_value": _clean(row.get("market_value_in_eur")),
        "tm_label": format_eur(row.get("market_value_in_eur")),
        "fair_value": _clean(row.get("fair_value")),
        "fair_label": format_eur(row.get("fair_value")),
        "true_value": _clean(row.get("true_value")),
        "true_label": format_eur(row.get("true_value")),
        "gap_pct": gap,
        "gap_label": format_pct(gap),
        "direction": gap_direction(gap),
        "confidence": _clean(row.get("confidence")),
        "minutes_365": _clean(row.get("minutes_365")),
        "minutes_2y": _clean(row.get("minutes_2y")),
        "contrib_p90": _clean(row.get("contrib_p90")),
        "contract_years": _clean(row.get("contract_years")),
        "goals_2y": _clean(row.get("goals_2y")),
        "assists_2y": _clean(row.get("assists_2y")),
        "href": player_path(pid, row.get("name")) if pid is not None else None,
        "slug": player_slug(pid, row.get("name")) if pid is not None else None,
        "club_href": club_path(club_id, club_name, league_id)
        if club_name and not is_free_agent(club_name)
        else None,
        "club_token": club_token(club_id, club_name, league_id)
        if club_name and not is_free_agent(club_name)
        else None,
    }
    return json_safe(payload)


def _name_rank(name: str, q: str) -> int:
    nl = (name or "").lower()
    if nl == q:
        return 0
    parts = nl.replace("-", " ").split()
    if q in parts:
        return 1
    if nl.startswith(q):
        return 2
    if any(part.startswith(q) for part in parts):
        return 3
    if q in nl:
        return 4
    return 7


def search(
    query: str,
    limit: int = 18,
    league: str | None = None,
    position: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
) -> list[dict]:
    raw = (query or "").strip()
    tm_id = parse_tm_id(raw)
    if tm_id:
        df = universe()
        hit = df[df["player_id"] == tm_id]
        if not hit.empty:
            item = card(hit.iloc[0])
            item["match"] = 0
            return json_safe([item])
        return json_safe(
            [
                {
                    "player_id": tm_id,
                    "name": raw.split("/")[-1] if "/" in raw else raw,
                    "href": player_path(tm_id, ""),
                    "live_only": True,
                    "direction": "belirsiz",
                    "match": 0,
                }
            ]
        )
    q = raw.lower()
    qn = fold_tr(raw)
    if len(q) < 2:
        return []
    club_hits: list[dict[str, Any]] = []
    seen_clubs: set[str] = set()
    try:
        for club in club_list().get("clubs") or []:
            name = str(club.get("name") or "")
            rank = club_query_hit(name, raw)
            if rank is None:
                continue
            token = str(club.get("id") or club.get("href") or name)
            if token in seen_clubs:
                continue
            seen_clubs.add(token)
            club_hits.append(
                {
                    "kind": "club",
                    "name": name,
                    "club": name,
                    "league": club.get("league"),
                    "position": "Kulüp",
                    "true_label": club.get("true_label"),
                    "tm_label": club.get("tm_label"),
                    "true_value": club.get("true_sum"),
                    "tm_value": club.get("tm_sum"),
                    "href": club.get("href"),
                    "match": rank,
                }
            )
        club_hits.sort(key=lambda r: (r.get("match") or 9, -(r.get("true_value") or 0)))
        club_hits = club_hits[:4]
    except Exception:
        club_hits = []
    df = universe()
    names = df["name"].astype("string").str.lower().fillna("")
    code = df["player_code"].astype("string").str.lower().fillna("") if "player_code" in df.columns else names
    club = df["current_club_name"].astype("string").str.lower().fillna("") if "current_club_name" in df.columns else names
    hit = df[names.str.contains(q, regex=False) | code.str.contains(q, regex=False) | club.str.contains(q, regex=False)].copy()
    if league:
        hit = hit[hit["league_id"].astype("string") == str(league)]
    if position:
        hit = hit[hit["position"].astype("string") == str(position)]
    if age_min is not None:
        hit = hit[pd.to_numeric(hit.get("age"), errors="coerce").fillna(0) >= int(age_min)]
    if age_max is not None:
        hit = hit[pd.to_numeric(hit.get("age"), errors="coerce").fillna(99) <= int(age_max)]
    if hit.empty and len(q) < 2:
        return json_safe(club_hits)
    hit["_rank"] = hit["name"].astype("string").fillna("").map(lambda n: _name_rank(str(n), q))
    tm = pd.to_numeric(hit.get("market_value_in_eur"), errors="coerce").fillna(0)
    true = pd.to_numeric(hit.get("true_value"), errors="coerce").fillna(0)
    peak = pd.to_numeric(hit.get("highest_market_value_in_eur"), errors="coerce").fillna(0)
    caps = pd.to_numeric(hit.get("international_caps"), errors="coerce").fillna(0)
    mins = pd.to_numeric(hit.get("minutes_365"), errors="coerce").fillna(0)
    hit["_pop"] = tm.combine(true, max) + peak * 0.2 + caps * 80_000 + mins * 400
    hit = hit.sort_values(["_pop", "_rank"], ascending=[False, True], na_position="last").head(limit)
    results = []
    for _, row in hit.iterrows():
        item = card(row)
        item["kind"] = "player"
        item["match"] = _name_rank(str(item.get("name") or ""), q)
        item["_pop"] = float(row.get("_pop") or 0)
        results.append(item)
    have_ids = {str(r.get("player_id")) for r in results if r.get("player_id") is not None}
    have_names = {str(r.get("name") or "").lower() for r in results}
    try:
        live = search_players(query)
    except Exception:
        live = {"results": []}
    for item in live.get("results") or []:
        pid = str(item.get("id") or "")
        name = item.get("name")
        if not name:
            continue
        if pid in have_ids or name.lower() in have_names:
            continue
        mv = item.get("marketValue")
        results.append(
            {
                "kind": "player",
                "player_id": int(pid) if pid.isdigit() else item.get("id"),
                "name": name,
                "club": (item.get("club") or {}).get("name") if isinstance(item.get("club"), dict) else item.get("club"),
                "position": item.get("position"),
                "age": item.get("age"),
                "tm_value": mv,
                "tm_label": format_eur(mv),
                "href": player_path(int(pid), name) if pid.isdigit() else None,
                "live_only": True,
                "direction": "belirsiz",
                "match": _name_rank(name, q),
            }
        )
        have_ids.add(pid)
        have_names.add(name.lower())
        if len(results) >= limit:
            break

    def _worth(row: dict[str, Any]) -> float:
        for key in ("tm_value", "true_value"):
            try:
                n = float(row.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if n == n and n > 0:
                return n
        return 0.0

    results.sort(key=lambda r: (-(r.get("_pop") or _worth(r)), r.get("match") if r.get("match") is not None else 9))
    return json_safe(club_hits + results)


def _active(df: pd.DataFrame) -> pd.DataFrame:
    last = pd.to_numeric(df.get("last_season"), errors="coerce")
    return df[last.ge(ACTIVE_SEASON_FLOOR) | df["minutes_365"].fillna(0).gt(90)]


def _catalog(df: pd.DataFrame | None = None) -> pd.DataFrame:
    base = _active(df if df is not None else universe())
    return base[base["league_id"].astype("string").isin(TOP_LEAGUES)]


def market(
    league: str | None = None,
    position: str | None = None,
    direction: str | None = None,
    q: str | None = None,
    sort: str = "true_value",
    order: str = "desc",
    page: int = 1,
    page_size: int = 40,
    min_minutes: int = 0,
    age_min: int | None = None,
    age_max: int | None = None,
) -> dict:
    df = _apply_overlays(_catalog())
    if league:
        df = df[df["league_id"].astype("string") == str(league)]
    if position:
        df = df[df["position"].astype("string") == str(position)]
    if min_minutes:
        df = df[df["minutes_365"].fillna(0) >= min_minutes]
    if age_min is not None:
        df = df[pd.to_numeric(df.get("age"), errors="coerce").fillna(0) >= int(age_min)]
    if age_max is not None:
        df = df[pd.to_numeric(df.get("age"), errors="coerce").fillna(99) <= int(age_max)]
    if q:
        needle = q.strip().lower()
        df = df[df["name"].astype("string").str.lower().str.contains(needle, regex=False, na=False)]
    if direction in {"dusuk", "yuksek", "denge"}:
        gap = df["gap_pct"]
        if direction == "dusuk":
            df = df[gap <= GAP_CHEAP]
        elif direction == "yuksek":
            df = df[gap >= GAP_RICH]
        else:
            df = df[gap.between(GAP_CHEAP, GAP_RICH)]
    allowed = {
        "true_value": "true_value",
        "tm": "market_value_in_eur",
        "gap": "gap_pct",
        "age": "age",
        "minutes": "minutes_365",
        "goals": "goals_2y",
    }
    col = allowed.get(sort, "true_value")
    want = str(order or "desc").lower()
    if want == "asc":
        ascending = True
    elif want == "desc":
        ascending = False
    else:
        ascending = sort in {"age", "gap"}
    df = df.sort_values(col, ascending=ascending, na_position="last")
    total = int(len(df))
    page = max(1, int(page))
    start = (page - 1) * page_size
    chunk = df.iloc[start : start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": int(math.ceil(total / page_size)) if page_size else 1,
        "items": [card(row) for _, row in chunk.iterrows()],
    }


def pulse() -> dict:
    df = _apply_overlays(_catalog())
    club_ok = ~df["current_club_name"].fillna("").astype(str).map(is_free_agent)
    liquid = df[
        club_ok
        & (df["minutes_365"].fillna(0) >= 900)
        & df["true_value"].notna()
        & df["gap_pct"].notna()
        & (df["market_value_in_eur"].fillna(0) >= 750_000)
        & (df["true_value"] >= 1_500_000)
        & (df["age"].fillna(99).between(18, 33))
    ]
    cheap = liquid[liquid["gap_pct"].between(-48, GAP_CHEAP)].sort_values("true_value", ascending=False).head(8)
    rich = liquid[liquid["gap_pct"] >= GAP_RICH].sort_values("market_value_in_eur", ascending=False).head(8)
    young = df[
        club_ok
        & (df["age"].fillna(99) <= 23)
        & (df["minutes_365"].fillna(0) >= 450)
    ].sort_values("true_value", ascending=False).head(8)
    superlig = df[
        club_ok & (df["league_id"].astype("string") == "TR1")
    ].sort_values("true_value", ascending=False).head(8)
    stars = df[
        club_ok
        & (df["minutes_365"].fillna(0) >= 900)
        & df["true_value"].notna()
        & (df["market_value_in_eur"].fillna(0) >= 400_000)
        & (df["age"].fillna(99).between(18, 34))
    ].sort_values("true_value", ascending=False).head(8)
    listed = leagues()
    by_id = {row["id"]: row for row in listed}
    featured = [by_id[code] for code in FEATURED_LEAGUES if code in by_id]

    def _league_top(code: str, n: int = 8) -> list[dict]:
        part = df[club_ok & (df["league_id"].astype("string") == code)]
        return [card(r) for _, r in part.sort_values("true_value", ascending=False).head(n).iterrows()]

    return {
        "undervalued": [card(r) for _, r in cheap.iterrows()],
        "overvalued": [card(r) for _, r in rich.iterrows()],
        "young": [card(r) for _, r in young.iterrows()],
        "superlig": [card(r) for _, r in superlig.iterrows()],
        "stars": [card(r) for _, r in stars.iterrows()],
        "brazil": _league_top("BRA1"),
        "argentina": _league_top("ARG1"),
        "mls": _league_top("MLS1"),
        "japan": _league_top("JAP1"),
        "leagues": listed,
        "featured": featured,
        "clubs": sorted(
            club_list().get("clubs", []),
            key=lambda r: (0 if r.get("league_id") == "TR1" else 1, -(r.get("true_sum") or 0)),
        )[:16],
        "counts": {
            "universe": int(len(universe())),
            "active": int(len(df)),
            "leagues": len(listed),
        },
    }


def _scout_pack(row: pd.Series) -> dict[str, Any]:
    gap = row.get("gap_pct")
    tm = format_eur(row.get("market_value_in_eur"))
    true = format_eur(row.get("true_value"))
    mins = int(float(row.get("minutes_365") or 0))
    mins2 = int(float(row.get("minutes_2y") or 0))
    apps = int(float(row.get("apps_2y") or 0))
    age = row.get("age")
    years = None
    try:
        if age is not None and age == age:
            years = int(round(float(age)))
    except (TypeError, ValueError):
        years = None
    club = str(row.get("current_club_name") or "")
    league = LEAGUE_NAMES.get(str(row.get("league_id") or ""), "")
    goals = int(float(row.get("goals_2y") or 0))
    assists = int(float(row.get("assists_2y") or 0))
    pos = POSITION_TR.get(str(row.get("position") or ""), row.get("position") or "")
    gap_n = float(gap) if gap is not None and gap == gap else None
    headline = f"Transfermarkt {tm}, Aurea değeri {true}." if true and tm else f"Aurea değeri {true}."
    paragraphs: list[str] = []
    where = club if club else "Kulüp belirsiz"
    if league:
        where = f"{where}, {league}"
    line = f"{where}."
    if years is not None:
        line += f" {years} yaşında {pos or 'oyuncu'}."
        if years <= 23:
            line += " Zirve öncesi; düzenli dakika değeri hızla taşır."
        elif years <= 28:
            line += " En verimli yaş bandında."
        else:
            line += " Zirve sonrası; sözleşme ve dakika daha kritik okunur."
    else:
        line += f" {pos or 'Mevki belirtilmedi'}."
    paragraphs.append(line)
    if mins2 or mins:
        paragraphs.append(
            f"Son iki sezon {apps} maç, {goals} gol, {assists} asist, {mins2} dakika. "
            f"Son 12 ayda {mins} dakika. "
            + (
                "As kadro temposu; üretim ölçülebilir."
                if mins >= 1800
                else "Dakika sınırlı; ucuzluk, süre almadığı için de oluşmuş olabilir."
                if mins < 700
                else "Düzenli ama her hafta tam 90 dakika değil."
            )
        )
    if gap_n is not None and gap_n <= GAP_CHEAP:
        paragraphs.append(
            "Transfermarkt etiketi, Aurea değerinin altında. "
            "Piyasa, üretime göre ucuz yazıyor. Sağlık ve sözleşme dosyada doğrulanır."
        )
    facts = [
        {"k": "Transfermarkt", "v": tm},
        {"k": "Aurea değeri", "v": true},
    ]
    return {
        "stamp": "",
        "headline": headline,
        "paragraphs": paragraphs,
        "why": " ".join(paragraphs),
        "facts": facts,
    }


def scout() -> dict:
    df = _apply_overlays(_catalog())
    liquid = df[
        df["true_value"].notna()
        & df["gap_pct"].notna()
        & (df["minutes_365"].fillna(0) >= 400)
        & (df["age"].fillna(99).between(17, 32))
        & (df["true_value"] >= 200_000)
        & (df["gap_pct"] <= -10)
    ].copy()
    mins = liquid["minutes_365"].clip(upper=2700) / 2700.0
    gap = (-liquid["gap_pct"]).clip(upper=55)
    age = liquid["age"].fillna(26)
    age_w = 1.0 - ((age - 24).abs() / 18.0).clip(upper=0.35)
    tr = (liquid["league_id"].astype("string") == "TR1").astype(float)
    liquid["_score"] = gap * (0.45 + 0.55 * mins) * age_w * (1.0 + 0.12 * tr)
    positions = (
        ("Goalkeeper", "Kaleci"),
        ("Defender", "Defans"),
        ("Midfield", "Orta saha"),
        ("Attack", "Forvet"),
    )
    bands = []
    for code, title in positions:
        part = liquid[liquid["position"] == code].sort_values("_score", ascending=False)
        tr1 = part[part["league_id"].astype("string") == "TR1"].head(5)
        rest = part[part["league_id"].astype("string") != "TR1"].head(9)
        items = pd.concat([tr1, rest]).drop_duplicates("player_id")
        items = items.sort_values("_score", ascending=False).head(12)
        rows = []
        for _, row in items.iterrows():
            item = card(row)
            pack = _scout_pack(row)
            item.update(pack)
            lid = str(row.get("league_id") or "")
            item["band"] = "Süper Lig" if lid == "TR1" else LEAGUE_NAMES.get(lid, lid)
            rows.append(item)
        bands.append({"id": code, "name": title, "items": rows})
    return json_safe({"ok": True, "positions": bands})


def leagues() -> list[dict]:
    df = _catalog()
    grouped = {str(code): part for code, part in df.groupby(df["league_id"].astype("string"))}
    rows = []
    for code in CATALOG_LEAGUES:
        part = grouped.get(code)
        if part is None or len(part) < 1:
            continue
        rows.append(
            {
                "id": code,
                "name": LEAGUE_NAMES.get(code, code),
                "region": LEAGUE_REGION.get(code, "Diğer"),
                "country": LEAGUE_COUNTRY.get(code, ""),
                "mark": LEAGUE_MARK.get(code, code[:3]),
                "flag": LEAGUE_FLAG.get(code, ""),
                "crest": f"https://flagcdn.com/w80/{LEAGUE_FLAG.get(code, 'un')}.png" if LEAGUE_FLAG.get(code) else "",
                "players": int(len(part)),
            }
        )
    return rows


def _virtual_from_live(player_id: int, bundle: dict) -> pd.DataFrame:
    profile = bundle.get("profile") or {}
    season = current_season_totals(bundle.get("stats") or [])
    club = profile.get("club") or {}
    pos = profile.get("position") or {}
    main = pos.get("main") if isinstance(pos, dict) else pos
    mapped = "Attack"
    if main:
        low = str(main).lower()
        if "keep" in low or "kaleci" in low:
            mapped = "Goalkeeper"
        elif "back" in low or "def" in low or "centre-back" in low:
            mapped = "Defender"
        elif "mid" in low:
            mapped = "Midfield"
        elif "wing" in low or "forward" in low or "striker" in low or "attack" in low:
            mapped = "Attack"
    mv = bundle.get("market_value") or profile.get("marketValue")
    row = {
        "player_id": player_id,
        "name": profile.get("name") or profile.get("fullName") or f"Oyuncu {player_id}",
        "image_url": profile.get("imageUrl"),
        "date_of_birth": profile.get("dateOfBirth"),
        "age": profile.get("age"),
        "height_in_cm": profile.get("height"),
        "foot": profile.get("foot"),
        "position": mapped,
        "sub_position": main or mapped,
        "country_of_citizenship": (profile.get("citizenship") or ["Other"])[0] if profile.get("citizenship") else "Other",
        "current_club_name": club.get("name"),
        "current_club_id": pd.to_numeric(club.get("id"), errors="coerce"),
        "current_club_domestic_competition_id": None,
        "market_value_in_eur": mv,
        "highest_market_value_in_eur": mv,
        "last_season": 2025,
        "contract_expiration_date": club.get("contractExpires"),
        "minutes_2y": season.get("minutes") or 0,
        "minutes_365": season.get("minutes") or 0,
        "apps_2y": season.get("apps") or 0,
        "apps_365": season.get("apps") or 0,
        "goals_2y": season.get("goals") or 0,
        "goals_365": season.get("goals") or 0,
        "assists_2y": season.get("assists") or 0,
        "assists_365": season.get("assists") or 0,
        "yellow_2y": season.get("yellow") or 0,
        "red_2y": season.get("red") or 0,
        "international_caps": 0,
        "international_goals": 0,
        "player_code": "",
    }
    return pd.DataFrame([row])


def _overlay_live(row: pd.Series, bundle: dict) -> pd.Series:
    if not bundle:
        return row
    out = row.copy()
    profile = bundle.get("profile") or {}
    if profile.get("name"):
        out["name"] = profile["name"]
    club = (profile.get("club") or {}).get("name") if isinstance(profile.get("club"), dict) else None
    if club:
        out["current_club_name"] = club
    if profile.get("imageUrl"):
        out["image_url"] = profile["imageUrl"]
    if profile.get("age"):
        out["age"] = profile["age"]
    if profile.get("height"):
        out["height_in_cm"] = profile["height"]
    if profile.get("foot"):
        out["foot"] = profile["foot"]
    if profile.get("internationalCaps"):
        out["international_caps"] = profile["internationalCaps"]
        out["intl_caps"] = profile["internationalCaps"]
    if bundle.get("market_value"):
        out["market_value_in_eur"] = bundle["market_value"]
    return out


def player_detail(player_id: int, live: bool = True) -> dict:
    df = universe()
    eng = engine()
    assert eng is not None
    hit = df[df["player_id"] == player_id]
    bundle = player_bundle(player_id, fresh=True) if live else {}
    season = current_season_totals(bundle.get("stats") or [])
    injury_days = open_injury_days(bundle.get("injuries") or [])
    hist = bundle.get("market_history") or []
    hist_vals = [h.get("marketValue") for h in hist if isinstance(h, dict) and h.get("marketValue")]
    tm_step = None
    if len(hist_vals) >= 2 and hist_vals[-2]:
        try:
            tm_step = 100.0 * (float(hist_vals[-1]) - float(hist_vals[-2])) / float(hist_vals[-2])
        except (TypeError, ValueError, ZeroDivisionError):
            tm_step = None
    if hit.empty:
        extra = _virtual_from_live(player_id, bundle)
        if extra.empty or extra.iloc[0].get("name") is None:
            raise KeyError(player_id)
        prepared_extra = prepare_frame(extra)
        scored_extra = score_universe(prepared_extra, eng)
        row = scored_extra.iloc[0]
        similar = similar_players(eng, pd.concat([df, scored_extra], ignore_index=True), player_id)
        if injury_days or tm_step is not None or bundle.get("market_value"):
            scored = rescore_row(
                eng,
                pd.concat([df, scored_extra], ignore_index=True),
                player_id,
                {
                    **({"tm_step_pct": tm_step} if tm_step is not None else {}),
                    **({"injury_days": injury_days} if injury_days else {}),
                    **({"market_value_in_eur": bundle["market_value"]} if bundle.get("market_value") else {}),
                },
            )
            row = row.copy()
            for key, value in scored.items():
                row[key] = value
    else:
        row = hit.iloc[0]
        similar = similar_players(eng, df, player_id)
        overrides = {}
        if season.get("minutes"):
            overrides["minutes_365"] = season["minutes"]
            overrides["apps_365"] = season["apps"]
            overrides["goals_365"] = season["goals"]
            overrides["assists_365"] = season["assists"]
        if bundle.get("market_value"):
            overrides["market_value_in_eur"] = bundle["market_value"]
        if injury_days:
            overrides["injury_days"] = injury_days
        if tm_step is not None:
            overrides["tm_step_pct"] = tm_step
        if overrides:
            scored = rescore_row(eng, df, player_id, overrides)
            row = row.copy()
            for key, value in scored.items():
                row[key] = value
            if scored.get("tm_value") is not None:
                row["market_value_in_eur"] = scored["tm_value"]
    row = _overlay_live(row, bundle)
    payload = card(row)
    payload.update(
        {
            "fair_value": _clean(row.get("fair_value")),
            "value_lo": _clean(row.get("value_lo")),
            "value_hi": _clean(row.get("value_hi")),
            "tm_value": _clean(row.get("market_value_in_eur")),
            "true_value": _clean(row.get("true_value")),
            "confidence": _clean(row.get("confidence")),
            "gap_pct": _clean(row.get("gap_pct")),
            "goals_p90": _clean(row.get("goals_p90")),
            "assists_p90": _clean(row.get("assists_p90")),
            "contrib_p90": _clean(row.get("contrib_p90")),
            "minutes_2y": _clean(row.get("minutes_2y")),
            "apps_2y": _clean(row.get("apps_2y")),
            "goals_2y": _clean(row.get("goals_2y")),
            "assists_2y": _clean(row.get("assists_2y")),
            "intl_caps": _clean(row.get("intl_caps") or row.get("international_caps")),
            "height_in_cm": _clean(row.get("height_in_cm")),
            "foot": None if pd.isna(row.get("foot")) else str(row.get("foot")),
            "contract_years": _clean(row.get("contract_years")),
            "pct_minutes": _clean(row.get("pct_minutes")),
            "pct_contrib": _clean(row.get("pct_contrib")),
            "pct_value": _clean(row.get("pct_value")),
            "pct_true": _clean(row.get("pct_true")),
            "yellow_2y": _clean(row.get("yellow_2y")),
            "red_2y": _clean(row.get("red_2y")),
            "highest_market_value_in_eur": _clean(row.get("highest_market_value_in_eur")),
            "lo_label": format_eur(row.get("value_lo")),
            "hi_label": format_eur(row.get("value_hi")),
            "peak_label": format_eur(row.get("highest_market_value_in_eur")),
            "url": row.get("url"),
            "nationality": row.get("country_of_citizenship"),
            "last_match": _clean(row.get("last_match")),
            "league_region": LEAGUE_REGION.get(str(row.get("league_id") or ""), ""),
        }
    )
    tm_v = payload.get("tm_value")
    true_v = payload.get("true_value")
    if tm_v is not None and true_v is not None:
        payload["gap_eur"] = tm_v - true_v
        payload["gap_eur_label"] = format_eur(abs(tm_v - true_v))
    live_view = None
    if bundle:
        live_view = {
            "season_totals": season,
            "injuries": (bundle.get("injuries") or [])[:8],
            "injury_days": injury_days,
            "market_history": (bundle.get("market_history") or [])[-24:],
            "transfers": (bundle.get("transfers") or [])[:8],
            "profile": {
                "fullName": (bundle.get("profile") or {}).get("fullName"),
                "shirtNumber": (bundle.get("profile") or {}).get("shirtNumber"),
                "description": (bundle.get("profile") or {}).get("description"),
                "imageUrl": (bundle.get("profile") or {}).get("imageUrl"),
                "club": (bundle.get("profile") or {}).get("club"),
                "caps": (bundle.get("profile") or {}).get("internationalCaps"),
                "intl_goals": (bundle.get("profile") or {}).get("internationalGoals"),
                "joined": (bundle.get("profile") or {}).get("joined"),
                "league": (bundle.get("profile") or {}).get("leagueName"),
                "birthplace": (bundle.get("profile") or {}).get("placeOfBirth"),
            },
            "source": bundle.get("source"),
            "fetched_at": bundle.get("fetched_at"),
            "live": True,
        }
        if live_view["profile"].get("imageUrl"):
            payload["image_url"] = live_view["profile"]["imageUrl"]
        club_pack = live_view["profile"].get("club") or {}
        club_live = club_pack.get("name")
        club_live_id = club_pack.get("id")
        if club_live:
            payload["club"] = club_display(str(club_live))
            if is_free_agent(str(club_live)):
                payload["club_href"] = None
                payload["club_token"] = None
            elif club_live_id:
                payload["club_href"] = club_path(club_live_id, club_live, payload.get("league_id") or "")
                payload["club_token"] = club_token(club_live_id, club_live, payload.get("league_id") or "")
            club_overlay_put(
                player_id,
                club_id=None if is_free_agent(str(club_live)) else club_live_id,
                club_name="Kulüpsüz" if is_free_agent(str(club_live)) else club_live,
                league_id=str(payload.get("league_id") or ""),
            )
        if live_view["profile"].get("shirtNumber"):
            payload["shirt"] = live_view["profile"]["shirtNumber"]
        if live_view["profile"].get("caps"):
            payload["intl_caps"] = live_view["profile"]["caps"]
        if live_view["profile"].get("intl_goals"):
            payload["intl_goals"] = live_view["profile"]["intl_goals"]
        if live_view["profile"].get("league"):
            payload["league"] = live_view["profile"]["league"]
            payload["league_live"] = live_view["profile"]["league"]
        if live_view["profile"].get("birthplace"):
            payload["birthplace"] = live_view["profile"]["birthplace"]
        payload["live_fetched_at"] = live_view.get("fetched_at")
        hist = live_view.get("market_history") or []
        valued = [h for h in hist if h.get("marketValue")]
        if len(valued) < 2:
            peak = payload.get("highest_market_value_in_eur")
            tm_now = payload.get("tm_value")
            if peak and tm_now:
                live_view["market_history"] = [
                    {"date": None, "marketValue": peak, "clubName": ""},
                    {"date": (live_view.get("fetched_at") or "")[:10], "marketValue": tm_now, "clubName": ""},
                ]
    if live_view is None:
        live_view = {}
    try:
        dossier = player_dossier(
            str(payload.get("name") or row.get("name") or ""),
            str(payload.get("club") or row.get("current_club_name") or ""),
        )
    except Exception:
        dossier = None
    if dossier:
        live_view["fotmob"] = dossier
        payload["form_live"] = {
            "apps": dossier.get("apps"),
            "minutes": dossier.get("minutes"),
            "goals": dossier.get("goals"),
            "assists": dossier.get("assists"),
            "xg": dossier.get("xg"),
            "xa": dossier.get("xa"),
            "shots": dossier.get("shots"),
            "sot": dossier.get("sot"),
            "recent": dossier.get("recent"),
            "injured": dossier.get("injured"),
            "league": dossier.get("league"),
            "season": dossier.get("season"),
            "source": "FotMob",
        }
    row_dict = {k: _clean(v) if not isinstance(v, (dict, list)) else v for k, v in row.items()}
    row_dict.update(payload)
    report = build_report(row_dict, similar, live_view if live_view else None)
    for item in similar:
        item["tm_label"] = format_eur(item.get("market_value_in_eur"))
        item["true_label"] = format_eur(item.get("true_value"))
        item["href"] = player_path(item.get("player_id"), item.get("name"))
    stats_rows = []
    for rec in season.get("rows") or []:
        stats_rows.append(
            {
                "competition": rec.get("competitionName"),
                "season": rec.get("seasonId"),
                "apps": rec.get("appearances") or 0,
                "goals": rec.get("goals") or 0,
                "assists": rec.get("assists") or 0,
                "minutes": rec.get("minutesPlayed") or 0,
            }
        )
    return json_safe(
        {
            "player": payload,
            "report": report,
            "similar": similar,
            "live": live_view,
            "season_table": stats_rows,
            "meta": eng.meta,
            "href": payload.get("href") or player_path(player_id, payload.get("name")),
            "pdf": f"/api/players/{int(player_id)}/pdf",
        }
    )


def club_list() -> dict:
    df = _apply_overlays(_catalog())
    if "current_club_name" not in df.columns:
        return {"clubs": []}
    rows = []
    grouped = df.groupby(["current_club_name", "league_id"], dropna=False)
    for (name, lid), part in grouped:
        label = str(name or "").strip()
        if not label or label.lower() in {"nan", "none"} or is_free_agent(label):
            continue
        label = club_display(label)
        cid = None
        if "current_club_id" in part.columns and part["current_club_id"].notna().any():
            cid = part["current_club_id"].dropna().iloc[0]
        token = club_token(cid, label, str(lid or ""))
        gap = pd.to_numeric(part.get("gap_pct"), errors="coerce")
        true = pd.to_numeric(part.get("true_value"), errors="coerce")
        tm = pd.to_numeric(part.get("market_value_in_eur"), errors="coerce")
        rows.append(
            {
                "id": token,
                "name": label,
                "league_id": str(lid or ""),
                "league": LEAGUE_NAMES.get(str(lid or ""), str(lid or "")),
                "players": int(len(part)),
                "href": club_path(cid, label, str(lid or "")),
                "cheap": int((gap <= GAP_CHEAP).sum()),
                "rich": int((gap >= GAP_RICH).sum()),
                "true_sum": float(true.fillna(0).sum()),
                "true_label": format_eur(true.fillna(0).sum()),
                "tm_sum": float(tm.fillna(0).sum()),
                "tm_label": format_eur(tm.fillna(0).sum()),
            }
        )
    by_id: dict[str, dict[str, Any]] = {}
    leftovers: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("id") or "")
        if not (key.startswith("c") and key[1:].isdigit()):
            leftovers.append(row)
            continue
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = row
            continue
        pick = row if _club_row_better(row, prev) else prev
        merged = dict(pick)
        merged["players"] = int(prev.get("players") or 0) + int(row.get("players") or 0)
        merged["cheap"] = int(prev.get("cheap") or 0) + int(row.get("cheap") or 0)
        merged["rich"] = int(prev.get("rich") or 0) + int(row.get("rich") or 0)
        merged["true_sum"] = float(prev.get("true_sum") or 0) + float(row.get("true_sum") or 0)
        merged["tm_sum"] = float(prev.get("tm_sum") or 0) + float(row.get("tm_sum") or 0)
        merged["true_label"] = format_eur(merged["true_sum"])
        merged["tm_label"] = format_eur(merged["tm_sum"])
        by_id[key] = merged
    rows = list(by_id.values()) + leftovers
    rows.sort(key=lambda r: (0 if r["league_id"] == "TR1" else 1, slugify(r.get("league") or ""), slugify(r.get("name") or "")))
    return json_safe({"clubs": rows})


def _club_row_better(row: dict[str, Any], prev: dict[str, Any]) -> bool:
    rp, pp = int(row.get("players") or 0), int(prev.get("players") or 0)
    if rp != pp:
        return rp > pp
    if row.get("league_id") == "TR1" and prev.get("league_id") != "TR1":
        return True
    if prev.get("league_id") == "TR1" and row.get("league_id") != "TR1":
        return False
    return len(str(row.get("name") or "")) > len(str(prev.get("name") or ""))


def _squad_live_card(row: dict[str, Any], club: str, club_href: str | None) -> dict[str, Any]:
    pid = row.get("player_id")
    name = str(row.get("name") or "")
    tm = row.get("tm_value")
    pos = str(row.get("position") or "")
    return {
        "player_id": pid,
        "name": name,
        "club": club_display(club),
        "club_href": club_href if club_display(club) != "Kulüpsüz" else None,
        "position": POSITION_TR.get(pos, pos),
        "age": row.get("age"),
        "tm_value": tm,
        "tm_label": format_eur(tm),
        "true_value": None,
        "true_label": "—",
        "gap_pct": None,
        "gap_label": "—",
        "direction": "belirsiz",
        "href": player_path(pid, name) if pid is not None else None,
        "live_only": True,
    }


def club_roster(token: str) -> dict:
    catalog = _apply_overlays(_catalog())
    uni = _apply_overlays(universe())
    key = str(token or "").strip()
    cid = None
    name_slug = ""
    lig = ""
    if key.startswith("c") and key[1:].isdigit():
        cid = int(key[1:])
        ids = pd.to_numeric(uni.get("current_club_id"), errors="coerce")
        part = uni[ids == cid]
        if part.empty:
            ids = pd.to_numeric(catalog.get("current_club_id"), errors="coerce")
            part = catalog[ids == cid]
    elif key.startswith("n-"):
        rest = key[2:]
        lig, _, name_slug = rest.partition("-")
        if not name_slug:
            name_slug = lig
            lig = ""
        names = uni["current_club_name"].astype("string").fillna("") if "current_club_name" in uni.columns else pd.Series(dtype="string")
        mask = names.map(lambda n: slugify(str(n)) == name_slug)
        if lig:
            mask = mask & (uni["league_id"].astype("string").str.lower() == lig.lower())
        part = uni[mask] if not names.empty else uni.iloc[0:0]
        if part.empty and lig:
            part = uni[names.map(lambda n: slugify(str(n)) == name_slug)]
    else:
        part = uni.iloc[0:0]
    sample = part.iloc[0] if not part.empty else None
    title = str((sample.get("current_club_name") if sample is not None else None) or "")
    lid = str((sample.get("league_id") if sample is not None else None) or lig or "")
    if not title:
        title = name_slug.replace("-", " ") if name_slug else "Kulüp"
    if sample is None and not name_slug and cid is None:
        raise KeyError(token)
    league_name = LEAGUE_NAMES.get(lid, lid)
    href = "/kulup/" + key
    if cid is None and sample is not None and not key.startswith("n-"):
        raw_cid = sample.get("current_club_id")
        try:
            if raw_cid == raw_cid and raw_cid is not None:
                cid = int(float(raw_cid))
        except (TypeError, ValueError):
            cid = None
    moves: dict[str, Any] = {"in": [], "out": [], "season": ""}
    squad_rows: list[dict[str, Any]] = []
    if cid is None:
        try:
            cid = resolve_club_id(title)
        except Exception:
            cid = None
    try:
        from app.transfers import club_moves, club_squad

        if cid is not None:
            moves = club_moves(int(cid), title)
            squad_rows = club_squad(int(cid), title)
    except Exception:
        moves = {"in": [], "out": [], "season": ""}
        squad_rows = []
    squad = [int(r["player_id"]) for r in squad_rows if r.get("player_id")]
    pids = pd.to_numeric(uni.get("player_id"), errors="coerce")
    if squad:
        matched = uni[pids.isin(squad)]
        if not matched.empty:
            part = matched
        else:
            leavers = {int(r["player_id"]) for r in (moves.get("out") or []) if r.get("player_id")}
            arrivals = {int(r["player_id"]) for r in (moves.get("in") or []) if r.get("player_id")}
            if leavers and not part.empty:
                part = part[~pids.loc[part.index].isin(leavers)]
            extra = uni[pids.isin(arrivals)]
            if not extra.empty:
                part = pd.concat([part, extra]).drop_duplicates(subset=["player_id"]) if not part.empty else extra
    else:
        leavers = {int(r["player_id"]) for r in (moves.get("out") or []) if r.get("player_id")}
        arrivals = {int(r["player_id"]) for r in (moves.get("in") or []) if r.get("player_id")}
        if leavers and not part.empty:
            part = part[~pids.loc[part.index].isin(leavers)]
        extra = uni[pids.isin(arrivals)]
        if not extra.empty:
            part = pd.concat([part, extra]).drop_duplicates(subset=["player_id"]) if not part.empty else extra
    title = club_display(title)
    scored: dict[int, dict[str, Any]] = {}
    if not part.empty:
        true = pd.to_numeric(part.get("true_value"), errors="coerce").fillna(0)
        tm = pd.to_numeric(part.get("market_value_in_eur"), errors="coerce").fillna(0)
        valued = part[(true > 0) | (tm > 0)]
        for _, row in valued.iterrows():
            pid = row.get("player_id")
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                continue
            item = card(row)
            item["club"] = title
            if href and title != "Kulüpsüz":
                item["club_href"] = href
            scored[pid_i] = item
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    if squad_rows:
        for raw in squad_rows:
            pid = raw.get("player_id")
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                continue
            if pid_i in seen:
                continue
            seen.add(pid_i)
            if pid_i in scored:
                item = scored[pid_i]
                if not item.get("tm_value") and raw.get("tm_value"):
                    item["tm_value"] = raw.get("tm_value")
                    item["tm_label"] = format_eur(raw.get("tm_value"))
                items.append(item)
            else:
                items.append(_squad_live_card(raw, title, href))
                if cid is not None:
                    club_overlay_put(pid_i, club_id=cid, club_name=title)
    else:
        items = list(scored.values())
    if not items:
        raise KeyError(token)
    if squad_rows:
        for raw in squad_rows:
            pid = raw.get("player_id")
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                continue
            if pid_i in scored:
                club_overlay_put(pid_i, club_id=cid, club_name=title)
    cheap = [x for x in items if x.get("direction") == "dusuk"]
    rich = [x for x in items if x.get("direction") == "yuksek"]
    even = [x for x in items if x.get("direction") == "denge"]
    true_sum = sum(float(x.get("true_value") or 0) for x in items)
    tm_sum = sum(float(x.get("tm_value") or 0) for x in items)
    return json_safe(
        {
            "id": key,
            "name": title,
            "league_id": lid,
            "league": league_name,
            "href": href,
            "club_id": None if cid is None else cid,
            "players": int(len(items)),
            "true_label": format_eur(true_sum),
            "tm_label": format_eur(tm_sum),
            "cheap": cheap,
            "rich": rich,
            "even": even,
            "items": items,
            "transfers": moves,
        }
    )


def compare_pack(left_id: int, right_id: int) -> dict:
    left = player_detail(int(left_id), live=True)
    right = player_detail(int(right_id), live=True)
    return json_safe(
        {
            "left": left,
            "right": right,
            "verdict": compare_verdict(left, right),
        }
    )


def calibration_pack() -> dict:
    df = _catalog().copy()
    liquid = df[
        df["true_value"].notna()
        & df["gap_pct"].notna()
        & (df["minutes_365"].fillna(0) >= 700)
        & (df["age"].fillna(99).between(18, 34))
    ]
    cheap = liquid[liquid["gap_pct"] <= -12].sort_values("gap_pct").head(12)
    rich = liquid[liquid["gap_pct"] >= 12].sort_values("gap_pct", ascending=False).head(12)
    bands = []
    for lo, hi, title in ((16, 21, "21 yaş ve altı"), (22, 26, "22–26"), (27, 31, "27–31"), (32, 38, "32+")):
        part = liquid[liquid["age"].fillna(0).between(lo, hi)]
        if part.empty:
            continue
        gap = pd.to_numeric(part["gap_pct"], errors="coerce")
        bands.append(
            {
                "title": title,
                "n": int(len(part)),
                "median_gap": float(gap.median()) if gap.notna().any() else None,
                "cheap": int((gap <= -12).sum()),
                "rich": int((gap >= 12).sum()),
            }
        )
    leagues_out = []
    for code, part in liquid.groupby(liquid["league_id"].astype("string")):
        gap = pd.to_numeric(part["gap_pct"], errors="coerce")
        if gap.notna().sum() < 8:
            continue
        leagues_out.append(
            {
                "id": str(code),
                "name": LEAGUE_NAMES.get(str(code), str(code)),
                "n": int(len(part)),
                "median_gap": float(gap.median()),
                "cheap": int((gap <= -12).sum()),
                "rich": int((gap >= 12).sum()),
            }
        )
    leagues_out.sort(key=lambda r: abs(r["median_gap"] or 0), reverse=True)
    deals = []
    try:
        from app.transfers import desk

        desk_pack = desk(refresh=False)
        for deal in (desk_pack.get("deals") or [])[:16]:
            deals.append(
                {
                    "name": deal.get("name"),
                    "club": deal.get("club"),
                    "fee_label": deal.get("fee_label"),
                    "tm_label": deal.get("tm_label"),
                    "true_label": deal.get("true_label"),
                    "verdict": deal.get("verdict"),
                    "headline": deal.get("headline"),
                    "href": deal.get("href"),
                }
            )
    except Exception:
        deals = []
    eng = engine()
    meta = dict(eng.meta) if eng and eng.meta else {}
    peak = liquid[
        liquid["highest_market_value_in_eur"].fillna(0) > liquid["market_value_in_eur"].fillna(0) * 1.35
    ].sort_values("highest_market_value_in_eur", ascending=False).head(10)
    return json_safe(
        {
            "counts": {
                "catalog": int(len(df)),
                "liquid": int(len(liquid)),
                "cheap": int((liquid["gap_pct"] <= -12).sum()),
                "rich": int((liquid["gap_pct"] >= 12).sum()),
            },
            "cheap": [card(r) for _, r in cheap.iterrows()],
            "rich": [card(r) for _, r in rich.iterrows()],
            "bands": bands,
            "leagues": leagues_out[:12],
            "deals": deals,
            "cooled": [card(r) for _, r in peak.iterrows()],
            "meta": {
                "mae": meta.get("mae") or meta.get("median_ae") or meta.get("error"),
                "n_train": meta.get("n_train") or meta.get("rows") or meta.get("n"),
                "updated": meta.get("trained_at") or meta.get("updated_at"),
            },
            "note": (
                "Aurea geçmişte saklanan bir tahmin defteri tutmaz. "
                "Bu sayfa bugünkü Aurea değeri ile bugünkü etiketi, kariyer tepesini ve "
                "Süper Lig gelen bedellerini yan yana koyar. "
                "Etiket geçmişi oyuncu dosyasındaki eğride okunur."
            ),
        }
    )

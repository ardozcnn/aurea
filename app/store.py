"""Bellekteki oyuncu evreni, arama ve piyasa listeleri."""

from __future__ import annotations

import math
import threading
from typing import Any

import numpy as np
import pandas as pd

from app.analysis import build_report
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
from app.live_tm import current_season_totals, open_injury_days, player_bundle, search_players
from app.model import Engine, rescore_row, score_universe, similar_players
from app.money import format_eur, format_pct, gap_direction
from app.warehouse import warehouse_ready

_LOCK = threading.Lock()
_UNIVERSE: pd.DataFrame | None = None
_ENGINE: Engine | None = None


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


def card(row: pd.Series) -> dict[str, Any]:
    pid = _clean(row.get("player_id"))
    gap = _clean(row.get("gap_pct"))
    payload = {
        "player_id": int(pid) if pid is not None else None,
        "name": row.get("name"),
        "image_url": _clean(row.get("image_url")),
        "club": row.get("current_club_name"),
        "league_id": None if pd.isna(row.get("league_id")) else str(row.get("league_id")),
        "league": LEAGUE_NAMES.get(str(row.get("league_id") or ""), str(row.get("league_id") or "")),
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


def search(query: str, limit: int = 18) -> list[dict]:
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    df = universe()
    names = df["name"].astype("string").str.lower().fillna("")
    code = df["player_code"].astype("string").str.lower().fillna("") if "player_code" in df.columns else names
    club = df["current_club_name"].astype("string").str.lower().fillna("") if "current_club_name" in df.columns else names
    hit = df[names.str.contains(q, regex=False) | code.str.contains(q, regex=False) | club.str.contains(q, regex=False)].copy()
    if hit.empty and len(q) < 2:
        return []
    hit["_rank"] = hit["name"].astype("string").fillna("").map(lambda n: _name_rank(str(n), q))
    in_top = hit["league_id"].astype("string").isin(TOP_LEAGUES) if "league_id" in hit.columns else False
    hit["_top"] = (~in_top).astype(int)
    hit = hit.sort_values(["_rank", "_top", "market_value_in_eur"], ascending=[True, True, False], na_position="last").head(limit)
    results = [card(row) for _, row in hit.iterrows()]
    for item in results:
        item["match"] = _name_rank(str(item.get("name") or ""), q)
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
        results.append(
            {
                "player_id": int(pid) if pid.isdigit() else item.get("id"),
                "name": name,
                "club": (item.get("club") or {}).get("name") if isinstance(item.get("club"), dict) else item.get("club"),
                "position": item.get("position"),
                "age": item.get("age"),
                "tm_value": item.get("marketValue"),
                "tm_label": format_eur(item.get("marketValue")),
                "live_only": True,
                "direction": "belirsiz",
                "match": _name_rank(name, q),
            }
        )
        have_ids.add(pid)
        have_names.add(name.lower())
        if len(results) >= limit:
            break
    results.sort(key=lambda r: (r.get("match") if r.get("match") is not None else 9, -(r.get("tm_value") or 0)))
    return json_safe(results)


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
) -> dict:
    df = _catalog()
    if league:
        df = df[df["league_id"].astype("string") == str(league)]
    if position:
        df = df[df["position"].astype("string") == str(position)]
    if min_minutes:
        df = df[df["minutes_365"].fillna(0) >= min_minutes]
    if q:
        needle = q.strip().lower()
        df = df[df["name"].astype("string").str.lower().str.contains(needle, regex=False, na=False)]
    if direction in {"dusuk", "yuksek", "denge"}:
        gap = df["gap_pct"]
        if direction == "dusuk":
            df = df[gap <= -12]
        elif direction == "yuksek":
            df = df[gap >= 12]
        else:
            df = df[gap.between(-12, 12)]
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
    df = _catalog()
    liquid = df[
        (df["minutes_365"].fillna(0) >= 900)
        & df["true_value"].notna()
        & df["gap_pct"].notna()
        & (df["market_value_in_eur"].fillna(0) >= 750_000)
        & (df["true_value"] >= 1_500_000)
        & (df["age"].fillna(99).between(18, 33))
    ]
    cheap = liquid[liquid["gap_pct"].between(-48, -12)].sort_values("true_value", ascending=False).head(8)
    rich = liquid[liquid["gap_pct"].between(12, 60)].sort_values("market_value_in_eur", ascending=False).head(8)
    young = df[(df["age"].fillna(99) <= 23) & (df["minutes_365"].fillna(0) >= 450)].sort_values("true_value", ascending=False).head(8)
    superlig = df[df["league_id"].astype("string") == "TR1"].sort_values("true_value", ascending=False).head(8)
    stars = df.sort_values("true_value", ascending=False).head(8)
    listed = leagues()
    by_id = {row["id"]: row for row in listed}
    featured = [by_id[code] for code in FEATURED_LEAGUES if code in by_id]

    def _league_top(code: str, n: int = 8) -> list[dict]:
        part = df[df["league_id"].astype("string") == code]
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
            line += " Zirve öncesi; düzenli dakika değerini hızla taşır."
        elif years <= 28:
            line += " En verimli yaş bandında."
        else:
            line += " Zirve sonrası; sözleşme ve dakika daha kritik."
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
                else "Dakika sınırlı; ucuzluk oynamadığı için de oluşmuş olabilir."
                if mins < 700
                else "Düzenli ama her hafta tam 90 değil."
            )
        )
    if gap_n is not None and gap_n <= -12:
        paragraphs.append(
            "Transfermarkt etiketi Aurea değerinin altında. "
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
    df = _catalog()
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
            "market_history": (bundle.get("market_history") or [])[-16:],
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
        club_live = (live_view["profile"].get("club") or {}).get("name")
        if club_live:
            payload["club"] = club_live
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
    row_dict = {k: _clean(v) if not isinstance(v, (dict, list)) else v for k, v in row.items()}
    row_dict.update(payload)
    report = build_report(row_dict, similar, live_view)
    for item in similar:
        item["tm_label"] = format_eur(item.get("market_value_in_eur"))
        item["true_label"] = format_eur(item.get("true_value"))
        item["position"] = POSITION_TR.get(str(item.get("position") or ""), item.get("position"))
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
        }
    )

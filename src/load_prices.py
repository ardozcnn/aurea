"""Fiyat yükleme ve istatistiklerle birleştirme."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .names import best_match, club_key, normalize_name


REQUIRED = ("player_name", "team", "position", "price_m")
OPTIONAL = (
    "display_name",
    "match_name",
    "search_name",
    "availability",
    "avail_pct",
    "avail_news",
    "tff_form",
    "selected_by",
    "tff_xg",
    "tff_xa",
    "tff_points",
    "tff_round_points",
    "tff_ppm",
    "tff_minutes",
    "tff_starts",
    "tff_goals",
    "tff_assists",
    "tff_bonus",
    "tff_bps",
)


def load_prices(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Fiyat dosyası yok: {path}")

    if path.suffix.lower() == ".json":
        df = pd.read_json(path)
    else:
        df = pd.read_csv(path)

    df.columns = [str(c).strip().lower() for c in df.columns]
    aliases = {
        "name": "player_name",
        "player": "player_name",
        "oyuncu": "player_name",
        "club": "team",
        "squad": "team",
        "takim": "team",
        "takım": "team",
        "pos": "position",
        "mevki": "position",
        "price": "price_m",
        "fiyat": "price_m",
        "cost": "price_m",
    }
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"Fiyat dosyasında eksik kolonlar: {missing}. "
            f"Gerekli: {list(REQUIRED)}"
        )

    keep = [c for c in (*REQUIRED, *OPTIONAL) if c in df.columns]
    df = df[keep].copy()
    df["player_name"] = df["player_name"].astype(str).str.strip()
    df["team"] = df["team"].astype(str).str.strip()
    if "display_name" not in df.columns:
        df["display_name"] = df["player_name"]
    else:
        df["display_name"] = df["display_name"].fillna(df["player_name"]).astype(str)
    if "match_name" not in df.columns:
        df["match_name"] = ""
    if "search_name" not in df.columns:
        df["search_name"] = df["display_name"]
    df["position"] = (
        df["position"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace(
            {
                "KALECI": "GK",
                "KALECİ": "GK",
                "KL": "GK",
                "G": "GK",
                "DEFANS": "DF",
                "D": "DF",
                "ORTA SAHA": "MF",
                "ORTASAHA": "MF",
                "OS": "MF",
                "M": "MF",
                "FORVET": "FW",
                "F": "FW",
                "ST": "FW",
            }
        )
    )
    df["price_m"] = pd.to_numeric(df["price_m"], errors="coerce")
    df = df.dropna(subset=["player_name", "price_m", "position"])
    df = df[df["position"].isin(["GK", "DF", "MF", "FW"])]
    df["player_key"] = df["player_name"].map(normalize_name)
    return df.reset_index(drop=True)


def _stat_row(stats: pd.DataFrame, match_name: str) -> pd.Series | None:
    hit = stats[stats["player"] == match_name]
    if hit.empty:
        key = normalize_name(match_name)
        keys = stats["player_key"] if "player_key" in stats.columns else stats["player"].map(normalize_name)
        hit = stats[keys == key]
    if hit.empty:
        return None
    return hit.iloc[0]


def _wrong_person(price_row: Any, stat_row: pd.Series) -> bool:
    """Farklı kulüpteki benzer soyadı eşleşmesini ele; gerçek transferi korur."""
    price_club = club_key(str(price_row.get("team") or ""))
    stat_club = club_key(str(stat_row.get("team") or ""))
    if not price_club or not stat_club or price_club == stat_club:
        return False
    stat_name = normalize_name(str(stat_row.get("player") or ""))
    if not stat_name:
        return True
    for field in ("player_name", "display_name", "match_name", "search_name"):
        value = normalize_name(str(price_row.get(field) or ""))
        if value and value == stat_name:
            return False
    return True


def merge_prices(stats: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """
    Fiyat listesindeki her oyuncuyu stats ile fuzzy eşleştir.
    Eşleşmeyenler projected_pts=0 ile kalır; dış lig adımı sonra doldurur.
    """
    if prices is None or prices.empty:
        raise ValueError("Fiyat verisi boş.")

    candidates = stats["player"].astype(str).tolist() if not stats.empty else []
    rows = []
    for _, pr in prices.iterrows():
        extras = [
            str(pr.get("display_name") or ""),
            str(pr.get("search_name") or ""),
            str(pr.get("match_name") or ""),
        ]
        extras = [x for x in extras if x and x != str(pr["player_name"])]
        match_name, score = best_match(
            pr["player_name"],
            candidates,
            score_cutoff=78,
            extra_queries=extras,
        )
        st = _stat_row(stats, match_name) if match_name and not stats.empty else None
        if st is not None:
            st_pos = str(st.get("position") or "")
            tff_pos = str(pr["position"])
            if st_pos in ("GK", "DF", "MF", "FW") and tff_pos != st_pos:
                if {st_pos, tff_pos} != {"MF", "FW"}:
                    st = None
                    score = 0.0
        if st is not None and _wrong_person(pr, st):
            st = None
            score = 0.0
        display = str(pr.get("display_name") or pr["player_name"])

        base = {
            "player": pr["player_name"],
            "display_name": display,
            "match_name": str(pr.get("match_name") or ""),
            "search_name": str(pr.get("search_name") or display),
            "team": pr["team"],
            "position": pr["position"],
            "price_m": float(pr["price_m"]),
            "availability": str(pr.get("availability") or ""),
            "avail_pct": pr.get("avail_pct"),
            "tff_form": pr.get("tff_form") or 0,
            "selected_by": pr.get("selected_by") or 0,
            "tff_xg": pr.get("tff_xg") or 0,
            "tff_xa": pr.get("tff_xa") or 0,
            "tff_points": pr.get("tff_points") or 0,
            "tff_round_points": pr.get("tff_round_points") or 0,
            "tff_ppm": pr.get("tff_ppm") or 0,
            "tff_minutes": pr.get("tff_minutes") or 0,
            "tff_starts": pr.get("tff_starts") or 0,
            "tff_goals": pr.get("tff_goals") or 0,
            "tff_assists": pr.get("tff_assists") or 0,
            "tff_bonus": pr.get("tff_bonus") or 0,
            "tff_bps": pr.get("tff_bps") or 0,
        }

        if st is not None:
            rows.append(
                {
                    **base,
                    "team": pr["team"] or st.get("team", ""),
                    "stats_player": st["player"],
                    "projected_pts": float(st.get("projected_pts", 0) or 0),
                    "match_score": score,
                    "reason": st.get("reason", ""),
                    "int_p90": st.get("int_p90", 0),
                    "tkl_p90": st.get("tkl_p90", 0),
                    "form_pts": st.get("form_pts", 0),
                    "base_pts": st.get("base_pts", 0),
                    "min_per_app": st.get("min_per_app", 0),
                    "gls_pa": st.get("gls_pa", 0),
                    "ast_pa": st.get("ast_pa", 0),
                    "xg_pa": st.get("xg_pa", 0),
                    "xa_pa": st.get("xa_pa", 0),
                    "form_apps": st.get("form_apps", 0),
                    "base_apps": st.get("base_apps", 0),
                    "current_apps": st.get("current_apps", 0),
                    "current_minutes": st.get("current_minutes", 0),
                    "prev_apps": st.get("prev_apps", 0),
                    "prev_minutes": st.get("prev_minutes", 0),
                    "established_sl_apps": st.get("established_sl_apps", 0),
                    "data_src": st.get("data_src", "super_lig"),
                    "base_src": st.get("base_src", ""),
                    "team_cs_base": st.get("team_cs_base"),
                    "cs_raw": st.get("cs_raw"),
                    "cs_after_fixture": st.get("cs_after_fixture"),
                    "saves_contrib": st.get("saves_contrib", 0),
                    "saves_pa": st.get("saves_pa", 0),
                    "prior_saves_pa": st.get("prior_saves_pa", 0),
                    "current_saves_pa": st.get("current_saves_pa", 0),
                    "w_saves_current": st.get("w_saves_current", 0),
                    "share_60": st.get("share_60", 0),
                    "fixture_opponent": st.get("fixture_opponent", ""),
                    "fixture_home": st.get("fixture_home"),
                    "fixture_attack_mult": st.get("fixture_attack_mult", 1.0),
                    "fixture_cs_mult": st.get("fixture_cs_mult", 1.0),
                    "fixture_cs_note": st.get("fixture_cs_note", ""),
                    "fixture_band": st.get("fixture_band", ""),
                    "fixture_match_kind": st.get("fixture_match_kind", ""),
                    "fixture_p_cs": st.get("fixture_p_cs"),
                    "fixture_lambda_for": st.get("fixture_lambda_for"),
                    "fixture_lambda_against": st.get("fixture_lambda_against"),
                    "table_pos": st.get("table_pos"),
                    "opp_table_pos": st.get("opp_table_pos"),
                    "table_n": st.get("table_n"),
                    "team_gf_pg": st.get("team_gf_pg"),
                    "team_ga_pg": st.get("team_ga_pg"),
                    "opp_gf_pg": st.get("opp_gf_pg"),
                    "opp_ga_pg": st.get("opp_ga_pg"),
                    "odds_favorite": st.get("odds_favorite"),
                    "odds_p_win": st.get("odds_p_win"),
                    "odds_p_over_25": st.get("odds_p_over_25"),
                    "odds_p_btts": st.get("odds_p_btts"),
                    "odds_p_first": st.get("odds_p_first"),
                    "odds_corner_line": st.get("odds_corner_line"),
                    "odds_expected_corners": st.get("odds_expected_corners"),
                    "odds_gs_override": st.get("odds_gs_override"),
                    "odds_source": st.get("odds_source"),
                    "pts_week0": st.get("pts_week0"),
                    "pts_week1": st.get("pts_week1"),
                    "pts_week2": st.get("pts_week2"),
                    "recency_mult": st.get("recency_mult", 1.0),
                }
            )
        else:
            rows.append(
                {
                    **base,
                    "stats_player": None,
                    "projected_pts": 0.0,
                    "match_score": score,
                    "reason": "Süper Lig istatistiği yok — dış lig aranacak",
                    "int_p90": 0,
                    "tkl_p90": 0,
                    "form_pts": 0,
                    "base_pts": 0,
                    "min_per_app": 0,
                    "gls_pa": 0,
                    "ast_pa": 0,
                    "xg_pa": 0,
                    "xa_pa": 0,
                    "form_apps": 0,
                    "base_apps": 0,
                    "current_apps": 0,
                    "current_minutes": 0,
                    "prev_apps": 0,
                    "prev_minutes": 0,
                    "established_sl_apps": 0,
                    "data_src": "",
                    "base_src": "",
                    "team_cs_base": None,
                    "cs_raw": None,
                    "cs_after_fixture": None,
                    "saves_contrib": 0,
                    "saves_pa": 0,
                    "prior_saves_pa": 0,
                    "current_saves_pa": 0,
                    "w_saves_current": 0,
                    "share_60": 0,
                    "fixture_opponent": "",
                    "fixture_home": None,
                    "fixture_attack_mult": 1.0,
                    "fixture_cs_mult": 1.0,
                    "fixture_cs_note": "",
                    "fixture_band": "",
                    "fixture_match_kind": "",
                    "fixture_p_cs": None,
                    "fixture_lambda_for": None,
                    "fixture_lambda_against": None,
                    "table_pos": None,
                    "opp_table_pos": None,
                    "table_n": None,
                    "team_gf_pg": None,
                    "team_ga_pg": None,
                    "opp_gf_pg": None,
                    "opp_ga_pg": None,
                    "pts_week0": None,
                    "pts_week1": None,
                    "pts_week2": None,
                    "recency_mult": 1.0,
                }
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        out["ppm"] = out.apply(
            lambda r: (float(r["projected_pts"]) / float(r["price_m"]))
            if float(r["price_m"]) > 0
            else 0.0,
            axis=1,
        )
    return out

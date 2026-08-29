"""Model özelliklerini Transfermarkt üretiminden üretir."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import LEAGUE_TIER, MIN_VALUE_EUR

NUM_COLS = [
    "age",
    "age_sq",
    "height_in_cm",
    "minutes_365",
    "minutes_2y",
    "apps_365",
    "apps_2y",
    "goals_2y",
    "assists_2y",
    "goals_p90",
    "assists_p90",
    "contrib_p90",
    "yellow_p90",
    "red_2y",
    "intl_caps",
    "intl_goals",
    "club_mv_log",
    "league_median_log",
    "tier",
    "contract_years",
    "is_gk",
]

CAT_COLS = ["position", "sub_position", "league_id", "foot", "nation_group"]


def _age_from_birth(series: pd.Series) -> pd.Series:
    birth = pd.to_datetime(series, errors="coerce", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    return (now - birth).dt.days / 365.25


def _contract_years(series: pd.Series) -> pd.Series:
    end = pd.to_datetime(series, errors="coerce", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    years = (end - now).dt.days / 365.25
    return years.clip(lower=0, upper=8).fillna(1.5)


def prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    if "age" not in frame.columns or frame["age"].isna().all():
        if "date_of_birth" in frame.columns:
            frame["age"] = _age_from_birth(frame["date_of_birth"])
        else:
            frame["age"] = np.nan
    frame["age"] = pd.to_numeric(frame["age"], errors="coerce")
    frame["age_sq"] = frame["age"] ** 2
    frame["height_in_cm"] = pd.to_numeric(frame.get("height_in_cm"), errors="coerce")
    minutes_2y = pd.to_numeric(frame.get("minutes_2y"), errors="coerce").fillna(0).clip(lower=0)
    minutes_365 = pd.to_numeric(frame.get("minutes_365"), errors="coerce").fillna(0).clip(lower=0)
    frame["minutes_2y"] = minutes_2y
    frame["minutes_365"] = minutes_365
    frame["apps_2y"] = pd.to_numeric(frame.get("apps_2y"), errors="coerce").fillna(0)
    frame["apps_365"] = pd.to_numeric(frame.get("apps_365"), errors="coerce").fillna(0)
    frame["goals_2y"] = pd.to_numeric(frame.get("goals_2y"), errors="coerce").fillna(0)
    frame["assists_2y"] = pd.to_numeric(frame.get("assists_2y"), errors="coerce").fillna(0)
    frame["yellow_2y"] = pd.to_numeric(frame.get("yellow_2y"), errors="coerce").fillna(0)
    frame["red_2y"] = pd.to_numeric(frame.get("red_2y"), errors="coerce").fillna(0)
    safe_min = minutes_2y.clip(lower=1)
    frame["goals_p90"] = frame["goals_2y"] * 90.0 / safe_min
    frame["assists_p90"] = frame["assists_2y"] * 90.0 / safe_min
    frame["contrib_p90"] = (frame["goals_2y"] + frame["assists_2y"]) * 90.0 / safe_min
    frame.loc[minutes_2y < 180, ["goals_p90", "assists_p90", "contrib_p90"]] *= 0.45
    frame["yellow_p90"] = frame["yellow_2y"] * 90.0 / safe_min
    intl_caps = frame.get("international_caps")
    if intl_caps is None:
        frame["intl_caps"] = 0.0
    else:
        frame["intl_caps"] = pd.to_numeric(intl_caps, errors="coerce").fillna(0)
    intl_goals = frame.get("international_goals")
    if intl_goals is None:
        frame["intl_goals"] = 0.0
    else:
        frame["intl_goals"] = pd.to_numeric(intl_goals, errors="coerce").fillna(0)
    league = frame.get("current_club_domestic_competition_id")
    frame["league_id"] = league.astype("string").fillna("UNK") if league is not None else "UNK"
    frame["tier"] = frame["league_id"].map(lambda x: LEAGUE_TIER.get(str(x), 4)).astype(float)
    club_mv = pd.to_numeric(frame.get("club_total_market_value"), errors="coerce")
    if club_mv is None:
        club_mv = pd.Series(np.nan, index=frame.index)
    league_club = club_mv.groupby(frame["league_id"]).transform("median")
    club_mv = club_mv.fillna(league_club)
    frame["club_mv_log"] = np.log1p(club_mv.fillna(0))
    league_med = (
        pd.to_numeric(frame.get("market_value_in_eur"), errors="coerce")
        .groupby(frame["league_id"])
        .transform("median")
    )
    frame["league_median_log"] = np.log1p(league_med.fillna(league_med.median() if league_med.notna().any() else 1_000_000))
    if "contract_expiration_date" in frame.columns:
        frame["contract_years"] = _contract_years(frame["contract_expiration_date"])
    else:
        frame["contract_years"] = 1.5
    pos = frame.get("position")
    frame["position"] = pos.astype("string").fillna("Unknown") if pos is not None else "Unknown"
    frame["is_gk"] = (frame["position"] == "Goalkeeper").astype(float)
    frame.loc[frame["is_gk"] == 1, ["goals_p90", "assists_p90", "contrib_p90"]] = 0.0
    sub = frame.get("sub_position")
    frame["sub_position"] = sub.astype("string").fillna(frame["position"]) if sub is not None else frame["position"]
    foot = frame.get("foot")
    frame["foot"] = foot.astype("string").fillna("unknown") if foot is not None else "unknown"
    nation = frame.get("country_of_citizenship")
    if nation is None:
        frame["nation_group"] = "Other"
    else:
        counts = nation.astype("string").value_counts()
        keep = set(counts[counts >= 80].index)
        frame["nation_group"] = nation.astype("string").map(lambda x: x if x in keep else "Other").fillna("Other")
    current = pd.to_numeric(frame.get("market_value_in_eur"), errors="coerce")
    peak = pd.to_numeric(frame.get("highest_market_value_in_eur"), errors="coerce")
    frame["peak_log"] = np.log1p(peak.fillna(current).fillna(0))
    frame["market_value_in_eur"] = current
    return frame


def model_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for col in NUM_COLS:
        out[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in CAT_COLS:
        out[col] = frame[col].astype("string").fillna("unknown").astype("category")
    med = out[NUM_COLS].median(numeric_only=True)
    out[NUM_COLS] = out[NUM_COLS].fillna(med)
    return out


def train_mask(frame: pd.DataFrame) -> pd.Series:
    value = pd.to_numeric(frame.get("market_value_in_eur"), errors="coerce")
    last = pd.to_numeric(frame.get("last_season"), errors="coerce")
    minutes = pd.to_numeric(frame.get("minutes_2y"), errors="coerce").fillna(0)
    age = pd.to_numeric(frame.get("age"), errors="coerce")
    has_sample = minutes.ge(250) | minutes.eq(0)
    return (
        value.ge(MIN_VALUE_EUR)
        & last.ge(2022)
        & has_sample
        & age.between(16, 42)
        & frame["position"].ne("Unknown")
    )

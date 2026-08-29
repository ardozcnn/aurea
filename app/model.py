"""sklearn ile adil değer, aralık, benzer oyuncu ve sapma motoru."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, IsolationForest
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error, median_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.config import ENGINE_PATH, META_PATH, MODELS_DIR
from app.features import CAT_COLS, NUM_COLS, model_matrix, prepare_frame, train_mask
from app import status as st


@dataclass
class Engine:
    gbm: HistGradientBoostingRegressor
    gbm_lo: HistGradientBoostingRegressor
    gbm_hi: HistGradientBoostingRegressor
    calibrator: IsotonicRegression
    isolator: IsolationForest
    nn: Pipeline
    feature_medians: dict
    cat_levels: dict
    train_index: np.ndarray
    player_ids: np.ndarray
    nn_ids: np.ndarray
    meta: dict


def _safe_expm1(log_value: np.ndarray) -> np.ndarray:
    return np.expm1(np.clip(log_value, 0, 20))


def confidence_score(row: pd.Series, has_live: bool = False) -> float:
    minutes = float(row.get("minutes_365") or 0)
    apps = float(row.get("apps_365") or 0)
    last = row.get("last_match")
    recency = 0.75
    if pd.notna(last):
        delta = (pd.Timestamp.now(tz="UTC") - pd.to_datetime(last, utc=True)).days
        recency = float(np.clip(1.0 - delta / 420.0, 0.28, 1.0))
    body = 0.22 + 0.50 * min(minutes / 2400.0, 1.0) + 0.18 * min(apps / 28.0, 1.0) + 0.10 * recency
    if has_live:
        body += 0.06
    return float(np.clip(body, 0.16, 0.88))


def signal_multiplier(
    *,
    age: float | None,
    minutes_365: float,
    minutes_2y: float = 0.0,
    contrib_p90: float = 0.0,
    yellow: float = 0.0,
    position: str | None = None,
    peak: float | None = None,
    tm: float | None = None,
    contract_years: float | None = None,
    sofa_rating: float | None = None,
    tm_step_pct: float | None = None,
    injury_days: int = 0,
) -> float:
    """GBM sonrası üretim, form ve sakatlık düzeltmesi. Güncel TM etiketini özellik olarak kullanmaz."""
    m = 1.0
    mins = float(minutes_365 or 0)
    mins2 = float(minutes_2y or 0)
    share = mins / max(mins2, 1.0)
    pos = str(position or "")
    if age is not None and 23 <= age <= 27 and mins >= 1800:
        m *= 1.03
    if age is not None and age <= 21 and mins < 400 and mins2 < 800:
        m *= 0.96
    if age is not None and age <= 22 and mins >= 800:
        m *= 1.07
    elif age is not None and age <= 24 and mins >= 1200:
        m *= 1.04
    if age is not None and 24 <= age <= 28 and mins >= 1400:
        m *= 1.02
    if age is not None and age >= 33:
        m *= 0.93
    if age is not None and age >= 36:
        m *= 0.88
    if mins >= 2200:
        m *= 1.025
    elif mins >= 1600 and (age or 25) <= 29:
        m *= 1.015
    if injury_days >= 45:
        m *= 0.90
    elif injury_days >= 20:
        m *= 0.95
    if share >= 0.62 and mins >= 1000:
        m *= 1.035
    elif share <= 0.28 and mins2 >= 1500 and mins < 400:
        m *= 0.94
    if pos in {"Attack", "Midfield"} and contrib_p90 >= 0.55 and mins >= 900:
        m *= 1.04
    if pos == "Attack" and contrib_p90 >= 0.50 and mins2 >= 1500 and age is not None and age <= 26:
        m *= 1.06
    if pos == "Attack" and contrib_p90 <= 0.15 and mins2 >= 1200:
        m *= 0.96
    if contract_years is not None and contract_years <= 0.7 and (age or 0) >= 28:
        m *= 0.965
    if contract_years is not None and contract_years >= 3.0 and (age or 99) <= 24 and mins >= 900:
        m *= 1.02
    if pos == "Defender" and yellow >= 14:
        m *= 0.97
    if peak and tm and peak >= 1_000_000 and tm < peak * 0.42 and (age or 0) >= 30:
        m *= 0.97
    if sofa_rating is not None:
        if sofa_rating >= 7.4:
            m *= 1.055
        elif sofa_rating >= 7.05:
            m *= 1.03
        elif sofa_rating <= 6.35:
            m *= 0.96
    if tm_step_pct is not None:
        if tm_step_pct >= 12:
            m *= 1.02
        elif tm_step_pct <= -12:
            m *= 0.98
    return float(np.clip(m, 0.80, 1.22))


def _clip_band(true: float, lo: float | None, hi: float | None) -> float:
    if lo is not None:
        true = max(true, float(lo) * 0.72)
    if hi is not None:
        true = min(true, float(hi) * 1.28)
    return float(true)


def blend_true_value(
    tm: float | None,
    fair: float | None,
    lo: float | None,
    hi: float | None,
    confidence: float,
    age: float | None,
    minutes_365: float,
    injury_days: int = 0,
    minutes_2y: float = 0.0,
    contrib_p90: float = 0.0,
    yellow: float = 0.0,
    position: str | None = None,
    peak: float | None = None,
    contract_years: float | None = None,
    sofa_rating: float | None = None,
    tm_step_pct: float | None = None,
) -> float | None:
    if tm is None and fair is None:
        return None
    if fair is None:
        return float(tm) if tm is not None else None
    if tm is None:
        base = float(fair)
    else:
        base = confidence * float(fair) + (1.0 - confidence) * float(tm)
    true = base * signal_multiplier(
        age=age,
        minutes_365=minutes_365,
        minutes_2y=minutes_2y,
        contrib_p90=contrib_p90,
        yellow=yellow,
        position=position,
        peak=peak,
        tm=tm,
        contract_years=contract_years,
        sofa_rating=sofa_rating,
        tm_step_pct=tm_step_pct,
        injury_days=injury_days,
    )
    return _clip_band(true, lo, hi)


def train_engine(universe: pd.DataFrame) -> Engine:
    st.set_state(phase="train", message="Özellikler hazırlanıyor.", progress=0.95)
    prepared = prepare_frame(universe)
    mask = train_mask(prepared)
    sample = prepared.loc[mask].copy()
    if len(sample) < 800:
        raise RuntimeError("Model için yeterli oyuncu yok. Veri ambarını yenileyin.")
    X = model_matrix(sample)
    y = np.log1p(pd.to_numeric(sample["market_value_in_eur"], errors="coerce").clip(lower=1))
    ids = pd.to_numeric(sample["player_id"], errors="coerce").to_numpy()
    X_train, X_hold, y_train, y_hold, id_train, id_hold = train_test_split(
        X, y, ids, test_size=0.15, random_state=11
    )
    common = dict(
        max_depth=5,
        learning_rate=0.05,
        max_iter=220,
        min_samples_leaf=48,
        l2_regularization=1.1,
        early_stopping=True,
        validation_fraction=0.12,
        random_state=11,
        categorical_features="from_dtype",
    )
    st.set_state(message="HistGradientBoosting ile Aurea değeri öğreniliyor.", progress=0.96)
    gbm = HistGradientBoostingRegressor(loss="squared_error", **common)
    gbm_lo = HistGradientBoostingRegressor(loss="quantile", quantile=0.15, **common)
    gbm_hi = HistGradientBoostingRegressor(loss="quantile", quantile=0.85, **common)
    gbm.fit(X_train, y_train)
    gbm_lo.fit(X_train, y_train)
    gbm_hi.fit(X_train, y_train)
    hold_pred = gbm.predict(X_hold)
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(hold_pred, y_hold.to_numpy() if hasattr(y_hold, "to_numpy") else np.asarray(y_hold))
    y_hat = calibrator.predict(hold_pred)
    mae = float(mean_absolute_error(_safe_expm1(y_hold), _safe_expm1(y_hat)))
    mdae = float(median_absolute_error(_safe_expm1(y_hold), _safe_expm1(y_hat)))
    mape = float(
        np.median(
            np.abs(_safe_expm1(y_hat) - _safe_expm1(y_hold)) / np.clip(_safe_expm1(y_hold), 1, None)
        )
    )
    residuals = y_train.to_numpy() - calibrator.predict(gbm.predict(X_train))
    isolator = IsolationForest(n_estimators=240, contamination=0.06, random_state=11)
    isolator.fit(residuals.reshape(-1, 1))
    nn_num = ["age", "minutes_2y", "goals_p90", "assists_p90", "contrib_p90", "tier", "is_gk", "intl_caps", "peak_log"]
    nn_pipe = Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        ("num", StandardScaler(), nn_num),
                        ("cat", OneHotEncoder(handle_unknown="ignore"), ["position"]),
                    ]
                ),
            ),
            ("nn", NearestNeighbors(n_neighbors=10, metric="euclidean")),
        ]
    )
    nn_frame = sample[nn_num + ["position"]].copy()
    nn_pipe.fit(nn_frame)
    st.set_state(message="Özellik önemleri ölçülüyor.", progress=0.98)
    probe = X_hold.sample(n=min(700, len(X_hold)), random_state=3)
    probe_y = y_hold.loc[probe.index]
    importance = permutation_importance(
        gbm, probe, probe_y, n_repeats=2, random_state=3, n_jobs=1
    )
    names = list(X.columns)
    ranked = sorted(
        zip(names, importance.importances_mean.tolist()),
        key=lambda kv: kv[1],
        reverse=True,
    )
    medians = {col: float(X[col].median()) for col in NUM_COLS}
    cat_levels = {col: [str(v) for v in X[col].cat.categories] for col in CAT_COLS}
    meta = {
        "n_train": int(len(X_train)),
        "n_hold": int(len(X_hold)),
        "mae_eur": mae,
        "median_ae_eur": mdae,
        "median_ape": mape,
        "importances": [{"feature": k, "importance": v} for k, v in ranked[:16]],
        "features": names,
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    engine = Engine(
        gbm=gbm,
        gbm_lo=gbm_lo,
        gbm_hi=gbm_hi,
        calibrator=calibrator,
        isolator=isolator,
        nn=nn_pipe,
        feature_medians=medians,
        cat_levels=cat_levels,
        train_index=X.index.to_numpy(),
        player_ids=ids,
        nn_ids=ids,
        meta=meta,
    )
    joblib.dump(engine, ENGINE_PATH)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return engine


def load_engine() -> Engine | None:
    if not ENGINE_PATH.exists():
        return None
    return joblib.load(ENGINE_PATH)


def _align_categories(engine: Engine, X: pd.DataFrame) -> pd.DataFrame:
    aligned = X.copy()
    for col, levels in (engine.cat_levels or {}).items():
        aligned[col] = pd.Categorical(aligned[col].astype("string").fillna("unknown"), categories=levels)
    return aligned


def _predict_log(engine: Engine, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = _align_categories(engine, X)
    mid = engine.calibrator.predict(engine.gbm.predict(X))
    lo = engine.gbm_lo.predict(X)
    hi = engine.gbm_hi.predict(X)
    lo = np.minimum(lo, mid)
    hi = np.maximum(hi, mid)
    return mid, lo, hi


def score_universe(universe: pd.DataFrame, engine: Engine) -> pd.DataFrame:
    prepared = prepare_frame(universe)
    X = model_matrix(prepared)
    mid, lo, hi = _predict_log(engine, X)
    fair = _safe_expm1(mid)
    band_lo = _safe_expm1(lo)
    band_hi = _safe_expm1(hi)
    tm = pd.to_numeric(prepared["market_value_in_eur"], errors="coerce")
    out = prepared.copy()
    out["fair_value"] = fair
    out["value_lo"] = band_lo
    out["value_hi"] = band_hi
    minutes = pd.to_numeric(out["minutes_365"], errors="coerce").fillna(0)
    apps = pd.to_numeric(out["apps_365"], errors="coerce").fillna(0)
    age = pd.to_numeric(out["age"], errors="coerce")
    recency = pd.Series(0.75, index=out.index)
    if "last_match" in out.columns:
        last = pd.to_datetime(out["last_match"], errors="coerce", utc=True)
        delta = (pd.Timestamp.now(tz="UTC") - last).dt.days
        recency = (1.0 - delta / 420.0).clip(0.28, 1.0).fillna(0.75)
    conf = (0.22 + 0.50 * (minutes.clip(upper=2400) / 2400.0) + 0.18 * (apps.clip(upper=28) / 28.0) + 0.10 * recency).clip(0.16, 0.88)
    out["confidence"] = conf
    tm_f = tm.astype(float)
    fair_s = pd.Series(fair, index=out.index)
    lo_s = pd.Series(band_lo, index=out.index)
    hi_s = pd.Series(band_hi, index=out.index)
    true = conf * fair_s + (1.0 - conf) * tm_f.where(tm_f.notna(), fair_s)
    mins2 = pd.to_numeric(out.get("minutes_2y"), errors="coerce").fillna(0)
    contrib = pd.to_numeric(out.get("contrib_p90"), errors="coerce").fillna(0)
    yellow = pd.to_numeric(out.get("yellow_2y"), errors="coerce").fillna(0)
    peak = pd.to_numeric(out.get("highest_market_value_in_eur"), errors="coerce")
    contract = pd.to_numeric(out.get("contract_years"), errors="coerce").fillna(1.5)
    pos = out.get("position")
    share = (minutes / mins2.clip(lower=1)).clip(0, 3)
    mult = pd.Series(1.0, index=out.index)
    young = age.le(22) & minutes.ge(800)
    mult = mult.where(~young, 1.07)
    young2 = age.between(22.0001, 24) & minutes.ge(1200)
    mult = mult.where(~young2, mult * 1.04)
    old = age.ge(33)
    mult = mult.where(~old, mult * 0.93)
    old2 = age.ge(36)
    mult = mult.where(~old2, mult * 0.88)
    hot = share.ge(0.62) & minutes.ge(1000)
    mult = mult.where(~hot, mult * 1.035)
    cold = share.le(0.28) & mins2.ge(1500) & minutes.lt(400)
    mult = mult.where(~cold, mult * 0.94)
    if pos is not None:
        att = pos.isin(["Attack", "Midfield"]) & contrib.ge(0.55) & minutes.ge(900)
        mult = mult.where(~att, mult * 1.04)
        dry = pos.eq("Attack") & contrib.le(0.15) & mins2.ge(1200)
        mult = mult.where(~dry, mult * 0.96)
        cards = pos.eq("Defender") & yellow.ge(14)
        mult = mult.where(~cards, mult * 0.97)
    bosman = contract.le(0.7) & age.ge(28)
    mult = mult.where(~bosman, mult * 0.965)
    decline = peak.ge(1_000_000) & tm_f.lt(peak * 0.42) & age.ge(30)
    mult = mult.where(~decline.fillna(False), mult * 0.97)
    true = (true * mult.clip(0.82, 1.18)).clip(lower=lo_s * 0.72, upper=hi_s * 1.28)
    out["true_value"] = true
    out["gap_pct"] = np.where((true > 0) & tm_f.gt(0), 100.0 * (tm_f - true) / true, np.nan)
    resid = np.log1p(tm_f.fillna(0).clip(lower=0)) - mid
    out["anomaly"] = 1
    valid = tm_f.notna() & tm_f.gt(0)
    if valid.any():
        flags = engine.isolator.predict(resid[valid].to_numpy().reshape(-1, 1))
        out.loc[valid, "anomaly"] = flags
    return out


def similar_players(engine: Engine, universe: pd.DataFrame, player_id: int, k: int = 8) -> list[dict]:
    from app.slugs import club_display, is_free_agent

    prepared = prepare_frame(universe)
    row = prepared.loc[prepared["player_id"] == player_id]
    if row.empty:
        return []
    seed = row.iloc[0]
    q_pos = str(seed.get("position") or "")
    q_sub = str(seed.get("sub_position") or "")
    q_league = str(seed.get("league_id") or "")
    q_age = float(seed.get("age") or 0) if pd.notna(seed.get("age")) else 0.0
    q_min = float(seed.get("minutes_2y") or 0)
    q_contrib = float(seed.get("contrib_p90") or 0)
    nn_num = ["age", "minutes_2y", "goals_p90", "assists_p90", "contrib_p90", "tier", "is_gk", "intl_caps", "peak_log"]
    query = row[nn_num + ["position"]]
    n_ask = min(max(k + 36, 20), len(engine.nn_ids))
    dist, idx = engine.nn.named_steps["nn"].kneighbors(
        engine.nn.named_steps["prep"].transform(query), n_neighbors=n_ask
    )
    ranked = []
    seen = {int(player_id)}
    for d, j in zip(dist[0], idx[0]):
        pid = int(engine.nn_ids[j])
        if pid in seen:
            continue
        seen.add(pid)
        hit = prepared.loc[prepared["player_id"] == pid]
        if hit.empty:
            continue
        rec = hit.iloc[0]
        club = str(rec.get("current_club_name") or "")
        if is_free_agent(club):
            continue
        pos = str(rec.get("position") or "")
        sub = str(rec.get("sub_position") or "")
        league = str(rec.get("league_id") or "")
        age = float(rec.get("age") or 0) if pd.notna(rec.get("age")) else 0.0
        mins = float(rec.get("minutes_2y") or 0)
        contrib = float(rec.get("contrib_p90") or 0)
        age_ok = (not q_age) or (not age) or abs(age - q_age) <= 6
        min_floor = max(500.0, q_min * 0.35) if q_min >= 900 else 240.0
        if q_min >= 1800:
            min_floor = max(min_floor, 900.0)
        min_ok = mins >= min_floor
        if q_contrib >= 0.28 and q_pos in {"Attack", "Midfield"} and mins >= 800:
            if contrib < q_contrib * 0.35 and pos == q_pos:
                continue
        if not age_ok or not min_ok:
            continue
        same_pos = 0 if q_pos and pos == q_pos else 1
        same_sub = 0 if q_sub and sub == q_sub else 1
        same_league = 0 if q_league and league == q_league else 1
        ranked.append(
            (
                same_pos,
                same_sub,
                same_league,
                float(d),
                {
                    "player_id": pid,
                    "name": rec.get("name"),
                    "image_url": rec.get("image_url"),
                    "club": club_display(club),
                    "position": rec.get("position"),
                    "sub_position": rec.get("sub_position"),
                    "league_id": league,
                    "age": None if pd.isna(rec.get("age")) else round(float(rec.get("age")), 1),
                    "market_value_in_eur": None if pd.isna(rec.get("market_value_in_eur")) else float(rec.get("market_value_in_eur")),
                    "true_value": None if pd.isna(rec.get("true_value")) else float(rec.get("true_value")) if "true_value" in rec else None,
                    "distance": float(d),
                },
            )
        )
    same = [item for item in ranked if item[0] == 0]
    pool = same if len(same) >= max(4, k // 2) else ranked
    pool.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [item[4] for item in pool[:k]]


def rescore_row(engine: Engine, universe: pd.DataFrame, player_id: int, overrides: dict[str, Any] | None = None) -> dict:
    prepared = prepare_frame(universe)
    idx = prepared.index[prepared["player_id"] == player_id]
    if len(idx) == 0:
        raise KeyError(player_id)
    i = idx[0]
    if overrides:
        for key, value in overrides.items():
            prepared.at[i, key] = value
        prepared = prepare_frame(prepared)
    X = model_matrix(prepared.loc[[i]])
    mid, lo, hi = _predict_log(engine, X)
    fair = float(_safe_expm1(mid)[0])
    band_lo = float(_safe_expm1(lo)[0])
    band_hi = float(_safe_expm1(hi)[0])
    row = prepared.loc[i]
    tm = row.get("market_value_in_eur")
    tm_f = None if pd.isna(tm) else float(tm)
    has_live = bool(overrides)
    conf = confidence_score(row, has_live=has_live)
    true = blend_true_value(
        tm_f,
        fair,
        band_lo,
        band_hi,
        conf,
        None if pd.isna(row.get("age")) else float(row.get("age")),
        float(row.get("minutes_365") or 0),
        int((overrides or {}).get("injury_days") or 0),
        minutes_2y=float(row.get("minutes_2y") or 0),
        contrib_p90=float(row.get("contrib_p90") or 0),
        yellow=float(row.get("yellow_2y") or 0),
        position=None if pd.isna(row.get("position")) else str(row.get("position")),
        peak=None if pd.isna(row.get("highest_market_value_in_eur")) else float(row.get("highest_market_value_in_eur")),
        contract_years=None if pd.isna(row.get("contract_years")) else float(row.get("contract_years")),
        sofa_rating=(overrides or {}).get("sofa_rating"),
        tm_step_pct=(overrides or {}).get("tm_step_pct"),
    )
    gap = None
    if true and tm_f:
        gap = 100.0 * (tm_f - true) / true
    return {
        "fair_value": fair,
        "value_lo": band_lo,
        "value_hi": band_hi,
        "true_value": true,
        "confidence": conf,
        "gap_pct": gap,
        "tm_value": tm_f,
    }

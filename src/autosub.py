"""TFF Fantezi Lig otomatik yedek girişi ve beklenen puan hesabı."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import AUTOSUB_MONTE_CARLO_DRAWS


def is_legal_xi(positions: list[str]) -> bool:
    """Resmi minimum: 1 kaleci, 3 defans, 1 forvet; toplam 11."""
    if len(positions) != 11:
        return False
    counts = {"GK": 0, "DF": 0, "MF": 0, "FW": 0}
    for pos in positions:
        key = str(pos or "").upper()
        if key not in counts:
            return False
        counts[key] += 1
    return counts["GK"] == 1 and counts["DF"] >= 3 and counts["FW"] >= 1


def _row_points(row: pd.Series) -> float:
    if "pts_if_plays" in row.index and pd.notna(row.get("pts_if_plays")):
        return float(row["pts_if_plays"])
    return float(row.get("projected_pts") or 0.0)


def _row_play_prob(row: pd.Series) -> float:
    if "play_probability" in row.index and pd.notna(row.get("play_probability")):
        return float(max(0.0, min(1.0, row["play_probability"])))
    return 0.85


def _bench_value(row: pd.Series) -> float:
    return _row_points(row) * _row_play_prob(row)


def _pick_bench_replacement(
    xi_work: pd.DataFrame,
    bench_work: pd.DataFrame,
    xi_pos: int,
    xi_row: pd.Series,
    used_bench: set[int],
) -> tuple[int, pd.Series] | None:
    """Yasal yedekler arasından aynı mevki öncelikli en yüksek EV'yi seç."""
    out_pos = str(xi_row.get("position") or "").upper()
    candidates: list[tuple[float, float, int, pd.Series]] = []

    for bn_pos, bn_row in bench_work.iterrows():
        if bn_pos in used_bench:
            continue
        in_pos = str(bn_row.get("position") or "").upper()
        if out_pos == "GK" and in_pos != "GK":
            continue
        if out_pos != "GK" and in_pos == "GK":
            continue
        trial_positions = [
            in_pos if idx == xi_pos else str(row.get("position") or "").upper()
            for idx, row in xi_work.iterrows()
        ]
        if not is_legal_xi(trial_positions):
            continue
        same_pos = 1.0 if in_pos == out_pos else 0.0
        candidates.append((same_pos, _bench_value(bn_row), bn_pos, bn_row))

    if not candidates:
        return None
    _, _, bn_pos, bn_row = max(candidates, key=lambda item: (item[0], item[1]))
    return bn_pos, bn_row


def apply_autosub(
    xi: pd.DataFrame,
    bench: pd.DataFrame,
    played: dict[Any, bool] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    TFF sırası: yedek kaleci, ardından saha yedeği 1-2-3.
    Oynamayan yedek atlanır; sıradaki oynayan ve yasal isim girer.
    Formasyon bozulacaksa o isim girmez, sonraki sıraya bakılır.
    Birden fazla ilk-11 boşluğu varsa sıra 1 ve 2 ayrı ayrı girebilir;
    3. sıra, öndeki oynayan yedeğin önüne geçemez.
    """
    if xi is None or xi.empty:
        return pd.DataFrame(), []

    xi_work = xi.reset_index(drop=True).copy()
    bench_work = (
        bench.reset_index(drop=True).copy()
        if isinstance(bench, pd.DataFrame)
        else pd.DataFrame()
    )
    if not bench_work.empty and "bench_rank" in bench_work.columns:
        bench_work = bench_work.sort_values("bench_rank", kind="mergesort")
        bench_work = bench_work.reset_index(drop=True)
    played = played or {}

    def did_play(row: pd.Series) -> bool:
        key = row.get("player")
        if key in played:
            return bool(played[key])
        return True

    events: list[dict[str, Any]] = []
    filled = {
        idx for idx, row in xi_work.iterrows() if did_play(row)
    }

    for _, bn_row in bench_work.iterrows():
        if not did_play(bn_row):
            continue
        in_pos = str(bn_row.get("position") or "").upper()
        for xi_pos, xi_row in xi_work.iterrows():
            if xi_pos in filled:
                continue
            out_pos = str(xi_row.get("position") or "").upper()
            if out_pos == "GK" and in_pos != "GK":
                continue
            if out_pos != "GK" and in_pos == "GK":
                continue
            trial_positions = []
            for idx, row in xi_work.iterrows():
                if idx == xi_pos:
                    trial_positions.append(in_pos)
                elif idx in filled:
                    trial_positions.append(str(row.get("position") or "").upper())
                else:
                    trial_positions.append(str(row.get("position") or "").upper())
            if not is_legal_xi(trial_positions):
                continue
            xi_work.loc[xi_pos] = bn_row
            filled.add(xi_pos)
            events.append(
                {
                    "out": str(xi_row.get("display_name") or xi_row.get("player") or ""),
                    "in": str(bn_row.get("display_name") or bn_row.get("player") or ""),
                    "out_pos": out_pos,
                    "in_pos": in_pos,
                }
            )
            break

    active = xi_work.loc[sorted(filled)].copy() if filled else pd.DataFrame()
    return active, events


def score_final_xi(final_xi: pd.DataFrame) -> float:
    if final_xi is None or final_xi.empty:
        return 0.0
    return float(sum(_row_points(row) for _, row in final_xi.iterrows()))


def _armband_names(xi: pd.DataFrame) -> tuple[str, str]:
    if xi is None or xi.empty or "player" not in xi.columns:
        return "", ""
    work = xi.reset_index(drop=True).copy()
    work["_v"] = work.apply(lambda row: _row_points(row) * _row_play_prob(row), axis=1)
    work = work.sort_values("_v", ascending=False)
    cap = str(work.iloc[0].get("player") or "")
    vice = ""
    if len(work) > 1:
        vice = str(work.iloc[1].get("player") or "")
        if vice == cap:
            vice = ""
    return cap, vice


def _named_points(frame: pd.DataFrame, name: str) -> float:
    if not name or frame is None or frame.empty or "player" not in frame.columns:
        return 0.0
    hit = frame[frame["player"].astype(str) == str(name)]
    if hit.empty:
        return 0.0
    return _row_points(hit.iloc[0])


def expected_squad_points(
    xi: pd.DataFrame,
    bench: pd.DataFrame,
    *,
    draws: int = AUTOSUB_MONTE_CARLO_DRAWS,
    seed: int = 20260817,
    full_bench: bool = False,
) -> dict[str, Any]:
    """Oynama olasılıklarıyla otomatik yedek beklenen puanı."""
    if xi is None or xi.empty:
        return {
            "expected_pts": 0.0,
            "xi_expected": 0.0,
            "bench_expected": 0.0,
            "captain_player": "",
            "captain_pts": 0.0,
            "vice_captain_player": "",
        }

    xi_df = xi.reset_index(drop=True).copy()
    bench_df = (
        bench.reset_index(drop=True).copy()
        if isinstance(bench, pd.DataFrame)
        else pd.DataFrame()
    )
    cap_name, vice_name = _armband_names(xi_df)
    rng = np.random.default_rng(seed)
    players = []
    for source, frame in (("xi", xi_df), ("bench", bench_df)):
        for idx, row in frame.iterrows():
            players.append(
                {
                    "source": source,
                    "idx": idx,
                    "player": row.get("player"),
                    "prob": _row_play_prob(row),
                    "pts": _row_points(row),
                }
            )

    totals = []
    xi_only = []
    bench_contrib = []
    for _ in range(max(1, int(draws))):
        played = {
            item["player"]: bool(rng.random() < item["prob"])
            for item in players
            if item["player"] is not None
        }
        final_xi, _events = apply_autosub(xi_df, bench_df, played=played)
        score = score_final_xi(final_xi)
        if played.get(cap_name, False):
            score += _named_points(xi_df, cap_name)
        elif vice_name and played.get(vice_name, False):
            score += _named_points(xi_df, vice_name)
        if full_bench and not bench_df.empty:
            used = set(final_xi["player"].tolist()) if "player" in final_xi.columns else set()
            for _, row in bench_df.iterrows():
                name = row.get("player")
                if name in used:
                    continue
                if played.get(name, False):
                    score += _row_points(row)
        base_xi = score_final_xi(
            xi_df[[played.get(row.get("player"), False) for _, row in xi_df.iterrows()]]
        )
        totals.append(score)
        xi_only.append(base_xi)
        bench_contrib.append(score - base_xi)

    cap_pts = _named_points(xi_df, cap_name)
    cap_play = 0.85
    if cap_name:
        cap_hit = xi_df[xi_df["player"].astype(str) == str(cap_name)]
        if not cap_hit.empty:
            cap_play = _row_play_prob(cap_hit.iloc[0])
    expected = float(np.mean(totals)) if totals else 0.0
    return {
        "expected_pts": round(expected, 3),
        "xi_expected": round(float(np.mean(xi_only)), 3) if xi_only else 0.0,
        "bench_expected": round(float(np.mean(bench_contrib)), 3) if bench_contrib else 0.0,
        "captain_player": cap_name,
        "captain_pts": round(cap_pts * cap_play, 3),
        "vice_captain_player": vice_name,
        "draws": int(draws),
    }


def order_bench_for_autosub(bench: pd.DataFrame) -> pd.DataFrame:
    """
    TFF yedek sırası: kaleci yedeği önde, ardından saha 1-2-3.
    Saha sırası oyuna girme potansiyeline göredir.
    """
    if bench is None or bench.empty:
        return pd.DataFrame() if bench is None else bench.copy()
    out = bench.copy()
    is_gk = out["position"].astype(str).str.upper().eq("GK")
    out["_gk"] = is_gk.astype(int)
    out["_enter"] = out.apply(_row_play_prob, axis=1)
    out["_score"] = out.apply(_bench_value, axis=1)
    gk = out[is_gk].copy()
    field = out[~is_gk].copy()
    field = field.sort_values(
        ["_enter", "_score"],
        ascending=[False, False],
    )
    ordered = pd.concat([gk, field], ignore_index=True) if not gk.empty else field
    if ordered.empty:
        ordered = out
    ordered = ordered.drop(columns=["_gk", "_enter", "_score"], errors="ignore")
    ordered = ordered.reset_index(drop=True)
    ranks: list[int] = []
    field_n = 0
    for _, row in ordered.iterrows():
        if str(row.get("position") or "").upper() == "GK":
            ranks.append(0)
        else:
            field_n += 1
            ranks.append(field_n)
    ordered["bench_rank"] = ranks
    return ordered

"""Tamsayı programlama: en iyi diziliş + ilk 11 + yedekler."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pulp

from .autosub import expected_squad_points, order_bench_for_autosub
from .config import AUTOSUB_MONTE_CARLO_DRAWS, BUDGET_M, FORMATIONS, MAX_PER_CLUB, SQUAD
from .names import club_key, normalize_name
from .team_model import _DERBY_CLUBS, _TOP_CLUBS


def _bench_of(
    xi: dict[str, int],
    squad: dict[str, int] | None = None,
) -> dict[str, int]:
    squad = squad or SQUAD
    return {pos: squad[pos] - xi[pos] for pos in squad}


def _this_week_value(row: pd.Series) -> float:
    pts = float(row.get("pts_if_plays") or row.get("projected_pts") or 0.0)
    play = float(row.get("play_probability") or 0.85)
    return pts * max(0.05, min(1.0, play))


def _selection_value(row: pd.Series) -> float:
    """ILP kadro seçimi: 3 haftalık ufuk varsa onu, yoksa bu haftayı kullan."""
    sel = row.get("selection_pts") if hasattr(row, "get") else None
    if sel is not None and pd.notna(sel):
        return float(sel)
    return _this_week_value(row)


def _armband_payload(row: pd.Series) -> dict[str, Any]:
    return {
        "player": row["player"],
        "display_name": str(row.get("display_name") or row["player"]),
        "projected_pts": float(row.get("projected_pts") or 0.0),
        "pts_if_plays": float(
            row.get("pts_if_plays") or row.get("projected_pts") or 0.0
        ),
        "play_probability": float(row.get("play_probability") or 0.85),
        "team": row["team"],
        "position": row["position"],
        "price_m": float(row["price_m"]),
        "reason": str(row.get("reason") or ""),
    }


def _row_team_key(df: pd.DataFrame, i: Any) -> str:
    if "team_key" in df.columns:
        return str(df.loc[i, "team_key"] or "")
    return club_key(str(df.loc[i, "team"] or ""))


def _row_fold(row: pd.Series) -> str:
    bits = [str(row.get("player") or "")]
    if "display_name" in getattr(row, "index", []):
        bits.append(str(row.get("display_name") or ""))
    return normalize_name(" ".join(bits))


def _is_osimhen_row(row: pd.Series) -> bool:
    return "osimhen" in _row_fold(row)


def pick_armbands(xi_df: pd.DataFrame) -> tuple[pd.Series, pd.Series | None]:
    """Kaptan: XI'de Osimhen varsa kilitlenir. Yedek kaptan başka bir isimdir."""
    ranked = xi_df.copy()
    ranked["_v"] = ranked.apply(_this_week_value, axis=1)
    ranked = ranked.sort_values("_v", ascending=False)
    osi = ranked[ranked.apply(_is_osimhen_row, axis=1)]
    if not osi.empty:
        captain_row = osi.iloc[0]
        rest = ranked.drop(index=captain_row.name)
        vice_row = rest.iloc[0] if len(rest) else None
        return captain_row, vice_row
    captain_row = ranked.iloc[0]
    vice_row = ranked.iloc[1] if len(ranked) > 1 else None
    return captain_row, vice_row


def _player_fold(df: pd.DataFrame, i: Any) -> str:
    bits = [str(df.loc[i, "player"] or "")]
    if "display_name" in df.columns:
        bits.append(str(df.loc[i, "display_name"] or ""))
    return normalize_name(" ".join(bits))


def _is_cs_club(team: str) -> bool:
    return club_key(str(team or "")) in _TOP_CLUBS


def _is_leaky_back_club(team: str) -> bool:
    key = club_key(str(team or ""))
    return "samsun" in key or "kocaeli" in key


def _is_joe_mendes(name_key: str) -> bool:
    if "mendes" not in name_key:
        return False
    return (
        "joe" in name_key
        or "josafat" in name_key
        or "wooding" in name_key
    )


def _derby_side_pairs(df: pd.DataFrame) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    if df is None or df.empty:
        return []
    has_kind = "fixture_match_kind" in df.columns
    has_opp = "fixture_opponent" in df.columns
    if not has_opp:
        return []
    for _, row in df.iterrows():
        team = club_key(str(row.get("team") or ""))
        opp = club_key(str(row.get("fixture_opponent") or ""))
        kind = str(row.get("fixture_match_kind") or "").strip().lower() if has_kind else ""
        if not team or not opp or team == opp:
            continue
        if kind == "derbi" or (team in _DERBY_CLUBS and opp in _DERBY_CLUBS):
            a, b = sorted((team, opp))
            pairs.add((a, b))
    return list(pairs)


def _even_fixture_pairs(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Denk veya derbi maçları: 15'li kadroda aynı maçın iki yakası durmaz."""
    pairs: set[tuple[str, str]] = set()
    if df is None or df.empty or "fixture_opponent" not in df.columns:
        return []
    has_kind = "fixture_match_kind" in df.columns
    for _, row in df.iterrows():
        team = club_key(str(row.get("team") or ""))
        opp = club_key(str(row.get("fixture_opponent") or ""))
        kind = str(row.get("fixture_match_kind") or "").strip().lower() if has_kind else ""
        if not team or not opp or team == opp:
            continue
        if kind in {"kolay", "zor"}:
            continue
        if (
            kind in {"derbi", "denk", ""}
            or (team in _DERBY_CLUBS and opp in _DERBY_CLUBS)
        ):
            a, b = sorted((team, opp))
            pairs.add((a, b))
    return list(pairs)


def _club_odds_mask(df: pd.DataFrame, club: str) -> pd.Series:
    mask = df.get("team_key", pd.Series("", index=df.index)).astype(str).eq(club)
    if not mask.any() and "team" in df.columns:
        mask = df["team"].map(lambda t: club_key(str(t))) == club
    if "odds_favorite" in df.columns:
        fav = df["odds_favorite"].map(lambda v: club_key(str(v or "")))
        opp = (
            df["fixture_opponent"].map(lambda v: club_key(str(v or "")))
            if "fixture_opponent" in df.columns
            else pd.Series("", index=df.index)
        )
        leaked = fav.ne("") & fav.ne("nan") & ~fav.isin({club}) & ~fav.eq(opp)
        mask = mask & ~leaked
    return mask


def _club_win_prob(df: pd.DataFrame, club: str) -> float:
    if df is None or df.empty or "odds_p_win" not in df.columns:
        return 0.0
    mask = _club_odds_mask(df, club)
    vals = pd.to_numeric(df.loc[mask, "odds_p_win"], errors="coerce").dropna()
    return float(vals.max()) if not vals.empty else 0.0


def _club_favorite_key(df: pd.DataFrame, club: str) -> str:
    if df is None or df.empty or "odds_favorite" not in df.columns:
        return ""
    mask = _club_odds_mask(df, club)
    for raw in df.loc[mask, "odds_favorite"].tolist():
        key = club_key(str(raw or ""))
        if key and key not in {"none", "nan", "home", "away"}:
            return key
    return ""


def _odds_favorite_of_pair(df: pd.DataFrame, club_a: str, club_b: str) -> str:
    """Net favori tarafı. Bir yakada kote yoksa zorlanmaz."""
    p_a = _club_win_prob(df, club_a)
    p_b = _club_win_prob(df, club_b)
    named = _club_favorite_key(df, club_a) or _club_favorite_key(df, club_b)
    if named in {club_a, club_b} and min(p_a, p_b) > 0:
        p_fav = p_a if named == club_a else p_b
        p_dog = p_b if named == club_a else p_a
        if p_fav + 0.02 >= p_dog:
            return named
    if p_a <= 0 or p_b <= 0:
        return ""
    if p_a >= p_b + 0.07 and p_a >= 0.36:
        return club_a
    if p_b >= p_a + 0.07 and p_b >= 0.36:
        return club_b
    return ""


def _bottom_table_rows(df: pd.DataFrame, *, cut: int = 4) -> list[Any]:
    """Puan durumunun dibindeki kulüplerin oyuncuları (yükselen takımlar dâhil)."""
    if df is None or df.empty or "table_pos" not in df.columns:
        return []
    pos = pd.to_numeric(df["table_pos"], errors="coerce")
    n = pd.to_numeric(df.get("table_n"), errors="coerce").fillna(18.0)
    n = n.where(n > 0, 18.0)
    mask = pos.notna() & (pos >= (n - cut))
    return list(df.index[mask])


def _sort_xi(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    order = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}
    out["_o"] = out["position"].map(order)
    out["_v"] = out.apply(_selection_value, axis=1)
    return out.sort_values(["_o", "_v"], ascending=[True, False]).drop(
        columns=["_o", "_v"], errors="ignore"
    )


def assign_formation(
    squad_df: pd.DataFrame,
    formation: dict[str, int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sabit 15'li kadroda formasyona göre greedy ilk 11 / yedek ayrımı."""
    xi_parts: list[pd.DataFrame] = []
    bench_parts: list[pd.DataFrame] = []
    for pos, need in formation.items():
        pool = squad_df[squad_df["position"] == pos].copy()
        if pool.empty:
            continue
        pool["_v"] = pool.apply(_selection_value, axis=1)
        pool = pool.sort_values("_v", ascending=False).drop(columns=["_v"])
        xi_parts.append(pool.head(int(need)))
        bench_parts.append(pool.iloc[int(need) :])
    xi = _sort_xi(pd.concat(xi_parts, ignore_index=True)) if xi_parts else pd.DataFrame()
    bench_raw = (
        pd.concat(bench_parts, ignore_index=True) if bench_parts else pd.DataFrame()
    )
    bench = order_bench_for_autosub(bench_raw)
    return xi, bench


def _formation_feasible(squad_df: pd.DataFrame, formation: dict[str, int]) -> bool:
    for pos, need in formation.items():
        if int((squad_df["position"] == pos).sum()) < int(need):
            return False
    return True


def _local_formation_candidates(
    xi: pd.DataFrame,
    bench: pd.DataFrame,
    formation: dict[str, int],
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Aynı formasyon içinde pahalı/yüksek EV yedeği XI ile yer değiştir."""
    candidates = [(xi.copy(), bench.copy())]
    if xi.empty or bench.empty:
        return candidates
    base_bottom = len(_bottom_table_rows(xi))
    for b_idx, b_row in bench.iterrows():
        b_pos = str(b_row.get("position") or "")
        xi_same = xi[xi["position"] == b_pos]
        if xi_same.empty:
            continue
        weak_idx = xi_same.apply(_selection_value, axis=1).idxmin()
        if _selection_value(b_row) <= _selection_value(xi.loc[weak_idx]) + 1e-9:
            continue
        new_xi = xi.copy()
        new_bench = bench.copy()
        new_xi.loc[weak_idx] = b_row
        new_bench.loc[b_idx] = xi.loc[weak_idx]
        if len(_bottom_table_rows(new_xi)) > base_bottom:
            continue
        candidates.append(
            (_sort_xi(new_xi.reset_index(drop=True)), order_bench_for_autosub(new_bench.reset_index(drop=True)))
        )
    return candidates


def _solve_formation_candidate(
    df: pd.DataFrame,
    formation: dict[str, int],
    *,
    budget: float,
    max_per_club: int,
    squad: dict[str, int],
    bench_weight: float,
    strict: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    idxs = list(df.index)
    prob = pulp.LpProblem("tff_fantasy_fixed_formation", pulp.LpMaximize)
    start = pulp.LpVariable.dicts("xi", idxs, cat="Binary")
    bench = pulp.LpVariable.dicts("bn", idxs, cat="Binary")
    values = {i: _selection_value(df.loc[i]) for i in idxs}
    prices = {i: float(df.loc[i, "price_m"]) for i in idxs}

    prob += pulp.lpSum(
        start[i] * values[i] + bench_weight * bench[i] * values[i]
        for i in idxs
    )
    banned: set[Any] = set()
    for i in idxs:
        prob += start[i] + bench[i] <= 1
        name_key = _player_fold(df, i)
        avail = str(df.loc[i, "availability"] if "availability" in df.columns else "").upper()
        pos = str(df.loc[i, "position"] or "").upper()
        play = 0.85
        if "play_probability" in df.columns:
            try:
                play = float(df.loc[i, "play_probability"] or 0.85)
            except (TypeError, ValueError):
                play = 0.85
        if _is_joe_mendes(name_key):
            banned.add(i)
        if play < 0.35:
            banned.add(i)
        if pos in {"DF", "GK"} and _is_leaky_back_club(str(df.loc[i, "team"] or "")):
            banned.add(i)
        if i in banned:
            prob += start[i] + bench[i] == 0
            continue
        if "osimhen" in name_key and avail not in {
            "INJURED",
            "SUSPENDED",
            "UNAVAILABLE",
            "OUT",
        }:
            prob += start[i] == 1
        if "talisca" in name_key and play < 0.40:
            prob += start[i] == 0
    prob += pulp.lpSum(
        (start[i] + bench[i]) * prices[i] for i in idxs
    ) <= budget

    free = [i for i in idxs if i not in banned]

    for pos, squad_need in squad.items():
        pos_idxs = [i for i in idxs if df.loc[i, "position"] == pos]
        prob += pulp.lpSum(start[i] for i in pos_idxs) == formation[pos]
        prob += (
            pulp.lpSum(bench[i] for i in pos_idxs)
            == squad_need - formation[pos]
        )

    for team_key, group in df.groupby("team_key"):
        if not team_key:
            continue
        team_idxs = list(group.index)
        if len(team_idxs) > max_per_club:
            prob += (
                pulp.lpSum(start[i] + bench[i] for i in team_idxs)
                <= max_per_club
            )

    cs_back = [
        i
        for i in free
        if str(df.loc[i, "position"] or "").upper() in {"DF", "GK"}
        and _is_cs_club(str(df.loc[i, "team"] or ""))
    ]
    # Kulüp limiti yüzünden erişilemeyecek bir taban istenmemeli;
    # her kulüpte hücumcuya bir kontenjan bırakılır.
    cs_clubs = {_row_team_key(df, i) for i in cs_back}
    cs_room = max(0, max_per_club * len(cs_clubs) - len(cs_clubs))
    cs_need = min(4, len(cs_back), cs_room)
    if cs_need >= 2:
        prob += pulp.lpSum(start[i] + bench[i] for i in cs_back) >= cs_need

    if strict:
        free_set = set(free)
        bottom = [i for i in _bottom_table_rows(df) if i in free_set]
        if bottom and len(free) - len(bottom) >= 40:
            prob += pulp.lpSum(start[i] + bench[i] for i in bottom) <= 2
            prob += pulp.lpSum(start[i] for i in bottom) <= 1

    for pair_i, (club_a, club_b) in enumerate(_even_fixture_pairs(df)):
        idxs_a = [i for i in idxs if _row_team_key(df, i) == club_a]
        idxs_b = [i for i in idxs if _row_team_key(df, i) == club_b]
        if not idxs_a or not idxs_b:
            continue
        use_a = pulp.LpVariable(f"even_a_{pair_i}", cat="Binary")
        use_b = pulp.LpVariable(f"even_b_{pair_i}", cat="Binary")
        for i in idxs_a:
            prob += start[i] + bench[i] <= use_a
        for i in idxs_b:
            prob += start[i] + bench[i] <= use_b
        prob += use_a + use_b <= 1
        fav = _odds_favorite_of_pair(df, club_a, club_b)
        if fav == club_a:
            prob += use_b == 0
        elif fav == club_b:
            prob += use_a == 0

    for pair_i, (club_a, club_b) in enumerate(_derby_side_pairs(df)):
        idxs_a = [i for i in idxs if _row_team_key(df, i) == club_a]
        idxs_b = [i for i in idxs if _row_team_key(df, i) == club_b]
        if not idxs_a or not idxs_b:
            continue
        prob += pulp.lpSum(start[i] + bench[i] for i in idxs_a) <= 2
        prob += pulp.lpSum(start[i] + bench[i] for i in idxs_b) <= 2

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        return None

    xi_idxs = [
        i for i in idxs if start[i].value() and start[i].value() > 0.5
    ]
    bench_idxs = [
        i for i in idxs if bench[i].value() and bench[i].value() > 0.5
    ]
    xi = _sort_xi(df.loc[xi_idxs].drop(columns=["team_key"], errors="ignore"))
    ordered_bench = order_bench_for_autosub(
        df.loc[bench_idxs].drop(columns=["team_key"], errors="ignore")
    )
    return xi.reset_index(drop=True), ordered_bench.reset_index(drop=True)


def _any_formation_solvable(
    df: pd.DataFrame,
    formations: dict[str, dict[str, int]],
    *,
    budget: float,
    max_per_club: int,
    squad: dict[str, int],
    bench_weight: float,
) -> bool:
    """Sıkı kısıtlarla hiçbir diziliş çözülmüyorsa kuralları gevşet."""
    for shape in formations.values():
        if (
            _solve_formation_candidate(
                df,
                shape,
                budget=budget,
                max_per_club=max_per_club,
                squad=squad,
                bench_weight=bench_weight,
                strict=True,
            )
            is not None
        ):
            return True
    return False


def rescore_formations(
    squad_df: pd.DataFrame,
    formations: dict[str, dict[str, int]],
    *,
    autosub_draws: int = AUTOSUB_MONTE_CARLO_DRAWS,
) -> dict[str, Any]:
    """15'li kadroyu tüm formasyonlarda gerçek autosub EV ile yeniden puanla."""
    best: dict[str, Any] | None = None
    comparisons: list[dict[str, Any]] = []
    clean = squad_df.drop(columns=["team_key", "role"], errors="ignore").copy()

    for name, shape in formations.items():
        if not _formation_feasible(clean, shape):
            continue
        base_xi, base_bench = assign_formation(clean, shape)
        formation_best: dict[str, Any] | None = None
        for xi_df, bn_df in _local_formation_candidates(base_xi, base_bench, shape):
            autosub = expected_squad_points(xi_df, bn_df, draws=autosub_draws)
            ev = float(autosub["expected_pts"])
            payload = {
                "formation": name,
                "xi": xi_df.assign(role="XI").reset_index(drop=True),
                "bench": bn_df.assign(role="yedek").reset_index(drop=True),
                "autosub": autosub,
                "expected_pts": ev,
            }
            if (
                formation_best is None
                or ev > float(formation_best["expected_pts"]) + 1e-9
            ):
                formation_best = payload
            if best is None or ev > float(best["expected_pts"]) + 1e-9:
                best = payload
            elif (
                best is not None
                and abs(ev - float(best["expected_pts"])) <= 1e-9
                and name < str(best["formation"])
            ):
                best = payload
        if formation_best is not None:
            formation_autosub = formation_best["autosub"]
            comparisons.append(
                {
                    "formation": name,
                    "expected_pts": round(
                        float(formation_best["expected_pts"]), 3
                    ),
                    "xi_expected": round(
                        float(formation_autosub["xi_expected"]), 3
                    ),
                    "bench_expected": round(
                        float(formation_autosub["bench_expected"]), 3
                    ),
                }
            )

    if best is None:
        raise RuntimeError("Formasyon EV yeniden skorlaması başarısız.")

    comparisons.sort(key=lambda row: row["expected_pts"], reverse=True)
    best["formation_comparisons"] = comparisons
    return best


def optimize_squad(
    players: pd.DataFrame,
    *,
    budget: float = BUDGET_M,
    max_per_club: int = MAX_PER_CLUB,
    squad: dict[str, int] | None = None,
    formations: dict[str, dict[str, int]] | None = None,
    bench_weight: float | None = None,
    autosub_draws: int = AUTOSUB_MONTE_CARLO_DRAWS,
    **_ignored: Any,
) -> dict[str, Any]:
    """
    15'li kadro: resmi 2-5-5-3.
    Her formasyon için ayrı aday 15 seçer; farklı yedek ağırlıklı adayları
    gerçek otomatik-yedek EV ile karşılaştırır.
    """
    squad = squad or SQUAD
    formations = formations or FORMATIONS
    df = players.copy()
    df = df.dropna(subset=["price_m", "position", "projected_pts"])
    df = df[df["position"].isin(squad.keys())]
    df = df[df["price_m"] > 0].reset_index(drop=True)

    if df.empty:
        raise ValueError("Optimize edilecek oyuncu yok.")

    if "pts_if_plays" not in df.columns:
        df["pts_if_plays"] = pd.to_numeric(df["projected_pts"], errors="coerce").fillna(0.0)
    if "play_probability" not in df.columns:
        df["play_probability"] = 0.85

    for pos, need in squad.items():
        have = int((df["position"] == pos).sum())
        if have < need:
            raise ValueError(
                f"{pos} için {need} oyuncu gerekiyor, listede {have} var."
            )

    df["team_key"] = df["team"].map(lambda t: club_key(str(t)))
    proxy_weights = (
        [float(bench_weight)]
        if bench_weight is not None
        else [0.12, 0.22, 0.40]
    )
    best: dict[str, Any] | None = None
    comparisons: list[dict[str, Any]] = []
    strict = _any_formation_solvable(
        df,
        formations,
        budget=budget,
        max_per_club=max_per_club,
        squad=squad,
        bench_weight=proxy_weights[0],
    )

    for formation_name, formation_shape in formations.items():
        formation_best: dict[str, Any] | None = None
        seen_candidates: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
        for proxy_weight in proxy_weights:
            candidate = _solve_formation_candidate(
                df,
                formation_shape,
                budget=budget,
                max_per_club=max_per_club,
                squad=squad,
                bench_weight=proxy_weight,
                strict=strict,
            )
            if candidate is None:
                continue
            base_xi, base_bench = candidate
            for xi_candidate, bench_candidate in _local_formation_candidates(
                base_xi, base_bench, formation_shape
            ):
                candidate_key = (
                    tuple(sorted(xi_candidate["player"].astype(str))),
                    tuple(sorted(bench_candidate["player"].astype(str))),
                )
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                autosub_candidate = expected_squad_points(
                    xi_candidate,
                    bench_candidate,
                    draws=autosub_draws,
                )
                expected = float(autosub_candidate["expected_pts"])
                payload = {
                    "formation": formation_name,
                    "xi": xi_candidate.assign(role="XI").reset_index(drop=True),
                    "bench": bench_candidate.assign(
                        role="yedek"
                    ).reset_index(drop=True),
                    "autosub": autosub_candidate,
                    "expected_pts": expected,
                    "proxy_bench_weight": proxy_weight,
                }
                if (
                    formation_best is None
                    or expected
                    > float(formation_best["expected_pts"]) + 1e-9
                ):
                    formation_best = payload
        if formation_best is None:
            continue
        formation_autosub = formation_best["autosub"]
        formation_xi = formation_best["xi"]
        formation_bench = formation_best["bench"]
        comparisons.append(
            {
                "formation": formation_name,
                "expected_pts": round(
                    float(formation_best["expected_pts"]), 3
                ),
                "xi_expected": round(
                    float(formation_autosub["xi_expected"]), 3
                ),
                "bench_expected": round(
                    float(formation_autosub["bench_expected"]), 3
                ),
                "xi_players": formation_xi["player"].astype(str).tolist(),
                "bench_players": formation_bench["player"].astype(str).tolist(),
            }
        )
        if (
            best is None
            or float(formation_best["expected_pts"])
            > float(best["expected_pts"]) + 1e-9
        ):
            best = formation_best

    if best is None:
        raise RuntimeError("Hiçbir formasyon için optimum kadro bulunamadı.")

    comparisons.sort(key=lambda row: row["expected_pts"], reverse=True)
    chosen = str(best["formation"])
    xi_df = best["xi"]
    bn_df = best["bench"]
    autosub = best["autosub"]
    squad_df = pd.concat([xi_df, bn_df], ignore_index=True)
    total_cost = float(squad_df["price_m"].sum())
    captain_row, vice_row = pick_armbands(xi_df)
    bench_shape = _bench_of(formations[chosen], squad)

    out: dict[str, Any] = {
        "squad": squad_df.reset_index(drop=True),
        "xi": xi_df.reset_index(drop=True),
        "bench": bn_df.reset_index(drop=True),
        "formation": chosen,
        "xi_shape": formations[chosen],
        "bench_shape": bench_shape,
        "total_cost": total_cost,
        "bank": budget - total_cost,
        "total_projected": float(autosub["expected_pts"]),
        "xi_projected": float(autosub["xi_expected"]),
        "bench_projected": float(autosub["bench_expected"]),
        "autosub": autosub,
        "formation_comparisons": comparisons,
        "captain": _armband_payload(captain_row),
        "budget": budget,
    }
    if vice_row is not None:
        out["vice_captain"] = _armband_payload(vice_row)
    return out

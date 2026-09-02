"""Bahis oranları: gerçek kote → ima edilen olasılık → fikstür çarpanı.

Sahte oran uydurmaz. Galatasaray–Fenerbahçe ve Galatasaray–Beşiktaş
derbilerinde favori her zaman Galatasaray’dır (kilit kural).
"""

from __future__ import annotations

import math
from typing import Any

from .config import (
    FIXTURE_ATTACK_CEILING,
    FIXTURE_ATTACK_FLOOR,
    FIXTURE_CS_CEILING,
    FIXTURE_CS_FLOOR,
    SAVE_MULT_CEILING,
    SAVE_MULT_FLOOR,
)
from .names import club_key

LEAGUE_CS_RATE = 0.28


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))

_GS_DERBY_OPPONENTS = frozenset({"fenerbahce", "besiktas"})
_ONE_X_TWO = {"1", "home", "1x2_1", "h", "ev", "ms1"}
_DRAW = {"x", "draw", "tie", "beraberlik", "1x2_x"}
_AWAY = {"2", "away", "1x2_2", "a", "dep", "ms2"}
_OVER = {"over", "üst", "ust", "o", "over 2.5", "over2.5"}
_UNDER = {"under", "alt", "u", "under 2.5", "under2.5"}
_BTTS_YES = {"yes", "evet", "gg", "y", "both"}
_BTTS_NO = {"no", "hayir", "hayır", "ng", "n", "none"}


def is_gs_derby(team: str, opponent: str) -> bool:
    keys = {club_key(team), club_key(opponent)}
    return "galatasaray" in keys and bool(keys & _GS_DERBY_OPPONENTS)


def _decimal(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        odds = float(value)
        return odds if odds > 1.01 else None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    if "/" in text and text.count("/") == 1:
        left, right = text.split("/", 1)
        try:
            num, den = float(left), float(right)
        except ValueError:
            return None
        if den <= 0:
            return None
        odds = 1.0 + num / den
        return odds if odds > 1.01 else None
    try:
        odds = float(text)
    except ValueError:
        return None
    return odds if odds > 1.01 else None


def implied_probs(*odds: float | None) -> list[float | None]:
    """Decimal oranlardan overround’suz ima edilen olasılık."""
    raw: list[float | None] = []
    total = 0.0
    for item in odds:
        if item is None:
            raw.append(None)
            continue
        dec = _decimal(item)
        if dec is None:
            raw.append(None)
            continue
        p = 1.0 / dec
        raw.append(p)
        total += p
    if total <= 1e-9:
        return raw
    return [None if p is None else p / total for p in raw]


def _fold(text: Any) -> str:
    return str(text or "").strip().casefold().replace(" ", "")


def _choice_name(choice: dict[str, Any]) -> str:
    return _fold(
        choice.get("name")
        or choice.get("label")
        or choice.get("outcome")
        or choice.get("type")
        or choice.get("choiceName")
        or ""
    )


def _choice_odds(choice: dict[str, Any]) -> float | None:
    for key in (
        "decimalValue",
        "decimal",
        "odds",
        "odd",
        "price",
        "value",
        "fractionalValue",
        "fractional",
    ):
        hit = _decimal(choice.get(key))
        if hit is not None:
            return hit
    return None


def _market_name(market: dict[str, Any]) -> str:
    return _fold(
        market.get("marketName")
        or market.get("name")
        or market.get("market")
        or market.get("label")
        or market.get("type")
        or ""
    )


def _choice_group(market: dict[str, Any]) -> str:
    return str(
        market.get("choiceGroup")
        or market.get("handicap")
        or market.get("line")
        or market.get("total")
        or ""
    ).strip().replace(",", ".")


def _is_full_time(market: dict[str, Any]) -> bool:
    name = _market_name(market)
    if "over" in name or "under" in name or "üst" in name or "alt" in name:
        return False
    if any(token in name for token in ("fulltime", "1x2", "matchwinner", "sonuc", "sonuç", "winner", "ms1x2")):
        return True
    if name in {"", "default", "featured", "main"}:
        return True
    choices = market.get("choices") or market.get("outcomes") or []
    names = {_choice_name(c) for c in choices if isinstance(c, dict)}
    return bool(names & _ONE_X_TWO) and bool(names & _AWAY)


def _is_btts(market: dict[str, Any]) -> bool:
    name = _market_name(market)
    return any(
        token in name
        for token in ("bothteam", "btts", "karşılıklı", "karsilikli", "ggng", "gg/ng")
    )


def _is_corners(market: dict[str, Any]) -> bool:
    return "corner" in _market_name(market) or "korner" in _market_name(market)


def _is_first_scorer(market: dict[str, Any]) -> bool:
    name = _market_name(market)
    return "firstteamtoscore" in name or "ilkgol" in name or "firstgoal" in name


def _is_ou_25(market: dict[str, Any]) -> bool:
    group = _choice_group(market)
    name = _market_name(market)
    choices = market.get("choices") or market.get("outcomes") or []
    names = {_choice_name(c) for c in choices if isinstance(c, dict)}
    has_ou = bool(names & _OVER) and bool(names & _UNDER)
    line_ok = group in {"2.5", "2,5", "2.50"} or "2.5" in name or "2,5" in name
    if has_ou and line_ok:
        return True
    ou_name = any(token in name for token in ("over", "under", "üst", "alt", "ou", "matchgoals", "totalgoals"))
    if line_ok and ou_name:
        return True
    return has_ou and (line_ok or group in {"", "2.5"})


def _walk_markets(blob: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any, depth: int) -> None:
        if depth > 8 or node is None:
            return
        if isinstance(node, dict):
            choices = node.get("choices") or node.get("outcomes")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                if any(_choice_odds(c) is not None for c in choices if isinstance(c, dict)):
                    found.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:40]:
                walk(item, depth + 1)

    walk(blob, 0)
    return found


def _side_odds(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        raw = item.get(key)
        if isinstance(raw, dict):
            hit = _decimal(raw.get("odds") or raw.get("decimal") or raw.get("value"))
            if hit is not None:
                return hit
        hit = _decimal(raw)
        if hit is not None:
            return hit
    return None


def parse_odds_blob(blob: Any) -> dict[str, Any] | None:
    """Sofascore / FotMob / gömülü event odds JSON’unu tek forma indirger."""
    if not blob:
        return None
    home_odds = draw_odds = away_odds = None
    over_odds = under_odds = None
    btts_yes = btts_no = None
    corner_over = corner_under = None
    corner_line: float | None = None
    first_named: list[tuple[str, float]] = []
    source_hint = ""
    if isinstance(blob, dict):
        source_hint = str(blob.get("source") or blob.get("provider") or "")
        # FotMob düz alanlar
        for key in ("odds", "bettingOdds", "prematchOdds"):
            inner = blob.get(key)
            items = inner if isinstance(inner, list) else ([inner] if isinstance(inner, dict) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                home_odds = home_odds or _side_odds(
                    item, "home", "homeOdds", "homeDecimal", "oddsHome"
                )
                draw_odds = draw_odds or _side_odds(
                    item, "draw", "drawOdds", "drawDecimal", "oddsDraw"
                )
                away_odds = away_odds or _side_odds(
                    item, "away", "awayOdds", "awayDecimal", "oddsAway"
                )
        home_odds = home_odds or _decimal(
            blob.get("homeOdds") or blob.get("homeDecimal") or blob.get("oddsHome")
        )
        draw_odds = draw_odds or _decimal(
            blob.get("drawOdds") or blob.get("drawDecimal") or blob.get("oddsDraw")
        )
        away_odds = away_odds or _decimal(
            blob.get("awayOdds") or blob.get("awayDecimal") or blob.get("oddsAway")
        )

    for market in _walk_markets(blob):
        if home_odds is None and _is_full_time(market):
            for choice in market.get("choices") or market.get("outcomes") or []:
                if not isinstance(choice, dict):
                    continue
                name = _choice_name(choice)
                odds = _choice_odds(choice)
                if odds is None:
                    continue
                if name in _ONE_X_TWO or name.endswith("home"):
                    home_odds = home_odds or odds
                elif name in _DRAW:
                    draw_odds = draw_odds or odds
                elif name in _AWAY or name.endswith("away"):
                    away_odds = away_odds or odds
        if over_odds is None and _is_ou_25(market):
            for choice in market.get("choices") or market.get("outcomes") or []:
                if not isinstance(choice, dict):
                    continue
                name = _choice_name(choice)
                odds = _choice_odds(choice)
                if odds is None:
                    continue
                if any(token in name for token in _OVER) or name.startswith("o"):
                    over_odds = over_odds or odds
                elif any(token in name for token in _UNDER) or name.startswith("u"):
                    under_odds = under_odds or odds
        if btts_yes is None and _is_btts(market):
            for choice in market.get("choices") or market.get("outcomes") or []:
                if not isinstance(choice, dict):
                    continue
                name = _choice_name(choice)
                odds = _choice_odds(choice)
                if odds is None:
                    continue
                if name in _BTTS_YES or name.startswith("yes"):
                    btts_yes = btts_yes or odds
                elif name in _BTTS_NO or name.startswith("no"):
                    btts_no = btts_no or odds
        if corner_over is None and _is_corners(market):
            group = _choice_group(market)
            try:
                line = float(group)
            except (TypeError, ValueError):
                line = None
            if line is not None and (corner_line is None or abs(line - 9.5) <= abs(float(corner_line) - 9.5)):
                corner_line = line
            for choice in market.get("choices") or market.get("outcomes") or []:
                if not isinstance(choice, dict):
                    continue
                name = _choice_name(choice)
                odds = _choice_odds(choice)
                if odds is None:
                    continue
                if any(token in name for token in _OVER) or name.startswith("o"):
                    corner_over = corner_over or odds
                elif any(token in name for token in _UNDER) or name.startswith("u"):
                    corner_under = corner_under or odds
        if _is_first_scorer(market):
            for choice in market.get("choices") or market.get("outcomes") or []:
                if not isinstance(choice, dict):
                    continue
                label = str(choice.get("name") or choice.get("label") or "")
                odds = _choice_odds(choice)
                if label and odds is not None:
                    first_named.append((label, odds))

    if home_odds is None or away_odds is None:
        return None
    p_home, p_draw, p_away = implied_probs(home_odds, draw_odds, away_odds)
    if p_home is None or p_away is None:
        return None
    p_over = p_under = None
    if over_odds is not None and under_odds is not None:
        p_over, p_under = implied_probs(over_odds, under_odds)
    elif over_odds is not None:
        inv = 1.0 / over_odds
        p_over = _clip(inv, 0.12, 0.88)
    out: dict[str, Any] = {
        "home_odds": round(float(home_odds), 3),
        "draw_odds": round(float(draw_odds), 3) if draw_odds else None,
        "away_odds": round(float(away_odds), 3),
        "p_home": round(float(p_home), 4),
        "p_draw": round(float(p_draw or 0.0), 4),
        "p_away": round(float(p_away), 4),
        "source": source_hint or "market",
        "gs_favorite_override": False,
    }
    if over_odds is not None:
        out["over_25_odds"] = round(float(over_odds), 3)
    if under_odds is not None:
        out["under_25_odds"] = round(float(under_odds), 3)
    if p_over is not None:
        out["p_over_25"] = round(float(p_over), 4)
    if p_under is not None:
        out["p_under_25"] = round(float(p_under), 4)
    out["favorite"] = "home" if p_home > p_away + 0.02 else ("away" if p_away > p_home + 0.02 else "none")
    if btts_yes is not None:
        out["btts_yes_odds"] = round(float(btts_yes), 3)
        p_yes, p_no = implied_probs(btts_yes, btts_no)
        if p_yes is not None:
            out["p_btts"] = round(float(p_yes), 4)
        if btts_no is not None:
            out["btts_no_odds"] = round(float(btts_no), 3)
            if p_no is not None:
                out["p_btts_no"] = round(float(p_no), 4)
    if corner_line is not None:
        out["corner_line"] = round(float(corner_line), 2)
    if corner_over is not None:
        out["corners_over_odds"] = round(float(corner_over), 3)
    if corner_under is not None:
        out["corners_under_odds"] = round(float(corner_under), 3)
    if corner_over is not None and corner_under is not None:
        p_co, p_cu = implied_probs(corner_over, corner_under)
        if p_co is not None:
            out["p_over_corners"] = round(float(p_co), 4)
        if p_cu is not None:
            out["p_under_corners"] = round(float(p_cu), 4)
        if corner_line is not None and p_co is not None:
            out["expected_corners"] = round(float(corner_line) + (float(p_co) - 0.5) * 2.0, 2)
    if first_named:
        out["first_scorer"] = [
            {"name": label, "odds": round(float(odds), 3)} for label, odds in first_named[:6]
        ]
    return out


def apply_gs_favorite_override(
    market: dict[str, Any] | None,
    home: str,
    away: str,
) -> dict[str, Any] | None:
    """GS–FB / GS–BJK: favori her zaman Galatasaray. Sahte kote yazılmaz."""
    home_key = club_key(home)
    away_key = club_key(away)
    if not is_gs_derby(home_key, away_key):
        if not market:
            return None
        out = dict(market)
        fav = out.get("favorite")
        out["favorite_key"] = home_key if fav == "home" else (away_key if fav == "away" else "")
        _attach_first_scorer(out, home, away)
        return out

    if market:
        out = dict(market)
    else:
        # Oran yok; kote uydurulmaz, yalnızca kilit kuralın ima ettiği pay.
        if home_key == "galatasaray":
            p_home, p_away, p_draw = 0.46, 0.28, 0.26
        else:
            p_home, p_away, p_draw = 0.28, 0.46, 0.26
        out = {
            "p_home": p_home,
            "p_draw": p_draw,
            "p_away": p_away,
            "source": "gs_rule",
        }

    p_home = float(out.get("p_home") or 0.0)
    p_away = float(out.get("p_away") or 0.0)
    p_draw = float(out.get("p_draw") or max(0.0, 1.0 - p_home - p_away))
    gs_is_home = home_key == "galatasaray"
    gs_p = p_home if gs_is_home else p_away
    opp_p = p_away if gs_is_home else p_home
    if gs_p <= opp_p + 0.04:
        # Gerçek kote GS’yi favori göstermiyorsa olasılığı kaydır; oran rakamına dokunma.
        gap = 0.10
        gs_p = max(gs_p, opp_p + gap)
        rest = max(0.12, 1.0 - gs_p)
        # Beraberlik payını koru, rakibi küçült.
        p_draw = min(p_draw, rest * 0.55)
        opp_p = max(0.08, rest - p_draw)
        total = gs_p + opp_p + p_draw
        gs_p, opp_p, p_draw = gs_p / total, opp_p / total, p_draw / total
        if gs_is_home:
            p_home, p_away = gs_p, opp_p
        else:
            p_home, p_away = opp_p, gs_p
        out["p_home"] = round(p_home, 4)
        out["p_away"] = round(p_away, 4)
        out["p_draw"] = round(p_draw, 4)
    out["favorite"] = "home" if home_key == "galatasaray" else "away"
    out["favorite_key"] = "galatasaray"
    out["gs_favorite_override"] = True
    _attach_first_scorer(out, home, away)
    return out


def _attach_first_scorer(market: dict[str, Any], home: str, away: str) -> None:
    rows = market.get("first_scorer") or []
    if not isinstance(rows, list) or not rows:
        return
    home_key = club_key(home)
    away_key = club_key(away)
    home_odds = away_odds = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = club_key(str(row.get("name") or ""))
        odds = _decimal(row.get("odds"))
        if odds is None:
            continue
        if key == home_key or (home_key and home_key in key):
            home_odds = home_odds or odds
        elif key == away_key or (away_key and away_key in key):
            away_odds = away_odds or odds
    if home_odds is None or away_odds is None:
        return
    p_h, p_a = implied_probs(home_odds, away_odds)
    if p_h is None or p_a is None:
        return
    market["p_first_home"] = round(float(p_h), 4)
    market["p_first_away"] = round(float(p_a), 4)


def _poisson_over_25(total: float) -> float:
    lam = max(0.05, float(total))
    p_le2 = math.exp(-lam) * (1.0 + lam + lam * lam / 2.0)
    return _clip(1.0 - p_le2, 0.02, 0.98)


def blend_lambdas_with_market(
    lambda_for: float,
    lambda_against: float,
    market: dict[str, Any] | None,
    *,
    home: bool,
) -> tuple[float, float]:
    """Favori ve 2.5 üst/alt ima edilen olasılıkla λ’yı kaydır."""
    lam_for = float(lambda_for)
    lam_ag = float(lambda_against)
    if not market:
        return lam_for, lam_ag
    p_home = float(market.get("p_home") or 0.0)
    p_away = float(market.get("p_away") or 0.0)
    if p_home <= 0 or p_away <= 0:
        return lam_for, lam_ag
    team_win = p_home if home else p_away
    opp_win = p_away if home else p_home
    edge = _clip(team_win - opp_win, -0.42, 0.42)
    lam_for *= 1.0 + 0.58 * edge
    lam_ag *= 1.0 - 0.48 * edge

    p_over = market.get("p_over_25")
    if p_over is not None:
        try:
            p_over_f = float(p_over)
        except (TypeError, ValueError):
            p_over_f = None
        else:
            model_over = _poisson_over_25(lam_for + lam_ag)
            total_shift = _clip((p_over_f - model_over) * 0.85, -0.24, 0.24)
            lam_for *= 1.0 + total_shift
            lam_ag *= 1.0 + total_shift

    p_btts = market.get("p_btts")
    if p_btts is not None:
        try:
            btts = float(p_btts)
        except (TypeError, ValueError):
            btts = None
        else:
            # GG piyasası: iki takım da gol atar → CS düşer, her iki λ yükselir.
            shift = _clip(btts - 0.52, -0.32, 0.32)
            lam_for *= 1.0 + 0.22 * shift
            lam_ag *= 1.0 + 0.36 * shift
            if shift < -0.08 and edge > 0:
                # GG hayır + favori: rakip golü daha da kısılır.
                lam_ag *= 0.90

    expected = market.get("expected_corners")
    if expected is None:
        line = market.get("corner_line")
        p_co = market.get("p_over_corners")
        if line is not None and p_co is not None:
            try:
                expected = float(line) + (float(p_co) - 0.5) * 2.0
            except (TypeError, ValueError):
                expected = None
    if expected is not None:
        try:
            corners = float(expected)
        except (TypeError, ValueError):
            corners = None
        else:
            # Düşük korner = şutlar auta değil kaleye/sekmeye gider.
            if corners <= 8.8:
                lam_for *= 0.97
            elif corners >= 11.2:
                lam_for *= 1.04
                lam_ag *= 1.03
    return (
        _clip(lam_for, 0.30, 3.50),
        _clip(lam_ag, 0.30, 3.50),
    )


def finalize_prediction(
    lambda_for: float,
    lambda_against: float,
    *,
    kind: str,
    league_avg: float,
    team_goal_rate: float,
    market: dict[str, Any] | None = None,
    home: bool = True,
) -> dict[str, Any]:
    lam_for, lam_ag = blend_lambdas_with_market(
        lambda_for, lambda_against, market, home=home
    )
    p_cs = math.exp(-lam_ag)
    attack_mult = _clip(lam_for / max(league_avg, 0.4), FIXTURE_ATTACK_FLOOR, FIXTURE_ATTACK_CEILING)
    cs_mult = _clip(p_cs / LEAGUE_CS_RATE, FIXTURE_CS_FLOOR, FIXTURE_CS_CEILING)
    save_mult = _clip(lam_ag / max(league_avg, 0.4), SAVE_MULT_FLOOR, SAVE_MULT_CEILING)
    if kind == "derbi":
        attack_mult = 1.0 + (attack_mult - 1.0) * 0.42
        cs_mult = 1.0 + (cs_mult - 1.0) * 0.38
        p_cs = _clip(0.52 * p_cs + 0.48 * LEAGUE_CS_RATE, 0.08, 0.50)
        save_mult = 1.0 + (save_mult - 1.0) * 0.50
    if market:
        expected = market.get("expected_corners")
        p_btts = market.get("p_btts")
        try:
            corners = float(expected) if expected is not None else None
        except (TypeError, ValueError):
            corners = None
        try:
            btts = float(p_btts) if p_btts is not None else None
        except (TypeError, ValueError):
            btts = None
        if corners is not None and corners <= 8.8:
            # Korner üstü kısık: şut kaleye veya defanstan seker → kurtarış.
            save_mult = _clip(save_mult * 1.16, SAVE_MULT_FLOOR, SAVE_MULT_CEILING)
        elif corners is not None and corners >= 11.2:
            save_mult = _clip(save_mult * 0.94, SAVE_MULT_FLOOR, SAVE_MULT_CEILING)
            cs_mult = _clip(cs_mult * 0.96, FIXTURE_CS_FLOOR, FIXTURE_CS_CEILING)
        if btts is not None and btts >= 0.58:
            p_cs = _clip(p_cs * 0.82, 0.04, 0.78)
            cs_mult = _clip(cs_mult * 0.88, FIXTURE_CS_FLOOR, FIXTURE_CS_CEILING)
        elif btts is not None and btts <= 0.42:
            p_cs = _clip(p_cs * 1.12, 0.04, 0.78)
            cs_mult = _clip(cs_mult * 1.08, FIXTURE_CS_FLOOR, FIXTURE_CS_CEILING)
    out = {
        "lambda_for": round(lam_for, 4),
        "lambda_against": round(lam_ag, 4),
        "p_cs": round(_clip(p_cs, 0.04, 0.78), 4),
        "attack_mult": round(attack_mult, 4),
        "cs_mult": round(cs_mult, 4),
        "save_mult": round(save_mult, 4),
        "team_goal_rate": round(team_goal_rate, 4),
        "match_kind": kind,
    }
    if market:
        team_win = float(market.get("p_home") or 0.0) if home else float(market.get("p_away") or 0.0)
        out["odds_p_win"] = round(team_win, 4)
        out["odds_p_over_25"] = market.get("p_over_25")
        out["odds_favorite"] = market.get("favorite_key") or market.get("favorite")
        out["odds_gs_override"] = bool(market.get("gs_favorite_override"))
        out["odds_source"] = market.get("source")
        if market.get("home_odds") is not None:
            out["odds_home"] = market.get("home_odds")
            out["odds_draw"] = market.get("draw_odds")
            out["odds_away"] = market.get("away_odds")
        if market.get("over_25_odds") is not None:
            out["odds_over_25"] = market.get("over_25_odds")
            out["odds_under_25"] = market.get("under_25_odds")
        if market.get("p_btts") is not None:
            out["odds_p_btts"] = market.get("p_btts")
        if market.get("corner_line") is not None:
            out["odds_corner_line"] = market.get("corner_line")
            out["odds_p_over_corners"] = market.get("p_over_corners")
            out["odds_expected_corners"] = market.get("expected_corners")
        p_first_home = market.get("p_first_home")
        p_first_away = market.get("p_first_away")
        if p_first_home is not None and p_first_away is not None:
            out["odds_p_first"] = round(
                float(p_first_home if home else p_first_away), 4
            )
    return out


def market_for_match(
    blob: Any,
    home: str,
    away: str,
) -> dict[str, Any] | None:
    parsed = parse_odds_blob(blob) if blob else None
    return apply_gs_favorite_override(parsed, home, away)

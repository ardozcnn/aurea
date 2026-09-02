import unittest

import pandas as pd

from src.odds import (
    apply_gs_favorite_override,
    blend_lambdas_with_market,
    implied_probs,
    is_gs_derby,
    parse_odds_blob,
)
from src.optimize import pick_armbands
from src.team_model import predict_lambdas


SOFA_ALL = {
    "markets": [
        {
            "marketName": "Full time",
            "choices": [
                {"name": "1", "decimalValue": "2.10"},
                {"name": "X", "decimalValue": "3.40"},
                {"name": "2", "decimalValue": "3.50"},
            ],
        },
        {
            "marketName": "Over/Under",
            "choiceGroup": "2.5",
            "choices": [
                {"name": "Over", "decimalValue": "1.70"},
                {"name": "Under", "decimalValue": "2.15"},
            ],
        },
    ]
}


class OddsTests(unittest.TestCase):
    def test_implied_probs_remove_overround(self) -> None:
        p_h, p_d, p_a = implied_probs(2.0, 4.0, 4.0)
        self.assertIsNotNone(p_h)
        assert p_h is not None and p_d is not None and p_a is not None
        self.assertAlmostEqual(p_h + p_d + p_a, 1.0, places=6)
        self.assertGreater(p_h, p_a)

    def test_parse_sofascore_match_goals_fractional(self) -> None:
        blob = {
            "markets": [
                {
                    "marketName": "Full time",
                    "choices": [
                        {"name": "1", "fractionalValue": "11/10"},
                        {"name": "X", "fractionalValue": "23/10"},
                        {"name": "2", "fractionalValue": "11/5"},
                    ],
                },
                {
                    "marketName": "Match goals",
                    "choiceGroup": "2.5",
                    "choices": [
                        {"name": "Over", "fractionalValue": "11/10"},
                        {"name": "Under", "fractionalValue": "7/10"},
                    ],
                },
            ]
        }
        parsed = parse_odds_blob(blob)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("p_over_25", parsed)
        self.assertGreater(parsed["p_under_25"], parsed["p_over_25"])
        parsed = parse_odds_blob(SOFA_ALL)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["home_odds"], 2.1)
        self.assertEqual(parsed["away_odds"], 3.5)
        self.assertAlmostEqual(parsed["p_home"] + parsed["p_draw"] + parsed["p_away"], 1.0, places=4)
        self.assertGreater(parsed["p_over_25"], parsed["p_under_25"])
        self.assertEqual(parsed["favorite"], "home")

    def test_gs_is_favorite_even_when_odds_prefer_fenerbahce(self) -> None:
        # FB ev sahibi, daha kısa kote — yine GS kilit favori.
        blob = {
            "markets": [
                {
                    "marketName": "Full time",
                    "choices": [
                        {"name": "1", "decimalValue": "2.05"},
                        {"name": "X", "decimalValue": "3.40"},
                        {"name": "2", "decimalValue": "3.60"},
                    ],
                }
            ]
        }
        parsed = parse_odds_blob(blob)
        assert parsed is not None
        self.assertEqual(parsed["favorite"], "home")
        self.assertGreater(parsed["p_home"], parsed["p_away"])
        market = apply_gs_favorite_override(parsed, "Fenerbahçe", "Galatasaray")
        assert market is not None
        self.assertTrue(market["gs_favorite_override"])
        self.assertEqual(market["favorite_key"], "galatasaray")
        self.assertEqual(market["favorite"], "away")
        self.assertGreater(market["p_away"], market["p_home"])
        self.assertEqual(market["home_odds"], 2.05)
        self.assertEqual(market["away_odds"], 3.60)

    def test_leaked_odds_do_not_make_basaksehir_favorite_over_gs(self) -> None:
        from src.optimize import _odds_favorite_of_pair

        df = pd.DataFrame(
            [
                {
                    "team": "Galatasaray",
                    "team_key": "galatasaray",
                    "fixture_opponent": "Başakşehir FK",
                    "odds_favorite": None,
                    "odds_p_win": None,
                },
                {
                    "team": "İstanbul Başakşehir",
                    "team_key": "basaksehir",
                    "fixture_opponent": "Galatasaray",
                    "odds_favorite": "trabzonspor",
                    "odds_p_win": 0.6085,
                },
                {
                    "team": "Fenerbahçe",
                    "team_key": "fenerbahce",
                    "fixture_opponent": "Beşiktaş",
                    "odds_favorite": "fenerbahce",
                    "odds_p_win": 0.52,
                },
                {
                    "team": "Beşiktaş",
                    "team_key": "besiktas",
                    "fixture_opponent": "Fenerbahçe",
                    "odds_favorite": "fenerbahce",
                    "odds_p_win": 0.23,
                },
            ]
        )
        self.assertEqual(_odds_favorite_of_pair(df, "basaksehir", "galatasaray"), "")
        self.assertEqual(_odds_favorite_of_pair(df, "besiktas", "fenerbahce"), "fenerbahce")

    def test_does_not_invent_decimal_odds_without_source(self) -> None:
        market = apply_gs_favorite_override(None, "Galatasaray", "Beşiktaş")
        assert market is not None
        self.assertTrue(market["gs_favorite_override"])
        self.assertNotIn("home_odds", market)
        self.assertEqual(market["favorite_key"], "galatasaray")
        self.assertGreater(market["p_home"], market["p_away"])

    def test_trabzonspor_is_not_a_gs_derby(self) -> None:
        self.assertFalse(is_gs_derby("Galatasaray", "Trabzonspor"))
        self.assertFalse(is_gs_derby("Galatasaray", "Başakşehir"))
        self.assertTrue(is_gs_derby("Galatasaray", "Fenerbahçe"))
        self.assertTrue(is_gs_derby("Beşiktaş JK", "Galatasaray"))

    def test_over_25_lifts_attack_and_cuts_cs(self) -> None:
        ratings = {
            "attack": {"galatasaray": 1.4, "kayserispor": 0.9},
            "defence": {"galatasaray": 0.8, "kayserispor": 1.2},
            "home_adv": 1.28,
            "scale": 1.35,
            "league_avg": 1.35,
        }
        even = {
            "p_home": 0.40,
            "p_draw": 0.28,
            "p_away": 0.32,
            "favorite": "none",
            "favorite_key": "",
            "home_odds": 2.40,
            "draw_odds": 3.40,
            "away_odds": 3.00,
            "source": "sofascore",
        }
        high_ou = {**even, "p_over_25": 0.72}
        low_ou = {**even, "p_over_25": 0.32}
        boosted = predict_lambdas(
            ratings, "Galatasaray", "Kayserispor", home=True, market=high_ou
        )
        muted = predict_lambdas(
            ratings, "Galatasaray", "Kayserispor", home=True, market=low_ou
        )
        self.assertGreater(boosted["lambda_for"] + boosted["lambda_against"], muted["lambda_for"] + muted["lambda_against"])
        self.assertLess(boosted["p_cs"], muted["p_cs"])

    def test_gs_derby_favorite_beats_opponent_after_caution(self) -> None:
        ratings = {
            "attack": {"galatasaray": 1.45, "fenerbahce": 1.42},
            "defence": {"galatasaray": 0.72, "fenerbahce": 0.74},
            "home_adv": 1.20,
            "scale": 1.35,
            "league_avg": 1.35,
        }
        # Odds FB'yi favori gösteriyor.
        blob = parse_odds_blob(
            {
                "markets": [
                    {
                        "marketName": "Full time",
                        "choices": [
                            {"name": "1", "decimalValue": "2.00"},
                            {"name": "X", "decimalValue": "3.30"},
                            {"name": "2", "decimalValue": "3.80"},
                        ],
                    }
                ]
            }
        )
        gs = predict_lambdas(
            ratings, "Galatasaray", "Fenerbahçe", home=False, market=blob
        )
        fb = predict_lambdas(
            ratings, "Fenerbahçe", "Galatasaray", home=True, market=blob
        )
        self.assertEqual(gs["match_kind"], "derbi")
        self.assertEqual(fb["match_kind"], "derbi")
        self.assertTrue(gs.get("odds_gs_override"))
        self.assertGreater(gs["lambda_for"], fb["lambda_for"])
        self.assertGreater(gs["p_cs"], fb["p_cs"])

    def test_parse_btts_corners_and_first_scorer(self) -> None:
        blob = {
            "markets": [
                {
                    "marketName": "Full time",
                    "choices": [
                        {"name": "1", "decimalValue": "1.76"},
                        {"name": "X", "decimalValue": "3.70"},
                        {"name": "2", "decimalValue": "3.90"},
                    ],
                },
                {
                    "marketName": "Both teams to score",
                    "choices": [
                        {"name": "Yes", "fractionalValue": "4/6"},
                        {"name": "No", "fractionalValue": "11/10"},
                    ],
                },
                {
                    "marketName": "Corners 2-Way",
                    "choiceGroup": "8.5",
                    "choices": [
                        {"name": "Over", "decimalValue": "2.20"},
                        {"name": "Under", "decimalValue": "1.65"},
                    ],
                },
                {
                    "marketName": "First team to score",
                    "choices": [
                        {"name": "Fenerbahçe", "fractionalValue": "8/13"},
                        {"name": "Beşiktaş JK", "fractionalValue": "11/8"},
                    ],
                },
            ]
        }
        parsed = parse_odds_blob(blob)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertGreater(parsed["p_btts"], parsed["p_btts_no"])
        self.assertEqual(parsed["corner_line"], 8.5)
        self.assertLess(parsed["p_over_corners"], parsed["p_under_corners"])
        self.assertLess(parsed["expected_corners"], 8.5)
        market = apply_gs_favorite_override(parsed, "Fenerbahçe", "Beşiktaş JK")
        assert market is not None
        self.assertEqual(market["favorite_key"], "fenerbahce")
        self.assertGreater(market["p_first_home"], market["p_first_away"])

    def test_low_corners_raise_saves_high_btts_cuts_cs(self) -> None:
        ratings = {
            "attack": {"fenerbahce": 1.35, "besiktas": 1.22},
            "defence": {"fenerbahce": 0.82, "besiktas": 0.90},
            "home_adv": 1.22,
            "scale": 1.35,
            "league_avg": 1.35,
        }
        base = {
            "p_home": 0.52,
            "p_draw": 0.25,
            "p_away": 0.23,
            "favorite": "home",
            "favorite_key": "fenerbahce",
            "source": "sofascore",
        }
        closed = predict_lambdas(
            ratings,
            "Fenerbahçe",
            "Beşiktaş",
            home=True,
            market={**base, "p_btts": 0.38, "expected_corners": 8.2, "corner_line": 8.5},
        )
        open_game = predict_lambdas(
            ratings,
            "Fenerbahçe",
            "Beşiktaş",
            home=True,
            market={**base, "p_btts": 0.68, "expected_corners": 11.6, "corner_line": 10.5},
        )
        self.assertGreater(closed["save_mult"], open_game["save_mult"])
        self.assertGreater(closed["p_cs"], open_game["p_cs"])

    def test_favorite_side_beats_underdog_attackers(self) -> None:
        from src.scoring import apply_context_adjustments

        frame = pd.DataFrame(
            [
                {
                    "player": "Greenwood",
                    "team": "Fenerbahçe",
                    "position": "MF",
                    "projected_pts": 6.0,
                    "price_m": 11.0,
                    "availability": "AVAILABLE",
                    "form_apps": 3,
                    "min_per_app": 80,
                    "fixture_opponent": "Beşiktaş",
                    "fixture_match_kind": "derbi",
                    "odds_favorite": "fenerbahce",
                    "odds_p_win": 0.52,
                    "gls_pa": 0.3,
                },
                {
                    "player": "Cerny",
                    "team": "Beşiktaş",
                    "position": "MF",
                    "projected_pts": 6.0,
                    "price_m": 7.0,
                    "availability": "AVAILABLE",
                    "form_apps": 3,
                    "min_per_app": 80,
                    "fixture_opponent": "Fenerbahçe",
                    "fixture_match_kind": "derbi",
                    "odds_favorite": "fenerbahce",
                    "odds_p_win": 0.23,
                    "gls_pa": 0.3,
                },
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertGreater(
            float(out.loc[0, "pts_if_plays"]),
            float(out.loc[1, "pts_if_plays"]),
        )

    def test_osimhen_is_captain_even_if_not_top_ev(self) -> None:
        xi = pd.DataFrame(
            [
                {
                    "player": "Mason Greenwood",
                    "display_name": "Mason Greenwood",
                    "team": "Beşiktaş",
                    "position": "FW",
                    "price_m": 11.0,
                    "projected_pts": 8.0,
                    "pts_if_plays": 8.0,
                    "play_probability": 1.0,
                    "reason": "",
                },
                {
                    "player": "Victor Osimhen",
                    "display_name": "Victor Osimhen",
                    "team": "Galatasaray",
                    "position": "FW",
                    "price_m": 14.0,
                    "projected_pts": 6.0,
                    "pts_if_plays": 6.0,
                    "play_probability": 1.0,
                    "reason": "",
                },
                {
                    "player": "Kaleci",
                    "display_name": "Kaleci",
                    "team": "Trabzonspor",
                    "position": "GK",
                    "price_m": 5.0,
                    "projected_pts": 4.0,
                    "pts_if_plays": 4.0,
                    "play_probability": 1.0,
                    "reason": "",
                },
            ]
        )
        cap, vice = pick_armbands(xi)
        self.assertIn("Osimhen", str(cap["player"]))
        self.assertIsNotNone(vice)
        assert vice is not None
        self.assertNotIn("Osimhen", str(vice["player"]))
        self.assertIn("Greenwood", str(vice["player"]))

    def test_optimize_takes_favorite_side_not_underdog(self) -> None:
        from src.optimize import optimize_squad

        rows = []

        def add(name, team, pos, price, pts, play=0.95, **kw):
            rows.append(
                {
                    "player": name,
                    "team": team,
                    "position": pos,
                    "price_m": price,
                    "pts_if_plays": pts,
                    "play_probability": play,
                    "projected_pts": pts * play,
                    "selection_pts": pts * play,
                    "availability": "AVAILABLE",
                    **kw,
                }
            )

        add("GK1", "Konyaspor", "GK", 4.0, 3.5)
        add("GK2", "Rizespor", "GK", 4.0, 3.2)
        clubs = [
            "Sivasspor",
            "Kayserispor",
            "Alanyaspor",
            "Eyupspor",
            "Goztepe",
            "Kasimpasa",
            "Bodrumspor",
            "Hatayspor",
        ]
        for i, club in enumerate(clubs):
            add(f"DF{i}", club, "DF", 4.5, 3.1)
        for i, club in enumerate(clubs[:6]):
            add(f"MF{i}", club, "MF", 5.0, 3.3)
        add(
            "Cerny",
            "Besiktas",
            "MF",
            7.0,
            8.2,
            fixture_opponent="Fenerbahce",
            fixture_match_kind="derbi",
            odds_favorite="fenerbahce",
            odds_p_win=0.23,
        )
        add(
            "Vlahovic",
            "Besiktas",
            "FW",
            10.0,
            7.7,
            fixture_opponent="Fenerbahce",
            fixture_match_kind="derbi",
            odds_favorite="fenerbahce",
            odds_p_win=0.23,
        )
        add(
            "Greenwood",
            "Fenerbahce",
            "MF",
            11.0,
            6.6,
            fixture_opponent="Besiktas",
            fixture_match_kind="derbi",
            odds_favorite="fenerbahce",
            odds_p_win=0.52,
        )
        add(
            "EnNesyri",
            "Fenerbahce",
            "FW",
            10.0,
            6.3,
            fixture_opponent="Besiktas",
            fixture_match_kind="derbi",
            odds_favorite="fenerbahce",
            odds_p_win=0.52,
        )
        add(
            "Osimhen",
            "Galatasaray",
            "FW",
            12.0,
            7.2,
            fixture_opponent="Basaksehir",
            fixture_match_kind="denk",
            odds_favorite="galatasaray",
            odds_p_win=0.48,
        )
        add("FWX", "Trabzonspor", "FW", 7.0, 4.0)
        add("FWY", "Sivasspor", "FW", 6.0, 3.6)
        result = optimize_squad(pd.DataFrame(rows), autosub_draws=16)
        names = set(result["squad"]["player"].astype(str))
        self.assertNotIn("Cerny", names)
        self.assertNotIn("Vlahovic", names)
        self.assertTrue(bool(names & {"Greenwood", "EnNesyri"}))
        self.assertIn("Osimhen", set(result["xi"]["player"].astype(str)))

    def test_over_blend_shifts_raw_lambdas(self) -> None:
        high = blend_lambdas_with_market(
            1.4,
            1.1,
            {"p_home": 0.55, "p_away": 0.25, "p_over_25": 0.70},
            home=True,
        )
        low = blend_lambdas_with_market(
            1.4,
            1.1,
            {"p_home": 0.55, "p_away": 0.25, "p_over_25": 0.32},
            home=True,
        )
        self.assertGreater(high[0] + high[1], low[0] + low[1])


if __name__ == "__main__":
    unittest.main()

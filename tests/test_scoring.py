import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from calibrate_leagues import is_domestic_league, season_start
from src.config import RED_PENALTY, YELLOW_PENALTY
from src.fetch_fotmob import (
    hot_form_blend_weight,
    hot_form_expected_points,
    readiness_multiplier,
    _soften_rate,
)
from src.manager_cards import choose_manager_card, manager_card_advice
from src.league_translation import (
    translate_external_rates,
    translate_metric,
    translate_metric_mixture,
)
from src.fetch_stats import blend_team_cs_rates
from src.names import best_match
from src.scoring import (
    _blend_rate_sets,
    _empty_rates,
    _recency_multiplier,
    apply_context_adjustments,
    blend_weights,
    estimate_play_probability,
    expected_points_from_rates,
    leftover_tff_season,
    lookup_fixture_context,
    recency_for_projection,
    shrink_small_sample_rates,
)


class ScoringTests(unittest.TestCase):
    def test_manager_cards_score_captain_and_full_bench_uplift(self) -> None:
        xi = pd.DataFrame(
            [
                {"player": "Kaleci", "team": "A", "position": "GK", "price_m": 4.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Defans 1", "team": "B", "position": "DF", "price_m": 4.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Defans 2", "team": "C", "position": "DF", "price_m": 4.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Defans 3", "team": "D", "position": "DF", "price_m": 4.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Defans 4", "team": "E", "position": "DF", "price_m": 4.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Orta 1", "team": "F", "position": "MF", "price_m": 5.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Orta 2", "team": "G", "position": "MF", "price_m": 5.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Orta 3", "team": "H", "position": "MF", "price_m": 5.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Orta 4", "team": "I", "position": "MF", "price_m": 5.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Forvet 1", "team": "J", "position": "FW", "price_m": 6.0, "projected_pts": 3.0, "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "Kaptan", "team": "K", "position": "FW", "price_m": 6.0, "projected_pts": 5.0, "pts_if_plays": 5.0, "play_probability": 1.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Yedek 1", "position": "MF", "projected_pts": 4.0, "pts_if_plays": 4.0, "play_probability": 1.0},
                {"player": "Yedek 2", "position": "FW", "projected_pts": 4.0, "pts_if_plays": 4.0, "play_probability": 1.0},
            ]
        )
        pool = pd.concat([xi, bench], ignore_index=True).fillna(
            {"team": "Y", "position": "MF", "price_m": 4.0}
        )
        result = {
            "xi": xi,
            "bench": bench,
            "captain": {"player": "Kaptan", "projected_pts": 5.0, "pts_if_plays": 5.0, "play_probability": 1.0},
            "total_projected": 38.0,
        }
        cards = {card["card"]: card for card in manager_card_advice(result, pool, budget=100)}

        self.assertEqual(cards["Tripleks Kaptan"]["extra_pts"], 5.0)
        self.assertEqual(cards["Dört Dörtlük Kaptan"]["extra_pts"], 10.0)
        self.assertGreaterEqual(cards["Tüm Takım Sahaya"]["extra_pts"], 0.0)

    def test_manager_recommends_only_one_card_or_hold(self) -> None:
        hold = choose_manager_card(
            [
                {"card": "Dört Dörtlük Kaptan", "extra_pts": 10.9, "why": "4x"},
                {"card": "Tüm Takım Sahaya", "extra_pts": 7.4, "why": "bench"},
            ]
        )
        use = choose_manager_card(
            [
                {"card": "Tripleks Kaptan", "extra_pts": 8.0, "why": "3x"},
                {"card": "Tüm Takım Sahaya", "extra_pts": 7.0, "why": "bench"},
            ],
            remaining=4,
            weeks_left=10,
        )

        self.assertFalse(hold["use"])
        self.assertEqual(hold["card"], "Kart kullanma")
        self.assertTrue(use["use"])
        self.assertEqual(use["card"], "Tripleks Kaptan")

    def test_fotmob_hot_form_softens_two_goal_burst(self) -> None:
        self.assertAlmostEqual(
            _soften_rate(2.0, 1.0, 0.40),
            6.0 / 11.0,
            places=5,
        )
        first_week_weight = hot_form_blend_weight(
            1.0,
            90.0,
            early_season=True,
        )
        self.assertGreater(first_week_weight, 0.05)
        self.assertLess(first_week_weight, 0.08)
        first_form, first_base = blend_weights(1.0)
        full_form, full_base = blend_weights(6.0)
        self.assertAlmostEqual(first_form, 1.0 / 5.0)
        self.assertAlmostEqual(first_base, 4.0 / 5.0)
        self.assertAlmostEqual(full_form, 0.30)
        self.assertAlmostEqual(full_base, 0.70)

        hot = hot_form_expected_points(
            {
                "fotmob_sl_apps": 1.0,
                "fotmob_sl_minutes": 90.0,
                "fotmob_sl_goals": 2.0,
                "fotmob_sl_assists": 0.0,
                "fotmob_sl_rating": 9.0,
            },
            "FW",
        )
        self.assertIsNotNone(hot)
        assert hot is not None
        self.assertGreater(hot, 4.0)
        self.assertLess(hot, 7.0)

        blended = (1.0 - first_week_weight) * 4.97 + first_week_weight * hot
        self.assertGreater(blended, 4.8)
        self.assertLess(blended, 5.2)

    def test_current_small_sample_is_blended_not_discarded(self) -> None:
        current = _empty_rates()
        current.update({"apps": 7.0, "gls_pa": 2 / 7, "ast_pa": 0.0})
        previous = _empty_rates()
        previous.update({"apps": 34.0, "gls_pa": 9 / 34, "ast_pa": 8 / 34})

        blended, current_weight = _blend_rate_sets(current, previous, 7.0)

        self.assertAlmostEqual(current_weight, 7 / 17)
        self.assertGreater(blended["gls_pa"], previous["gls_pa"])
        self.assertLess(blended["ast_pa"], previous["ast_pa"])

    def test_single_clean_sheet_is_shrunk_for_goalkeepers(self) -> None:
        one_match = _empty_rates()
        one_match.update(
            {
                "apps": 1.0,
                "apps_60": 1.0,
                "share_60": 1.0,
                "min_per_app": 90.0,
                "cs_rate": 1.0,
                "saves_pa": 1.0,
                "ga_pa": 0.0,
                "rating": 7.4,
            }
        )
        shrunk, weight = shrink_small_sample_rates(one_match, "GK")
        raw = expected_points_from_rates(one_match, "GK", appearance=1.0)
        tempered = expected_points_from_rates(shrunk, "GK", appearance=1.0)

        self.assertAlmostEqual(weight, 1 / 9)
        self.assertLess(shrunk["cs_rate"], 0.45)
        self.assertGreater(shrunk["saves_pa"], 2.0)
        self.assertLess(tempered, raw)
        self.assertLess(tempered, 5.0)

    def test_count_metrics_get_more_early_season_weight_than_rare_events(self) -> None:
        current = _empty_rates()
        current.update(
            {
                "apps": 1.0,
                "cs_rate": 1.0,
                "saves_pa": 6.0,
                "gls_pa": 0.0,
            }
        )
        previous = _empty_rates()
        previous.update(
            {
                "apps": 30.0,
                "cs_rate": 0.30,
                "saves_pa": 3.0,
                "gls_pa": 0.0,
            }
        )
        blended, _ = _blend_rate_sets(current, previous, 1.0)
        self.assertLess(blended["cs_rate"], 0.45)
        self.assertGreater(blended["saves_pa"], 3.5)
        self.assertGreater(blended["saves_pa"], blended["cs_rate"] + 3.0)

    def test_early_team_cs_is_blended_not_taken_as_certainty(self) -> None:
        blended = blend_team_cs_rates(
            {"Rizespor": 1.0, "Başakşehir": 0.0},
            {"Rizespor": 0.30, "Başakşehir": 0.36},
            {"Rizespor": 1.0, "Başakşehir": 0.0},
        )
        self.assertGreater(blended["Rizespor"], 0.30)
        self.assertLess(blended["Rizespor"], 0.45)
        self.assertAlmostEqual(blended["Başakşehir"], 0.36)

        four = blend_team_cs_rates(
            {"Rizespor": 1.0},
            {"Rizespor": 0.30},
            {"Rizespor": 4.0},
        )
        self.assertLess(four["Rizespor"], 1.0)
        self.assertAlmostEqual(four["Rizespor"], 4 / 12 * 1.0 + 8 / 12 * 0.30, places=5)

        perfect = expected_points_from_rates(
            {"apps": 10, "share_60": 1.0, "min_per_app": 90, "saves_pa": 3.0},
            "GK",
            team_cs_rate=1.0,
            appearance=1.0,
        )
        tempered = expected_points_from_rates(
            {"apps": 10, "share_60": 1.0, "min_per_app": 90, "saves_pa": 3.0},
            "GK",
            team_cs_rate=blended["Rizespor"],
            appearance=1.0,
        )
        self.assertLess(tempered, perfect - 1.5)

    def test_appearance_probability_scales_attacking_returns(self) -> None:
        rates = _empty_rates()
        rates.update(
            {
                "apps": 10.0,
                "min_per_app": 80.0,
                "share_60": 1.0,
                "gls_pa": 0.5,
                "xg_pa": 0.5,
                "ast_pa": 0.2,
                "xa_pa": 0.2,
                "rating": 7.0,
            }
        )

        certain = expected_points_from_rates(rates, "MF", appearance=1.0)
        half = expected_points_from_rates(rates, "MF", appearance=0.5)

        self.assertAlmostEqual(half, certain * 0.5, places=6)

    def test_cards_reduce_projection(self) -> None:
        clean = _empty_rates()
        clean.update({"apps": 10.0, "min_per_app": 80.0, "share_60": 1.0})
        carded = clean.copy()
        carded.update({"yc_pa": 0.2, "rc_pa": 0.1})

        clean_points = expected_points_from_rates(clean, "MF", appearance=1.0)
        carded_points = expected_points_from_rates(carded, "MF", appearance=1.0)

        self.assertAlmostEqual(
            clean_points - carded_points,
            0.2 * YELLOW_PENALTY + 0.1 * RED_PENALTY,
            places=6,
        )

    def test_official_tff_points_calibrate_only_after_minutes_exist(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "A",
                    "team": "X",
                    "position": "MF",
                    "projected_pts": 4.0,
                    "price_m": 7.0,
                    "data_src": "super_lig",
                    "form_apps": 6,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 750,
                    "tff_starts": 10,
                    "tff_points": 60,
                    "tff_ppm": 6.0,
                },
                {
                    "player": "B",
                    "team": "Y",
                    "position": "MF",
                    "projected_pts": 4.0,
                    "price_m": 7.0,
                    "data_src": "super_lig",
                    "form_apps": 6,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 0,
                    "tff_starts": 0,
                    "tff_points": 0,
                    "tff_ppm": 0,
                },
            ]
        )

        adjusted = apply_context_adjustments(frame)

        self.assertGreater(adjusted.loc[0, "pts_if_plays"], 4.0)
        self.assertAlmostEqual(adjusted.loc[1, "pts_if_plays"], 4.0)

    def test_first_official_match_has_conservative_weight(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Osimhen",
                    "team": "Galatasaray",
                    "position": "FW",
                    "projected_pts": 5.0,
                    "form_apps": 1,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 90,
                    "tff_starts": 1,
                    "tff_points": 13,
                    "tff_ppm": 13,
                }
            ]
        )

        adjusted = apply_context_adjustments(frame)

        weight = float(adjusted.loc[0, "tff_calibration_weight"])
        self.assertGreater(weight, 0.12)
        self.assertLess(weight, 0.20)
        self.assertGreater(float(adjusted.loc[0, "pts_if_plays"]), 5.0)
        self.assertLess(float(adjusted.loc[0, "pts_if_plays"]), 7.0)

    def test_lucky_one_week_haul_does_not_outrank_established_star(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Şanslı Forvet",
                    "team": "X",
                    "position": "FW",
                    "price_m": 5.5,
                    "projected_pts": 3.5,
                    "form_apps": 1,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 90,
                    "tff_starts": 1,
                    "tff_points": 14,
                    "tff_ppm": 14,
                },
                {
                    "player": "Talisca",
                    "team": "Fenerbahçe",
                    "position": "FW",
                    "price_m": 11.0,
                    "projected_pts": 6.2,
                    "form_apps": 2,
                    "min_per_app": 90,
                    "established_sl_apps": 20,
                    "availability": "AVAILABLE",
                    "tff_minutes": 180,
                    "tff_starts": 2,
                    "tff_points": 12,
                    "tff_ppm": 6,
                },
            ]
        )

        adjusted = apply_context_adjustments(frame)

        self.assertGreater(
            float(adjusted.loc[1, "pts_if_plays"]),
            float(adjusted.loc[0, "pts_if_plays"]),
        )

    def test_repeat_high_official_weeks_raise_star_projection(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Yildiz Forvet",
                    "team": "Y",
                    "position": "FW",
                    "price_m": 12.0,
                    "projected_pts": 5.8,
                    "form_apps": 2,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 180,
                    "tff_starts": 0,
                    "tff_points": 29,
                    "tff_ppm": 14.5,
                }
            ]
        )
        adjusted = apply_context_adjustments(frame)
        pts = float(adjusted.loc[0, "pts_if_plays"])
        self.assertGreaterEqual(pts, 8.5)
        self.assertLess(pts, 13.0)

    def test_one_week_high_score_starter_stays_selectable(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Ucuza Patlayan",
                    "team": "Z",
                    "position": "MF",
                    "price_m": 5.5,
                    "projected_pts": 3.7,
                    "form_apps": 1,
                    "min_per_app": 77,
                    "availability": "AVAILABLE",
                    "tff_minutes": 77,
                    "tff_starts": 0,
                    "tff_points": 16,
                    "tff_ppm": 16,
                }
            ]
        )
        adjusted = apply_context_adjustments(frame)
        self.assertTrue(bool(adjusted.loc[0, "selection_eligible"]))
        self.assertGreaterEqual(float(adjusted.loc[0, "pts_if_plays"]), 3.4)
        self.assertLess(float(adjusted.loc[0, "pts_if_plays"]), 5.2)

    def test_fotmob_injury_blocks_selection_even_if_tff_says_available(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Sakat Yildiz",
                    "team": "A",
                    "position": "FW",
                    "price_m": 12.0,
                    "projected_pts": 9.0,
                    "form_apps": 6,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 180,
                    "tff_points": 29,
                    "tff_ppm": 14.5,
                    "fotmob_injury": True,
                },
                {
                    "player": "Saglam Forvet",
                    "team": "B",
                    "position": "FW",
                    "price_m": 8.0,
                    "projected_pts": 5.5,
                    "form_apps": 6,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 180,
                    "tff_points": 10,
                    "tff_ppm": 5.0,
                    "fotmob_injury": False,
                },
            ]
        )
        adjusted = apply_context_adjustments(frame)
        self.assertFalse(bool(adjusted.loc[0, "selection_eligible"]))
        self.assertEqual(float(adjusted.loc[0, "play_probability"]), 0.0)
        self.assertTrue(bool(adjusted.loc[1, "selection_eligible"]))
        self.assertGreater(float(adjusted.loc[1, "projected_pts"]), 0.0)

    def test_projection_is_not_raw_tff_points_per_match(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Ham 16 Ppm",
                    "team": "A",
                    "position": "MF",
                    "price_m": 5.5,
                    "projected_pts": 3.6,
                    "form_apps": 1,
                    "min_per_app": 77,
                    "availability": "AVAILABLE",
                    "tff_minutes": 77,
                    "tff_starts": 0,
                    "tff_points": 16,
                    "tff_ppm": 16,
                },
                {
                    "player": "Model 6 Ppm",
                    "team": "B",
                    "position": "FW",
                    "price_m": 11.0,
                    "projected_pts": 6.2,
                    "form_apps": 2,
                    "min_per_app": 90,
                    "established_sl_apps": 20,
                    "availability": "AVAILABLE",
                    "tff_minutes": 180,
                    "tff_starts": 2,
                    "tff_points": 12,
                    "tff_ppm": 6,
                },
            ]
        )
        adjusted = apply_context_adjustments(frame)
        cheap = float(adjusted.loc[0, "pts_if_plays"])
        star = float(adjusted.loc[1, "pts_if_plays"])
        self.assertLess(cheap, 5.2)
        self.assertLess(star, 9.0)
        self.assertNotAlmostEqual(cheap, 16.0, places=1)
        self.assertGreater(cheap, 3.4)
        self.assertGreater(star, 5.5)

    def test_current_week_goalkeeper_tff_ranks_clean_sheet_over_collapse(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Iyi Hafta Kaleci",
                    "team": "A",
                    "position": "GK",
                    "price_m": 4.5,
                    "projected_pts": 4.7,
                    "form_apps": 1,
                    "min_per_app": 90,
                    "current_minutes": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 90,
                    "tff_starts": 0,
                    "tff_points": 9,
                    "tff_ppm": 9,
                },
                {
                    "player": "Uc Gol Kaleci",
                    "team": "B",
                    "position": "GK",
                    "price_m": 4.5,
                    "projected_pts": 4.5,
                    "form_apps": 1,
                    "min_per_app": 90,
                    "current_minutes": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 90,
                    "tff_starts": 0,
                    "tff_points": 1,
                    "tff_ppm": 1,
                },
            ]
        )
        adjusted = apply_context_adjustments(frame)
        self.assertGreater(
            float(adjusted.loc[0, "pts_if_plays"]),
            float(adjusted.loc[1, "pts_if_plays"]),
        )
        self.assertGreater(
            float(adjusted.loc[0, "projected_pts"]),
            float(adjusted.loc[1, "projected_pts"]),
        )

    def test_goalkeeper_depth_prevents_single_old_clean_sheet_from_starting(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Takımın Birincisi",
                    "team": "Başakşehir",
                    "position": "GK",
                    "projected_pts": 4.8,
                    "base_apps": 33,
                    "min_per_app": 90,
                    "form_apps": 0,
                    "availability": "AVAILABLE",
                },
                {
                    "player": "Tek Maçlık Yedek",
                    "team": "Başakşehir",
                    "position": "GK",
                    "projected_pts": 6.4,
                    "base_apps": 1,
                    "min_per_app": 90,
                    "form_apps": 0,
                    "availability": "AVAILABLE",
                },
            ]
        )

        adjusted = apply_context_adjustments(frame)

        self.assertAlmostEqual(adjusted.loc[0, "gk_start_probability"], 0.95)
        self.assertLess(adjusted.loc[1, "gk_start_probability"], 0.10)
        self.assertGreater(
            adjusted.loc[0, "projected_pts"],
            adjusted.loc[1, "projected_pts"],
        )

    def test_leftover_tff_backup_does_not_outrank_current_goalkeeper(self) -> None:
        self.assertTrue(leftover_tff_season(1800, 0))
        self.assertFalse(leftover_tff_season(90, 1))
        frame = pd.DataFrame(
            [
                {
                    "player": "Guncel Kaleci",
                    "team": "A",
                    "position": "GK",
                    "projected_pts": 4.1,
                    "price_m": 4.5,
                    "base_apps": 1,
                    "min_per_app": 90,
                    "form_apps": 1,
                    "current_minutes": 90,
                    "tff_minutes": 90,
                    "tff_starts": 1,
                    "availability": "AVAILABLE",
                },
                {
                    "player": "Eski Yedek",
                    "team": "A",
                    "position": "GK",
                    "projected_pts": 5.8,
                    "price_m": 4.5,
                    "base_apps": 33,
                    "min_per_app": 90,
                    "form_apps": 0,
                    "current_minutes": 0,
                    "tff_minutes": 1800,
                    "tff_starts": 20,
                    "availability": "AVAILABLE",
                },
            ]
        )
        adjusted = apply_context_adjustments(frame)
        self.assertGreater(
            float(adjusted.loc[0, "gk_start_probability"]),
            float(adjusted.loc[1, "gk_start_probability"]),
        )
        self.assertGreater(
            float(adjusted.loc[0, "projected_pts"]),
            float(adjusted.loc[1, "projected_pts"]),
        )

    def test_unused_last_season_goalkeeper_has_lower_play_probability(self) -> None:
        current = {
            "player": "Bu Sezon Oynayan",
            "team": "A",
            "position": "GK",
            "form_apps": 1,
            "min_per_app": 90,
            "current_minutes": 90,
            "tff_minutes": 90,
            "tff_starts": 1,
            "gk_start_probability": 1.0,
            "availability": "AVAILABLE",
        }
        unused = {
            "player": "Gecen Sezon Kaleci",
            "team": "B",
            "position": "GK",
            "form_apps": 0,
            "min_per_app": 90,
            "current_minutes": 0,
            "tff_minutes": 1800,
            "tff_starts": 34,
            "gk_start_probability": 1.0,
            "availability": "AVAILABLE",
        }
        self.assertGreater(
            estimate_play_probability(current),
            estimate_play_probability(unused) + 0.25,
        )

    def test_zero_minute_backup_gk_has_crushed_play_probability(self) -> None:
        unused = {
            "player": "Bilal Bayazit",
            "team": "Samsunspor",
            "position": "GK",
            "form_apps": 5,
            "min_per_app": 90,
            "current_minutes": 0,
            "tff_minutes": 0,
            "tff_starts": 0,
            "availability": "AVAILABLE",
        }
        self.assertLess(estimate_play_probability(unused), 0.20)

    def test_unused_last_season_attacker_has_lower_play_probability(self) -> None:
        current = {
            "player": "Muriqi",
            "team": "Fenerbahçe",
            "position": "FW",
            "form_apps": 1,
            "min_per_app": 85,
            "current_minutes": 80,
            "tff_minutes": 80,
            "tff_starts": 1,
            "availability": "AVAILABLE",
        }
        unused = {
            "player": "Talisca",
            "team": "Fenerbahçe",
            "position": "FW",
            "form_apps": 0,
            "min_per_app": 88,
            "current_minutes": 0,
            "tff_minutes": 2100,
            "tff_starts": 28,
            "availability": "AVAILABLE",
        }
        self.assertGreater(
            estimate_play_probability(current),
            estimate_play_probability(unused) + 0.35,
        )

    def test_one_match_three_goals_conceded_does_not_crush_goalkeeper(self) -> None:
        rates = _empty_rates()
        rates.update(
            {
                "apps": 1.0,
                "apps_60": 1.0,
                "share_60": 1.0,
                "min_per_app": 90.0,
                "cs_rate": 0.0,
                "ga_pa": 3.0,
                "saves_pa": 4.0,
                "rating": 6.8,
            }
        )
        pts = expected_points_from_rates(
            rates,
            "GK",
            team_cs_rate=0.30,
            appearance=1.0,
        )
        self.assertGreater(pts, 3.0)
        thin = expected_points_from_rates(
            rates,
            "GK",
            appearance=1.0,
        )
        crushed = expected_points_from_rates(
            {**rates, "apps": 10.0},
            "GK",
            appearance=1.0,
        )
        self.assertGreater(thin, crushed)

    def test_mid_price_current_starter_gets_selection_floor(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Orta Fiyat Forvet",
                    "team": "X",
                    "position": "FW",
                    "price_m": 7.0,
                    "projected_pts": 2.0,
                    "form_apps": 1,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 90,
                    "tff_starts": 1,
                    "tff_points": 2,
                    "tff_ppm": 2,
                    "tff_xg": 0.6,
                    "xg_pa": 0.0,
                }
            ]
        )
        adjusted = apply_context_adjustments(frame)
        self.assertGreaterEqual(float(adjusted.loc[0, "pts_if_plays"]), 3.4)
        self.assertGreater(float(adjusted.loc[0, "xg_pa"]), 0.0)

    def test_long_surname_variant_matches_without_alias_list(self) -> None:
        matched, score = best_match(
            "Luka Verylongsurname",
            ["Verylongsurname", "Other Player"],
        )
        self.assertEqual(matched, "Verylongsurname")
        self.assertGreaterEqual(score, 78)

    def test_injured_and_suspended_players_are_not_selection_eligible(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "A",
                    "team": "T",
                    "position": "MF",
                    "projected_pts": 5.0,
                    "min_per_app": 90,
                    "form_apps": 6,
                    "availability": "AVAILABLE",
                },
                {
                    "player": "B",
                    "team": "T",
                    "position": "MF",
                    "projected_pts": 5.0,
                    "min_per_app": 90,
                    "form_apps": 6,
                    "availability": "INJURED",
                },
                {
                    "player": "C",
                    "team": "T",
                    "position": "MF",
                    "projected_pts": 5.0,
                    "min_per_app": 90,
                    "form_apps": 6,
                    "availability": "SUSPENDED",
                },
                {
                    "player": "D",
                    "team": "T",
                    "position": "MF",
                    "projected_pts": 5.0,
                    "min_per_app": 90,
                    "form_apps": 6,
                    "availability": "DOUBTFUL",
                    "avail_pct": 60,
                },
            ]
        )

        adjusted = apply_context_adjustments(frame)

        self.assertEqual(adjusted["selection_eligible"].tolist(), [True, False, False, True])
        self.assertEqual(adjusted.loc[1, "play_probability"], 0.0)
        self.assertEqual(adjusted.loc[2, "play_probability"], 0.0)
        self.assertLess(adjusted.loc[3, "play_probability"], adjusted.loc[0, "play_probability"])

    def test_leftover_full_season_tff_points_are_ignored(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Asensio",
                    "team": "Fenerbahçe",
                    "position": "MF",
                    "projected_pts": 4.0,
                    "price_m": 10.0,
                    "data_src": "super_lig",
                    "form_apps": 1,
                    "min_per_app": 90,
                    "availability": "AVAILABLE",
                    "tff_minutes": 1886,
                    "tff_starts": 25,
                    "tff_points": 150,
                    "tff_ppm": 6.0,
                }
            ]
        )

        adjusted = apply_context_adjustments(frame)

        self.assertAlmostEqual(adjusted.loc[0, "pts_if_plays"], 4.0)
        self.assertEqual(adjusted.loc[0, "tff_calibration_weight"], 0.0)

    def test_fixture_team_aliases_match(self) -> None:
        context = {"basaksehir fk": {"opponent": "Kocaelispor"}}
        fixture = lookup_fixture_context("İstanbul Başakşehir", context)
        self.assertEqual(fixture["opponent"], "Kocaelispor")

    def test_talisca_alias_matches(self) -> None:
        matched, score = best_match(
            "Anderson Talisca",
            ["Talisca", "Other"],
        )
        self.assertEqual(matched, "Talisca")
        self.assertGreaterEqual(score, 78)

    def test_missing_recent_appearances_reduce_weekly_projection(self) -> None:
        self.assertEqual(_recency_multiplier(6, 6), 1.0)
        self.assertAlmostEqual(_recency_multiplier(0, 6), 0.72)
        self.assertGreater(_recency_multiplier(5, 6), 0.9)
        self.assertEqual(recency_for_projection(1, 6, preseason=True), 1.0)
        self.assertAlmostEqual(recency_for_projection(1, 6, preseason=False), 0.72 + 0.28 / 6)

    def test_current_club_matches_restore_readiness(self) -> None:
        self.assertEqual(readiness_multiplier(4, 280), 1.0)
        self.assertGreater(readiness_multiplier(2, 180), 0.85)
        self.assertEqual(readiness_multiplier(0, 0), 0.65)

    def test_exact_league_translation_beats_global_fallback(self) -> None:
        model = {
            "global": {
                "positions": {
                    "MF": {
                        "goals_p90": {
                            "intercept": 0.0,
                            "slope": 0.9,
                            "cap": 2.0,
                            "n_players": 100,
                        }
                    }
                }
            },
            "leagues": {
                "98": {
                    "name": "Trendyol 1.Lig",
                    "positions": {
                        "MF": {
                            "goals_p90": {
                                "intercept": 0.0,
                                "slope": 0.7,
                                "cap": 2.0,
                                "n_players": 25,
                                "local_weight": 0.6,
                            }
                        }
                    },
                }
            },
        }
        exact, exact_meta = translate_metric(model, 98, "MF", "goals_p90", 0.5)
        fallback, fallback_meta = translate_metric(model, 999, "MF", "goals_p90", 0.5)
        mixed, _ = translate_metric_mixture(
            model,
            [
                {"tournament_id": 98, "weight": 0.5},
                {"tournament_id": 999, "weight": 0.5},
            ],
            "MF",
            "goals_p90",
            0.5,
        )

        self.assertAlmostEqual(exact, 0.35)
        self.assertAlmostEqual(fallback, 0.45)
        self.assertAlmostEqual(mixed, 0.40)
        self.assertEqual(exact_meta["level"], "league")
        self.assertEqual(fallback_meta["level"], "global")

    def test_star_goal_rate_mixes_toward_source_not_squad_mean(self) -> None:
        model = {
            "leagues": {
                "34": {
                    "name": "Ligue 1",
                    "observed_source_ga_p90": 0.20,
                    "positions": {
                        "FW": {
                            "goals_p90": {
                                "intercept": 0.22,
                                "slope": 0.55,
                                "cap": 1.22,
                                "n_players": 13,
                                "local_weight": 0.7,
                            }
                        }
                    },
                }
            }
        }
        source = 0.61
        predicted, meta = translate_metric(model, 34, "FW", "goals_p90", source)
        regression = 0.22 + 0.55 * source

        self.assertGreater(predicted, regression)
        self.assertLess(predicted, source)
        self.assertGreater(meta["identity_mix"], 0.25)
        self.assertLessEqual(meta["identity_mix"], 0.38)

    def test_typical_goal_rate_keeps_regression(self) -> None:
        model = {
            "leagues": {
                "34": {
                    "name": "Ligue 1",
                    "observed_source_ga_p90": 0.20,
                    "positions": {
                        "FW": {
                            "goals_p90": {
                                "intercept": 0.0,
                                "slope": 0.66,
                                "cap": 1.22,
                                "n_players": 13,
                                "local_weight": 0.7,
                            }
                        }
                    },
                }
            }
        }
        source = 0.10
        predicted, meta = translate_metric(model, 34, "FW", "goals_p90", source)
        self.assertAlmostEqual(predicted, 0.066)
        self.assertEqual(meta["identity_mix"], 0.0)

    def test_tier_peer_fallback_beats_global_when_league_weight_is_zero(self) -> None:
        model = {
            "global": {
                "positions": {
                    "FW": {
                        "goals_p90": {
                            "intercept": 0.0,
                            "slope": 0.4,
                            "cap": 2.0,
                            "n_players": 100,
                        }
                    }
                }
            },
            "leagues": {
                "34": {
                    "name": "Ligue 1",
                    "positions": {
                        "FW": {
                            "goals_p90": {
                                "intercept": 0.0,
                                "slope": 0.8,
                                "cap": 2.0,
                                "n_players": 20,
                                "local_weight": 0.6,
                            }
                        }
                    },
                },
                "17": {"name": "Premier League", "positions": {}},
            },
        }
        predicted, meta = translate_metric(model, 17, "FW", "goals_p90", 0.5)
        self.assertEqual(meta["level"], "tier")
        self.assertAlmostEqual(predicted, 0.4)

    def test_translation_converts_per90_back_to_projected_minutes(self) -> None:
        model = {
            "global": {
                "positions": {
                    "MF": {
                        "goals_p90": {
                            "intercept": 0.0,
                            "slope": 0.5,
                            "cap": 2.0,
                            "n_players": 50,
                        },
                        "assists_p90": {
                            "intercept": 0.0,
                            "slope": 1.0,
                            "cap": 2.0,
                            "n_players": 50,
                        },
                        "clean_sheet_rate": {
                            "intercept": 0.0,
                            "slope": 1.0,
                            "cap": 1.0,
                            "n_players": 50,
                        },
                    }
                }
            },
            "leagues": {},
        }
        rates = _empty_rates()
        rates.update(
            {
                "apps": 10.0,
                "min_per_app": 90.0,
                "gls_pa": 0.4,
                "ast_pa": 0.2,
                "cs_rate": 0.3,
            }
        )

        translated, _ = translate_external_rates(
            rates,
            {"tournament_id": 999, "tournament": "Test League"},
            "MF",
            60.0,
            model=model,
        )

        self.assertAlmostEqual(translated["gls_pa"], 0.4 * 0.5 * 60 / 90)
        self.assertAlmostEqual(translated["ast_pa"], 0.2 * 60 / 90)

    def test_team_clean_sheet_prior_overrides_old_club_conceding_rate(self) -> None:
        low_concede = _empty_rates()
        low_concede.update(
            {
                "apps": 10.0,
                "min_per_app": 90.0,
                "share_60": 1.0,
                "ga_pa": 0.4,
                "cs_rate": 0.5,
            }
        )
        high_concede = low_concede.copy()
        high_concede["ga_pa"] = 2.4

        low = expected_points_from_rates(
            low_concede, "GK", team_cs_rate=0.45, appearance=1.0
        )
        high = expected_points_from_rates(
            high_concede, "GK", team_cs_rate=0.45, appearance=1.0
        )

        self.assertAlmostEqual(low, high)

    def test_calibration_source_filter_keeps_leagues_not_cups(self) -> None:
        self.assertEqual(season_start("24/25"), 2024)
        self.assertTrue(
            is_domestic_league(
                {"tournament_id": 98, "tournament": "Trendyol 1.Lig"}
            )
        )
        self.assertTrue(
            is_domestic_league(
                {"tournament_id": 53, "tournament": "Serie B"}
            )
        )
        self.assertFalse(
            is_domestic_league(
                {"tournament_id": 96, "tournament": "Türkiye Kupası"}
            )
        )
        self.assertFalse(
            is_domestic_league(
                {"tournament_id": 373, "tournament": "Copa Betano do Brasil"}
            )
        )

    def test_autosub_replaces_goalkeeper_only_with_goalkeeper(self) -> None:
        from src.autosub import apply_autosub, is_legal_xi

        self.assertTrue(is_legal_xi(["GK", "DF", "DF", "DF", "MF", "MF", "MF", "MF", "FW", "FW", "FW"]))
        self.assertFalse(is_legal_xi(["GK", "DF", "DF", "MF", "MF", "MF", "MF", "MF", "FW", "FW", "FW"]))

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0, "play_probability": 0.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Bench DF", "position": "DF", "pts_if_plays": 5.0, "play_probability": 1.0},
                {"player": "Bench GK", "position": "GK", "pts_if_plays": 3.5, "play_probability": 1.0},
            ]
        )
        played = {name: name != "XI GK" for name in list(xi["player"]) + list(bench["player"])}
        final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(events[0]["in"], "Bench GK")
        self.assertIn("Bench GK", final_xi["player"].tolist())
        self.assertNotIn("Bench DF", final_xi["player"].tolist())

    def test_autosub_skips_illegal_outfield_swap_and_uses_next_bench(self) -> None:
        from src.autosub import apply_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF5", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Bench FW", "position": "FW", "pts_if_plays": 5.0},
                {"player": "Bench DF", "position": "DF", "pts_if_plays": 4.0},
            ]
        )
        played = {p: p != "DF1" for p in list(xi["player"]) + list(bench["player"])}
        final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(events[0]["in"], "Bench DF")
        self.assertIn("Bench DF", final_xi["player"].tolist())

    def test_autosub_prefers_same_position_over_higher_scoring_other_line(self) -> None:
        from src.autosub import apply_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF5", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Bench FW", "position": "FW", "pts_if_plays": 8.0},
                {"player": "Bench DF", "position": "DF", "pts_if_plays": 4.0},
            ]
        )
        played = {p: p != "DF1" for p in list(xi["player"]) + list(bench["player"])}
        _final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(events[0]["in"], "Bench DF")

    def test_bench_order_shows_autosub_rank(self) -> None:
        from src.autosub import order_bench_for_autosub

        bench = pd.DataFrame(
            [
                {"player": "Yedek FW", "position": "FW", "pts_if_plays": 5.0, "play_probability": 0.8},
                {"player": "Yedek KL", "position": "GK", "pts_if_plays": 3.0, "play_probability": 0.7},
                {"player": "Yedek OS", "position": "MF", "pts_if_plays": 4.0, "play_probability": 0.9},
            ]
        )
        ordered = order_bench_for_autosub(bench)
        self.assertEqual(str(ordered.iloc[0]["position"]), "GK")
        self.assertEqual(int(ordered.iloc[0]["bench_rank"]), 0)
        self.assertEqual(str(ordered.iloc[1]["position"]), "MF")
        self.assertEqual(int(ordered.iloc[1]["bench_rank"]), 1)
        self.assertEqual(list(ordered["player"]), ["Yedek KL", "Yedek OS", "Yedek FW"])

    def test_autosub_skips_unused_backup_gk_so_outfielder_enters(self) -> None:
        from src.autosub import apply_autosub, order_bench_for_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = order_bench_for_autosub(
            pd.DataFrame(
                [
                    {"player": "Yedek KL", "position": "GK", "pts_if_plays": 2.0, "play_probability": 0.1},
                    {"player": "Yedek OS", "position": "MF", "pts_if_plays": 8.0, "play_probability": 1.0},
                ]
            )
        )
        played = {name: True for name in list(xi["player"]) + list(bench["player"])}
        played["MF1"] = False
        played["Yedek KL"] = False
        final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(events[0]["in"], "Yedek OS")
        self.assertIn("Yedek OS", final_xi["player"].tolist())
        self.assertNotIn("Yedek KL", final_xi["player"].tolist())

    def test_expected_squad_points_rewards_useful_bench_cover(self) -> None:
        from src.autosub import expected_squad_points

        xi = pd.DataFrame(
            [
                {"player": "Risky GK", "position": "GK", "pts_if_plays": 5.0, "play_probability": 0.2},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0, "play_probability": 1.0},
            ]
        )
        covered = expected_squad_points(
            xi,
            pd.DataFrame(
                [{"player": "Cover GK", "position": "GK", "pts_if_plays": 4.0, "play_probability": 1.0}]
            ),
            draws=200,
        )
        uncovered = expected_squad_points(
            xi,
            pd.DataFrame(
                [{"player": "Useless FW", "position": "FW", "pts_if_plays": 8.0, "play_probability": 1.0}]
            ),
            draws=200,
        )
        self.assertGreater(covered["expected_pts"], uncovered["expected_pts"])

    def test_autosub_stops_after_first_legal_entry(self) -> None:
        from src.autosub import apply_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {
                    "player": "Bench DF",
                    "position": "DF",
                    "pts_if_plays": 4.0,
                    "bench_rank": 1,
                },
                {
                    "player": "Bench MF",
                    "position": "MF",
                    "pts_if_plays": 5.0,
                    "bench_rank": 2,
                },
            ]
        )
        played = {name: True for name in list(xi["player"]) + list(bench["player"])}
        played["DF1"] = False
        played["MF1"] = False
        final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["in"], "Bench DF")
        self.assertEqual(events[1]["in"], "Bench MF")
        self.assertIn("Bench DF", final_xi["player"].tolist())
        self.assertIn("Bench MF", final_xi["player"].tolist())

    def test_autosub_later_bench_cannot_jump_playing_earlier_slot(self) -> None:
        from src.autosub import apply_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Sira1", "position": "DF", "pts_if_plays": 4.0, "bench_rank": 1},
                {"player": "Sira3", "position": "MF", "pts_if_plays": 9.0, "bench_rank": 3},
            ]
        )
        played = {name: True for name in list(xi["player"]) + list(bench["player"])}
        played["DF1"] = False
        _final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["in"], "Sira1")

    def test_autosub_idle_rank_one_gives_way_to_rank_two(self) -> None:
        from src.autosub import apply_autosub

        xi = pd.DataFrame(
            [
                {"player": "XI GK", "position": "GK", "pts_if_plays": 4.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 3.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 3.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 3.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 3.0},
                {"player": "FW1", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW2", "position": "FW", "pts_if_plays": 3.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 3.0},
            ]
        )
        bench = pd.DataFrame(
            [
                {"player": "Sira1", "position": "DF", "pts_if_plays": 4.0, "bench_rank": 1},
                {"player": "Sira2", "position": "MF", "pts_if_plays": 5.0, "bench_rank": 2},
                {"player": "Sira3", "position": "FW", "pts_if_plays": 9.0, "bench_rank": 3},
            ]
        )
        played = {name: True for name in list(xi["player"]) + list(bench["player"])}
        played["MF1"] = False
        played["Sira1"] = False
        _final_xi, events = apply_autosub(xi, bench, played=played)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["in"], "Sira2")
        self.assertNotIn("Sira3", [event["in"] for event in events])

    def test_expected_squad_points_passes_armband_to_vice(self) -> None:
        from src.autosub import expected_squad_points

        xi = pd.DataFrame(
            [
                {"player": "Star", "position": "FW", "pts_if_plays": 8.0, "play_probability": 0.9},
                {"player": "Vice", "position": "FW", "pts_if_plays": 5.0, "play_probability": 1.0},
                {"player": "XI GK", "position": "GK", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "DF1", "position": "DF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "DF2", "position": "DF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "DF3", "position": "DF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "MF1", "position": "MF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "MF2", "position": "MF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "MF3", "position": "MF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "MF4", "position": "MF", "pts_if_plays": 2.0, "play_probability": 1.0},
                {"player": "FW3", "position": "FW", "pts_if_plays": 2.0, "play_probability": 1.0},
            ]
        )
        ev = expected_squad_points(xi, pd.DataFrame(), draws=40)
        self.assertEqual(ev["captain_player"], "Star")
        self.assertEqual(ev["vice_captain_player"], "Vice")
        self.assertGreater(ev["expected_pts"], 36.0)

    def test_hot_tff_round_lifts_vlahovic_like_forward(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "player": "Vlahović",
                    "team": "Beşiktaş",
                    "position": "FW",
                    "projected_pts": 4.0,
                    "price_m": 10.0,
                    "availability": "AVAILABLE",
                    "form_apps": 1,
                    "min_per_app": 80,
                    "tff_minutes": 104,
                    "tff_starts": 1,
                    "tff_points": 17,
                    "tff_round_points": 16,
                    "tff_goals": 3,
                    "tff_ppm": 8.5,
                    "gls_pa": 0.45,
                    "xg_pa": 0.40,
                    "fixture_match_kind": "denk",
                }
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertGreater(float(out.loc[0, "pts_if_plays"]), 6.0)

    def test_talisca_without_current_start_has_crushed_play_probability(self) -> None:
        unused = {
            "player": "Talisca",
            "team": "Fenerbahçe",
            "position": "FW",
            "form_apps": 0,
            "min_per_app": 88,
            "current_minutes": 0,
            "tff_minutes": 2100,
            "tff_starts": 28,
            "availability": "AVAILABLE",
        }
        self.assertLess(estimate_play_probability(unused), 0.20)

    def test_derby_side_pairs_detects_fener_besiktas(self) -> None:
        from src.optimize import _derby_side_pairs

        df = pd.DataFrame(
            [
                {
                    "team": "Fenerbahçe",
                    "fixture_opponent": "Beşiktaş",
                    "fixture_match_kind": "derbi",
                },
                {
                    "team": "Beşiktaş",
                    "fixture_opponent": "Fenerbahçe",
                    "fixture_match_kind": "derbi",
                },
                {
                    "team": "Galatasaray",
                    "fixture_opponent": "Konyaspor",
                    "fixture_match_kind": "kolay",
                },
            ]
        )
        pairs = _derby_side_pairs(df)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(set(pairs[0]), {"besiktas", "fenerbahce"})

    def test_even_fixture_pairs_detects_samsun_kocaeli(self) -> None:
        from src.optimize import _even_fixture_pairs

        df = pd.DataFrame(
            [
                {
                    "team": "Samsunspor",
                    "fixture_opponent": "Kocaelispor",
                    "fixture_match_kind": "",
                },
                {
                    "team": "Kocaelispor",
                    "fixture_opponent": "Samsunspor",
                },
                {
                    "team": "Galatasaray",
                    "fixture_opponent": "Başakşehir",
                    "fixture_match_kind": "kolay",
                },
            ]
        )
        pairs = _even_fixture_pairs(df)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(set(pairs[0]), {"kocaelispor", "samsunspor"})

    def test_optimize_keeps_one_derby_side_and_drops_joe_mendes(self) -> None:
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
        add(
            "Josafat Wooding Mendes",
            "Samsunspor",
            "DF",
            4.5,
            9.0,
            display_name="Joe Mendes",
            fixture_opponent="Kocaelispor",
        )
        add(
            "Haidara",
            "Kocaelispor",
            "DF",
            4.5,
            8.5,
            fixture_opponent="Samsunspor",
        )
        add(
            "Bayazit",
            "Samsunspor",
            "GK",
            4.0,
            8.0,
            play=0.10,
        )
        add(
            "Archie",
            "Fenerbahce",
            "DF",
            5.0,
            8.0,
            fixture_opponent="Besiktas",
            fixture_match_kind="derbi",
        )
        add(
            "Greenwood",
            "Fenerbahce",
            "MF",
            8.0,
            6.6,
            fixture_opponent="Besiktas",
            fixture_match_kind="derbi",
        )
        add(
            "Salih",
            "Besiktas",
            "MF",
            7.5,
            6.5,
            fixture_opponent="Fenerbahce",
            fixture_match_kind="derbi",
        )
        for i, club in enumerate(clubs[:6]):
            add(f"MF{i}", club, "MF", 5.0, 3.3)
        add(
            "Osimhen",
            "Galatasaray",
            "FW",
            14.0,
            7.2,
            fixture_opponent="Konyaspor",
            fixture_match_kind="kolay",
        )
        add(
            "EnNesyri",
            "Fenerbahce",
            "FW",
            10.0,
            6.3,
            fixture_opponent="Besiktas",
            fixture_match_kind="derbi",
        )
        add(
            "Immobile",
            "Besiktas",
            "FW",
            9.0,
            6.2,
            fixture_opponent="Fenerbahce",
            fixture_match_kind="derbi",
        )
        add("Talisca", "Fenerbahce", "FW", 8.5, 8.0, play=0.15)
        add("FWX", "Trabzonspor", "FW", 7.0, 4.0)
        add("FWY", "Sivasspor", "FW", 6.0, 3.6)
        result = optimize_squad(pd.DataFrame(rows), autosub_draws=16)
        names = set(result["squad"]["player"].astype(str))
        xi_names = set(result["xi"]["player"].astype(str))
        fb = names & {"Greenwood", "EnNesyri", "Talisca"}
        bjk = names & {"Salih", "Immobile"}
        self.assertFalse(bool(fb) and bool(bjk))
        self.assertNotIn("Joe Mendes", names)
        self.assertNotIn("Josafat Wooding Mendes", names)
        self.assertNotIn("Haidara", names)
        self.assertNotIn("Bayazit", names)
        self.assertLessEqual(len(names & {"Archie", "Greenwood", "EnNesyri", "Talisca"}), 2)
        self.assertNotIn("Talisca", xi_names)
        self.assertIn("Osimhen", xi_names)
        self.assertTrue(result.get("vice_captain", {}).get("player"))
        self.assertNotEqual(
            result["captain"]["player"], result["vice_captain"]["player"]
        )

    def test_optimize_limits_bottom_table_clubs_and_zero_minute_players(self) -> None:
        from src.optimize import optimize_squad

        rows = []

        def add(name, team, pos, price, pts, play=0.95, table_pos=9.0, **kw):
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
                    "table_pos": table_pos,
                    "table_n": 18.0,
                    **kw,
                }
            )

        mid_clubs = [
            "Konyaspor",
            "Rizespor",
            "Sivasspor",
            "Kayserispor",
            "Alanyaspor",
            "Eyupspor",
            "Goztepe",
            "Kasimpasa",
            "Antalyaspor",
            "Gaziantep FK",
        ]
        for i, club in enumerate(mid_clubs):
            add(f"GK{i}", club, "GK", 4.0, 3.4)
            add(f"DFa{i}", club, "DF", 4.5, 3.2)
            add(f"DFb{i}", club, "DF", 4.5, 3.1)
            add(f"MFa{i}", club, "MF", 5.0, 3.6)
            add(f"MFb{i}", club, "MF", 5.0, 3.5)
            add(f"FW{i}", club, "FW", 5.5, 3.8)

        # Dip sıradaki kulüpler yüksek puanla bile kadroyu doldurmamalı.
        for i, club in enumerate(["Çorum FK", "Amed Sportif Faaliyetler"]):
            add(f"BOTMF{i}", club, "MF", 5.0, 7.4, table_pos=18.0)
            add(f"BOTFW{i}", club, "FW", 5.5, 7.2, table_pos=17.0)
            add(f"BOTDF{i}", club, "DF", 4.5, 7.0, table_pos=18.0)

        add("Sifir Dakika", "Konyaspor", "DF", 4.5, 12.0, play=0.20)

        result = optimize_squad(pd.DataFrame(rows), autosub_draws=16)
        names = list(result["squad"]["player"].astype(str))
        xi_names = list(result["xi"]["player"].astype(str))
        self.assertNotIn("Sifir Dakika", names)
        bottom_in_squad = [n for n in names if n.startswith("BOT")]
        bottom_in_xi = [n for n in xi_names if n.startswith("BOT")]
        self.assertLessEqual(len(bottom_in_squad), 2)
        self.assertLessEqual(len(bottom_in_xi), 1)

    def test_merge_prices_rejects_same_surname_from_other_club(self) -> None:
        from src.load_prices import merge_prices

        stats = pd.DataFrame(
            [
                {
                    "player": "Barış Alper Yılmaz",
                    "team": "Galatasaray",
                    "position": "MF",
                    "projected_pts": 6.0,
                    "current_minutes": 253.0,
                    "form_apps": 3.0,
                    "min_per_app": 84.3,
                },
                {
                    "player": "Kerem Aktürkoğlu",
                    "team": "Galatasaray",
                    "position": "MF",
                    "projected_pts": 5.5,
                    "current_minutes": 240.0,
                    "form_apps": 3.0,
                    "min_per_app": 80.0,
                },
            ]
        )
        prices = pd.DataFrame(
            [
                {
                    "player_name": "Emirhan Yılmaz",
                    "display_name": "Emirhan Yılmaz",
                    "team": "Rizespor",
                    "position": "MF",
                    "price_m": 4.0,
                },
                {
                    "player_name": "Kerem Aktürkoğlu",
                    "display_name": "Kerem Aktürkoğlu",
                    "team": "Fenerbahçe",
                    "position": "MF",
                    "price_m": 9.0,
                },
            ]
        )
        merged = merge_prices(stats, prices)
        wrong = merged[merged["player"] == "Emirhan Yılmaz"].iloc[0]
        self.assertTrue(pd.isna(wrong.get("stats_player")))
        self.assertEqual(float(wrong.get("current_minutes") or 0.0), 0.0)
        transfer = merged[merged["player"] == "Kerem Aktürkoğlu"].iloc[0]
        self.assertEqual(str(transfer.get("stats_player")), "Kerem Aktürkoğlu")

    def test_merge_prices_preserves_established_super_lig_apps(self) -> None:
        from src.load_prices import merge_prices

        stats = pd.DataFrame(
            [
                {
                    "player": "Muhammed Şengezer",
                    "team": "Başakşehir",
                    "position": "GK",
                    "projected_pts": 4.0,
                    "form_apps": 1.0,
                    "base_apps": 1.0,
                    "current_apps": 1.0,
                    "prev_apps": 33.0,
                    "established_sl_apps": 33.0,
                    "data_src": "super_lig",
                    "reason": "CS",
                    "min_per_app": 90.0,
                    "cs_raw": 0.43,
                    "cs_after_fixture": 0.37,
                    "fixture_cs_mult": 0.85,
                }
            ]
        )
        prices = pd.DataFrame(
            [
                {
                    "player_name": "Muhammed Şengezer",
                    "display_name": "Muhammed Şengezer",
                    "team": "Başakşehir",
                    "position": "GK",
                    "price_m": 4.5,
                }
            ]
        )
        merged = merge_prices(stats, prices)
        self.assertEqual(float(merged.iloc[0]["prev_apps"]), 33.0)
        self.assertEqual(float(merged.iloc[0]["established_sl_apps"]), 33.0)
        self.assertAlmostEqual(float(merged.iloc[0]["cs_raw"]), 0.43)

    def test_merge_prices_keeps_match_kind_and_league_table(self) -> None:
        from src.load_prices import merge_prices

        stats = pd.DataFrame(
            [
                {
                    "player": "Archie Brown",
                    "team": "Fenerbahçe",
                    "position": "DF",
                    "projected_pts": 4.2,
                    "fixture_opponent": "Beşiktaş",
                    "fixture_match_kind": "derbi",
                    "fixture_lambda_for": 1.62,
                    "table_pos": 2,
                    "opp_table_pos": 3,
                    "table_n": 18,
                    "team_gf_pg": 2.1,
                    "team_ga_pg": 0.8,
                    "opp_gf_pg": 1.9,
                    "opp_ga_pg": 0.9,
                }
            ]
        )
        prices = pd.DataFrame(
            [
                {
                    "player_name": "Archie Brown",
                    "display_name": "Archie Brown",
                    "team": "Fenerbahçe",
                    "position": "DF",
                    "price_m": 5.0,
                }
            ]
        )
        merged = merge_prices(stats, prices)
        row = merged.iloc[0]
        self.assertEqual(str(row["fixture_match_kind"]), "derbi")
        self.assertEqual(float(row["table_pos"]), 2.0)
        self.assertEqual(float(row["opp_table_pos"]), 3.0)
        self.assertEqual(float(row["table_n"]), 18.0)
        self.assertAlmostEqual(float(row["team_ga_pg"]), 0.8)
        self.assertAlmostEqual(float(row["fixture_lambda_for"]), 1.62)

    def test_established_super_lig_history_skips_external_prior(self) -> None:
        from src.fetch_external import apply_external_priors

        frame = pd.DataFrame(
            [
                {
                    "player": "Şengezer",
                    "team": "Başakşehir",
                    "position": "GK",
                    "price_m": 4.5,
                    "projected_pts": 4.2,
                    "stats_player": "Muhammed Şengezer",
                    "form_apps": 1.0,
                    "current_apps": 1.0,
                    "prev_apps": 33.0,
                    "established_sl_apps": 33.0,
                    "base_apps": 1.0,
                    "min_per_app": 90.0,
                    "data_src": "super_lig",
                },
                {
                    "player": "Yeni Kaleci",
                    "team": "X",
                    "position": "GK",
                    "price_m": 5.0,
                    "projected_pts": 0.0,
                    "stats_player": "",
                    "form_apps": 0.0,
                    "current_apps": 0.0,
                    "prev_apps": 0.0,
                    "established_sl_apps": 0.0,
                    "base_apps": 0.0,
                    "min_per_app": 0.0,
                    "data_src": "",
                },
            ]
        )
        out = apply_external_priors(frame, max_fetch=0)
        self.assertEqual(out.loc[0, "data_src"], "super_lig")
        self.assertEqual(float(out.loc[0, "prev_apps"]), 33.0)

    def test_goalkeeper_opener_keeps_external_saves_as_component_blend(self) -> None:
        from src.fetch_external import apply_external_priors

        frame = pd.DataFrame(
            [
                {
                    "player": "Alexander Nübel",
                    "team": "Beşiktaş",
                    "position": "GK",
                    "price_m": 5.0,
                    "projected_pts": 3.26,
                    "stats_player": "Alexander Nübel",
                    "form_apps": 1.0,
                    "current_apps": 1.0,
                    "current_minutes": 90.0,
                    "prev_apps": 0.0,
                    "established_sl_apps": 0.0,
                    "base_apps": 1.0,
                    "min_per_app": 90.0,
                    "share_60": 1.0,
                    "saves_pa": 1.0,
                    "current_saves_pa": 1.0,
                    "team_cs_base": 0.40,
                    "fixture_cs_mult": 1.0,
                    "fixture_attack_mult": 1.0,
                    "data_src": "super_lig",
                }
            ]
        )
        external = {
            "projected_pts": 6.0,
            "reason": "Bundesliga",
            "data_src": "external_prior",
            "ext_league": "Bundesliga",
            "ext_saves": 109,
            "ext_cs": 11,
            "ext_saves_pa": 3.30,
            "ext_cs_rate": 0.333,
            "translated_saves_pa": 3.0,
            "translated_cs_rate": 0.27,
            "share_60": 1.0,
            "min_per_app": 90.0,
            "league_calibration_level": "global",
            "league_calibration_note": "global küçültme",
            "rating": 7.0,
        }
        with (
            patch(
                "src.fetch_external.resolve_one",
                return_value={"player": {"id": 1}},
            ),
            patch(
                "src.fetch_external.project_external_player",
                return_value=external,
            ),
        ):
            out = apply_external_priors(frame, max_fetch=1)

        self.assertEqual(out.loc[0, "data_src"], "external_blend")
        self.assertEqual(float(out.loc[0, "ext_saves"]), 109)
        self.assertEqual(float(out.loc[0, "ext_cs"]), 11)
        self.assertAlmostEqual(float(out.loc[0, "saves_pa"]), 2.6, places=3)
        self.assertLess(float(out.loc[0, "projected_pts"]), 6.0)
        self.assertGreater(float(out.loc[0, "projected_pts"]), 3.26)
        self.assertIn("kurtarış:", str(out.loc[0, "reason"]))

    def test_goalkeeper_season_transition_weights_are_monotonic(self) -> None:
        from src.scoring import blend_goalkeeper_components, season_sample_weight

        weights = [
            season_sample_weight(n, 4.0) for n in (0, 1, 3, 6, 10, 20)
        ]
        self.assertEqual(weights[0], 0.0)
        self.assertAlmostEqual(weights[1], 1 / 5)
        self.assertAlmostEqual(weights[2], 3 / 7)
        self.assertAlmostEqual(weights[3], 6 / 10)
        self.assertAlmostEqual(weights[4], 10 / 14)
        self.assertAlmostEqual(weights[5], 20 / 24)
        self.assertEqual(weights, sorted(weights))

        packs = [
            blend_goalkeeper_components(
                current_saves_pa=1.0,
                prior_saves_pa=3.3,
                current_sample=float(n),
                team_cs=0.40,
            )
            for n in (0, 1, 3, 6, 10, 20)
        ]
        saves = [p["saves_pa"] for p in packs]
        prior_w = [p["w_saves_prior"] for p in packs]
        self.assertEqual(saves, sorted(saves, reverse=True))
        self.assertEqual(prior_w, sorted(prior_w, reverse=True))
        self.assertAlmostEqual(packs[0]["saves_pa"], 3.3, places=3)
        self.assertAlmostEqual(packs[-1]["saves_pa"], 20 / 24 * 1.0 + 4 / 24 * 3.3, places=3)

    def test_nubel_and_sengezer_component_priors_compare_fairly(self) -> None:
        from src.scoring import blend_goalkeeper_components

        nubel = blend_goalkeeper_components(
            current_saves_pa=1.0,
            prior_saves_pa=109 / 33,
            current_sample=1.0,
            team_cs=0.40,
            personal_prior_cs=11 / 33,
            fixture_cs_mult=1.01,
        )
        sengezer = blend_goalkeeper_components(
            current_saves_pa=4.0,
            prior_saves_pa=105 / 33,
            current_sample=1.0,
            team_cs=0.43,
            personal_prior_cs=12 / 33,
            fixture_cs_mult=0.85,
        )
        self.assertGreater(nubel["saves_pa"], 2.5)
        self.assertGreater(sengezer["saves_pa"], 3.0)
        self.assertAlmostEqual(nubel["personal_prior_cs"], 11 / 33, places=4)
        self.assertAlmostEqual(sengezer["personal_prior_cs"], 12 / 33, places=4)
        self.assertAlmostEqual(nubel["cs_raw"], 0.40, places=4)
        self.assertAlmostEqual(sengezer["cs_raw"], 0.43, places=4)
        self.assertLess(sengezer["cs_after_fixture"], sengezer["cs_raw"])

    def test_limited_super_lig_history_can_blend_external_prior(self) -> None:
        from src.fetch_external import apply_external_priors

        frame = pd.DataFrame(
            [
                {
                    "player": "Sınırlı Örnek",
                    "team": "X",
                    "position": "MF",
                    "price_m": 7.0,
                    "projected_pts": 4.0,
                    "stats_player": "Sınırlı Örnek",
                    "form_apps": 1.0,
                    "current_apps": 1.0,
                    "prev_apps": 5.0,
                    "established_sl_apps": 5.0,
                    "base_apps": 1.0,
                    "min_per_app": 75.0,
                    "data_src": "super_lig",
                }
            ]
        )
        external = {
            "projected_pts": 6.0,
            "reason": "dış lig",
            "data_src": "external_prior",
        }
        with (
            patch(
                "src.fetch_external.resolve_one",
                return_value={"player": {"id": 1}},
            ),
            patch(
                "src.fetch_external.project_external_player",
                return_value=external,
            ),
        ):
            out = apply_external_priors(frame, max_fetch=1)

        self.assertEqual(out.loc[0, "data_src"], "external_blend")
        self.assertAlmostEqual(float(out.loc[0, "projected_pts"]), 4.9)
        self.assertEqual(float(out.loc[0, "prev_apps"]), 5.0)

    def test_soft_early_form_keeps_strong_super_lig_base(self) -> None:
        from src.scoring import soft_early_form_rates

        form = _empty_rates()
        form.update({"apps": 1.0, "gls_pa": 1.0, "ast_pa": 0.0, "xg_pa": 0.9})
        base = _empty_rates()
        base.update({"apps": 30.0, "gls_pa": 0.25, "ast_pa": 0.20, "xg_pa": 0.22})
        softened = soft_early_form_rates(form, base, 1.0, 30.0)
        self.assertLess(softened["gls_pa"], 0.40)
        self.assertGreater(softened["gls_pa"], base["gls_pa"])

    def test_fixture_cs_floor_preserves_strong_team_edge(self) -> None:
        from src.config import FIXTURE_CS_FLOOR

        self.assertGreaterEqual(FIXTURE_CS_FLOOR, 0.70)
        basaksehir = 0.43 * FIXTURE_CS_FLOOR
        rizespor = 0.30 * 1.0
        self.assertGreater(basaksehir, rizespor)

    def test_formation_rescore_prefers_three_forwards_when_bench_star_is_valuable(self) -> None:
        from src.optimize import rescore_formations

        rows = []
        teams = list("ABCDEFGHIJKLMNO")
        rows += [
            {"player": "GK1", "team": teams[0], "position": "GK", "price_m": 4.0, "pts_if_plays": 4.0, "play_probability": 0.95, "projected_pts": 3.8},
            {"player": "GK2", "team": teams[1], "position": "GK", "price_m": 4.0, "pts_if_plays": 2.0, "play_probability": 0.4, "projected_pts": 0.8},
        ]
        for i in range(5):
            rows.append(
                {
                    "player": f"DF{i}",
                    "team": teams[2 + i],
                    "position": "DF",
                    "price_m": 4.5,
                    "pts_if_plays": 3.2 - i * 0.05,
                    "play_probability": 0.9,
                    "projected_pts": 2.8,
                }
            )
        for i in range(5):
            rows.append(
                {
                    "player": f"MF{i}",
                    "team": teams[7 + i] if 7 + i < len(teams) else f"T{i}",
                    "position": "MF",
                    "price_m": 5.0,
                    "pts_if_plays": 3.5 - i * 0.1,
                    "play_probability": 0.9,
                    "projected_pts": 3.0,
                }
            )
        rows += [
            {"player": "Osimhen", "team": "Galatasaray", "position": "FW", "price_m": 14.0, "pts_if_plays": 7.0, "play_probability": 0.95, "projected_pts": 6.6},
            {"player": "Shomu", "team": "Fenerbahce", "position": "FW", "price_m": 10.0, "pts_if_plays": 6.0, "play_probability": 0.95, "projected_pts": 5.7},
            {"player": "Talisca", "team": "Fenerbahce", "position": "FW", "price_m": 8.5, "pts_if_plays": 5.8, "play_probability": 0.92, "projected_pts": 5.3},
        ]
        squad = pd.DataFrame(rows)
        formations = {
            "3-5-2": {"GK": 1, "DF": 3, "MF": 5, "FW": 2},
            "3-4-3": {"GK": 1, "DF": 3, "MF": 4, "FW": 3},
            "4-3-3": {"GK": 1, "DF": 4, "MF": 3, "FW": 3},
        }
        best = rescore_formations(squad, formations, autosub_draws=80)
        self.assertIn(best["formation"], ("3-4-3", "4-3-3"))
        self.assertIn("Talisca", best["xi"]["player"].tolist())
        compared = [
            row["formation"] for row in best["formation_comparisons"]
        ]
        self.assertEqual(len(compared), len(set(compared)))

    def test_card_budget_raises_threshold_when_rights_are_scarce(self) -> None:
        from src.manager_cards import choose_manager_card, opportunity_threshold

        self.assertGreater(
            opportunity_threshold(6.0, remaining=2, weeks_left=20),
            opportunity_threshold(6.0, remaining=10, weeks_left=34),
        )
        self.assertAlmostEqual(
            opportunity_threshold(6.0, remaining=10, weeks_left=34),
            6.0,
            places=1,
        )
        self.assertLessEqual(
            opportunity_threshold(6.0, remaining=10, weeks_left=12),
            opportunity_threshold(6.0, remaining=10, weeks_left=34) + 1e-9,
        )
        hold = choose_manager_card(
            [{"card": "Tripleks Kaptan", "extra_pts": 6.4, "why": "3x"}],
            remaining=2,
            weeks_left=20,
        )
        self.assertFalse(hold["use"])
        self.assertEqual(hold["remaining"], 2)
        early_use = choose_manager_card(
            [{"card": "Tripleks Kaptan", "extra_pts": 6.4, "why": "3x"}],
            remaining=10,
            weeks_left=33,
        )
        self.assertTrue(early_use["use"])
        early_hold = choose_manager_card(
            [{"card": "Tripleks Kaptan", "extra_pts": 5.2, "why": "3x"}],
            remaining=10,
            weeks_left=33,
        )
        self.assertFalse(early_hold["use"])

    def test_record_card_use_persists_history_and_decrements_total(self) -> None:
        from src.manager_cards import (
            load_card_state,
            record_card_use,
            set_cards_remaining,
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "card_state.json"
            set_cards_remaining(
                8,
                path=path,
                season=2026,
                weeks_left=30,
            )
            state = record_card_use(
                "Tripleks Kaptan",
                path=path,
                season=2026,
                week=5,
                weeks_left=29,
            )
            loaded = load_card_state(path, season=2026)

        self.assertEqual(state["remaining"], 7)
        self.assertEqual(state["used"], 3)
        self.assertEqual(loaded["remaining"], 7)
        self.assertEqual(loaded["history"][-1]["card"], "Tripleks Kaptan")
        self.assertEqual(loaded["history"][-1]["week"], 5)

        with TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "card_state.json"
            with self.assertRaises(ValueError):
                set_cards_remaining(11, path=invalid_path, season=2026)

    def test_card_state_cli_does_not_run_weekly_pipeline(self) -> None:
        from src.main import main

        state = {
            "remaining": 8,
            "budget": 10,
            "season": 2026,
            "weeks_left": 30,
        }
        with patch(
            "src.manager_cards.set_cards_remaining",
            return_value=state,
        ) as update:
            code = main(
                [
                    "--set-cards-remaining",
                    "8",
                    "--season",
                    "2026",
                    "--weeks-left",
                    "30",
                ]
            )

        self.assertEqual(code, 0)
        update.assert_called_once()

    def test_league_evaluation_promotes_only_better_than_identity(self) -> None:
        from calibrate_leagues import evaluate_leagues_forward

        samples = []
        for year in (2020, 2021, 2022, 2023, 2024):
            for i in range(20):
                src = 0.4 + 0.02 * i
                samples.append(
                    {
                        "player_id": year * 100 + i,
                        "source_tournament_id": 17,
                        "source_league": "Premier League",
                        "position": "FW",
                        "target_season_start": year,
                        "source_minutes": 2000.0,
                        "target_minutes": 1800.0,
                        "source_apps": 34.0,
                        "target_apps": 30.0,
                        "source_goals": src * 20,
                        "source_assists": 5.0,
                        "target_goals": src * 14,
                        "target_assists": 3.0,
                        "source_xg": src * 18,
                        "target_xg": src * 13,
                        "source_xa": 4.0,
                        "target_xa": 3.0,
                        "source_key_passes": 30.0,
                        "target_key_passes": 22.0,
                        "source_shots_on_target": 40.0,
                        "target_shots_on_target": 28.0,
                        "source_saves": 0.0,
                        "target_saves": 0.0,
                        "source_clean_sheets": 0.0,
                        "target_clean_sheets": 0.0,
                        "source_goals_conceded": 0.0,
                        "target_goals_conceded": 0.0,
                        "source_yellow_cards": 2.0,
                        "target_yellow_cards": 2.0,
                        "source_red_cards": 0.0,
                        "target_red_cards": 0.0,
                        "source_rating": 7.0,
                        "target_rating": 6.8,
                        "source_has_xg": True,
                        "target_has_xg": True,
                        "source_has_xa": True,
                        "target_has_xa": True,
                        "source_has_key_passes": True,
                        "target_has_key_passes": True,
                        "source_has_shots_on_target": True,
                        "target_has_shots_on_target": True,
                    }
                )
            for i in range(8):
                src = 0.5 + 0.03 * i
                samples.append(
                    {
                        "player_id": 9000 + year * 10 + i,
                        "source_tournament_id": 99,
                        "source_league": "Noise League",
                        "position": "FW",
                        "target_season_start": year,
                        "source_minutes": 1600.0,
                        "target_minutes": 1500.0,
                        "source_apps": 28.0,
                        "target_apps": 25.0,
                        "source_goals": src * 25,
                        "source_assists": 2.0,
                        "target_goals": 2.0 + (i % 3),
                        "target_assists": 1.0,
                        "source_xg": src * 20,
                        "target_xg": 2.0,
                        "source_xa": 2.0,
                        "target_xa": 1.0,
                        "source_key_passes": 20.0,
                        "target_key_passes": 10.0,
                        "source_shots_on_target": 30.0,
                        "target_shots_on_target": 12.0,
                        "source_saves": 0.0,
                        "target_saves": 0.0,
                        "source_clean_sheets": 0.0,
                        "target_clean_sheets": 0.0,
                        "source_goals_conceded": 0.0,
                        "target_goals_conceded": 0.0,
                        "source_yellow_cards": 1.0,
                        "target_yellow_cards": 1.0,
                        "source_red_cards": 0.0,
                        "target_red_cards": 0.0,
                        "source_rating": 7.2,
                        "target_rating": 6.5,
                        "source_has_xg": True,
                        "target_has_xg": True,
                        "source_has_xa": True,
                        "target_has_xa": True,
                        "source_has_key_passes": True,
                        "target_has_key_passes": True,
                        "source_has_shots_on_target": True,
                        "target_has_shots_on_target": True,
                    }
                )

        report = evaluate_leagues_forward(samples)
        self.assertIn("summary", report)
        self.assertIn("leagues", report)
        noise = report["leagues"].get("99", {})
        if noise:
            promotes = [
                row.get("promote")
                for pos in (noise.get("positions") or {}).values()
                for row in pos.values()
            ]
            self.assertTrue(any(p is False for p in promotes) or not promotes)


class LiveTmPackTests(unittest.TestCase):
    def test_club_display_strips_trailing_dot_not_as(self) -> None:
        from app.slugs import club_display

        self.assertEqual(club_display("Galatasaray ·"), "Galatasaray")
        self.assertEqual(club_display("Trabzonspor A.Ş."), "Trabzonspor A.Ş.")

    def test_club_wage_hit_basaksehir(self) -> None:
        from app.live_tm import _club_wage_hit

        self.assertTrue(_club_wage_hit("İstanbul Başakşehir", "Başakşehir FK"))
        self.assertTrue(_club_wage_hit("Galatasaray", "Galatasaray A.Ş."))

    def test_shirt_from_headline_hash(self) -> None:
        from bs4 import BeautifulSoup

        from app.live_tm import _read_shirt_number

        html = '<h1 class="data-header__headline-wrapper">#9 Mauro Icardi</h1>'
        soup = BeautifulSoup(html, "lxml")
        self.assertEqual(_read_shirt_number(soup, {}, "Mauro Icardi"), "9")
        html2 = '<h1 class="data-header__headline-wrapper">Mauro Icardi</h1>'
        soup2 = BeautifulSoup(html2, "lxml")
        self.assertIsNone(_read_shirt_number(soup2, {}, "Mauro Icardi"))

    def test_wage_bills_joined_to_contract_end(self) -> None:
        from app.live_tm import _apply_wage_pack, _finish_spell
        from datetime import date

        spell = {
            "club": "Galatasaray",
            "arrived": "2024-07-01",
            "contract_until": "2027-06-30",
            "ongoing": True,
            "kind": "bedel",
            "fee": 10_000_000,
        }
        today = date(2026, 9, 1)
        _finish_spell(spell, today)
        self.assertLess(int(spell["days"] or 0), 900)
        career = {"current": [spell], "former": []}
        _apply_wage_pack(
            career,
            {"rows": [{"year": 2024, "club": "Galatasaray", "annual_eur": 1_000_000}]},
        )
        billed = int(career["current"][0].get("wage_total") or 0)
        self.assertGreater(billed, 2_700_000)
        self.assertLess(billed, 3_200_000)
        self.assertEqual(career["current"][0]["total"], 10_000_000 + billed)


if __name__ == "__main__":
    unittest.main()

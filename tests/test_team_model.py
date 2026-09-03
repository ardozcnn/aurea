import unittest

from src.optimize import _selection_value, _this_week_value
from src.scoring import (
    apply_context_adjustments,
    expected_points_from_rates,
    weighted_horizon_points,
)
from src.team_model import (
    blend_goal_expectation,
    classify_fixture,
    fit_poisson_ratings,
    group_events_by_matchweek,
    predict_lambdas,
    ratings_from_standings,
)


def _attacker_rates() -> dict[str, float]:
    return {
        "apps": 12.0,
        "share_60": 0.9,
        "min_per_app": 82.0,
        "gls_pa": 0.45,
        "ast_pa": 0.20,
        "xg_pa": 0.42,
        "xa_pa": 0.18,
        "sot_pa": 1.4,
        "key_passes_pa": 1.2,
        "cs_rate": 0.0,
        "yc_pa": 0.1,
        "rc_pa": 0.0,
        "saves_pa": 0.0,
        "ga_pa": 0.0,
        "rating": 7.0,
        "pen_save_pa": 0.0,
        "pen_miss_pa": 0.0,
        "og_pa": 0.0,
        "bcc_pa": 0.0,
    }


class TeamModelTests(unittest.TestCase):
    def test_poisson_gives_higher_lambda_to_strong_attack_vs_weak_defence(self) -> None:
        matches = []
        for i in range(8):
            matches.append(
                {
                    "home": "gs",
                    "away": "weak",
                    "hg": 3.0,
                    "ag": 0.0,
                    "weight": 1.0,
                }
            )
            matches.append(
                {
                    "home": "weak",
                    "away": "gs",
                    "hg": 0.0,
                    "ag": 2.0,
                    "weight": 1.0,
                }
            )
            matches.append(
                {
                    "home": "mid",
                    "away": "other",
                    "hg": 1.0,
                    "ag": 1.0,
                    "weight": 1.0,
                }
            )
            matches.append(
                {
                    "home": "other",
                    "away": "mid",
                    "hg": 1.0,
                    "ag": 1.0,
                    "weight": 1.0,
                }
            )
        ratings = fit_poisson_ratings(matches)
        self.assertEqual(ratings["source"], "poisson")
        easy = predict_lambdas(ratings, "gs", "weak", home=True)
        hard = predict_lambdas(ratings, "weak", "gs", home=True)
        self.assertGreater(easy["lambda_for"], hard["lambda_for"])
        self.assertGreater(easy["p_cs"], hard["p_cs"])
        self.assertGreater(easy["attack_mult"], 1.0)
        self.assertLess(hard["attack_mult"], easy["attack_mult"])

    def test_home_advantage_raises_home_lambda(self) -> None:
        matches = []
        for _ in range(10):
            matches.append(
                {"home": "a", "away": "b", "hg": 2.0, "ag": 1.0, "weight": 1.0}
            )
            matches.append(
                {"home": "b", "away": "a", "hg": 2.0, "ag": 1.0, "weight": 1.0}
            )
        ratings = fit_poisson_ratings(matches)
        home = predict_lambdas(ratings, "a", "b", home=True)
        away = predict_lambdas(ratings, "a", "b", home=False)
        self.assertGreater(home["lambda_for"], away["lambda_for"])
        self.assertGreater(home["p_cs"], away["p_cs"])

    def test_standings_fallback_separates_attack_and_defence(self) -> None:
        ratings = ratings_from_standings(
            {
                "city": {"gf": 2.4, "ga": 0.7},
                "weak": {"gf": 0.8, "ga": 2.1},
            }
        )
        easy = predict_lambdas(ratings, "city", "weak", home=True)
        hard = predict_lambdas(ratings, "weak", "city", home=True)
        self.assertGreater(easy["lambda_for"], hard["lambda_for"])
        self.assertGreater(easy["p_cs"], hard["p_cs"])

    def test_player_share_tracks_team_lambda(self) -> None:
        hist = 0.40
        easy = blend_goal_expectation(
            hist, attack_mult=1.2, lambda_for=2.0, team_goal_rate=1.4
        )
        hard = blend_goal_expectation(
            hist, attack_mult=0.8, lambda_for=0.7, team_goal_rate=1.4
        )
        self.assertGreater(easy, hard)
        self.assertGreater(easy, hist * 0.8)

    def test_easy_fixture_scores_more_fantasy_points(self) -> None:
        rates = _attacker_rates()
        easy = expected_points_from_rates(
            rates,
            "FW",
            appearance=1.0,
            attack_mult=1.25,
            lambda_for=2.1,
            lambda_against=0.7,
            p_cs=0.50,
            team_goal_rate=1.4,
        )
        hard = expected_points_from_rates(
            rates,
            "FW",
            appearance=1.0,
            attack_mult=0.78,
            lambda_for=0.7,
            lambda_against=2.0,
            p_cs=0.14,
            team_goal_rate=1.4,
        )
        self.assertGreater(easy, hard)

    def test_horizon_weights_this_week_most(self) -> None:
        blended = weighted_horizon_points([10.0, 4.0, 1.0])
        self.assertGreater(blended, 7.0)
        self.assertLess(blended, 10.0)

    def test_selection_uses_horizon_captain_uses_this_week(self) -> None:
        import pandas as pd

        row = pd.Series(
            {
                "pts_if_plays": 8.0,
                "play_probability": 1.0,
                "projected_pts": 8.0,
                "selection_pts": 6.2,
            }
        )
        self.assertAlmostEqual(_this_week_value(row), 8.0)
        self.assertAlmostEqual(_selection_value(row), 6.2)

    def test_context_adjustment_builds_selection_pts(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "Forvet",
                    "team": "A",
                    "position": "FW",
                    "projected_pts": 6.0,
                    "pts_week0": 6.0,
                    "pts_week1": 3.0,
                    "pts_week2": 3.0,
                    "availability": "AVAILABLE",
                    "form_apps": 6.0,
                    "min_per_app": 80.0,
                }
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertIn("selection_pts", out.columns)
        self.assertLess(float(out.loc[0, "selection_pts"]), float(out.loc[0, "projected_pts"]))
        self.assertGreater(float(out.loc[0, "horizon_pts"]), 4.5)

    def test_fotmob_unplayed_rows_become_sofa_events(self) -> None:
        from src.fetch_fotmob import fotmob_rows_to_sofa_events

        rows = [
            {
                "home": {"name": "Galatasaray"},
                "away": {"name": "Kayserispor"},
                "status": {"finished": False, "utcTime": "2026-08-22T18:00:00.000Z"},
            },
            {
                "home": {"name": "Fenerbahçe"},
                "away": {"name": "Trabzonspor"},
                "status": {"finished": True, "utcTime": "2026-08-15T18:00:00.000Z"},
            },
        ]
        events = fotmob_rows_to_sofa_events(rows)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["homeTeam"]["name"], "Galatasaray")
        self.assertGreater(int(events[0]["startTimestamp"]), 0)

    def test_matchweek_grouping_splits_when_team_repeats(self) -> None:
        events = [
            {
                "startTimestamp": 1,
                "homeTeam": {"name": "A"},
                "awayTeam": {"name": "B"},
            },
            {
                "startTimestamp": 2,
                "homeTeam": {"name": "C"},
                "awayTeam": {"name": "D"},
            },
            {
                "startTimestamp": 3,
                "homeTeam": {"name": "A"},
                "awayTeam": {"name": "C"},
            },
        ]
        weeks = group_events_by_matchweek(events, weeks=3)
        self.assertEqual(len(weeks), 2)
        self.assertEqual(len(weeks[0]), 2)
        self.assertEqual(len(weeks[1]), 1)

    def test_top_clubs_are_always_derby_even_if_one_is_favourite(self) -> None:
        from src.team_model import classify_fixture, predict_lambdas

        ratings = {
            "attack": {
                "galatasaray": 1.55,
                "fenerbahce": 1.42,
                "besiktas": 1.28,
                "basaksehir": 0.98,
                "erzurumspor": 0.62,
            },
            "defence": {
                "galatasaray": 0.68,
                "fenerbahce": 0.74,
                "besiktas": 0.88,
                "basaksehir": 1.12,
                "erzurumspor": 1.48,
            },
            "home_adv": 1.28,
            "scale": 1.35,
            "league_avg": 1.35,
        }
        derby = predict_lambdas(ratings, "Beşiktaş", "Fenerbahçe", home=True)
        reverse = predict_lambdas(ratings, "Fenerbahçe", "Beşiktaş", home=True)
        easy = predict_lambdas(ratings, "Galatasaray", "Erzurumspor", home=True)
        hard = predict_lambdas(ratings, "Erzurumspor", "Galatasaray", home=False)
        mismatch = predict_lambdas(ratings, "Galatasaray", "Başakşehir", home=True)
        self.assertEqual(derby["match_kind"], "derbi")
        self.assertEqual(reverse["match_kind"], "derbi")
        self.assertEqual(easy["match_kind"], "kolay")
        self.assertEqual(hard["match_kind"], "zor")
        self.assertEqual(mismatch["match_kind"], "kolay")
        self.assertGreater(easy["attack_mult"], derby["attack_mult"])
        self.assertGreater(easy["p_cs"], derby["p_cs"])
        self.assertLess(abs(derby["attack_mult"] - 1.0), abs(easy["attack_mult"] - 1.0))
        self.assertEqual(
            classify_fixture(2.4, 0.9, "galatasaray", "fenerbahce", ratings["attack"]),
            "derbi",
        )

    def test_easy_clean_sheet_defence_is_boosted(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "GS Defans",
                    "team": "Galatasaray",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.22,
                    "fixture_match_kind": "kolay",
                },
                {
                    "player": "Derbi Defans",
                    "team": "Beşiktaş",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.00,
                    "fixture_match_kind": "derbi",
                },
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertAlmostEqual(float(out.loc[0, "pts_if_plays"]), 4.56, places=2)
        # Derbi defansı yasak değil, sadece ihtiyatlı: 4.0 × 0.90.
        self.assertAlmostEqual(float(out.loc[1, "pts_if_plays"]), 3.6, places=2)

    def test_easy_attack_fixture_beats_derby_star(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "Osimhen",
                    "team": "Galatasaray",
                    "position": "FW",
                    "price_m": 14.0,
                    "projected_pts": 6.0,
                    "availability": "AVAILABLE",
                    "form_apps": 2,
                    "min_per_app": 90,
                    "fixture_attack_mult": 1.28,
                    "fixture_match_kind": "kolay",
                },
                {
                    "player": "Greenwood",
                    "team": "Beşiktaş",
                    "position": "FW",
                    "price_m": 12.0,
                    "projected_pts": 6.0,
                    "availability": "AVAILABLE",
                    "form_apps": 2,
                    "min_per_app": 90,
                    "fixture_attack_mult": 1.05,
                    "fixture_match_kind": "derbi",
                },
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertGreater(
            float(out.loc[0, "pts_if_plays"]),
            float(out.loc[1, "pts_if_plays"]),
        )

    def test_analysis_names_mismatch_and_derby(self) -> None:
        from app.fantasy_bridge import _analysis, _describe_match

        gs_basak = _describe_match(
            {
                "home": "Galatasaray",
                "away": "Başakşehir",
                "players": [
                    {
                        "player": "Osimhen",
                        "team": "Galatasaray",
                        "position": "FW",
                        "pts_if_plays": 7.2,
                        "fixture_match_kind": "kolay",
                    },
                    {
                        "player": "Shomurodov",
                        "team": "Başakşehir",
                        "position": "FW",
                        "pts_if_plays": 6.1,
                        "fixture_match_kind": "zor",
                    },
                ],
            }
        )
        self.assertIn("Galatasaray", gs_basak)
        self.assertIn("önde", gs_basak)
        self.assertIn("Osimhen", gs_basak)
        derby = _describe_match(
            {
                "home": "Beşiktaş",
                "away": "Fenerbahçe",
                "players": [
                    {
                        "player": "Greenwood",
                        "team": "Beşiktaş",
                        "position": "FW",
                        "pts_if_plays": 6.4,
                        "fixture_match_kind": "derbi",
                    },
                    {
                        "player": "Černý",
                        "team": "Fenerbahçe",
                        "position": "FW",
                        "pts_if_plays": 6.3,
                        "fixture_match_kind": "derbi",
                    },
                ],
            }
        )
        self.assertIn("denk derbi", derby)
        self.assertIn("Greenwood", derby)
        payload = {
            "result": {
                "xi": [
                    {
                        "player": "Osimhen",
                        "team": "Galatasaray",
                        "position": "FW",
                        "pts_if_plays": 7.2,
                        "projected_pts": 7.0,
                        "fixture_opponent": "Başakşehir",
                        "fixture_home": True,
                        "fixture_match_kind": "kolay",
                    }
                ],
                "bench": [],
                "squad": [
                    {
                        "player": "Osimhen",
                        "team": "Galatasaray",
                        "position": "FW",
                        "pts_if_plays": 7.2,
                        "fixture_match_kind": "kolay",
                    }
                ],
                "captain": {
                    "player": "Osimhen",
                    "team": "Galatasaray",
                    "pts_if_plays": 7.2,
                    "fixture_opponent": "Başakşehir",
                    "fixture_home": True,
                    "fixture_match_kind": "kolay",
                },
                "xi_if_plays": 7.2,
                "total_projected": 7.0,
                "bench_projected": 0.0,
                "bank": 1.0,
                "formation": "4-3-3",
            },
            "fixtures": [{"home": "Galatasaray", "away": "Başakşehir"}],
            "manager_card": {"card": "Kart kullanma", "use": False, "why": ""},
            "formation_comparisons": [],
            "watch": [],
        }
        sections = {row["title"]: " ".join(row["paragraphs"]) for row in _analysis({}, payload)}
        self.assertIn("Maçlar", sections)
        self.assertIn("tarafı tutulur", sections["Maçlar"])
        self.assertIn("TFF puanı şans", sections["Haftalık okuma"])
        self.assertIn("Rakip zayıf", sections["Kaptan"])

    def test_analysis_names_hot_tff_outsider(self) -> None:
        from app.fantasy_bridge import _analysis

        payload = {
            "result": {
                "xi": [
                    {
                        "player": "Osimhen",
                        "team": "Galatasaray",
                        "position": "FW",
                        "pts_if_plays": 7.2,
                    }
                ],
                "bench": [],
                "squad": [
                    {
                        "player": "Osimhen",
                        "team": "Galatasaray",
                        "position": "FW",
                        "pts_if_plays": 7.2,
                    }
                ],
                "captain": {"player": "Osimhen"},
                "xi_if_plays": 7.2,
                "total_projected": 7.0,
                "bench_projected": 0.0,
                "formation": "4-3-3",
            },
            "watch": [
                {
                    "player": "Dušan Vlahović",
                    "team": "Beşiktaş",
                    "position": "FW",
                    "tff_points": 17,
                    "tff_round_points": 16,
                    "tff_goals": 3,
                    "price_m": 10.0,
                }
            ],
            "manager_card": {"card": "Kart kullanma", "use": False, "why": ""},
            "formation_comparisons": [],
        }
        sections = {row["title"]: " ".join(row["paragraphs"]) for row in _analysis({}, payload)}
        self.assertIn("Bu hafta TFF", sections)
        self.assertIn("Vlahović", sections["Bu hafta TFF"])
        self.assertIn("kadro dışı", sections["Bu hafta TFF"])

    def test_basaksehir_forward_is_not_easy_against_galatasaray(self) -> None:
        from app.fantasy_bridge import _describe_match, _match_kind

        osi = {
            "player": "Osimhen",
            "team": "Galatasaray",
            "fixture_opponent": "Başakşehir FK",
            "fixture_match_kind": "",
        }
        shomu = {
            "player": "Shomurodov",
            "team": "İstanbul Başakşehir",
            "fixture_opponent": "Galatasaray",
            "fixture_match_kind": "",
        }
        self.assertEqual(_match_kind(osi), "kolay")
        self.assertEqual(_match_kind(shomu), "zor")
        text = _describe_match(
            {
                "home": "Galatasaray",
                "away": "Başakşehir FK",
                "players": [osi, shomu],
            }
        )
        self.assertIn("önde", text)
        self.assertNotIn("denk derbi", text)
        derby = _describe_match(
            {
                "home": "Fenerbahçe",
                "away": "Beşiktaş JK",
                "players": [
                    {
                        "player": "Černý",
                        "team": "Fenerbahçe",
                        "fixture_opponent": "Beşiktaş JK",
                    },
                    {
                        "player": "Greenwood",
                        "team": "Beşiktaş JK",
                        "fixture_opponent": "Fenerbahçe",
                    },
                ],
            }
        )
        self.assertIn("denk derbi", derby)
        self.assertIn("Greenwood", derby)
        mid = _describe_match(
            {
                "home": "Kasımpaşa",
                "away": "Amed Sportif Faaliyetler",
                "players": [
                    {
                        "player": "Benedyczak",
                        "team": "Kasımpaşa",
                        "fixture_opponent": "Amed Sportif Faaliyetler",
                    },
                    {
                        "player": "Saba",
                        "team": "Amed Sportif Faaliyetler",
                        "fixture_opponent": "Kasımpaşa",
                    },
                ],
            }
        )
        self.assertNotIn("denk derbi", mid)

    def test_trabzonspor_galatasaray_is_not_described_as_derby(self) -> None:
        from app.fantasy_bridge import _describe_match, _match_kind

        gs = {
            "player": "Osimhen",
            "team": "Galatasaray",
            "fixture_opponent": "Trabzonspor",
            "fixture_match_kind": "",
        }
        ts = {
            "player": "Nwakaeme",
            "team": "Trabzonspor",
            "fixture_opponent": "Galatasaray",
            "fixture_match_kind": "",
        }
        self.assertNotEqual(_match_kind(gs), "derbi")
        self.assertNotEqual(_match_kind(ts), "derbi")
        text = _describe_match(
            {
                "home": "Galatasaray",
                "away": "Trabzonspor",
                "players": [gs, ts],
            }
        )
        self.assertNotIn("denk derbi", text)
        self.assertIn("Osimhen", text)

    def test_table_rank_lifts_top_defence_and_cuts_bottom(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "Ust Defans",
                    "team": "Galatasaray",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.0,
                    "fixture_match_kind": "denk",
                    "table_pos": 1,
                    "opp_table_pos": 18,
                    "table_n": 18,
                    "team_ga_pg": 0.70,
                    "opp_gf_pg": 0.80,
                },
                {
                    "player": "Alt Defans",
                    "team": "Hatayspor",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.0,
                    "fixture_match_kind": "denk",
                    "table_pos": 18,
                    "opp_table_pos": 1,
                    "table_n": 18,
                    "team_ga_pg": 1.80,
                    "opp_gf_pg": 1.70,
                },
            ]
        )
        out = apply_context_adjustments(frame)
        self.assertGreater(float(out.loc[0, "pts_if_plays"]), 4.0)
        self.assertLess(float(out.loc[1, "pts_if_plays"]), 3.4)

    def test_joe_mendes_is_crushed_against_peer_defender(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "Joe Mendes",
                    "team": "Samsunspor",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.0,
                    "fixture_match_kind": "denk",
                },
                {
                    "player": "Diger Defans",
                    "team": "Samsunspor",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.0,
                    "fixture_match_kind": "denk",
                },
            ]
        )
        out = apply_context_adjustments(frame)
        mendes = float(out.loc[out["player"] == "Joe Mendes", "pts_if_plays"].iloc[0])
        peer = float(out.loc[out["player"] == "Diger Defans", "pts_if_plays"].iloc[0])
        self.assertLess(mendes, peer * 0.70)

    def test_samsun_and_kocaeli_defence_lose_to_galatasaray(self) -> None:
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "player": "GS Defans",
                    "team": "Galatasaray",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.22,
                    "fixture_match_kind": "kolay",
                },
                {
                    "player": "Samsun Defans",
                    "team": "Samsunspor",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.22,
                    "fixture_match_kind": "kolay",
                },
                {
                    "player": "Kocaeli Defans",
                    "team": "Kocaelispor",
                    "position": "DF",
                    "projected_pts": 4.0,
                    "availability": "AVAILABLE",
                    "form_apps": 4,
                    "min_per_app": 90,
                    "fixture_cs_mult": 1.18,
                    "fixture_match_kind": "kolay",
                },
            ]
        )
        out = apply_context_adjustments(frame)
        gs = float(out.loc[0, "pts_if_plays"])
        self.assertAlmostEqual(gs, 4.56, places=2)
        self.assertLess(float(out.loc[1, "pts_if_plays"]), 2.6)
        self.assertLess(float(out.loc[2, "pts_if_plays"]), 2.6)

    def test_club_key_folds_suffix_and_sponsor(self) -> None:
        from src.names import club_key

        self.assertEqual(club_key("Beşiktaş JK"), "besiktas")
        self.assertEqual(club_key("Başakşehir FK"), "basaksehir")
        self.assertEqual(club_key("Gaziantep FK"), "gaziantep")
        self.assertEqual(club_key("Çaykur Rizespor"), "rizespor")
        self.assertEqual(club_key("Amed Sportif Faaliyetler"), "amed")
        self.assertEqual(club_key("Çorum FK"), "corum")

    def test_only_the_big_three_meetings_count_as_derby(self) -> None:
        attack = {
            "galatasaray": 1.45,
            "trabzonspor": 1.25,
            "basaksehir": 1.20,
        }
        self.assertEqual(
            classify_fixture(1.6, 1.5, "galatasaray", "trabzonspor", attack),
            "denk",
        )
        self.assertEqual(
            classify_fixture(1.6, 1.5, "galatasaray", "basaksehir", attack),
            "denk",
        )

    def test_suffixed_top_club_names_still_read_as_derby(self) -> None:
        attack = {"fenerbahce": 1.35, "besiktas": 1.30}
        kind = classify_fixture(1.7, 1.4, "fenerbahce", "besiktas", attack)
        self.assertEqual(kind, "derbi")
        pred = predict_lambdas(
            {"attack": attack, "defence": {"fenerbahce": 0.8, "besiktas": 0.85}},
            "Fenerbahçe",
            "Beşiktaş JK",
            home=True,
        )
        self.assertEqual(pred["match_kind"], "derbi")

    def test_bottom_table_attacker_is_discounted(self) -> None:
        import pandas as pd

        def row(name: str, team: str, pos_in_table: float) -> dict[str, object]:
            return {
                "player": name,
                "team": team,
                "position": "MF",
                "projected_pts": 4.0,
                "price_m": 6.0,
                "availability": "AVAILABLE",
                "form_apps": 4,
                "min_per_app": 90,
                "fixture_match_kind": "kolay",
                "fixture_lambda_for": 1.8,
                "table_pos": pos_in_table,
                "table_n": 18.0,
                "opp_table_pos": 9.0,
            }

        frame = pd.DataFrame(
            [row("Orta Sira", "Kasımpaşa", 9.0), row("Dip Sira", "Çorum FK", 18.0)]
        )
        out = apply_context_adjustments(frame)
        mid = float(out.loc[0, "pts_if_plays"])
        bottom = float(out.loc[1, "pts_if_plays"])
        self.assertLess(bottom, mid * 0.85)

    def test_gencler_second_is_not_easy_for_trabzon(self) -> None:
        from app.fantasy_bridge import _describe_match, _match_kind

        salah = {
            "player": "Salah",
            "team": "Trabzonspor",
            "position": "MF",
            "fixture_opponent": "Gençlerbirliği",
            "fixture_home": True,
            "fixture_match_kind": "denk",
            "fixture_band": "rahat",
            "fixture_cs_mult": 1.38,
            "table_pos": 11,
            "opp_table_pos": 2,
            "table_n": 18,
            "odds_favorite": "trabzonspor",
            "odds_p_win": 0.61,
        }
        self.assertEqual(_match_kind(salah), "denk")
        text = _describe_match(
            {
                "home": "Trabzonspor",
                "away": "Gençlerbirliği",
                "players": [salah],
            }
        )
        self.assertIn("denk maç", text)
        self.assertIn("11", text)
        self.assertIn("2", text)
        self.assertNotIn("hücum ve savunma üstün", text)
        self.assertNotIn("Alt sıra rakibe karşı", text)
        self.assertNotIn("rakip zayıf", text.lower())


if __name__ == "__main__":
    unittest.main()

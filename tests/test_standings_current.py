import time
import unittest
from unittest.mock import patch

from src.fetch_stats import (
    _table_from_standings,
    build_fixture_context,
    pick_table_standings,
)
from src.names import club_key


def _row(
    name: str,
    pos: int,
    matches: int,
    points: int,
    gf: int,
    ga: int,
) -> dict:
    return {
        "team": {"name": name},
        "position": pos,
        "matches": matches,
        "points": points,
        "scoresFor": gf,
        "scoresAgainst": ga,
    }


# Resmî 2026/27 tablo, 3. hafta sonu (TFF / Wikipedia).
CURRENT_3GW = [
    _row("Galatasaray", 1, 3, 7, 9, 4),
    _row("Gençlerbirliği", 2, 3, 7, 4, 2),
    _row("Beşiktaş JK", 3, 3, 6, 7, 3),
    _row("Fenerbahçe", 4, 3, 6, 7, 4),
    _row("Amed Sportif Faaliyetler", 5, 3, 6, 5, 3),
    _row("Kocaelispor", 6, 3, 6, 4, 3),
    _row("Çaykur Rizespor", 7, 3, 6, 3, 3),
    _row("Kasımpaşa", 8, 3, 5, 3, 2),
    _row("Başakşehir FK", 9, 3, 4, 4, 3),
    _row("Samsunspor", 10, 3, 4, 5, 5),
    _row("Trabzonspor", 11, 3, 4, 4, 4),
    _row("Alanyaspor", 12, 3, 4, 3, 3),
    _row("Gaziantep FK", 13, 3, 4, 3, 3),
    _row("Eyüpspor", 14, 3, 3, 2, 3),
    _row("Göztepe", 15, 3, 1, 5, 7),
    _row("Çorum FK", 16, 3, 1, 4, 9),
    _row("Erzurumspor FK", 17, 3, 1, 1, 8),
    _row("Konyaspor", 18, 3, 0, 3, 7),
]

# 2025/26 bitmiş tablo — Gençler 14., Trabzon 3.
PREV_FULL = [
    _row("Galatasaray", 1, 34, 77, 77, 30),
    _row("Fenerbahçe", 2, 34, 74, 77, 37),
    _row("Trabzonspor", 3, 34, 69, 61, 39),
    _row("Beşiktaş JK", 4, 34, 60, 59, 40),
    _row("Başakşehir FK", 5, 34, 57, 58, 35),
    _row("Göztepe", 6, 34, 55, 42, 32),
    _row("Samsunspor", 7, 34, 51, 46, 45),
    _row("Çaykur Rizespor", 8, 34, 41, 46, 52),
    _row("Konyaspor", 9, 34, 40, 43, 50),
    _row("Kocaelispor", 10, 34, 37, 26, 38),
    _row("Alanyaspor", 11, 34, 37, 41, 41),
    _row("Gaziantep FK", 12, 34, 37, 43, 58),
    _row("Kasımpaşa", 13, 34, 35, 33, 49),
    _row("Gençlerbirliği", 14, 34, 34, 36, 47),
    _row("Eyüpspor", 15, 34, 33, 33, 48),
    _row("Antalyaspor", 16, 34, 32, 33, 55),
    _row("Kayserispor", 17, 34, 30, 27, 62),
    _row("Fatih Karagümrük", 18, 34, 30, 31, 54),
]

CURRENT_SID = 98080
PREV_SID = 77805


def _prev_season_events() -> list[dict]:
    """Geçen yıl Trabzon güçlü / Gençler zayıf görünsün diye şişirilmiş geçmiş."""
    now = time.time() - 200 * 86400
    events = []
    for i in range(12):
        events.append(
            {
                "homeTeam": {"name": "Trabzonspor"},
                "awayTeam": {"name": "Gençlerbirliği"},
                "homeScore": {"current": 3},
                "awayScore": {"current": 0},
                "startTimestamp": now - i * 86400,
            }
        )
        events.append(
            {
                "homeTeam": {"name": "Gençlerbirliği"},
                "awayTeam": {"name": "Galatasaray"},
                "homeScore": {"current": 0},
                "awayScore": {"current": 2},
                "startTimestamp": now - i * 86400 - 3600,
            }
        )
        events.append(
            {
                "homeTeam": {"name": "Fenerbahçe"},
                "awayTeam": {"name": "Konyaspor"},
                "homeScore": {"current": 2},
                "awayScore": {"current": 1},
                "startTimestamp": now - i * 86400 - 7200,
            }
        )
        events.append(
            {
                "homeTeam": {"name": "Beşiktaş JK"},
                "awayTeam": {"name": "Alanyaspor"},
                "homeScore": {"current": 1},
                "awayScore": {"current": 1},
                "startTimestamp": now - i * 86400 - 10800,
            }
        )
    return events


class CurrentStandingsTests(unittest.TestCase):
    def test_pick_table_keeps_three_game_current_over_previous(self) -> None:
        rows, src = pick_table_standings(CURRENT_3GW, PREV_FULL)
        self.assertEqual(src, "current")
        self.assertIs(rows, CURRENT_3GW)
        table = _table_from_standings(rows)
        self.assertEqual(table[club_key("Gençlerbirliği")]["pos"], 2.0)
        self.assertEqual(table[club_key("Trabzonspor")]["pos"], 11.0)
        self.assertEqual(table[club_key("Galatasaray")]["pos"], 1.0)
        self.assertNotEqual(table[club_key("Gençlerbirliği")]["pos"], 14.0)

    def test_pick_table_falls_back_only_when_current_unplayed(self) -> None:
        empty_current = [_row("Galatasaray", 1, 0, 0, 0, 0)]
        rows, src = pick_table_standings(empty_current, PREV_FULL)
        self.assertEqual(src, "previous")
        self.assertIs(rows, PREV_FULL)
        none_rows, none_src = pick_table_standings([], [])
        self.assertEqual(none_src, "current")
        self.assertEqual(none_rows, [])

    def test_ts_vs_gencler_not_auto_kolay_from_last_year_14th(self) -> None:
        upcoming = [
            {
                "homeTeam": {"name": "Trabzonspor"},
                "awayTeam": {"name": "Gençlerbirliği"},
                "startTimestamp": int(time.time()) + 86400,
            }
        ]

        def fake_standings(season_id: int) -> list[dict]:
            if season_id == CURRENT_SID:
                return CURRENT_3GW
            return PREV_FULL

        def fake_recent(season_id: int, max_pages: int = 8) -> list[dict]:
            if season_id == PREV_SID:
                return _prev_season_events()
            return []

        with (
            patch("src.fetch_stats.fetch_standings_rows", side_effect=fake_standings),
            patch("src.fetch_stats.fetch_recent_events", side_effect=fake_recent),
            patch("src.fetch_stats.fetch_upcoming_events", return_value=upcoming),
            patch("src.fetch_stats.attach_odds_to_events", return_value={}),
        ):
            ctx = build_fixture_context(
                CURRENT_SID,
                CURRENT_SID,
                fallback_strength_season_id=PREV_SID,
                prefer_fallback=True,
            )

        ts = ctx[club_key("Trabzonspor")]
        gencler = ctx[club_key("Gençlerbirliği")]
        self.assertEqual(ts["table_pos"], 11.0)
        self.assertEqual(ts["opp_table_pos"], 2.0)
        self.assertEqual(gencler["table_pos"], 2.0)
        self.assertEqual(gencler["opp_table_pos"], 11.0)
        self.assertNotEqual(ts["match_kind"], "kolay")
        self.assertNotEqual(gencler["match_kind"], "kolay")
        self.assertNotEqual(ts["opp_table_pos"], 14.0)


if __name__ == "__main__":
    unittest.main()

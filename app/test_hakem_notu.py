import unittest

from app.hakem_notu import can_create_rating, clamp_score, home_pack, match_pack, penalty_for_incident, rate_match


class PenaltyTests(unittest.TestCase):
    def test_missed_penalty(self):
        row = penalty_for_incident(
            {
                "impactLevel": "CRITICAL",
                "editorialVerdict": "INCORRECT",
                "confidence": "HIGH_CONFIDENCE_WRONG",
            }
        )
        self.assertEqual(row["penalty"], 15)
        self.assertTrue(row["countsAsIncorrect"])

    def test_wrong_yellow(self):
        row = penalty_for_incident(
            {
                "impactLevel": "LOW",
                "editorialVerdict": "INCORRECT",
                "confidence": "HIGH_CONFIDENCE_WRONG",
            }
        )
        self.assertEqual(row["penalty"], 2)

    def test_split_red(self):
        row = penalty_for_incident(
            {
                "impactLevel": "HIGH",
                "editorialVerdict": "DEBATABLE",
                "confidence": "SPLIT",
            }
        )
        self.assertEqual(row["penalty"], 4)
        self.assertTrue(row["countsAsDebatable"])
        self.assertFalse(row["countsAsIncorrect"])

    def test_insufficient_evidence(self):
        row = penalty_for_incident(
            {
                "impactLevel": "CRITICAL",
                "editorialVerdict": "INCORRECT",
                "confidence": "INSUFFICIENT",
            }
        )
        self.assertEqual(row["penalty"], 0)
        self.assertTrue(row["countsAsOpenReview"])

    def test_correct(self):
        row = penalty_for_incident(
            {
                "impactLevel": "CRITICAL",
                "editorialVerdict": "CORRECT",
                "confidence": "HIGH_CONFIDENCE_WRONG",
            }
        )
        self.assertEqual(row["penalty"], 0)
        self.assertTrue(row["countsAsCorrect"])


class RateMatchTests(unittest.TestCase):
    def test_example_is_79(self):
        result = rate_match(
            [
                {
                    "impactLevel": "CRITICAL",
                    "editorialVerdict": "INCORRECT",
                    "confidence": "HIGH_CONFIDENCE_WRONG",
                },
                {
                    "impactLevel": "LOW",
                    "editorialVerdict": "INCORRECT",
                    "confidence": "HIGH_CONFIDENCE_WRONG",
                },
                {
                    "impactLevel": "HIGH",
                    "editorialVerdict": "DEBATABLE",
                    "confidence": "SPLIT",
                },
            ]
        )
        self.assertEqual(result["totalPenalty"], 21)
        self.assertEqual(result["score"], 79)

    def test_floor(self):
        incidents = [
            {
                "impactLevel": "CRITICAL",
                "editorialVerdict": "INCORRECT",
                "confidence": "HIGH_CONFIDENCE_WRONG",
            }
        ] * 12
        self.assertEqual(rate_match(incidents)["score"], 0)
        self.assertEqual(clamp_score(-40), 0)

    def test_center_only(self):
        self.assertTrue(can_create_rating("CENTER"))
        self.assertFalse(can_create_rating("VAR"))
        self.assertFalse(can_create_rating("FOURTH"))

    def test_week1_genclerbirligi_is_79(self):
        match = match_pack("genclerbirligi-fenerbahce-2026-1")
        self.assertIsNotNone(match)
        self.assertFalse(match["isDemo"])
        self.assertEqual(match["season"], "2026/27")
        self.assertEqual(match["homeScore"], 2)
        self.assertEqual(match["awayScore"], 1)
        self.assertEqual(match["rating"]["score"], 79)
        self.assertEqual(match["rating"]["referee"]["slug"], "oguzhan-aksu")
        self.assertGreaterEqual(len(match["sources"]), 2)
        missed = next(row for row in match["incidents"] if row["minute"] == 49)
        self.assertEqual(missed["editorialVerdict"], "INCORRECT")
        self.assertEqual(missed["penalty"], 15)
        kerem = next(row for row in match["incidents"] if row["minute"] == 58)
        self.assertEqual(kerem["eventType"], "YELLOW_CARD")
        self.assertEqual(kerem["penalty"], 0)
        self.assertNotIn("video", missed)
        self.assertTrue(missed["sources"][0]["excerpt"])
        self.assertTrue(any("milliyet.com.tr" in (src.get("url") or "") for src in missed["sources"]))
        var_rows = [row for row in match["officials"] if row["role"] == "VAR"]
        self.assertTrue(var_rows)
        self.assertFalse(var_rows[0]["scored"])

    def test_catalog_is_live_season(self):
        pack = home_pack()
        self.assertGreaterEqual(len(pack["matches"]), 5)
        self.assertTrue(all(not row["isDemo"] for row in pack["matches"]))
        self.assertGreaterEqual(sum(len(row["incidents"]) for row in pack["matches"]), 10)
        self.assertIn("eski hakem", pack["disclaimer"].lower())
        kol = match_pack("samsunspor-fenerbahce-2026-3")
        self.assertEqual(kol["rating"]["score"], 70)
        self.assertEqual(kol["rating"]["referee"]["slug"], "yasin-kol")
        yellows = [
            item
            for row in pack["matches"]
            for item in row["incidents"]
            if item["eventType"] == "YELLOW_CARD"
        ]
        self.assertGreaterEqual(len(yellows), 10)
        derby = match_pack("fenerbahce-besiktas-2026-4")
        self.assertEqual(derby["rating"]["score"], 73)
        pk = next(row for row in derby["incidents"] if row["minute"] == 75)
        self.assertEqual(pk["editorialVerdict"], "DEBATABLE")
        self.assertEqual(pk["penalty"], 6)
        red = next(row for row in derby["incidents"] if row["eventType"] == "RED_CARD")
        self.assertEqual(red["penalty"], 15)
        saglam = match_pack("basaksehir-galatasaray-2026-4")
        self.assertEqual(saglam["rating"]["score"], 85)
        self.assertTrue(
            any("hurriyet.com.tr" in (src.get("url") or "") for src in derby["sources"])
        )
        goztepe = match_pack("galatasaray-goztepe-2026-3")
        self.assertEqual(goztepe["rating"]["score"], 94)
        self.assertTrue(any(row["editorialVerdict"] == "OPEN_REVIEW" for row in goztepe["incidents"]))
        self.assertTrue(
            any("sabah.com.tr" in (src.get("url") or "") for src in goztepe["sources"])
        )
        samsun = match_pack("samsunspor-fenerbahce-2026-3")
        self.assertTrue(
            any("mustafa-culcu" in (src.get("url") or "") for src in samsun["sources"])
        )
        desk = home_pack()
        self.assertIn("galatasaray-goztepe-2026-3", {row["slug"] for row in desk["highest"]})
        for row in desk["highest"] + desk["lowest"]:
            self.assertTrue(row.get("incidents"), row["slug"])
        noted = [row for row in desk["matches"] if row.get("incidents")]
        self.assertEqual(desk["summary"]["ratedMatchCount"], len(noted))
        self.assertLess(desk["summary"]["averageScore"], 96)


class HarvestTests(unittest.TestCase):
    def test_slugify_super_lig_names(self):
        from app.hakem_harvest import slugify

        self.assertEqual(slugify("Gençlerbirliği"), "genclerbirligi")
        self.assertEqual(slugify("Göztepe"), "goztepe")
        self.assertEqual(slugify("Başakşehir"), "basaksehir")
        self.assertEqual(
            f"{slugify('Fenerbahçe')}-{slugify('Beşiktaş')}-2026-4",
            "fenerbahce-besiktas-2026-4",
        )

    def test_editorial_match_keeps_incidents(self):
        from app.hakem_harvest import merge_editorial

        merged = merge_editorial(
            {
                "referees": [{"slug": "oguzhan-aksu", "firstName": "Oğuzhan", "lastName": "Aksu"}],
                "matches": [
                    {
                        "slug": "genclerbirligi-fenerbahce-2026-1",
                        "home": {"name": "Gençlerbirliği"},
                        "away": {"name": "Fenerbahçe"},
                        "incidents": [{"minute": 49, "editorialVerdict": "INCORRECT"}],
                        "sources": [{"url": "https://editorial.example/a"}],
                    }
                ],
            },
            {
                "referees": [{"slug": "yeni-hakem", "firstName": "Yeni", "lastName": "Hakem"}],
                "matches": [
                    {
                        "slug": "genclerbirligi-fenerbahce-2026-1",
                        "fotmobId": "5904708",
                        "incidents": [{"minute": 1, "editorialVerdict": "CORRECT"}],
                        "sources": [{"url": "https://harvest.example/b", "origin": "harvest", "sourceType": "EXPERT_COMMENTARY"}],
                    },
                    {
                        "slug": "alanyaspor-trabzonspor-2026-1",
                        "home": {"name": "Alanyaspor"},
                        "away": {"name": "Trabzonspor"},
                        "incidents": [],
                        "sources": [],
                    },
                ],
            },
        )
        by_slug = {row["slug"]: row for row in merged["matches"]}
        locked = by_slug["genclerbirligi-fenerbahce-2026-1"]
        self.assertEqual(locked["incidents"][0]["minute"], 49)
        self.assertTrue(locked["lock"])
        self.assertEqual(locked["fotmobId"], "5904708")
        self.assertEqual(len(locked["sources"]), 2)
        self.assertIn("alanyaspor-trabzonspor-2026-1", by_slug)
        self.assertEqual(len(merged["referees"]), 2)

    def test_red_card_title_is_wrong_claim(self):
        from app.hakem_harvest import claims_from_text

        rows = claims_from_text(
            "Fırat Aydınus: Skriniar da Vlahovic de kırmızı kart görmeliydi",
            "Fırat Aydınus",
        )
        self.assertEqual(rows[0]["eventType"], "RED_CARD")
        self.assertEqual(rows[0]["stance"], "WRONG")

    def test_two_experts_become_incorrect(self):
        from app.hakem_harvest import incidents_from_claims

        rows = incidents_from_claims(
            [
                {"expert": "Aydınus", "eventType": "PENALTY", "stance": "WRONG", "minute": 5, "excerpt": "net penaltı"},
                {"expert": "Çulcu", "eventType": "PENALTY", "stance": "WRONG", "minute": 5, "excerpt": "penaltı olmalıydı"},
            ],
            [],
        )
        self.assertEqual(rows[0]["editorialVerdict"], "INCORRECT")
        self.assertEqual(rows[0]["confidence"], "HIGH_CONFIDENCE_WRONG")

    def test_single_expert_stays_open_review(self):
        from app.hakem_harvest import incidents_from_claims

        rows = incidents_from_claims(
            [{"expert": "Çulcu", "eventType": "YELLOW_CARD", "stance": "WRONG", "minute": 15, "excerpt": "sarı eksik"}],
            [],
        )
        self.assertEqual(rows[0]["editorialVerdict"], "OPEN_REVIEW")
        self.assertEqual(rows[0]["confidence"], "INSUFFICIENT")

    def test_harvest_writes_new_match_without_touching_week1(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app import hakem_harvest
        from app.hakem_notu import match_pack

        fixtures = [
            {
                "slug": "alanyaspor-konyaspor-2026-1",
                "fotmobId": "1",
                "season": "2026/27",
                "week": 1,
                "playedAt": "2026-08-16T19:00:00+03:00",
                "home": {"id": "alanyaspor", "name": "Alanyaspor", "shortName": "ALA"},
                "away": {"id": "konyaspor", "name": "Konyaspor", "shortName": "KON"},
                "homeScore": 1,
                "awayScore": 0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(hakem_harvest, "HARVEST_PATH", root / "harvest.json"), patch.object(
                hakem_harvest, "STATUS_PATH", root / "status.json"
            ), patch.object(hakem_harvest, "CACHE_PATH", root / "cache.json"):
                hakem_harvest.harvest(
                    fetch_matches=lambda: fixtures,
                    fetch_news=lambda _rows: [
                        {
                            "title": "Alanyaspor Konyaspor maçında Trio: 40. dakika penaltı olmalıydı",
                            "url": "https://example.com/trio",
                            "publisher": "Fanatik",
                            "publishedAt": "Sun, 16 Aug 2026 21:00:00 GMT",
                        }
                    ],
                    fetch_detail=lambda _mid: {"referee": "Deneme Hakem", "stadium": "Bahçeşehir"},
                )
                with patch("app.hakem_notu.load_merged_catalog", hakem_harvest.load_merged_catalog):
                    week1 = match_pack("genclerbirligi-fenerbahce-2026-1")
                    self.assertEqual(week1["rating"]["score"], 79)
                    fresh = match_pack("alanyaspor-konyaspor-2026-1")
                    self.assertIsNotNone(fresh)
                    self.assertEqual(fresh["rating"]["referee"]["slug"], "deneme-hakem")
                    missed = next(row for row in fresh["incidents"] if row["minute"] == 40)
                    self.assertEqual(missed["editorialVerdict"], "OPEN_REVIEW")


if __name__ == "__main__":
    unittest.main()

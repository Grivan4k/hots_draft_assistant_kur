"""Unit tests for the core modules of the HotS Draft Assistant.

Run:  python -m unittest test_core -v
"""
import os
import tempfile
import unittest

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")

from engine import DraftAssistant
import data_sources


def seed(db, tag, mmr, stats):
    g = sum(x[1] for x in stats); w = sum(x[2] for x in stats)
    db.upsert_player(tag, current_mmr=mmr, total_games=g, total_wins=w)
    for hero, games, wins in stats:
        db.upsert_hero_stats(tag, hero, games_played=games, wins=wins, losses=games - wins)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.a = DraftAssistant()

    def tearDown(self):
        self.a.close()

    # T1 — ростер героев загружается
    def test_roster_seeded(self):
        self.assertGreaterEqual(len(self.a.known_heroes()), 80)

    # T2 — новый игрок получает нейтральную оценку
    def test_new_player_neutral(self):
        p = self.a.analyzer.build_profile("Unknown#0000")
        self.assertTrue(p.is_new)
        self.assertEqual(p.mmr, config.ELO_NEUTRAL_RATING)

    # T3 — определение игрока-специализации (OTP)
    def test_otp_detection(self):
        seed(self.a.db, "Otp#1", 2000, [("Illidan", 80, 58), ("Genji", 10, 5), ("Tracer", 10, 4)])
        p = self.a.analyzer.build_profile("Otp#1")
        self.assertTrue(p.is_otp)
        self.assertEqual(p.otp_hero, "Illidan")

    # T4 — игрок с равномерным пулом не является OTP
    def test_non_otp(self):
        seed(self.a.db, "Flex#1", 1800, [("Muradin", 30, 16), ("Diablo", 30, 15), ("Garrosh", 30, 17)])
        p = self.a.analyzer.build_profile("Flex#1")
        self.assertFalse(p.is_otp)

    # T5 — буквенная оценка повышается с рейтингом
    def test_letter_grade_scale(self):
        seed(self.a.db, "Hi#1", 2500, [("Jaina", 100, 70)])
        seed(self.a.db, "Lo#1", 1400, [("Jaina", 100, 40)])
        self.assertEqual(self.a.analyzer.build_profile("Hi#1").letter, "S")
        self.assertIn(self.a.analyzer.build_profile("Lo#1").letter, ("C", "D"))

    # T6 — построение пула героев
    def test_pool_built(self):
        seed(self.a.db, "Pool#1", 1900, [("Li-Ming", 40, 26), ("Jaina", 20, 12)])
        p = self.a.analyzer.build_profile("Pool#1")
        self.assertTrue(len(p.pool) >= 1)

    # T7 — прогноз вероятности победы в диапазоне [0,1]
    def test_win_probability_range(self):
        self.a.start_session(["A#1", "B#2", "C#3", "D#4", "E#5"],
                             ["F#6", "G#7", "H#8", "I#9", "J#10"], "Sky Temple")
        self.a.update_draft_state([], [None]*5, [None]*5)
        recs = self.a.recommendations("A#1", "Sky Temple")
        pr = recs["prediction"]["ally_win_probability"]
        self.assertGreaterEqual(pr, 0.0)
        self.assertLessEqual(pr, 1.0)

    # T8 — бан-рекомендации приоритизируют OTP-героя противника
    def test_ban_recommends_enemy_otp(self):
        seed(self.a.db, "EnemyOtp#5", 2200, [("Illidan", 90, 65), ("Genji", 10, 5)])
        self.a.start_session(["Me#1", "A#2", "B#3", "C#4", "D#5"],
                             ["EnemyOtp#5", "F#6", "G#7", "H#8", "I#9"], "Cursed Hollow")
        self.a.update_draft_state([], [None]*5, [None]*5)
        recs = self.a.recommendations("Me#1", "Cursed Hollow")
        self.assertIn("Illidan", [b.hero for b in recs["bans"]])

    # T9 — пик-рекомендации исключают забаненных героев
    def test_picks_exclude_bans(self):
        self.a.start_session(["Me#1", "A#2", "B#3", "C#4", "D#5"],
                             ["F#6", "G#7", "H#8", "I#9", "J#10"], "Sky Temple")
        self.a.update_draft_state(["Jaina", "Illidan", "Muradin"], [None]*5, [None]*5)
        recs = self.a.recommendations("Me#1", "Sky Temple")
        picks = [p.hero for p in recs["picks"]]
        for banned in ("Jaina", "Illidan", "Muradin"):
            self.assertNotIn(banned, picks)

    # T10 — импорт статистики из match-JSON средствами программы
    def test_import_match(self):
        match = {
            "match_id": "t1", "map_name": "Sky Temple",
            "players": [
                {"battletag": "P1", "team": "1", "hero": "Jaina", "is_winner": True,
                 "kills": 5, "deaths": 2, "assists": 7},
                {"battletag": "P2", "team": "2", "hero": "Muradin", "is_winner": False,
                 "kills": 1, "deaths": 6, "assists": 3},
            ],
            "bans": ["Illidan"],
        }
        res = self.a.import_matches_dict([match])
        self.assertEqual(res["matches"], 1)
        rows = self.a.db.conn.execute("SELECT COUNT(*) c FROM PlayerMatch").fetchone()["c"]
        self.assertEqual(rows, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

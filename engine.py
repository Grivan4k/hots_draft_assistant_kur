"""Core engine that ties the database, analysis and recommendations together.

This module is UI-independent so it can be used from the GUI, a script or tests.
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

import config
from analytics import PlayerAnalyzer, TeamComparator
from data_sources import seed_hero_roster
from db import Database
from recommendations import BanAdvisor, PickAdvisor


class DraftAssistant:
    """Owns the database and exposes high-level draft operations."""

    def __init__(self):
        self.db = Database()
        self.analyzer = PlayerAnalyzer(self.db)
        self.comparator = TeamComparator(self.db, self.analyzer)
        self.pick_advisor = PickAdvisor(self.db, self.analyzer)
        self.ban_advisor = BanAdvisor(self.db, self.analyzer)
        self.session_id: Optional[str] = None
        self._ensure_roster()

    def _ensure_roster(self) -> None:
        if not self.db.get_all_heroes():
            seed_hero_roster(self.db)

    def known_heroes(self) -> List[str]:
        return [h["hero_name"] for h in self.db.get_all_heroes()]

    def _resolve_map(self, map_name: Optional[str]) -> Optional[str]:
        """Match a recognised map name to MapStats case-insensitively."""
        if not map_name:
            return None
        target = map_name.strip().lower()
        for row in self.db.conn.execute("SELECT map_name FROM MapStats").fetchall():
            if row["map_name"].lower() == target:
                return row["map_name"]
        return None

    def _sync_player(self, battletag: str) -> None:
        """Ensure a player record exists (neutral profile until stats are imported)."""
        if not self.db.is_known_player(battletag):
            self.db.upsert_player(battletag)

    def start_session(self, ally_tags: List[str], enemy_tags: List[str],
                      map_name: Optional[str], game_mode: str = "Storm League") -> str:
        """Create a draft session and register all detected players."""
        self.session_id = str(uuid.uuid4())
        self.db.create_draft_session(
            self.session_id, self._resolve_map(map_name), game_mode, "ally"
        )
        for slot, tag in enumerate(ally_tags):
            self._sync_player(tag)
            p = self.analyzer.build_profile(tag)
            self.db.set_draft_player(self.session_id, slot, tag, "ally", p.is_otp, p.otp_hero)
        for slot, tag in enumerate(enemy_tags, start=5):
            self._sync_player(tag)
            p = self.analyzer.build_profile(tag)
            self.db.set_draft_player(self.session_id, slot, tag, "enemy", p.is_otp, p.otp_hero)
        return self.session_id

    def update_draft_state(self, banned: List[str],
                           ally_picks: List[Optional[str]],
                           enemy_picks: List[Optional[str]]) -> None:
        """Record current bans and picks for the active session."""
        if not self.session_id:
            return
        order = 0
        for hero in banned:
            self.db.set_hero_state(self.session_id, hero, "banned_enemy", order)
            order += 1
        for hero in ally_picks:
            if hero:
                self.db.set_hero_state(self.session_id, hero, "picked_ally", order)
                order += 1
        for hero in enemy_picks:
            if hero:
                self.db.set_hero_state(self.session_id, hero, "picked_enemy", order)
                order += 1

    def recommendations(self, current_player: str, map_name: Optional[str]) -> Optional[Dict]:
        """Win-probability estimate plus ban and pick suggestions."""
        if not self.session_id:
            return None
        ally = [p["player_battletag"] for p in self.db.get_draft_players(self.session_id, "ally")]
        enemy = [p["player_battletag"] for p in self.db.get_draft_players(self.session_id, "enemy")]
        return {
            "prediction": self.comparator.win_probability(ally, enemy),
            "bans": self.ban_advisor.recommend(self.session_id),
            "picks": self.pick_advisor.recommend(self.session_id, current_player, "ally", map_name),
        }

    def player_profile(self, battletag: str):
        return self.analyzer.build_profile(battletag)

    def close(self) -> None:
        if self.session_id:
            self.db.complete_draft_session(self.session_id)
        self.db.close()


def _seed_demo_players(db) -> None:
    """Seed sample player statistics used by both demo scenarios."""
    def seed(tag, mmr, stats):
        total_g = sum(g for _, g, _ in stats)
        total_w = sum(w for _, _, w in stats)
        db.upsert_player(tag, current_mmr=mmr,
                         total_games=total_g, total_wins=total_w)
        for hero, g, w in stats:
            db.upsert_hero_stats(tag, hero, games_played=g, wins=w, losses=g - w)

    # Our team (left)
    seed("Dynouh#1234", 2100, [("Li-Ming", 40, 26), ("Jaina", 20, 12), ("Kael'thas", 15, 8)])
    seed("Hasu#2222",   1900, [("Muradin", 35, 20), ("Diablo", 25, 14), ("Garrosh", 20, 11)])
    # Enemy team (right) — EnemyOTP is a one-trick Illidan
    seed("EnemyOTP#5555", 2200, [("Illidan", 95, 68), ("Genji", 15, 8), ("Tracer", 10, 5)])
    seed("Smokey#6666",   1850, [("Alexstrasza", 40, 24), ("Uther", 30, 17), ("Rehgar", 20, 11)])
    seed("Cara#7777",     2000, [("Thrall", 45, 28), ("Sonya", 25, 14), ("Dehaka", 15, 8)])

    db.upsert_synergy("Muradin", "Li-Ming", games=30, wins=20, score=0.12)
    db.upsert_counter("Illidan", "Muradin", games=25, wins=16, score=0.15)


def scenario_1(assistant: "DraftAssistant") -> dict:
    """Team-building stage: 2 players left, 3 players right, 3 bans each side."""
    _seed_demo_players(assistant.db)
    return {
        "map": "Cursed Hollow",
        "me_slot": 4,
        "ally":  [(0, "Dynouh#1234", ""), (4, "", "")],
        "enemy": [(0, "EnemyOTP#5555", ""), (1, "Smokey#6666", ""), (2, "Cara#7777", "")],
        "ally_bans":  ["Illidan", "Alexstrasza", "Thrall"],   # ban enemy signature heroes
        "enemy_bans": ["Li-Ming", "Jaina", "Kael'thas"],      # enemy bans our carry's pool
    }


def scenario_2(assistant: "DraftAssistant") -> dict:
    """Mid-draft stage: 2 bans each side, one enemy pick, one ally pick."""
    _seed_demo_players(assistant.db)
    return {
        "map": "Sky Temple",
        "me_slot": 4,
        "ally":  [(4, "Hasu#2222", "Muradin")],
        "enemy": [(0, "EnemyOTP#5555", "Illidan")],
        "ally_bans":  ["Alexstrasza", "Thrall"],   # our bans against enemy threats
        "enemy_bans": ["Li-Ming", "Jaina"],        # enemy bans our carry's pool
    }


def load_sample_data(assistant: "DraftAssistant"):
    """Console-demo helper: seed data via scenario 1 and start a session."""
    data = scenario_1(assistant)
    ally  = ["", "", "", "", ""]
    enemy = ["", "", "", "", ""]
    for idx, tag, _ in data["ally"]:
        ally[idx] = tag
    for idx, tag, _ in data["enemy"]:
        enemy[idx] = tag
    ally  = [t or f"Ally{i+1}"  for i, t in enumerate(ally)]
    enemy = [t or f"Enemy{i+1}" for i, t in enumerate(enemy)]
    assistant.start_session(ally, enemy, data["map"])
    return "Hasu#2222", data["map"]
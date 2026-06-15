"""Reference data (heroes, maps) and replay-parser ingestion.

Player statistics are populated from a replay parser that reads
.StormReplay files produced by Heroes of the Storm.
See import_from_replay_parser() for the expected data format.
"""
from __future__ import annotations

import json
import os
from typing import List, Tuple

import config
from db import Database


HERO_ROSTER_SEED: List[Tuple[str, str]] = [
    ("Abathur", "Support"),
    ("Alarak", "Assassin"),
    ("Alexstrasza", "Healer"),
    ("Ana", "Healer"),
    ("Anduin", "Healer"),
    ("Anub'arak", "Tank"),
    ("Artanis", "Bruiser"),
    ("Arthas", "Bruiser"),
    ("Auriel", "Healer"),
    ("Azmodan", "Assassin"),
    ("Blaze", "Tank"),
    ("Brightwing", "Healer"),
    ("Cassia", "Assassin"),
    ("Chen", "Bruiser"),
    ("Cho'gall", "Tank"),
    ("Chromie", "Assassin"),
    ("D.Va", "Bruiser"),
    ("Deathwing", "Bruiser"),
    ("Deckard", "Healer"),
    ("Dehaka", "Bruiser"),
    ("Diablo", "Tank"),
    ("E.T.C.", "Tank"),
    ("Falstad", "Assassin"),
    ("Fenix", "Assassin"),
    ("Gall", "Assassin"),
    ("Garrosh", "Tank"),
    ("Gazlowe", "Bruiser"),
    ("Genji", "Assassin"),
    ("Greymane", "Assassin"),
    ("Gul'dan", "Assassin"),
    ("Hanzo", "Assassin"),
    ("Hogger", "Bruiser"),
    ("Illidan", "Assassin"),
    ("Imperius", "Bruiser"),
    ("Jaina", "Assassin"),
    ("Johanna", "Tank"),
    ("Junkrat", "Assassin"),
    ("Kael'thas", "Assassin"),
    ("Kel'Thuzad", "Assassin"),
    ("Kerrigan", "Assassin"),
    ("Kharazim", "Healer"),
    ("Leoric", "Bruiser"),
    ("Li Li", "Healer"),
    ("Li-Ming", "Assassin"),
    ("Lúcio", "Healer"),
    ("Lunara", "Assassin"),
    ("Maiev", "Assassin"),
    ("Mal'Ganis", "Bruiser"),
    ("Malfurion", "Healer"),
    ("Malthael", "Bruiser"),
    ("Medivh", "Support"),
    ("Mei", "Tank"),
    ("Mephisto", "Assassin"),
    ("Lt. Morales", "Healer"),
    ("Muradin", "Tank"),
    ("Murky", "Assassin"),
    ("Nazeebo", "Assassin"),
    ("Nova", "Assassin"),
    ("Orphea", "Assassin"),
    ("Probius", "Assassin"),
    ("Qhira", "Assassin"),
    ("Ragnaros", "Bruiser"),
    ("Raynor", "Assassin"),
    ("Rehgar", "Healer"),
    ("Rexxar", "Bruiser"),
    ("Samuro", "Assassin"),
    ("Sgt. Hammer", "Assassin"),
    ("Sonya", "Bruiser"),
    ("Stitches", "Tank"),
    ("Stukov", "Healer"),
    ("Sylvanas", "Assassin"),
    ("Tassadar", "Assassin"),
    ("The Butcher", "Assassin"),
    ("The Lost Vikings", "Support"),
    ("Thrall", "Bruiser"),
    ("Tracer", "Assassin"),
    ("Tychus", "Assassin"),
    ("Tyrael", "Bruiser"),
    ("Tyrande", "Healer"),
    ("Uther", "Healer"),
    ("Valeera", "Assassin"),
    ("Valla", "Assassin"),
    ("Varian", "Bruiser"),
    ("Whitemane", "Healer"),
    ("Xul", "Bruiser"),
    ("Yrel", "Bruiser"),
    ("Zagara", "Assassin"),
    ("Zarya", "Support"),
    ("Zeratul", "Assassin"),
    ("Zul'jin", "Assassin"),
]

MAP_ROSTER_SEED: List[str] = [
    "Cursed Hollow", "Dragon Shire", "Sky Temple", "Tomb of the Spider Queen",
    "Battlefield of Eternity", "Infernal Shrines", "Towers of Doom",
    "Braxis Holdout", "Volskaya Foundry", "Alterac Pass", "Garden of Terror",
    "Hanamura Temple", "Blackheart's Bay", "Haunted Mines",
]


def seed_hero_roster(db: Database) -> int:
    """Populate the Hero and MapStats reference tables. Returns hero count."""
    count = 0
    for name, role in HERO_ROSTER_SEED:
        db.upsert_hero(name, role)
        count += 1
    for map_name in MAP_ROSTER_SEED:
        db.conn.execute(
            "INSERT OR IGNORE INTO MapStats (map_name) VALUES (?)", (map_name,)
        )
    db.conn.commit()
    return count


def load_heroes_from_json(db: Database, json_path: str) -> int:
    """Load a hero roster exported by HeroesDataParser (JSON array)."""
    if not os.path.exists(json_path):
        return 0
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    count = 0
    for hero in data:
        db.upsert_hero(
            hero.get("name", hero.get("hero_name", "")),
            hero.get("role", "Assassin"),
            hero_difficulty=hero.get("difficulty"),
            franchise=hero.get("universe", hero.get("franchise")),
        )
        count += 1
    return count


def import_from_replay_parser(db: Database, parsed_matches) -> int:
    """Ingest match data produced by the heroprotocol-based replay parser.

    Each item in parsed_matches is one match dict:
        {
          "match_id": str, "map_name": str, "game_mode": str,
          "players": [
             {"battletag": str, "team": "ally"|"enemy", "hero": str,
              "role": str, "is_winner": bool, "kills": int,
              "deaths": int, "assists": int},
             ...  (10 players)
          ],
          "bans": ["HeroName", ...]
        }
    """
    from datetime import datetime
    imported = 0
    affected = set()
    for match in parsed_matches:
        mid = match["match_id"]
        map_name = match.get("map_name")
        # Ensure referenced rows exist so foreign keys are satisfied
        # (Match.map_name -> MapStats.map_name).
        if map_name:
            db.conn.execute(
                "INSERT OR IGNORE INTO MapStats (map_name) VALUES (?)", (map_name,))
        db.conn.execute(
            "INSERT OR REPLACE INTO Match (match_id, map_name, game_mode, match_date) "
            "VALUES (?, ?, ?, ?)",
            (mid, map_name, match.get("game_mode"), datetime.utcnow().isoformat()),
        )
        for p in match.get("players", []):
            tag = p["battletag"]
            hero = p.get("hero")
            db.upsert_player(tag)
            # Ensure the hero exists (PlayerMatch.hero_played -> Hero.hero_name).
            if hero:
                db.conn.execute(
                    "INSERT OR IGNORE INTO Hero (hero_name, hero_role) VALUES (?, ?)",
                    (hero, p.get("role") or "Unknown"))
            # PlayerMatch is keyed by (player_battletag, match_id); INSERT OR
            # REPLACE makes re-importing the same match idempotent (no dupes).
            db.conn.execute(
                """INSERT OR REPLACE INTO PlayerMatch
                   (player_battletag, match_id, hero_played, role_played, team,
                    is_winner, kills, deaths, assists)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tag, mid, hero, p.get("role"), p.get("team"),
                 int(bool(p.get("is_winner"))),
                 int(p.get("kills") or 0), int(p.get("deaths") or 0),
                 int(p.get("assists") or 0)),
            )
            affected.add(tag)
        db.conn.commit()
        imported += 1

    # Recompute per-hero and overall aggregates from PlayerMatch (the source of
    # truth). Deriving rather than incrementing keeps imports idempotent: re-
    # importing the same match does not inflate any counters.
    for tag in affected:
        _recompute_player_aggregates(db, tag)
    db.conn.commit()
    return imported


def _recompute_player_aggregates(db: Database, battletag: str) -> None:
    """Rebuild PlayerHeroStats and Player totals for one player from PlayerMatch."""
    win = "COALESCE(SUM(CASE WHEN is_winner THEN 1 ELSE 0 END), 0)"
    rows = db.conn.execute(
        f"SELECT hero_played AS hero, COUNT(*) AS g, {win} AS w "
        "FROM PlayerMatch WHERE player_battletag = ? AND hero_played IS NOT NULL "
        "GROUP BY hero_played", (battletag,)).fetchall()
    for r in rows:
        g, w = r["g"], r["w"]
        db.upsert_hero_stats(battletag, r["hero"],
                             games_played=g, wins=w, losses=g - w)
    tot = db.conn.execute(
        f"SELECT COUNT(*) AS g, {win} AS w FROM PlayerMatch "
        "WHERE player_battletag = ?", (battletag,)).fetchone()
    g, w = tot["g"], tot["w"]
    db.upsert_player(battletag, total_games=g, total_wins=w, total_losses=g - w)

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
    for match in parsed_matches:
        mid = match["match_id"]
        db.conn.execute(
            "INSERT OR REPLACE INTO Match (match_id, map_name, game_mode, match_date) "
            "VALUES (?, ?, ?, ?)",
            (mid, match.get("map_name"), match.get("game_mode"),
             datetime.utcnow().isoformat()),
        )
        for p in match.get("players", []):
            tag = p["battletag"]
            db.upsert_player(tag)
            db.conn.execute(
                """INSERT OR REPLACE INTO PlayerMatch
                   (player_battletag, match_id, hero_played, role_played, team,
                    is_winner, kills, deaths, assists)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tag, mid, p.get("hero"), p.get("role"), p.get("team"),
                 int(p.get("is_winner", False)),
                 p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0)),
            )
            hero = p.get("hero")
            if hero:
                row = db.conn.execute(
                    "SELECT games_played, wins, losses FROM PlayerHeroStats "
                    "WHERE player_battletag=? AND hero_name=?", (tag, hero)
                ).fetchone()
                g = (row["games_played"] if row else 0) + 1
                w = (row["wins"]         if row else 0) + int(p.get("is_winner", False))
                l = (row["losses"]       if row else 0) + int(not p.get("is_winner", False))
                db.upsert_hero_stats(tag, hero, games_played=g, wins=w, losses=l)
        db.conn.commit()
        imported += 1
    return imported

"""SQLite access layer for players, heroes, draft sessions and recommendations."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import config


class Database:
    """Thin wrapper around the SQLite connection with domain-specific helpers."""

    def __init__(self, db_path: str = config.DB_PATH, schema_path: str = config.SCHEMA_PATH):
        self.db_path = db_path
        self.schema_path = schema_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Run schema.sql; CREATE IF NOT EXISTS makes this safe to call always."""
        if os.path.exists(self.schema_path):
            with open(self.schema_path, "r", encoding="utf-8") as f:
                self.conn.executescript(f.read())
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ── Players ───────────────────────────────────────────────────────────────
    def get_player(self, battletag: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM Player WHERE battletag = ?", (battletag,))
        return cur.fetchone()

    def upsert_player(self, battletag: str, **fields: Any) -> None:
        """Insert a player if missing, then apply any provided field updates."""
        now = datetime.utcnow().isoformat()
        if self.get_player(battletag) is None:
            self.conn.execute(
                """INSERT INTO Player
                   (battletag, current_mmr, first_seen, last_seen, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (battletag, config.ELO_NEUTRAL_RATING, now, now, now),
            )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [now, battletag]
            self.conn.execute(
                f"UPDATE Player SET {cols}, last_seen = ? WHERE battletag = ?", vals
            )
        else:
            self.conn.execute(
                "UPDATE Player SET last_seen = ? WHERE battletag = ?", (now, battletag)
            )
        self.conn.commit()

    def is_known_player(self, battletag: str) -> bool:
        return self.get_player(battletag) is not None

    # ── Per-hero stats ──────────────────────────────────────────────────────────
    def get_hero_stats(self, battletag: str) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM PlayerHeroStats WHERE player_battletag = ? "
            "ORDER BY games_played DESC",
            (battletag,),
        )
        return cur.fetchall()

    def upsert_hero_stats(self, battletag: str, hero: str, **fields: Any) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM PlayerHeroStats WHERE player_battletag = ? AND hero_name = ?",
            (battletag, hero),
        ).fetchone()
        if exists is None:
            self.conn.execute(
                "INSERT INTO PlayerHeroStats (player_battletag, hero_name) VALUES (?, ?)",
                (battletag, hero),
            )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [battletag, hero]
            self.conn.execute(
                f"UPDATE PlayerHeroStats SET {cols} "
                f"WHERE player_battletag = ? AND hero_name = ?",
                vals,
            )
        self.conn.commit()

    # ── Hero pool ────────────────────────────────────────────────────────────────
    def get_pool(self, battletag: str) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM PlayerPool WHERE player_battletag = ? "
            "ORDER BY priority_tier ASC, comfort_score DESC",
            (battletag,),
        )
        return cur.fetchall()

    def clear_pool(self, battletag: str) -> None:
        self.conn.execute("DELETE FROM PlayerPool WHERE player_battletag = ?", (battletag,))

    def insert_pool_entry(self, battletag: str, hero: str, tier: int,
                          comfort: float, is_otp: bool,
                          games_30d: int = 0, wins_30d: int = 0,
                          games_7d: int = 0) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO PlayerPool
               (player_battletag, hero_name, priority_tier, comfort_score,
                games_last_30d, wins_last_30d, games_last_7d, is_otp_hero,
                last_recalculated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (battletag, hero, tier, comfort, games_30d, wins_30d,
             games_7d, int(is_otp), now),
        )
        self.conn.commit()

    # ── Role stats ────────────────────────────────────────────────────────────────
    def get_role_stats(self, battletag: str) -> List[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM PlayerRoleStats WHERE player_battletag = ?", (battletag,)
        )
        return cur.fetchall()

    # ── Synergy / counter matrices ──────────────────────────────────────────────
    def get_synergy(self, hero_a: str, hero_b: str) -> Optional[float]:
        a, b = sorted([hero_a, hero_b])
        row = self.conn.execute(
            "SELECT synergy_score FROM HeroSynergy WHERE hero_a = ? AND hero_b = ?",
            (a, b),
        ).fetchone()
        return row["synergy_score"] if row else None

    def get_counter(self, hero: str, counter_hero: str) -> Optional[float]:
        row = self.conn.execute(
            "SELECT counter_score FROM HeroCounter WHERE hero = ? AND counter_hero = ?",
            (hero, counter_hero),
        ).fetchone()
        return row["counter_score"] if row else None

    def upsert_synergy(self, hero_a: str, hero_b: str,
                       games: int, wins: int, score: float) -> None:
        a, b = sorted([hero_a, hero_b])
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO HeroSynergy
               (hero_a, hero_b, games_together, wins_together, synergy_score, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (a, b, games, wins, score, now),
        )
        self.conn.commit()

    def upsert_counter(self, hero: str, counter_hero: str,
                       games: int, wins: int, score: float) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO HeroCounter
               (hero, counter_hero, games_against, wins_as_counter, counter_score, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (hero, counter_hero, games, wins, score, now),
        )
        self.conn.commit()

    # ── Hero reference ────────────────────────────────────────────────────────────
    def upsert_hero(self, name: str, role: str, **fields: Any) -> None:
        if self.conn.execute("SELECT 1 FROM Hero WHERE hero_name = ?", (name,)).fetchone() is None:
            self.conn.execute(
                "INSERT INTO Hero (hero_name, hero_role) VALUES (?, ?)", (name, role)
            )
        else:
            self.conn.execute(
                "UPDATE Hero SET hero_role = ? WHERE hero_name = ?", (role, name)
            )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            vals = list(fields.values()) + [name]
            self.conn.execute(f"UPDATE Hero SET {cols} WHERE hero_name = ?", vals)
        self.conn.commit()

    def get_hero(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM Hero WHERE hero_name = ?", (name,)).fetchone()

    def get_all_heroes(self) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM Hero WHERE is_available = 1 ORDER BY hero_name"
        ).fetchall()

    def get_global_winrate(self, hero: str) -> float:
        """Aggregate win rate of a hero across every player's stats."""
        row = self.conn.execute(
            "SELECT SUM(wins) AS w, SUM(games_played) AS g "
            "FROM PlayerHeroStats WHERE hero_name = ?",
            (hero,),
        ).fetchone()
        if row and row["g"]:
            return row["w"] / row["g"]
        return 0.5  # no data => neutral

    # ── Draft sessions ───────────────────────────────────────────────────────────
    def create_draft_session(self, session_id: str, map_name: Optional[str],
                             game_mode: str, first_pick_team: str) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO DraftSession
               (session_id, map_name, created_at, status, game_mode, first_pick_team)
               VALUES (?, ?, ?, 'in_progress', ?, ?)""",
            (session_id, map_name, now, game_mode, first_pick_team),
        )
        self.conn.commit()

    def complete_draft_session(self, session_id: str) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            "UPDATE DraftSession SET status='completed', completed_at=? WHERE session_id=?",
            (now, session_id),
        )
        self.conn.commit()

    def set_draft_player(self, session_id: str, slot: int, battletag: str,
                         team: str, is_otp: bool, otp_hero: Optional[str]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO DraftPlayerSlot
               (session_id, slot_position, player_battletag, team, is_otp, otp_hero)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, slot, battletag, team, int(is_otp), otp_hero),
        )
        self.conn.commit()

    def set_hero_state(self, session_id: str, hero: str, state: str,
                       order: int, performed_by: Optional[str] = None,
                       phase: int = 0) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO DraftHeroState
               (session_id, hero_name, state, action_order, performed_by, phase)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, hero, state, order, performed_by, phase),
        )
        self.conn.commit()

    def get_available_heroes(self, session_id: str) -> List[str]:
        """Heroes that are neither banned nor picked in this session."""
        taken = {
            r["hero_name"]
            for r in self.conn.execute(
                "SELECT hero_name FROM DraftHeroState "
                "WHERE session_id = ? AND state != 'available'",
                (session_id,),
            ).fetchall()
        }
        return [r["hero_name"] for r in self.get_all_heroes() if r["hero_name"] not in taken]

    def get_draft_picks(self, session_id: str, team: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT hero_name FROM DraftHeroState WHERE session_id = ? AND state = ?",
            (session_id, f"picked_{team}"),
        ).fetchall()
        return [r["hero_name"] for r in rows]

    def get_draft_players(self, session_id: str, team: Optional[str] = None) -> List[sqlite3.Row]:
        if team:
            return self.conn.execute(
                "SELECT * FROM DraftPlayerSlot WHERE session_id = ? AND team = ?",
                (session_id, team),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM DraftPlayerSlot WHERE session_id = ?", (session_id,)
        ).fetchall()

    # ── Recommendations ──────────────────────────────────────────────────────────
    def save_pick_recommendation(self, rec: Dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO PickRecommendation
               (recommendation_id, session_id, target_battletag, hero_name,
                pick_score, score_global, score_synergy, score_counter,
                score_comfort, score_map, pool_tier, priority_reason,
                rank, is_available, created_at)
               VALUES (:recommendation_id, :session_id, :target_battletag, :hero_name,
                :pick_score, :score_global, :score_synergy, :score_counter,
                :score_comfort, :score_map, :pool_tier, :priority_reason,
                :rank, :is_available, :created_at)""",
            rec,
        )
        self.conn.commit()

    def save_ban_recommendation(self, rec: Dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO BanRecommendation
               (recommendation_id, session_id, recommended_hero, reason, priority,
                opponent_battletag, is_otp_ban, target_player_battletag,
                is_still_available, created_at)
               VALUES (:recommendation_id, :session_id, :recommended_hero, :reason,
                :priority, :opponent_battletag, :is_otp_ban, :target_player_battletag,
                :is_still_available, :created_at)""",
            rec,
        )
        self.conn.commit()

    # ── Maintenance ────────────────────────────────────────────────────────────────
    def cleanup_old_form_history(self, days: int = 90) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        self.conn.execute("DELETE FROM PlayerFormHistory WHERE match_date < ?", (cutoff,))
        self.conn.commit()

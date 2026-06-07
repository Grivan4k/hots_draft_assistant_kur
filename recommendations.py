"""Ban and pick recommendations for the current draft."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import config
from analytics import PlayerAnalyzer
from db import Database


@dataclass
class PickSuggestion:
    hero: str
    score: float
    components: Dict[str, float]
    pool_tier: Optional[int]
    reason: str


@dataclass
class BanSuggestion:
    hero: str
    priority: float
    reason: str
    target_player: Optional[str]
    is_otp_ban: bool


class PickAdvisor:
    """Scores each available hero with a weighted multi-factor model:
    global win rate, team synergy, counter value, player comfort and map fit.
    """

    def __init__(self, db: Database, analyzer: PlayerAnalyzer):
        self.db = db
        self.analyzer = analyzer

    def f_global(self, hero: str) -> float:
        return self.db.get_global_winrate(hero)

    def f_synergy(self, hero: str, team_heroes: List[str]) -> float:
        """Mean synergy with already-picked allies (0.5 = neutral)."""
        if not team_heroes:
            return 0.5
        scores = []
        for ally in team_heroes:
            s = self.db.get_synergy(hero, ally)
            scores.append(0.5 + s if s is not None else 0.5)
        return sum(scores) / len(scores)

    def f_counter(self, hero: str, enemy_heroes: List[str]) -> float:
        """How well this hero counters the enemy picks (0.5 = neutral)."""
        if not enemy_heroes:
            return 0.5
        scores = []
        for enemy in enemy_heroes:
            c = self.db.get_counter(enemy, hero)
            scores.append(0.5 + c if c is not None else 0.5)
        return sum(scores) / len(scores)

    def f_player_comfort(self, hero: str, battletag: str):
        """Comfort scaled by pool tier. Returns (value, tier)."""
        pool = {r["hero_name"]: r for r in self.db.get_pool(battletag)}
        if hero in pool:
            tier = pool[hero]["priority_tier"]
            base = pool[hero]["comfort_score"]
        else:
            tier, base = None, 0.0
        return min(1.0, base * config.POOL_TIER_MULTIPLIER.get(tier, 0.5)), tier

    def f_map(self, hero: str, map_name: Optional[str]) -> float:
        if not map_name:
            return 0.5
        row = self.db.conn.execute(
            "SELECT wins, games_played FROM PlayerMapStats WHERE map_name = ? "
            "AND favorite_hero_on_map = ?", (map_name, hero)
        ).fetchone()
        if row and row["games_played"]:
            return row["wins"] / row["games_played"]
        return 0.5

    def score_hero(self, hero: str, battletag: str,
                   team_heroes: List[str], enemy_heroes: List[str],
                   map_name: Optional[str], is_otp_player: bool) -> PickSuggestion:
        weights = config.PICK_WEIGHTS_OTP if is_otp_player else config.PICK_WEIGHTS

        s_global = self.f_global(hero)
        s_synergy = self.f_synergy(hero, team_heroes)
        s_counter = self.f_counter(hero, enemy_heroes)
        s_comfort, tier = self.f_player_comfort(hero, battletag)
        s_map = self.f_map(hero, map_name)

        total = (
            weights["global"] * s_global
            + weights["synergy"] * s_synergy
            + weights["counter"] * s_counter
            + weights["comfort"] * s_comfort
            + weights["map"] * s_map
        )

        if tier == config.POOL_TIER_OTP:
            reason = "OTP"
        elif tier == config.POOL_TIER_MAIN:
            reason = "pool_main"
        elif tier == config.POOL_TIER_REGULAR:
            reason = "pool_regular"
        elif s_counter > 0.6:
            reason = "counter"
        elif s_synergy > 0.6:
            reason = "synergy"
        else:
            reason = "meta"

        return PickSuggestion(
            hero=hero, score=round(total, 4),
            components={
                "global": round(s_global, 3), "synergy": round(s_synergy, 3),
                "counter": round(s_counter, 3), "comfort": round(s_comfort, 3),
                "map": round(s_map, 3),
            },
            pool_tier=tier, reason=reason,
        )

    def recommend(self, session_id: str, battletag: str,
                  team: str, map_name: Optional[str],
                  n: int = config.N_PICK_RECOMMENDATIONS) -> List[PickSuggestion]:
        """Top-N picks for a player, scoring only still-available heroes."""
        available = self.db.get_available_heroes(session_id)
        team_heroes = self.db.get_draft_picks(session_id, team)
        enemy_team = "enemy" if team == "ally" else "ally"
        enemy_heroes = self.db.get_draft_picks(session_id, enemy_team)

        player = self.db.get_player(battletag)
        is_otp = bool(player["is_otp"]) if player else False

        suggestions = [
            self.score_hero(h, battletag, team_heroes, enemy_heroes, map_name, is_otp)
            for h in available
        ]
        suggestions.sort(key=lambda s: s.score, reverse=True)
        top = suggestions[:n]

        now = datetime.utcnow().isoformat()
        for rank, s in enumerate(top, start=1):
            self.db.save_pick_recommendation({
                "recommendation_id": str(uuid.uuid4()), "session_id": session_id,
                "target_battletag": battletag, "hero_name": s.hero,
                "pick_score": s.score, "score_global": s.components["global"],
                "score_synergy": s.components["synergy"], "score_counter": s.components["counter"],
                "score_comfort": s.components["comfort"], "score_map": s.components["map"],
                "pool_tier": s.pool_tier, "priority_reason": s.reason,
                "rank": rank, "is_available": 1, "created_at": now,
            })
        return top


class BanAdvisor:
    """Suggests bans, prioritising enemy one-trick and high-win-rate heroes."""

    def __init__(self, db: Database, analyzer: PlayerAnalyzer):
        self.db = db
        self.analyzer = analyzer

    def _meta_weight(self, hero: str) -> float:
        row = self.db.get_hero(hero)
        tier_map = {"S": 1.0, "A": 0.85, "B": 0.7, "C": 0.55, "D": 0.4}
        if row and row["current_meta_tier"]:
            return tier_map.get(row["current_meta_tier"], 0.6)
        return 0.6

    def recommend(self, session_id: str,
                  n: int = config.N_BAN_RECOMMENDATIONS) -> List[BanSuggestion]:
        """Top-N ban candidates drawn from enemy players' pools."""
        available = set(self.db.get_available_heroes(session_id))
        enemies = self.db.get_draft_players(session_id, "enemy")
        candidates: Dict[str, BanSuggestion] = {}

        for enemy in enemies:
            tag = enemy["player_battletag"]
            if not tag:
                continue
            profile = self.analyzer.build_profile(tag)
            for entry in (profile.pool[:3] if profile.pool else []):
                hero = entry["hero_name"]
                if hero not in available:
                    continue
                winrate = entry["winrate"]
                priority = winrate * self._meta_weight(hero)
                if entry["is_otp"]:
                    priority *= 1.5  # boost enemy one-trick heroes

                if entry["is_otp"]:
                    reason = f"OTP-герой игрока {tag} (WR {winrate:.0%})"
                elif winrate >= 0.65:
                    reason = f"Сигнатурный герой {tag} (WR {winrate:.0%})"
                else:
                    reason = f"Сильный герой {tag} (WR {winrate:.0%})"

                if hero not in candidates or priority > candidates[hero].priority:
                    candidates[hero] = BanSuggestion(
                        hero=hero, priority=round(priority, 4), reason=reason,
                        target_player=tag, is_otp_ban=entry["is_otp"],
                    )

        top = sorted(candidates.values(), key=lambda b: b.priority, reverse=True)[:n]

        now = datetime.utcnow().isoformat()
        for rank, b in enumerate(top, start=1):
            self.db.save_ban_recommendation({
                "recommendation_id": str(uuid.uuid4()), "session_id": session_id,
                "recommended_hero": b.hero, "reason": b.reason, "priority": rank,
                "opponent_battletag": b.target_player, "is_otp_ban": int(b.is_otp_ban),
                "target_player_battletag": b.target_player, "is_still_available": 1,
                "created_at": now,
            })
        return top

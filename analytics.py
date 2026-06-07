"""Player rating, OTP detection, hero-pool tiers and role analysis."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config
from db import Database


def expected_score(rating_a: float, rating_b: float) -> float:
    """Elo expected win probability of A against B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def choose_k(total_games: int) -> int:
    """Elo K-factor: larger for new players, smaller for veterans."""
    if total_games < config.ELO_NEW_PLAYER_GAMES:
        return config.ELO_K_NEW
    if total_games > config.ELO_PRO_PLAYER_GAMES:
        return config.ELO_K_PRO
    return config.ELO_K_EXPERIENCED


def update_rating(current: float, k: int, actual: int, expected: float) -> int:
    """R' = R + K·(S - E)."""
    return int(round(current + k * (actual - expected)))


def rating_to_letter(mmr: int) -> Tuple[str, str]:
    """Map an MMR value to a letter grade and colour."""
    for threshold, letter, color in config.RATING_SCALE:
        if mmr >= threshold:
            return letter, color
    return "D", "#9D9D9D"


@dataclass
class PlayerProfile:
    """Everything the UI needs to render a player card."""
    battletag: str
    mmr: int
    letter: str
    color: str
    total_games: int
    winrate: float
    is_otp: bool
    otp_hero: Optional[str]
    top_role: Optional[str]
    top_hero: Optional[str]
    pool: List[Dict] = field(default_factory=list)
    role_breakdown: Dict[str, float] = field(default_factory=dict)
    is_new: bool = False


class PlayerAnalyzer:
    """Builds player profiles from stored stats."""

    def __init__(self, db: Database):
        self.db = db

    def classify_otp(self, total_games: int,
                     hero_stats: List) -> Tuple[bool, Optional[str], float]:
        """Return (is_otp, otp_hero, share_of_games_on_top_hero)."""
        if total_games <= 0 or not hero_stats:
            return False, None, 0.0
        top = max(hero_stats, key=lambda r: r["games_played"])
        share = top["games_played"] / total_games
        is_otp = share > config.OTP_THRESHOLD_HIGH or (
            total_games >= config.OTP_MIN_GAMES_FOR_MEDIUM
            and share > config.OTP_THRESHOLD_MEDIUM
        )
        return is_otp, (top["hero_name"] if is_otp else None), share

    @staticmethod
    def comfort_score(wins: int, games: int) -> float:
        """Win rate damped by a regularisation term for small samples (0..1)."""
        if games <= 0:
            return 0.0
        winrate = wins / games
        reg = 1.0 - config.COMFORT_LAMBDA * math.exp(-config.COMFORT_GAMMA * games)
        return max(0.0, min(1.0, winrate * reg))

    def build_pool(self, battletag: str, total_games: int,
                   hero_stats: List, otp_hero: Optional[str]) -> List[Dict]:
        """Assign each hero a pool tier and persist the pool."""
        if total_games <= 0:
            return []
        ranked = sorted(hero_stats, key=lambda r: r["games_played"], reverse=True)
        pool: List[Dict] = []
        self.db.clear_pool(battletag)
        for idx, row in enumerate(ranked):
            games, wins = row["games_played"], row["wins"]
            if games == 0:
                continue
            share = games / total_games
            winrate = wins / games
            comfort = self.comfort_score(wins, games)

            if otp_hero and row["hero_name"] == otp_hero:
                tier = config.POOL_TIER_OTP
            elif idx < 3 and share > config.MAIN_TIER_SHARE:
                tier = config.POOL_TIER_MAIN
            elif games >= config.REGULAR_MIN_GAMES and winrate >= config.REGULAR_MIN_WINRATE:
                tier = config.POOL_TIER_REGULAR
            else:
                tier = config.POOL_TIER_FLEX

            is_otp = bool(otp_hero and row["hero_name"] == otp_hero)
            pool.append({
                "hero_name": row["hero_name"], "tier": tier, "comfort": comfort,
                "games": games, "winrate": winrate, "is_otp": is_otp,
            })
            self.db.insert_pool_entry(
                battletag, row["hero_name"], tier, comfort, is_otp,
                games_30d=row["recent_games_30d"] if "recent_games_30d" in row.keys() else 0,
                wins_30d=row["recent_wins_30d"] if "recent_wins_30d" in row.keys() else 0,
            )
        return pool

    def analyze_roles(self, battletag: str) -> Dict[str, float]:
        """Win rate per role."""
        out: Dict[str, float] = {}
        for row in self.db.get_role_stats(battletag):
            if row["games_played"] > 0:
                out[row["role_name"]] = row["wins"] / row["games_played"]
        return out

    def top_role(self, role_breakdown: Dict[str, float]) -> Optional[str]:
        return max(role_breakdown, key=role_breakdown.get) if role_breakdown else None

    def build_profile(self, battletag: str) -> PlayerProfile:
        """Assemble a full profile; unknown players get a neutral rating."""
        player = self.db.get_player(battletag)
        hero_stats = self.db.get_hero_stats(battletag)

        if player is None or not hero_stats:
            letter, color = rating_to_letter(config.ELO_NEUTRAL_RATING)
            return PlayerProfile(
                battletag=battletag, mmr=config.ELO_NEUTRAL_RATING,
                letter=letter, color=color, total_games=0, winrate=0.0,
                is_otp=False, otp_hero=None, top_role=None, top_hero=None, is_new=True,
            )

        total_games = player["total_games"] or sum(r["games_played"] for r in hero_stats)
        total_wins = player["total_wins"] or sum(r["wins"] for r in hero_stats)
        winrate = (total_wins / total_games) if total_games else 0.0

        is_otp, otp_hero, otp_score = self.classify_otp(total_games, hero_stats)
        pool = self.build_pool(battletag, total_games, hero_stats, otp_hero)
        roles = self.analyze_roles(battletag)

        mmr = player["current_mmr"] or config.ELO_NEUTRAL_RATING
        letter, color = rating_to_letter(mmr)
        top_hero = max(hero_stats, key=lambda r: r["games_played"])["hero_name"]

        # Cache derived OTP fields back onto the player row.
        self.db.upsert_player(
            battletag, is_otp=int(is_otp), otp_hero_name=otp_hero, otp_score=otp_score,
            total_games=total_games, total_wins=total_wins,
            pool_size=len([p for p in pool if p["tier"] <= config.POOL_TIER_REGULAR]),
        )

        return PlayerProfile(
            battletag=battletag, mmr=mmr, letter=letter, color=color,
            total_games=total_games, winrate=winrate,
            is_otp=is_otp, otp_hero=otp_hero,
            top_role=self.top_role(roles), top_hero=top_hero,
            pool=pool, role_breakdown=roles,
        )


class TeamComparator:
    """Average-MMR comparison and win-probability estimate."""

    def __init__(self, db: Database, analyzer: PlayerAnalyzer):
        self.db = db
        self.analyzer = analyzer

    def average_mmr(self, battletags: List[str]) -> Tuple[float, bool]:
        """Mean team MMR; second value flags that some players had no data."""
        ratings, partial = [], False
        for tag in battletags:
            profile = self.analyzer.build_profile(tag)
            ratings.append(profile.mmr)
            if profile.is_new:
                partial = True
        avg = sum(ratings) / len(ratings) if ratings else config.ELO_NEUTRAL_RATING
        return avg, partial

    def win_probability(self, ally_tags: List[str], enemy_tags: List[str]) -> Dict:
        ally_mmr, ally_partial = self.average_mmr(ally_tags)
        enemy_mmr, enemy_partial = self.average_mmr(enemy_tags)
        return {
            "ally_mmr": round(ally_mmr),
            "enemy_mmr": round(enemy_mmr),
            "ally_win_probability": round(expected_score(ally_mmr, enemy_mmr), 3),
            "partial_data": ally_partial or enemy_partial,
        }

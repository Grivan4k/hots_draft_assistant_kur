"""Application configuration — analytics constants and UI defaults."""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "analytics.db")
SCHEMA_PATH= os.path.join(BASE_DIR, "schema.sql")
CONFIG_JSON= os.path.join(BASE_DIR, "user_settings.json")

# ── OTP / hero-pool thresholds ──────────────────────────────────────────────
OTP_THRESHOLD_HIGH        = 0.60   # > 60 % of games on one hero → OTP
OTP_THRESHOLD_MEDIUM      = 0.45   # > 45 % counts once sample ≥ 50 games
OTP_MIN_GAMES_FOR_MEDIUM  = 50

POOL_TIER_OTP     = 1
POOL_TIER_MAIN    = 2
POOL_TIER_REGULAR = 3
POOL_TIER_FLEX    = 4

MAIN_TIER_SHARE    = 0.10   # top-3 hero with > 10 % share → Main
REGULAR_MIN_GAMES  = 10
REGULAR_MIN_WINRATE= 0.45

# ── Player rating (Elo) ────────────────────────────────────────────────────────
ELO_K_NEW             = 40
ELO_K_EXPERIENCED     = 20
ELO_K_PRO             = 10
ELO_NEW_PLAYER_GAMES  = 30
ELO_PRO_PLAYER_GAMES  = 1000
ELO_NEUTRAL_RATING    = 1500

RATING_SCALE: List[Tuple[int, str, str]] = [
    (2400, "S", "#FFD700"),
    (2100, "A", "#A335EE"),
    (1800, "B", "#0070DD"),
    (1500, "C", "#1EFF00"),
    (0,    "D", "#9D9D9D"),
]

# ── Pick-score factor weights ──────────────────────────────────────────────────
PICK_WEIGHTS = {
    "global":  0.25,
    "synergy": 0.25,
    "counter": 0.20,
    "comfort": 0.20,
    "map":     0.10,
}
# Higher comfort weight for one-trick players.
PICK_WEIGHTS_OTP = {
    "global":  0.20,
    "synergy": 0.20,
    "counter": 0.15,
    "comfort": 0.35,
    "map":     0.10,
}

POOL_TIER_MULTIPLIER = {
    POOL_TIER_OTP:     1.50,
    POOL_TIER_MAIN:    1.20,
    POOL_TIER_REGULAR: 1.00,
    POOL_TIER_FLEX:    0.70,
    None:              0.50,
}

COMFORT_LAMBDA = 0.9
COMFORT_GAMMA  = 0.1

# ── Recommendation counts ──────────────────────────────────────────────────────
N_BAN_RECOMMENDATIONS  = 3
N_PICK_RECOMMENDATIONS = 5

# ── Role labels ────────────────────────────────────────────────────────────────
ROLE_NAMES = ["Tank", "Bruiser", "Healer", "Assassin", "Support"]
ROLE_NAMES_RU = {
    "Tank": "Танк", "Bruiser": "Рубака", "Healer": "Лекарь",
    "Assassin": "Убийца", "Support": "Поддержка",
}

# ── Default UI settings (persisted in user_settings.json) ────────────────────
DEFAULT_SETTINGS: Dict = {
    "overlay_enabled":         True,
    "overlay_opacity":         85,
    "show_ban_recommendations": True,
    "show_pick_recommendations":True,
    "panel_x":                 20,
    "panel_y":                 200,
    "language":                "ru",
}

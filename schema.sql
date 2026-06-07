-- ============================================================
-- НОВАЯ СХЕМА БД: Draft Assistant for Heroes of the Storm
-- Версия: 2.0 (с поддержкой OTP, пула, драфта, синергий)
-- ============================================================

-- ============================================================
-- БЛОК 1. СПРАВОЧНИКИ
-- ============================================================

CREATE TABLE IF NOT EXISTS Hero (
    hero_name           TEXT PRIMARY KEY,
    hero_role           TEXT NOT NULL,         -- Tank/Healer/Assassin/Bruiser/Support
    hero_difficulty     TEXT,                  -- Easy/Medium/Hard
    release_date        DATE,
    franchise           TEXT,                  -- Warcraft/Starcraft/Diablo/Overwatch/Classic
    icon_path           TEXT,
    current_meta_tier   TEXT,                  -- S/A/B/C/D (обновляется с патчем)
    is_available        BOOLEAN DEFAULT 1,     -- доступен в текущем патче
    meta_updated_at     DATETIME
);

CREATE TABLE IF NOT EXISTS MapStats (
    map_name            TEXT PRIMARY KEY,
    average_duration    INTEGER,               -- средняя длительность (сек)
    winrate_blue_side   REAL,
    winrate_red_side    REAL,
    objective_timings   TEXT,                  -- JSON с таймингами объектов
    minions_per_lane    INTEGER
);


-- ============================================================
-- БЛОК 2. ПРОФИЛЬ ИГРОКА И ЕГО СТАТИСТИКА
-- ============================================================

CREATE TABLE IF NOT EXISTS Player (
    battletag           TEXT PRIMARY KEY,
    battle_id           INTEGER,
    current_rank        TEXT,
    current_mmr         INTEGER DEFAULT 1500,
    total_games         INTEGER DEFAULT 0,
    total_wins          INTEGER DEFAULT 0,
    total_losses        INTEGER DEFAULT 0,

    -- OTP-поля (пересчитываются при каждом обновлении статистики)
    is_otp              BOOLEAN DEFAULT 0,
    otp_hero_name       TEXT REFERENCES Hero(hero_name),
    otp_score           REAL DEFAULT 0.0,      -- max_hero_games / total_games

    -- Пул
    pool_size           INTEGER DEFAULT 0,     -- кол-во героев в тирах 1–3

    last_seen           DATETIME,
    first_seen          DATETIME,
    region              TEXT DEFAULT 'EU',
    last_updated        DATETIME
);

CREATE TABLE IF NOT EXISTS PlayerHeroStats (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    hero_name           TEXT NOT NULL REFERENCES Hero(hero_name),
    games_played        INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    last_played         DATETIME,
    average_kda         REAL DEFAULT 0.0,

    -- Пул и OTP
    pool_tier           INTEGER,               -- 1=OTP, 2=Main, 3=Regular, 4=Flex, NULL=не в пуле
    otp_score           REAL DEFAULT 0.0,      -- games_played / player.total_games
    comfort_score       REAL DEFAULT 0.0,      -- winrate * (1 - e^(-0.1*games)), от 0 до 1

    -- Актуальность (для «свежести» пула)
    recent_games_30d    INTEGER DEFAULT 0,
    recent_wins_30d     INTEGER DEFAULT 0,
    recent_games_7d     INTEGER DEFAULT 0,

    PRIMARY KEY (player_battletag, hero_name)
);

-- Явный пул игрока с тирами (отдельно от сырой статистики)
CREATE TABLE IF NOT EXISTS PlayerPool (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    hero_name           TEXT NOT NULL REFERENCES Hero(hero_name),

    -- Тир: 1=OTP (>60% игр), 2=Main (топ-3, >10%), 3=Regular (>10 игр, WR≥45%), 4=Flex
    priority_tier       INTEGER NOT NULL CHECK (priority_tier BETWEEN 1 AND 4),

    comfort_score       REAL DEFAULT 0.0,      -- кэш из PlayerHeroStats
    games_last_30d      INTEGER DEFAULT 0,
    wins_last_30d       INTEGER DEFAULT 0,
    games_last_7d       INTEGER DEFAULT 0,     -- для «горячести» пика
    is_otp_hero         BOOLEAN DEFAULT 0,
    last_played         DATETIME,
    last_recalculated   DATETIME,

    PRIMARY KEY (player_battletag, hero_name)
);

CREATE TABLE IF NOT EXISTS PlayerRoleStats (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    role_name           TEXT NOT NULL,         -- Tank/Healer/Assassin/Bruiser
    games_played        INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    most_played_hero    TEXT REFERENCES Hero(hero_name),
    PRIMARY KEY (player_battletag, role_name)
);

CREATE TABLE IF NOT EXISTS PlayerFormHistory (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    match_date          DATETIME NOT NULL,
    match_id            TEXT REFERENCES Match(match_id),
    was_win             BOOLEAN,
    hero_played         TEXT REFERENCES Hero(hero_name),
    delta_mmr           INTEGER,
    PRIMARY KEY (player_battletag, match_date)
);


-- ============================================================
-- БЛОК 3. МАТЧИ (перенесены из Приложения Г в основные)
-- ============================================================

CREATE TABLE IF NOT EXISTS Match (
    match_id            TEXT PRIMARY KEY,
    match_date          DATETIME,
    match_duration      INTEGER,               -- секунды
    map_name            TEXT REFERENCES MapStats(map_name),
    result              TEXT,                  -- win/loss (для своей команды)
    game_mode           TEXT,
    replay_available    BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS PlayerMatch (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    match_id            TEXT NOT NULL REFERENCES Match(match_id),
    hero_played         TEXT REFERENCES Hero(hero_name),
    role_played         TEXT,
    team                TEXT,                  -- ally/enemy
    is_winner           BOOLEAN,
    kills               INTEGER DEFAULT 0,
    deaths              INTEGER DEFAULT 0,
    assists             INTEGER DEFAULT 0,
    siege_damage        INTEGER DEFAULT 0,
    hero_damage         INTEGER DEFAULT 0,
    healing             INTEGER DEFAULT 0,
    exp_contribution    INTEGER DEFAULT 0,
    mvp_score           REAL DEFAULT 0.0,
    PRIMARY KEY (player_battletag, match_id)
);

CREATE TABLE IF NOT EXISTS PlayerMapStats (
    player_battletag    TEXT NOT NULL REFERENCES Player(battletag),
    map_name            TEXT NOT NULL REFERENCES MapStats(map_name),
    games_played        INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    favorite_hero_on_map TEXT REFERENCES Hero(hero_name),
    average_kda_on_map  REAL DEFAULT 0.0,
    PRIMARY KEY (player_battletag, map_name)
);


-- ============================================================
-- БЛОК 4. МАТРИЦЫ СИНЕРГИЙ И КОНТРПИКОВ
-- ============================================================

-- Синергия пар героев (Steam(h, team))
CREATE TABLE IF NOT EXISTS HeroSynergy (
    hero_a              TEXT NOT NULL REFERENCES Hero(hero_name),
    hero_b              TEXT NOT NULL REFERENCES Hero(hero_name),
    games_together      INTEGER DEFAULT 0,
    wins_together       INTEGER DEFAULT 0,
    -- wins_together/games_together - expected_wr: положительное = синергия
    synergy_score       REAL DEFAULT 0.0,
    last_updated        DATETIME,
    PRIMARY KEY (hero_a, hero_b),
    -- Исключаем дубли (A,B) и (B,A)
    CHECK (hero_a < hero_b)
);

-- Контрпики (Cenemy(h, enemy))
-- counter_hero контрит hero
CREATE TABLE IF NOT EXISTS HeroCounter (
    hero                TEXT NOT NULL REFERENCES Hero(hero_name),
    counter_hero        TEXT NOT NULL REFERENCES Hero(hero_name),
    games_against       INTEGER DEFAULT 0,
    wins_as_counter     INTEGER DEFAULT 0,
    -- wins_as_counter/games_against - 0.5: насколько эффективен контрпик
    counter_score       REAL DEFAULT 0.0,
    last_updated        DATETIME,
    PRIMARY KEY (hero, counter_hero)
);


-- ============================================================
-- БЛОК 5. ДРАФТ (новые таблицы)
-- ============================================================

-- Сессия драфта — центральная сущность
CREATE TABLE IF NOT EXISTS DraftSession (
    session_id          TEXT PRIMARY KEY,
    map_name            TEXT REFERENCES MapStats(map_name),
    created_at          DATETIME NOT NULL,
    status              TEXT DEFAULT 'in_progress', -- in_progress/completed/cancelled
    game_mode           TEXT,                  -- StormLeague/HeroLeague/QuickMatch
    first_pick_team     TEXT,                  -- ally/enemy (кто пикует первым)
    completed_at        DATETIME
);

-- Слоты игроков в сессии
CREATE TABLE IF NOT EXISTS DraftPlayerSlot (
    session_id          TEXT NOT NULL REFERENCES DraftSession(session_id),
    slot_position       INTEGER NOT NULL,      -- 1–10
    player_battletag    TEXT REFERENCES Player(battletag),
    team                TEXT NOT NULL,         -- ally/enemy
    picked_hero         TEXT REFERENCES Hero(hero_name),  -- NULL до пика
    pick_phase          INTEGER,               -- фаза, в которую сделан пик
    -- Кэш OTP-данных на момент драфта
    is_otp              BOOLEAN DEFAULT 0,
    otp_hero            TEXT REFERENCES Hero(hero_name),
    PRIMARY KEY (session_id, slot_position)
);

-- Состояние каждого героя в текущем драфте
CREATE TABLE IF NOT EXISTS DraftHeroState (
    session_id          TEXT NOT NULL REFERENCES DraftSession(session_id),
    hero_name           TEXT NOT NULL REFERENCES Hero(hero_name),
    -- available / banned_ally / banned_enemy / picked_ally / picked_enemy
    state               TEXT DEFAULT 'available',
    action_order        INTEGER,               -- порядковый номер действия
    performed_by        TEXT REFERENCES Player(battletag),
    phase               INTEGER,
    PRIMARY KEY (session_id, hero_name)
);


-- ============================================================
-- БЛОК 6. РЕКОМЕНДАЦИИ
-- ============================================================

-- Рекомендации по пикам (новая таблица)
CREATE TABLE IF NOT EXISTS PickRecommendation (
    recommendation_id   TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES DraftSession(session_id),
    target_battletag    TEXT REFERENCES Player(battletag),  -- для кого
    hero_name           TEXT NOT NULL REFERENCES Hero(hero_name),

    -- Итоговый PickScore и его компоненты
    pick_score          REAL DEFAULT 0.0,
    score_global        REAL DEFAULT 0.0,      -- Wglobal(h)
    score_synergy       REAL DEFAULT 0.0,      -- Steam(h, team)
    score_counter       REAL DEFAULT 0.0,      -- Cenemy(h, enemy)
    score_comfort       REAL DEFAULT 0.0,      -- Fplayer(h,p) с pool_tier
    score_map           REAL DEFAULT 0.0,      -- M(h, map)

    pool_tier           INTEGER,               -- тир из PlayerPool (1=OTP — наивысший)
    priority_reason     TEXT,                  -- OTP/pool_main/pool_regular/counter/synergy/meta
    rank                INTEGER,               -- место в списке (1 = наиболее приоритетный)
    is_available        BOOLEAN DEFAULT 1,     -- герой ещё не взят/не забанен
    created_at          DATETIME NOT NULL
);

-- Рекомендации по банам (обновлённая таблица)
CREATE TABLE IF NOT EXISTS BanRecommendation (
    recommendation_id       TEXT PRIMARY KEY,
    session_id              TEXT REFERENCES DraftSession(session_id),  -- НОВОЕ
    recommended_hero        TEXT NOT NULL REFERENCES Hero(hero_name),
    reason                  TEXT,
    priority                INTEGER,
    opponent_battletag      TEXT REFERENCES Player(battletag),
    -- OTP-флаги (НОВЫЕ)
    is_otp_ban              BOOLEAN DEFAULT 0,     -- банить как OTP
    target_player_battletag TEXT REFERENCES Player(battletag), -- чей OTP/сигнатурный
    is_still_available      BOOLEAN DEFAULT 1,     -- герой ещё не выбран
    was_actual              BOOLEAN,
    created_at              DATETIME
);


-- ============================================================
-- БЛОК 7. НАСТРОЙКИ
-- ============================================================

CREATE TABLE IF NOT EXISTS Settings (
    setting_key     TEXT PRIMARY KEY,
    setting_value   TEXT,
    setting_type    TEXT,   -- int/bool/string/float
    description     TEXT
);


-- ============================================================
-- БЛОК 8. ИНДЕКСЫ
-- ============================================================

-- Быстрый поиск игрока
CREATE INDEX IF NOT EXISTS idx_player_battletag
    ON Player(battletag);

-- OTP-игроки (для быстрой фильтрации при генерации банов)
CREATE INDEX IF NOT EXISTS idx_player_otp
    ON Player(is_otp) WHERE is_otp = 1;

-- Статистика по героям: сигнатурные герои для рекомендаций банов
CREATE INDEX IF NOT EXISTS idx_herostats_player_tier
    ON PlayerHeroStats(player_battletag, pool_tier, comfort_score);

-- Пул: быстрый доступ к топ-героям игрока
CREATE INDEX IF NOT EXISTS idx_pool_player_tier
    ON PlayerPool(player_battletag, priority_tier);

-- Статистика по ролям
CREATE INDEX IF NOT EXISTS idx_rolestats_player
    ON PlayerRoleStats(player_battletag);

-- История формы (последние N матчей)
CREATE INDEX IF NOT EXISTS idx_formhistory_player_date
    ON PlayerFormHistory(player_battletag, match_date DESC);

-- Активные сессии драфта
CREATE INDEX IF NOT EXISTS idx_draft_session_status
    ON DraftSession(status) WHERE status = 'in_progress';

-- Состояние героев в активном драфте
CREATE INDEX IF NOT EXISTS idx_draft_hero_state
    ON DraftHeroState(session_id, state);

-- Рекомендации по пикам для конкретной сессии и игрока
CREATE INDEX IF NOT EXISTS idx_pick_rec_session
    ON PickRecommendation(session_id, target_battletag, rank);

-- Синергии: поиск всех партнёров героя
CREATE INDEX IF NOT EXISTS idx_synergy_hero_a
    ON HeroSynergy(hero_a, synergy_score DESC);
CREATE INDEX IF NOT EXISTS idx_synergy_hero_b
    ON HeroSynergy(hero_b, synergy_score DESC);

-- Контрпики: поиск контрпиков для героя
CREATE INDEX IF NOT EXISTS idx_counter_hero
    ON HeroCounter(hero, counter_score DESC);

-- Статистика по матчам
CREATE INDEX IF NOT EXISTS idx_playermatch_player
    ON PlayerMatch(player_battletag, match_id);

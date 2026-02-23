# Practical Database Design for Combat Game (Server-Authoritative)

This version refines the schema to match your exact gameplay requirements:

- User can register and login.
- Login is required to play.
- User can be banned.
- One user can own many game profiles.
- Profile names can duplicate.
- Profiles have assets, stats, and position.
- Profile can equip only one weapon at a time, but can switch equipped weapon.
- Profile can accept quests.
- Profile can have only one skill.
- Hit registration and knockback calculations are done by server.
- Skills, weapons, and quests are canonical server data.

---

## 1) Core Entities

### 1. `users`
Account identity.

- `user_id` (PK)
- `username` (unique)
- `password_hash`
- `created_at`
- `last_login_at`

### 2. `auth_sessions`
Login sessions; playing requires valid session.

- `session_id` (PK)
- `user_id` (FK -> users.user_id)
- `issued_at`
- `expires_at`
- `revoked_at` (nullable)

### 3. `user_bans`
Ban records for users.

- `ban_id` (PK)
- `user_id` (FK -> users.user_id)
- `reason`
- `banned_at`
- `expires_at` (nullable for permanent)
- `is_active`

### 4. `player_profiles`
Playable characters owned by users.

- `player_id` (PK)
- `user_id` (FK -> users.user_id)
- `display_name` (**not unique; duplicates allowed**)
- `skill_id` (FK -> skills.skill_id, nullable while creating profile)
- `created_at`

### 5. `player_assets`
Per-profile economy and inventory metadata.

- `player_id` (PK, FK -> player_profiles.player_id)
- `coins`
- `inventory_json` (or normalized inventory table later)
- `updated_at`

### 6. `player_stats`
Per-profile stat values and PvP knockback behavior.

- `player_id` (PK, FK -> player_profiles.player_id)
- `attributes_json`
- `can_receive_pvp_knockback` (boolean)
- `updated_at`

### 7. `player_positions`
Current world position used by server for hit/knockback calculations.

- `player_id` (PK, FK -> player_profiles.player_id)
- `map_id`
- `pos_x`
- `pos_y`
- `updated_at`

### 8. `skills`
Server-managed skill catalog.

- `skill_id` (PK)
- `name` (unique)
- `knockback_multiplier`

### 9. `weapons`
Server-managed weapon catalog.

- `weapon_id` (PK)
- `name` (unique)
- `base_knockback`

### 10. `player_weapons_owned`
Which weapons a profile owns and which one is currently equipped.

- `player_id` (FK -> player_profiles.player_id)
- `weapon_id` (FK -> weapons.weapon_id)
- `obtained_at`
- `is_equipped`
- PK: (`player_id`, `weapon_id`)

> Rule: each profile can have **at most one** row with `is_equipped = TRUE`.

### 11. `quests`
Server-managed quest catalog.

- `quest_id` (PK)
- `title`
- `description`

### 12. `player_quests`
Accepted quest state per profile.

- `player_id` (FK -> player_profiles.player_id)
- `quest_id` (FK -> quests.quest_id)
- `status` (`accepted`, `completed`, `failed`, `abandoned`)
- `accepted_at`
- `updated_at`
- PK: (`player_id`, `quest_id`)

### 13. `combat_hit_events`
Server-side hit registration log for audit/replay/debug.

- `hit_id` (PK)
- `attacker_player_id` (FK -> player_profiles.player_id)
- `target_player_id` (FK -> player_profiles.player_id)
- `weapon_id` (FK -> weapons.weapon_id)
- `knockback_applied_x`
- `knockback_applied_y`
- `was_applied` (boolean)
- `server_reason` (nullable text; e.g., `target_pvp_disabled`)
- `created_at`

---

## 2) SQL DDL (PostgreSQL-flavored)

```sql
CREATE TABLE users (
  user_id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login_at TIMESTAMPTZ NULL
);

CREATE TABLE auth_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ NULL
);

CREATE TABLE user_bans (
  ban_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  reason TEXT NOT NULL,
  banned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE skills (
  skill_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  knockback_multiplier NUMERIC(6,3) NOT NULL DEFAULT 1.0 CHECK (knockback_multiplier >= 0)
);

CREATE TABLE weapons (
  weapon_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_knockback NUMERIC(8,3) NOT NULL CHECK (base_knockback >= 0)
);

CREATE TABLE quests (
  quest_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL
);

CREATE TABLE player_profiles (
  player_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  display_name TEXT NOT NULL,
  skill_id TEXT NULL REFERENCES skills(skill_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE player_assets (
  player_id TEXT PRIMARY KEY REFERENCES player_profiles(player_id),
  coins BIGINT NOT NULL DEFAULT 0 CHECK (coins >= 0),
  inventory_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE player_stats (
  player_id TEXT PRIMARY KEY REFERENCES player_profiles(player_id),
  attributes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  can_receive_pvp_knockback BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE player_positions (
  player_id TEXT PRIMARY KEY REFERENCES player_profiles(player_id),
  map_id TEXT NOT NULL,
  pos_x NUMERIC(12,3) NOT NULL,
  pos_y NUMERIC(12,3) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE player_weapons_owned (
  player_id TEXT NOT NULL REFERENCES player_profiles(player_id),
  weapon_id TEXT NOT NULL REFERENCES weapons(weapon_id),
  obtained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_equipped BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (player_id, weapon_id)
);

CREATE TABLE player_quests (
  player_id TEXT NOT NULL REFERENCES player_profiles(player_id),
  quest_id TEXT NOT NULL REFERENCES quests(quest_id),
  status TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'failed', 'abandoned')),
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (player_id, quest_id)
);

CREATE TABLE combat_hit_events (
  hit_id TEXT PRIMARY KEY,
  attacker_player_id TEXT NOT NULL REFERENCES player_profiles(player_id),
  target_player_id TEXT NOT NULL REFERENCES player_profiles(player_id),
  weapon_id TEXT NOT NULL REFERENCES weapons(weapon_id),
  knockback_applied_x NUMERIC(12,3) NOT NULL,
  knockback_applied_y NUMERIC(12,3) NOT NULL,
  was_applied BOOLEAN NOT NULL,
  server_reason TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Only one equipped weapon per player profile.
CREATE UNIQUE INDEX uq_player_one_equipped_weapon
  ON player_weapons_owned(player_id)
  WHERE is_equipped = TRUE;

CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_user_bans_user_id_active ON user_bans(user_id, is_active);
CREATE INDEX idx_player_profiles_user_id ON player_profiles(user_id);
CREATE INDEX idx_player_quests_status ON player_quests(status);
CREATE INDEX idx_hit_events_target_time ON combat_hit_events(target_player_id, created_at);
```

---

## 3) Server Rules (Practical Minimum)

1. **Register** creates `users` row with secure password hash (PBKDF2/bcrypt/argon2).
2. **Login required to play**: all gameplay endpoints require valid `auth_sessions` token.
3. **Ban check on login and gameplay**:
   - deny access when an active ban exists and (`expires_at IS NULL` or `expires_at > NOW()`).
4. **Profile ownership**: every gameplay action must verify `player_profiles.user_id == session.user_id`.
5. **Duplicate profile names allowed**: do not put unique constraint on `display_name`.
6. **Only one skill per profile**: store in `player_profiles.skill_id`.
7. **Weapon switching**:
   - set current equipped row to `FALSE`, target owned weapon to `TRUE` in one transaction.
8. **Quest acceptance**:
   - insert/update in `player_quests` with `status='accepted'`.
9. **Hit registration by server**:
   - validate distance/position from `player_positions`.
   - validate attacker equipped weapon from `player_weapons_owned` where `is_equipped=TRUE`.
10. **Knockback calculated by server**:
   - if `target.player_stats.can_receive_pvp_knockback = FALSE`, no force applied (`was_applied=FALSE`).
   - else apply force from weapon + skill modifiers and record in `combat_hit_events`.

---

## 4) Why this is practical for your game

- Supports account flow (register/login/ban) directly.
- Supports multi-profile ownership with explicit user mapping.
- Supports duplicate profile names as requested.
- Supports position-aware PvP and server-authoritative hit + knockback.
- Supports one-skill and one-equipped-weapon constraints cleanly.
- Keeps canonical game content (skills/weapons/quests) on server tables.

PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS combat_hit_events;
DROP TABLE IF EXISTS combat_events;
DROP TABLE IF EXISTS player_quests;
DROP TABLE IF EXISTS quest_progress;
DROP TABLE IF EXISTS player_weapons_owned;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS learned_skills;
DROP TABLE IF EXISTS positions;
DROP TABLE IF EXISTS player_stats;
DROP TABLE IF EXISTS stats;
DROP TABLE IF EXISTS player_profiles;
DROP TABLE IF EXISTS game_profiles;
DROP TABLE IF EXISTS auth_sessions;
DROP TABLE IF EXISTS user_bans;
DROP TABLE IF EXISTS quests;
DROP TABLE IF EXISTS skills;
DROP TABLE IF EXISTS weapons;
DROP TABLE IF EXISTS assets;
DROP TABLE IF EXISTS users;

PRAGMA foreign_keys = ON;

CREATE TABLE users (
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE auth_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  issued_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER NULL,
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE user_bans (
  ban_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  banned_at INTEGER NOT NULL,
  expires_at INTEGER NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE game_profiles (
  profile_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  username TEXT NOT NULL,
  total_xp INTEGER NOT NULL DEFAULT 0,
  rank TEXT NOT NULL DEFAULT 'rookie',
  equipped_weapon_id TEXT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(user_id),
  FOREIGN KEY (equipped_weapon_id) REFERENCES weapons(weapon_id)
);

CREATE TABLE stats (
  profile_id TEXT PRIMARY KEY,
  kills INTEGER NOT NULL DEFAULT 0,
  deaths INTEGER NOT NULL DEFAULT 0,
  wins INTEGER NOT NULL DEFAULT 0,
  play_time_seconds INTEGER NOT NULL DEFAULT 0,
  can_receive_pvp_knockback INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY (profile_id) REFERENCES game_profiles(profile_id)
);

CREATE TABLE weapons (
  weapon_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  base_damage REAL NOT NULL,
  fire_rate REAL NOT NULL
);

CREATE TABLE skills (
  skill_id TEXT PRIMARY KEY,
  skill_name TEXT NOT NULL UNIQUE,
  cooldown_seconds REAL NOT NULL,
  mana_cost INTEGER NOT NULL
);

CREATE TABLE learned_skills (
  profile_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  learned_at INTEGER NOT NULL,
  PRIMARY KEY (profile_id, skill_id),
  FOREIGN KEY (profile_id) REFERENCES game_profiles(profile_id),
  FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
);

CREATE TABLE assets (
  asset_id TEXT PRIMARY KEY,
  asset_name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE inventory (
  profile_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (profile_id, asset_id),
  FOREIGN KEY (profile_id) REFERENCES game_profiles(profile_id),
  FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

CREATE TABLE quests (
  quest_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  xp_reward INTEGER NOT NULL,
  requirement TEXT NOT NULL
);

CREATE TABLE quest_progress (
  profile_id TEXT NOT NULL,
  quest_id TEXT NOT NULL,
  status TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (profile_id, quest_id),
  FOREIGN KEY (profile_id) REFERENCES game_profiles(profile_id),
  FOREIGN KEY (quest_id) REFERENCES quests(quest_id)
);

CREATE TABLE positions (
  profile_id TEXT PRIMARY KEY,
  x REAL NOT NULL,
  y REAL NOT NULL,
  z REAL NOT NULL DEFAULT 0,
  rotation REAL NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES game_profiles(profile_id)
);

CREATE TABLE combat_events (
  event_id TEXT PRIMARY KEY,
  attacker_profile_id TEXT NOT NULL,
  victim_profile_id TEXT NOT NULL,
  weapon_id TEXT NOT NULL,
  damage_dealt REAL NOT NULL,
  knockback_x REAL NOT NULL DEFAULT 0,
  knockback_y REAL NOT NULL DEFAULT 0,
  knockback_z REAL NOT NULL DEFAULT 0,
  peer_signature TEXT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (attacker_profile_id) REFERENCES game_profiles(profile_id),
  FOREIGN KEY (victim_profile_id) REFERENCES game_profiles(profile_id),
  FOREIGN KEY (weapon_id) REFERENCES weapons(weapon_id)
);

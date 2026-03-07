# Practical Database Design for Combat Game (Peer-to-Peer)

This document describes the new P2P-oriented schema now used by the backend.

## Migration summary

- Server-authoritative hit/knockback tables were removed.
- Legacy tables are dropped during schema initialization.
- New schema is created from `backend/sql/p2p_schema.sql`.
- Database reset is explicit and reproducible because all DDL lives in a single SQL file.

## Core entities

1. **User**: `users` (`email`, `password_hash`, `created_at`).
2. **GameProfile**: `game_profiles` (`username`, `total_xp`, `rank`, ownership via `user_id`).
3. **Stats**: `stats` one-to-one with profile (`kills`, `deaths`, `wins`, `play_time_seconds`).
4. **Weapon**: `weapons` (`name`, `base_damage`, `fire_rate`).
5. **Skill**: `skills` (`skill_name`, `cooldown_seconds`, `mana_cost`).
6. **Inventory**: `inventory` links profile to asset and quantity.
7. **Asset**: `assets` stores item definitions.
8. **Quest**: `quests` (`title`, `xp_reward`, `requirement`).
9. **Position**: `positions` stores live sync (`x`, `y`, `z`, `rotation`).
10. **CombatEvent**: `combat_events` logs peer-declared outcomes (`attacker_profile_id`, `victim_profile_id`, `damage_dealt`).

## Supporting link tables

- `learned_skills` (profile ↔ skill)
- `quest_progress` (profile ↔ quest status)
- `auth_sessions` and `user_bans` (auth/session lifecycle)

## Authority model

The backend now treats combat actions as **peer-declared events**:

- `/combat/hit` records an event in `combat_events`.
- The event is tagged with `authoritative: "peer"` in API responses.
- No distance-based, server-authoritative knockback calculation is performed.

## Canonical schema source

See `backend/sql/p2p_schema.sql` for the exact migration/reset DDL.

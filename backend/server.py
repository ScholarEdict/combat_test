#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import mimetypes
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path(__file__).parent / "data"
WEB_DIR = Path(__file__).parent / "web"
DB_PATH = DATA_DIR / "game.db"
SCHEMA_PATH = Path(__file__).parent / "sql" / "p2p_schema.sql"
SESSION_TTL_SECONDS = 60 * 60


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict, set_cookie: str | None = None) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    if set_cookie:
        handler.send_header("Set-Cookie", set_cookie)
    handler.end_headers()
    handler.wfile.write(encoded)


def ok(handler: BaseHTTPRequestHandler, data: dict, status: int = HTTPStatus.OK, set_cookie: str | None = None) -> None:
    _json_response(handler, status, {"ok": True, "data": data}, set_cookie=set_cookie)


def err(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    _json_response(handler, status, {"ok": False, "error": {"code": code, "message": message}})


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}:{digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    salt_hex, digest_hex = encoded.split(":", maxsplit=1)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(candidate, expected)


class DB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._seed_static_data()

    def _init_schema(self) -> None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(schema)

    def _seed_static_data(self) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO weapons(weapon_id, name, base_damage, fire_rate) VALUES(?, ?, ?, ?)",
                [
                    ("diamond_sword", "Diamond Sword", 12.0, 1.0),
                    ("netherite_sword", "Netherite Sword", 14.0, 0.9),
                ],
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO skills(skill_id, skill_name, cooldown_seconds, mana_cost) VALUES(?, ?, ?, ?)",
                [
                    ("dash", "Dash", 5.0, 20),
                    ("heavy_strike", "Heavy Strike", 8.0, 35),
                ],
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO assets(asset_id, asset_name, asset_type, metadata_json) VALUES(?, ?, ?, ?)",
                [
                    ("health_potion", "Health Potion", "consumable", "{}"),
                    ("rare_skin", "Rare Skin", "cosmetic", "{}"),
                ],
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO quests(quest_id, title, xp_reward, requirement) VALUES(?, ?, ?, ?)",
                [
                    ("welcome_duel", "Welcome Duel", 120, "Land one combat event"),
                    ("first_steps", "First Steps", 80, "Move to x=10 y=10"),
                ],
            )

    def create_user(self, email: str, password: str) -> tuple[bool, dict | str]:
        now = int(time.time())
        user_id = secrets.token_hex(8)
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO users(user_id, email, password_hash, created_at) VALUES(?, ?, ?, ?)",
                    (user_id, email.strip().lower(), _hash_password(password), now),
                )
            except sqlite3.IntegrityError:
                return False, "DUPLICATE_USER"

        return True, {"id": user_id, "email": email.strip().lower(), "created_at": now}

    def find_user_by_credential(self, credential: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, email, password_hash, created_at FROM users WHERE lower(email)=?",
                (credential.strip().lower(),),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["user_id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "created_at": row["created_at"],
        }

    def find_user_by_id(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT user_id, email, created_at FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return {"id": row["user_id"], "email": row["email"], "created_at": row["created_at"]}

    def is_user_banned(self, user_id: str) -> bool:
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM user_bans
                WHERE user_id=? AND is_active=1
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (user_id, now),
            ).fetchone()
        return row is not None

    def create_session(self, user_id: str) -> str:
        now = int(time.time())
        sid = secrets.token_urlsafe(32)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO auth_sessions(session_id, user_id, issued_at, expires_at, revoked_at) VALUES(?, ?, ?, ?, NULL)",
                (sid, user_id, now, now + SESSION_TTL_SECONDS),
            )
        return sid

    def resolve_session(self, sid: str | None) -> str | None:
        if not sid:
            return None
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, expires_at, revoked_at FROM auth_sessions WHERE session_id=?",
                (sid,),
            ).fetchone()
        if not row:
            return None
        if row["revoked_at"] is not None or row["expires_at"] <= now:
            self.destroy_session(sid)
            return None
        return str(row["user_id"])

    def destroy_session(self, sid: str | None) -> bool:
        if not sid:
            return False
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM auth_sessions WHERE session_id=?", (sid,))
        return cur.rowcount > 0

    def create_profile(self, user_id: str, display_name: str) -> tuple[bool, dict | str]:
        now = int(time.time())
        profile_id = secrets.token_hex(8)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO game_profiles(profile_id, user_id, username, total_xp, rank, equipped_weapon_id, created_at)
                VALUES(?, ?, ?, 0, 'rookie', ?, ?)
                """,
                (profile_id, user_id, display_name, "diamond_sword", now),
            )
            self._conn.execute("INSERT INTO stats(profile_id) VALUES(?)", (profile_id,))
            self._conn.execute(
                "INSERT INTO positions(profile_id, x, y, z, rotation, updated_at) VALUES(?, 0, 0, 0, 0, ?)",
                (profile_id, now),
            )
            self._conn.executemany(
                "INSERT INTO inventory(profile_id, asset_id, quantity) VALUES(?, ?, ?)",
                [(profile_id, "health_potion", 3), (profile_id, "rare_skin", 1)],
            )
        return True, self.get_profile(profile_id)

    def get_profile(self, profile_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT gp.profile_id, gp.user_id, gp.username, gp.total_xp, gp.rank, gp.equipped_weapon_id,
                       gp.created_at, st.can_receive_pvp_knockback, pos.x, pos.y, pos.z, pos.rotation,
                       st.kills, st.deaths, st.wins, st.play_time_seconds
                FROM game_profiles gp
                JOIN stats st ON st.profile_id = gp.profile_id
                JOIN positions pos ON pos.profile_id = gp.profile_id
                WHERE gp.profile_id=?
                """,
                (profile_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_profile(row)

    def list_profiles_by_user(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT gp.profile_id, gp.user_id, gp.username, gp.total_xp, gp.rank, gp.equipped_weapon_id,
                       gp.created_at, st.can_receive_pvp_knockback, pos.x, pos.y, pos.z, pos.rotation,
                       st.kills, st.deaths, st.wins, st.play_time_seconds
                FROM game_profiles gp
                JOIN stats st ON st.profile_id = gp.profile_id
                JOIN positions pos ON pos.profile_id = gp.profile_id
                WHERE gp.user_id=? ORDER BY gp.created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def list_all_profiles(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT gp.profile_id, gp.user_id, gp.username, gp.total_xp, gp.rank, gp.equipped_weapon_id,
                       gp.created_at, st.can_receive_pvp_knockback, pos.x, pos.y, pos.z, pos.rotation,
                       st.kills, st.deaths, st.wins, st.play_time_seconds
                FROM game_profiles gp
                JOIN stats st ON st.profile_id = gp.profile_id
                JOIN positions pos ON pos.profile_id = gp.profile_id
                ORDER BY gp.created_at ASC
                """
            ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def _row_to_profile(self, row: sqlite3.Row) -> dict:
        return {
            "player_id": row["profile_id"],
            "profile_id": row["profile_id"],
            "user_id": row["user_id"],
            "display_name": row["username"],
            "username": row["username"],
            "total_xp": row["total_xp"],
            "rank": row["rank"],
            "equipped_weapon_id": row["equipped_weapon_id"],
            "position": {"x": row["x"], "y": row["y"], "z": row["z"], "rotation": row["rotation"]},
            "can_receive_pvp_knockback": bool(row["can_receive_pvp_knockback"]),
            "stats": {
                "kills": row["kills"],
                "deaths": row["deaths"],
                "wins": row["wins"],
                "play_time_seconds": row["play_time_seconds"],
            },
            "created_at": row["created_at"],
        }

    def set_profile_position(self, profile_id: str, x: float, y: float, z: float = 0.0, rotation: float = 0.0) -> bool:
        now = int(time.time())
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE positions SET x=?, y=?, z=?, rotation=?, updated_at=? WHERE profile_id=?",
                (x, y, z, rotation, now, profile_id),
            )
        return cur.rowcount > 0

    def set_profile_weapon(self, profile_id: str, weapon_id: str) -> tuple[bool, str | None]:
        with self._lock, self._conn:
            weapon = self._conn.execute("SELECT 1 FROM weapons WHERE weapon_id=?", (weapon_id,)).fetchone()
            if not weapon:
                return False, "WEAPON_NOT_FOUND"
            cur = self._conn.execute("UPDATE game_profiles SET equipped_weapon_id=? WHERE profile_id=?", (weapon_id, profile_id))
        return (cur.rowcount > 0, None if cur.rowcount > 0 else "PROFILE_NOT_FOUND")

    def accept_quest(self, profile_id: str, quest_id: str) -> tuple[bool, str | None]:
        now = int(time.time())
        with self._lock, self._conn:
            exists = self._conn.execute("SELECT 1 FROM quests WHERE quest_id=?", (quest_id,)).fetchone()
            if not exists:
                return False, "QUEST_NOT_FOUND"
            self._conn.execute(
                """
                INSERT INTO quest_progress(profile_id, quest_id, status, updated_at)
                VALUES(?, ?, 'accepted', ?)
                ON CONFLICT(profile_id, quest_id)
                DO UPDATE SET status='accepted', updated_at=excluded.updated_at
                """,
                (profile_id, quest_id, now),
            )
        return True, None

    def register_hit(self, attacker_profile_id: str, victim_profile_id: str, damage_dealt: float = 10.0) -> tuple[bool, dict | str]:
        now = int(time.time())
        with self._lock, self._conn:
            attacker = self._conn.execute(
                "SELECT profile_id, equipped_weapon_id FROM game_profiles WHERE profile_id=?",
                (attacker_profile_id,),
            ).fetchone()
            victim = self._conn.execute("SELECT profile_id FROM game_profiles WHERE profile_id=?", (victim_profile_id,)).fetchone()
            if not attacker or not victim:
                return False, "PROFILE_NOT_FOUND"
            event_id = secrets.token_hex(10)
            self._conn.execute(
                """
                INSERT INTO combat_events(
                  event_id, attacker_profile_id, victim_profile_id, weapon_id,
                  damage_dealt, knockback_x, knockback_y, knockback_z, peer_signature, created_at
                ) VALUES(?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (event_id, attacker_profile_id, victim_profile_id, attacker["equipped_weapon_id"], float(damage_dealt), None, now),
            )
            self._conn.execute("UPDATE stats SET kills = kills + 1 WHERE profile_id=?", (attacker_profile_id,))
            self._conn.execute("UPDATE stats SET deaths = deaths + 1 WHERE profile_id=?", (victim_profile_id,))
        return True, {
            "event_id": event_id,
            "attacker_profile_id": attacker_profile_id,
            "victim_profile_id": victim_profile_id,
            "weapon_id": attacker["equipped_weapon_id"],
            "damage_dealt": float(damage_dealt),
            "authoritative": "peer",
        }

    def list_weapons(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT weapon_id, name, base_damage, fire_rate FROM weapons ORDER BY weapon_id").fetchall()
        return [dict(r) for r in rows]

    def list_skills(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT skill_id, skill_name, cooldown_seconds, mana_cost FROM skills ORDER BY skill_id").fetchall()
        return [dict(r) for r in rows]

    def list_quests(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT quest_id, title, xp_reward, requirement FROM quests ORDER BY quest_id").fetchall()
        return [dict(r) for r in rows]


class PresenceStore:
    def __init__(self) -> None:
        self._presence_by_player: dict[str, dict] = {}
        self._lock = threading.Lock()

    def connect(self, user_id: str, player_id: str) -> None:
        now = int(time.time())
        with self._lock:
            self._presence_by_player[player_id] = {"user_id": user_id, "connected_at": now, "last_seen": now}

    def disconnect_player(self, player_id: str) -> None:
        with self._lock:
            self._presence_by_player.pop(player_id, None)

    def disconnect_user(self, user_id: str) -> None:
        with self._lock:
            victims = [pid for pid, data in self._presence_by_player.items() if data.get("user_id") == user_id]
            for pid in victims:
                del self._presence_by_player[pid]

    def touch(self, player_id: str) -> None:
        with self._lock:
            if player_id in self._presence_by_player:
                self._presence_by_player[player_id]["last_seen"] = int(time.time())

    def online_players(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._presence_by_player)


class Handler(BaseHTTPRequestHandler):
    db: DB
    presence: PresenceStore

    def log_message(self, *_args) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _session_id(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            if "session_id" in cookie:
                return cookie["session_id"].value
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.removeprefix("Bearer ").strip()
        return None

    def _auth_user_id(self) -> str | None:
        sid = self._session_id()
        user_id = self.db.resolve_session(sid)
        if not user_id or self.db.is_user_banned(user_id):
            return None
        return user_id

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/auth/register":
            return self._handle_register()
        if self.path == "/auth/login":
            return self._handle_login()
        if self.path == "/auth/logout":
            return self._handle_logout()
        if self.path == "/profiles":
            return self._handle_create_profile()
        if self.path == "/profiles/position":
            return self._handle_update_position()
        if self.path == "/profiles/equip":
            return self._handle_equip_weapon()
        if self.path == "/quests/accept":
            return self._handle_accept_quest()
        if self.path == "/combat/hit":
            return self._handle_combat_hit()
        if self.path == "/session/connect":
            return self._handle_connect()
        if self.path == "/session/disconnect":
            return self._handle_disconnect()
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Unknown endpoint")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ["/", "/index.html"]:
            return self._serve_file(WEB_DIR / "index.html")
        if path.startswith("/assets/"):
            return self._serve_file(WEB_DIR / path.lstrip("/"))
        if path == "/profile/me":
            return self._handle_profile_me()
        if path == "/profiles":
            return self._handle_list_profiles()
        if path == "/world/state":
            return self._handle_world_state()
        if path == "/session/online":
            return self._handle_online()
        if path == "/meta/weapons":
            return self._handle_list_weapons()
        if path == "/meta/skills":
            return self._handle_list_skills()
        if path == "/meta/quests":
            return self._handle_list_quests()
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Unknown endpoint")

    def _serve_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_register(self) -> None:
        payload = self._read_json()
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not email or "@" not in email or len(password) < 4:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "email and password(min 4) are required")

        created, user = self.db.create_user(email, password)
        if not created:
            return err(self, HTTPStatus.CONFLICT, str(user), "Email already exists")

        sid = self.db.create_session(user["id"])
        cookie = f"session_id={sid}; HttpOnly; Path=/; Max-Age={SESSION_TTL_SECONDS}; SameSite=Lax"
        ok(self, {
            "user": {"id": user["id"], "email": user["email"], "username": user["email"].split("@")[0]},
            "session": {"token": sid},
        }, status=HTTPStatus.CREATED, set_cookie=cookie)

    def _handle_login(self) -> None:
        payload = self._read_json()
        credential = str(payload.get("credential", "")).strip().lower()
        password = str(payload.get("password", ""))
        if not credential or not password:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "credential and password are required")
        user = self.db.find_user_by_credential(credential)
        if not user or not _verify_password(password, user["password_hash"]):
            return err(self, HTTPStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Invalid credential or password")
        sid = self.db.create_session(user["id"])
        cookie = f"session_id={sid}; HttpOnly; Path=/; Max-Age={SESSION_TTL_SECONDS}; SameSite=Lax"
        ok(self, {
            "user": {"id": user["id"], "email": user["email"], "username": user["email"].split("@")[0]},
            "session": {"token": sid},
        }, set_cookie=cookie)

    def _handle_profile_me(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        user = self.db.find_user_by_id(user_id)
        if not user:
            return err(self, HTTPStatus.NOT_FOUND, "USER_NOT_FOUND", "User no longer exists")
        ok(self, {"id": user["id"], "email": user["email"], "username": user["email"].split("@")[0]})

    def _handle_create_profile(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        display_name = str(payload.get("display_name", "")).strip()
        if not display_name:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "display_name is required")
        created, result = self.db.create_profile(user_id, display_name)
        if not created:
            return err(self, HTTPStatus.BAD_REQUEST, str(result), "Unable to create profile")
        ok(self, {"profile": result}, status=HTTPStatus.CREATED)

    def _handle_list_profiles(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        ok(self, {"profiles": self.db.list_profiles_by_user(user_id)})

    def _handle_update_position(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        x = payload.get("x")
        y = payload.get("y")
        z = payload.get("z", 0)
        rotation = payload.get("rotation", 0)
        if not player_id or x is None or y is None:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id, x, y are required")
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
        if not self.db.set_profile_position(player_id, float(x), float(y), float(z), float(rotation)):
            return err(self, HTTPStatus.NOT_FOUND, "PROFILE_NOT_FOUND", "Profile missing")
        self.presence.touch(player_id)
        ok(self, {"player_id": player_id, "position": {"x": float(x), "y": float(y), "z": float(z), "rotation": float(rotation)}})

    def _handle_equip_weapon(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        weapon_id = str(payload.get("weapon_id", ""))
        if not player_id or not weapon_id:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id and weapon_id are required")
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
        changed, code = self.db.set_profile_weapon(player_id, weapon_id)
        if not changed:
            return err(self, HTTPStatus.BAD_REQUEST, code or "EQUIP_FAILED", "Unable to equip weapon")
        ok(self, {"player_id": player_id, "equipped_weapon_id": weapon_id})

    def _handle_accept_quest(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        quest_id = str(payload.get("quest_id", ""))
        if not player_id or not quest_id:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id and quest_id are required")
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
        accepted, code = self.db.accept_quest(player_id, quest_id)
        if not accepted:
            return err(self, HTTPStatus.BAD_REQUEST, code or "QUEST_ACCEPT_FAILED", "Unable to accept quest")
        ok(self, {"player_id": player_id, "quest_id": quest_id, "status": "accepted"})

    def _handle_combat_hit(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        attacker = str(payload.get("attacker_player_id", ""))
        target = str(payload.get("target_player_id", ""))
        damage = float(payload.get("damage_dealt", 10.0))
        if not attacker or not target:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "attacker_player_id and target_player_id are required")
        attacker_profile = self.db.get_profile(attacker)
        if not attacker_profile or attacker_profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Attacker profile not owned by this user")
        success, result = self.db.register_hit(attacker, target, damage_dealt=damage)
        if not success:
            return err(self, HTTPStatus.BAD_REQUEST, str(result), "Peer combat event rejected")
        ok(self, {"combat": result})

    def _handle_connect(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        if not player_id:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id is required")
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
        self.presence.connect(user_id, player_id)
        user = self.db.find_user_by_id(user_id)
        ok(self, {"connected": True, "player_id": player_id, "user": {"id": user_id, "username": user["email"].split("@")[0] if user else ""}})

    def _handle_disconnect(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        if not player_id:
            return err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id is required")
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            return err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
        self.presence.disconnect_player(player_id)
        ok(self, {"disconnected": True, "player_id": player_id})

    def _handle_logout(self) -> None:
        sid = self._session_id()
        if sid:
            self.db.destroy_session(sid)
        ok(self, {"logged_out": True}, set_cookie="session_id=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax")

    def _handle_online(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        ok(self, {"online": self.presence.online_players()})

    def _handle_world_state(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            return err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
        online = self.presence.online_players()
        players = []
        for profile in self.db.list_all_profiles():
            players.append({
                "player_id": profile["player_id"],
                "user_id": profile["user_id"],
                "display_name": profile["display_name"],
                "position": profile["position"],
                "equipped_weapon_id": profile["equipped_weapon_id"],
                "online": profile["player_id"] in online,
            })
        ok(self, {"players": players, "authority": "peer_to_peer"})

    def _handle_list_weapons(self) -> None:
        ok(self, {"weapons": self.db.list_weapons()})

    def _handle_list_skills(self) -> None:
        ok(self, {"skills": self.db.list_skills()})

    def _handle_list_quests(self) -> None:
        ok(self, {"quests": self.db.list_quests()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combat test web backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Handler.db = DB(DB_PATH)
    Handler.presence = PresenceStore()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

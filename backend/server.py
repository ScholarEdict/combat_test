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
SESSION_TTL_SECONDS = 60 * 60  # 1 hour
MAX_HIT_DISTANCE = 3.0


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
        schema = """
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          last_login_at INTEGER NULL
        );

        CREATE TABLE IF NOT EXISTS auth_sessions (
          session_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          issued_at INTEGER NOT NULL,
          expires_at INTEGER NOT NULL,
          revoked_at INTEGER NULL,
          FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS user_bans (
          ban_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          banned_at INTEGER NOT NULL,
          expires_at INTEGER NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS skills (
          skill_id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          knockback_multiplier REAL NOT NULL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS weapons (
          weapon_id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          base_knockback REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quests (
          quest_id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS player_profiles (
          player_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          skill_id TEXT NULL,
          equipped_weapon_id TEXT NULL,
          pos_x REAL NOT NULL DEFAULT 0,
          pos_y REAL NOT NULL DEFAULT 0,
          can_receive_pvp_knockback INTEGER NOT NULL DEFAULT 1,
          attributes_json TEXT NOT NULL DEFAULT '{}',
          assets_json TEXT NOT NULL DEFAULT '{}',
          created_at INTEGER NOT NULL,
          FOREIGN KEY (user_id) REFERENCES users(user_id),
          FOREIGN KEY (skill_id) REFERENCES skills(skill_id),
          FOREIGN KEY (equipped_weapon_id) REFERENCES weapons(weapon_id)
        );

        CREATE TABLE IF NOT EXISTS player_weapons_owned (
          player_id TEXT NOT NULL,
          weapon_id TEXT NOT NULL,
          obtained_at INTEGER NOT NULL,
          PRIMARY KEY (player_id, weapon_id),
          FOREIGN KEY (player_id) REFERENCES player_profiles(player_id),
          FOREIGN KEY (weapon_id) REFERENCES weapons(weapon_id)
        );

        CREATE TABLE IF NOT EXISTS player_quests (
          player_id TEXT NOT NULL,
          quest_id TEXT NOT NULL,
          status TEXT NOT NULL,
          accepted_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (player_id, quest_id),
          FOREIGN KEY (player_id) REFERENCES player_profiles(player_id),
          FOREIGN KEY (quest_id) REFERENCES quests(quest_id)
        );

        CREATE TABLE IF NOT EXISTS combat_hit_events (
          hit_id TEXT PRIMARY KEY,
          attacker_player_id TEXT NOT NULL,
          target_player_id TEXT NOT NULL,
          weapon_id TEXT NOT NULL,
          knockback_applied_x REAL NOT NULL,
          knockback_applied_y REAL NOT NULL,
          was_applied INTEGER NOT NULL,
          server_reason TEXT NULL,
          created_at INTEGER NOT NULL,
          FOREIGN KEY (attacker_player_id) REFERENCES player_profiles(player_id),
          FOREIGN KEY (target_player_id) REFERENCES player_profiles(player_id),
          FOREIGN KEY (weapon_id) REFERENCES weapons(weapon_id)
        );
        """
        with self._lock:
            self._conn.executescript(schema)

    def _seed_static_data(self) -> None:
        with self._lock, self._conn:
            # Two swords from assets; same gameplay stats, different skin/name.
            self._conn.executemany(
                "INSERT OR IGNORE INTO weapons(weapon_id, name, base_knockback) VALUES(?, ?, ?)",
                [
                    ("diamond_sword", "Diamond Sword", 12.0),
                    ("netherite_sword", "Netherite Sword", 12.0),
                ],
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO skills(skill_id, name, knockback_multiplier) VALUES(?, ?, ?)",
                [
                    ("novice", "Novice", 1.0),
                    ("heavy_strike", "Heavy Strike", 1.2),
                ],
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO quests(quest_id, title, description) VALUES(?, ?, ?)",
                [
                    ("welcome_duel", "Welcome Duel", "Land one valid hit in PvP."),
                    ("step_master", "Step Master", "Reach position x=10, y=10."),
                ],
            )

    def create_user(self, username: str, email: str, password: str) -> tuple[bool, dict | str]:
        now = int(time.time())
        user_id = secrets.token_hex(8)
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO users(user_id, username, email, password_hash, created_at) VALUES(?, ?, ?, ?, ?)",
                    (user_id, username.strip(), email.strip(), _hash_password(password), now),
                )
            except sqlite3.IntegrityError:
                return False, "DUPLICATE_USER"

        return True, {
            "id": user_id,
            "username": username.strip(),
            "email": email.strip(),
            "created_at": now,
        }

    def find_user_by_credential(self, credential: str) -> dict | None:
        needle = credential.strip().lower()
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, username, email, password_hash, created_at FROM users WHERE lower(username)=? OR lower(email)=?",
                (needle, needle),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["user_id"],
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "created_at": row["created_at"],
        }

    def find_user_by_id(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, username, email, created_at FROM users WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["user_id"],
            "username": row["username"],
            "email": row["email"],
            "created_at": row["created_at"],
        }

    def update_last_login(self, user_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET last_login_at=? WHERE user_id=?", (int(time.time()), user_id))

    def is_user_banned(self, user_id: str) -> bool:
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM user_bans
                WHERE user_id=?
                  AND is_active=1
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

    def create_profile(self, user_id: str, display_name: str, skill_id: str | None = None) -> tuple[bool, dict | str]:
        now = int(time.time())
        player_id = secrets.token_hex(8)
        attributes = json.dumps({"power": 10, "agility": 10})
        assets = json.dumps({"coins": 100})
        with self._lock, self._conn:
            if skill_id:
                skill_exists = self._conn.execute("SELECT 1 FROM skills WHERE skill_id=?", (skill_id,)).fetchone()
                if not skill_exists:
                    return False, "SKILL_NOT_FOUND"
            self._conn.execute(
                """
                INSERT INTO player_profiles(
                  player_id, user_id, display_name, skill_id, equipped_weapon_id,
                  pos_x, pos_y, can_receive_pvp_knockback, attributes_json, assets_json, created_at
                ) VALUES(?, ?, ?, ?, NULL, 0, 0, 1, ?, ?, ?)
                """,
                (player_id, user_id, display_name, skill_id, attributes, assets, now),
            )
            # Give both swords by default; equip diamond sword by default.
            self._conn.executemany(
                "INSERT INTO player_weapons_owned(player_id, weapon_id, obtained_at) VALUES(?, ?, ?)",
                [
                    (player_id, "diamond_sword", now),
                    (player_id, "netherite_sword", now),
                ],
            )
            self._conn.execute(
                "UPDATE player_profiles SET equipped_weapon_id=? WHERE player_id=?",
                ("diamond_sword", player_id),
            )

        return True, self.get_profile(player_id)

    def list_profiles_by_user(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT player_id, display_name, skill_id, equipped_weapon_id, pos_x, pos_y,
                       can_receive_pvp_knockback, attributes_json, assets_json, created_at
                FROM player_profiles WHERE user_id=? ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_profile(r) for r in rows]

    def get_profile(self, player_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT player_id, user_id, display_name, skill_id, equipped_weapon_id, pos_x, pos_y,
                       can_receive_pvp_knockback, attributes_json, assets_json, created_at
                FROM player_profiles WHERE player_id=?
                """,
                (player_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_profile(row)

    def list_all_profiles(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT player_id, user_id, display_name, skill_id, equipped_weapon_id, pos_x, pos_y,
                       can_receive_pvp_knockback, attributes_json, assets_json, created_at
                FROM player_profiles ORDER BY created_at ASC
                """
            ).fetchall()
        return [self._row_to_profile(r) for r in rows]

    def _row_to_profile(self, row: sqlite3.Row) -> dict:
        return {
            "player_id": row["player_id"],
            "user_id": row["user_id"] if "user_id" in row.keys() else None,
            "display_name": row["display_name"],
            "skill_id": row["skill_id"],
            "equipped_weapon_id": row["equipped_weapon_id"],
            "position": {"x": row["pos_x"], "y": row["pos_y"]},
            "can_receive_pvp_knockback": bool(row["can_receive_pvp_knockback"]),
            "attributes": json.loads(row["attributes_json"]),
            "assets": json.loads(row["assets_json"]),
            "created_at": row["created_at"],
        }

    def set_profile_position(self, player_id: str, x: float, y: float) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE player_profiles SET pos_x=?, pos_y=? WHERE player_id=?",
                (x, y, player_id),
            )
        return cur.rowcount > 0

    def set_profile_weapon(self, player_id: str, weapon_id: str) -> tuple[bool, str | None]:
        with self._lock, self._conn:
            owned = self._conn.execute(
                "SELECT 1 FROM player_weapons_owned WHERE player_id=? AND weapon_id=?",
                (player_id, weapon_id),
            ).fetchone()
            if not owned:
                return False, "WEAPON_NOT_OWNED"
            self._conn.execute(
                "UPDATE player_profiles SET equipped_weapon_id=? WHERE player_id=?",
                (weapon_id, player_id),
            )
        return True, None

    def accept_quest(self, player_id: str, quest_id: str) -> tuple[bool, str | None]:
        now = int(time.time())
        with self._lock, self._conn:
            exists = self._conn.execute("SELECT 1 FROM quests WHERE quest_id=?", (quest_id,)).fetchone()
            if not exists:
                return False, "QUEST_NOT_FOUND"
            self._conn.execute(
                """
                INSERT INTO player_quests(player_id, quest_id, status, accepted_at, updated_at)
                VALUES(?, ?, 'accepted', ?, ?)
                ON CONFLICT(player_id, quest_id) DO UPDATE SET status='accepted', updated_at=excluded.updated_at
                """,
                (player_id, quest_id, now, now),
            )
        return True, None

    def list_weapons(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT weapon_id, name, base_knockback FROM weapons ORDER BY weapon_id").fetchall()
        return [{"weapon_id": r["weapon_id"], "name": r["name"], "base_knockback": r["base_knockback"]} for r in rows]

    def list_skills(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT skill_id, name, knockback_multiplier FROM skills ORDER BY skill_id").fetchall()
        return [{"skill_id": r["skill_id"], "name": r["name"], "knockback_multiplier": r["knockback_multiplier"]} for r in rows]

    def list_quests(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT quest_id, title, description FROM quests ORDER BY quest_id").fetchall()
        return [{"quest_id": r["quest_id"], "title": r["title"], "description": r["description"]} for r in rows]

    def register_hit(self, attacker_player_id: str, target_player_id: str) -> tuple[bool, dict | str]:
        now = int(time.time())
        with self._lock, self._conn:
            attacker = self._conn.execute(
                "SELECT player_id, equipped_weapon_id, skill_id, pos_x, pos_y FROM player_profiles WHERE player_id=?",
                (attacker_player_id,),
            ).fetchone()
            target = self._conn.execute(
                "SELECT player_id, can_receive_pvp_knockback, pos_x, pos_y FROM player_profiles WHERE player_id=?",
                (target_player_id,),
            ).fetchone()
            if not attacker or not target:
                return False, "PROFILE_NOT_FOUND"
            if not attacker["equipped_weapon_id"]:
                return False, "NO_EQUIPPED_WEAPON"

            dx = float(target["pos_x"]) - float(attacker["pos_x"])
            dy = float(target["pos_y"]) - float(attacker["pos_y"])
            distance = (dx * dx + dy * dy) ** 0.5
            if distance > MAX_HIT_DISTANCE:
                return False, "TARGET_OUT_OF_RANGE"

            weapon = self._conn.execute(
                "SELECT base_knockback FROM weapons WHERE weapon_id=?",
                (attacker["equipped_weapon_id"],),
            ).fetchone()
            if not weapon:
                return False, "WEAPON_NOT_FOUND"

            skill_mult = 1.0
            if attacker["skill_id"]:
                skill = self._conn.execute(
                    "SELECT knockback_multiplier FROM skills WHERE skill_id=?",
                    (attacker["skill_id"],),
                ).fetchone()
                if skill:
                    skill_mult = float(skill["knockback_multiplier"])

            force = float(weapon["base_knockback"]) * skill_mult
            if distance == 0:
                nx, ny = 1.0, 0.0
            else:
                nx, ny = dx / distance, dy / distance

            apply_knockback = bool(target["can_receive_pvp_knockback"])
            kx, ky = (nx * force, ny * force) if apply_knockback else (0.0, 0.0)

            if apply_knockback:
                self._conn.execute(
                    "UPDATE player_profiles SET pos_x = pos_x + ?, pos_y = pos_y + ? WHERE player_id=?",
                    (kx, ky, target_player_id),
                )
                reason = None
            else:
                reason = "target_pvp_disabled"

            hit_id = secrets.token_hex(10)
            self._conn.execute(
                """
                INSERT INTO combat_hit_events(
                  hit_id, attacker_player_id, target_player_id, weapon_id,
                  knockback_applied_x, knockback_applied_y, was_applied, server_reason, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hit_id,
                    attacker_player_id,
                    target_player_id,
                    attacker["equipped_weapon_id"],
                    kx,
                    ky,
                    1 if apply_knockback else 0,
                    reason,
                    now,
                ),
            )

        return True, {
            "hit_id": hit_id,
            "weapon_id": attacker["equipped_weapon_id"],
            "distance": distance,
            "knockback": {"x": kx, "y": ky},
            "was_applied": apply_knockback,
            "reason": reason,
        }


class PresenceStore:
    def __init__(self) -> None:
        self._presence_by_user: dict[str, dict] = {}
        self._lock = threading.Lock()

    def connect(self, user_id: str) -> None:
        now = int(time.time())
        with self._lock:
            self._presence_by_user[user_id] = {
                "connected_at": now,
                "last_seen": now,
            }

    def disconnect(self, user_id: str) -> None:
        with self._lock:
            if user_id in self._presence_by_user:
                del self._presence_by_user[user_id]

    def touch(self, user_id: str) -> None:
        now = int(time.time())
        with self._lock:
            if user_id in self._presence_by_user:
                self._presence_by_user[user_id]["last_seen"] = now

    def online_user_ids(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._presence_by_user)


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
        if not user_id:
            return None
        if self.db.is_user_banned(user_id):
            return None
        return user_id

    def do_POST(self) -> None:
        if self.path == "/auth/register":
            self._handle_register()
            return
        if self.path == "/auth/login":
            self._handle_login()
            return
        if self.path == "/session/connect":
            self._handle_connect()
            return
        if self.path == "/session/disconnect":
            self._handle_disconnect()
            return
        if self.path == "/auth/logout":
            self._handle_logout()
            return
        if self.path == "/profiles":
            self._handle_create_profile()
            return
        if self.path == "/profiles/position":
            self._handle_update_position()
            return
        if self.path == "/profiles/equip":
            self._handle_equip_weapon()
            return
        if self.path == "/profiles/quests/accept":
            self._handle_accept_quest()
            return
        if self.path == "/combat/hit":
            self._handle_combat_hit()
            return
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        clean_path = parsed.path

        if clean_path == "/" or clean_path == "/index.html":
            self._serve_static("index.html")
            return
        if clean_path.startswith("/assets/"):
            rel_path = clean_path.removeprefix("/")
            self._serve_static(rel_path)
            return

        if clean_path == "/profile/me":
            self._handle_profile_me()
            return
        if clean_path == "/profiles":
            self._handle_list_profiles()
            return
        if clean_path == "/world/state":
            self._handle_world_state()
            return
        if clean_path == "/session/online":
            self._handle_online()
            return
        if clean_path == "/catalog/weapons":
            self._handle_list_weapons()
            return
        if clean_path == "/catalog/skills":
            self._handle_list_skills()
            return
        if clean_path == "/catalog/quests":
            self._handle_list_quests()
            return
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")

    def _serve_static(self, relative_path: str) -> None:
        requested = (WEB_DIR / relative_path).resolve()
        web_root = WEB_DIR.resolve()
        if not str(requested).startswith(str(web_root)) or not requested.is_file():
            err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Static file not found")
            return

        content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
        content = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_register(self) -> None:
        payload = self._read_json()
        username = str(payload.get("username", "")).strip()
        email = str(payload.get("email", "")).strip()
        password = str(payload.get("password", ""))

        if not username or not email or not password:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "username, email and password are required")
            return
        if len(password) < 8:
            err(self, HTTPStatus.BAD_REQUEST, "WEAK_PASSWORD", "password must have at least 8 characters")
            return

        created, result = self.db.create_user(username, email, password)
        if not created:
            err(self, HTTPStatus.CONFLICT, str(result), "A user with this username or email already exists")
            return

        user = result
        ok(self, {
            "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
            "next": "login_required",
        }, status=HTTPStatus.CREATED)

    def _handle_login(self) -> None:
        payload = self._read_json()
        credential = str(payload.get("credential", "")).strip()
        password = str(payload.get("password", ""))
        if not credential or not password:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "credential and password are required")
            return

        user = self.db.find_user_by_credential(credential)
        if not user or not _verify_password(password, user["password_hash"]):
            err(self, HTTPStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Credential or password is incorrect")
            return

        if self.db.is_user_banned(user["id"]):
            err(self, HTTPStatus.FORBIDDEN, "BANNED", "This account is banned")
            return

        sid = self.db.create_session(user["id"])
        self.db.update_last_login(user["id"])
        cookie = f"session_id={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL_SECONDS}"
        ok(self, {
            "session": {"token": sid, "expires_in": SESSION_TTL_SECONDS},
            "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
        }, set_cookie=cookie)

    def _handle_profile_me(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return

        user = self.db.find_user_by_id(user_id)
        if not user:
            err(self, HTTPStatus.NOT_FOUND, "USER_NOT_FOUND", "User account not found")
            return

        ok(self, {
            "profile": user,
            "profiles_count": len(self.db.list_profiles_by_user(user_id)),
        })

    def _handle_create_profile(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        payload = self._read_json()
        display_name = str(payload.get("display_name", "")).strip()
        skill_id = payload.get("skill_id")
        if not display_name:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "display_name is required")
            return
        created, result = self.db.create_profile(user_id, display_name, str(skill_id) if skill_id else None)
        if not created:
            err(self, HTTPStatus.BAD_REQUEST, str(result), "Unable to create profile")
            return
        ok(self, {"profile": result}, status=HTTPStatus.CREATED)

    def _handle_list_profiles(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        ok(self, {"profiles": self.db.list_profiles_by_user(user_id)})

    def _handle_update_position(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        x = payload.get("x")
        y = payload.get("y")
        if not player_id or x is None or y is None:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id, x, y are required")
            return
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
            return
        self.db.set_profile_position(player_id, float(x), float(y))
        ok(self, {"player_id": player_id, "position": {"x": float(x), "y": float(y)}})

    def _handle_equip_weapon(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        weapon_id = str(payload.get("weapon_id", ""))
        if not player_id or not weapon_id:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id and weapon_id are required")
            return
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
            return
        changed, code = self.db.set_profile_weapon(player_id, weapon_id)
        if not changed:
            err(self, HTTPStatus.BAD_REQUEST, code or "EQUIP_FAILED", "Unable to equip weapon")
            return
        ok(self, {"player_id": player_id, "equipped_weapon_id": weapon_id})

    def _handle_accept_quest(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        payload = self._read_json()
        player_id = str(payload.get("player_id", ""))
        quest_id = str(payload.get("quest_id", ""))
        if not player_id or not quest_id:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "player_id and quest_id are required")
            return
        profile = self.db.get_profile(player_id)
        if not profile or profile["user_id"] != user_id:
            err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Profile not owned by this user")
            return
        accepted, code = self.db.accept_quest(player_id, quest_id)
        if not accepted:
            err(self, HTTPStatus.BAD_REQUEST, code or "QUEST_ACCEPT_FAILED", "Unable to accept quest")
            return
        ok(self, {"player_id": player_id, "quest_id": quest_id, "status": "accepted"})

    def _handle_combat_hit(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        payload = self._read_json()
        attacker = str(payload.get("attacker_player_id", ""))
        target = str(payload.get("target_player_id", ""))
        if not attacker or not target:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "attacker_player_id and target_player_id are required")
            return
        attacker_profile = self.db.get_profile(attacker)
        if not attacker_profile or attacker_profile["user_id"] != user_id:
            err(self, HTTPStatus.FORBIDDEN, "FORBIDDEN", "Attacker profile not owned by this user")
            return

        success, result = self.db.register_hit(attacker, target)
        if not success:
            err(self, HTTPStatus.BAD_REQUEST, str(result), "Hit rejected by server rules")
            return
        ok(self, {"combat": result})

    def _handle_connect(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return

        self.presence.connect(user_id)
        user = self.db.find_user_by_id(user_id)
        ok(self, {
            "connected": True,
            "user": {
                "id": user_id,
                "username": user.get("username", "") if user else "",
            }
        })

    def _handle_disconnect(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return

        self.presence.disconnect(user_id)
        ok(self, {"disconnected": True})

    def _handle_logout(self) -> None:
        sid = self._session_id()
        user_id = self.db.resolve_session(sid)
        if user_id:
            self.presence.disconnect(user_id)
        self.db.destroy_session(sid)
        clear_cookie = "session_id=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
        ok(self, {"logged_out": True}, set_cookie=clear_cookie)

    def _handle_online(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return

        self.presence.touch(user_id)
        online_payload = []
        for online_user_id, presence in self.presence.online_user_ids().items():
            user = self.db.find_user_by_id(online_user_id)
            if not user:
                continue
            online_payload.append({
                "id": online_user_id,
                "username": user["username"],
                "connected_at": presence.get("connected_at", 0),
                "last_seen": presence.get("last_seen", 0),
            })

        ok(self, {
            "online": online_payload,
            "count": len(online_payload),
        })

    def _handle_world_state(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return

        self.presence.touch(user_id)
        all_profiles = self.db.list_all_profiles()
        online_user_ids = set(self.presence.online_user_ids().keys())
        world_players = []
        for profile in all_profiles:
            world_players.append({
                "player_id": profile["player_id"],
                "user_id": profile["user_id"],
                "display_name": profile["display_name"],
                "equipped_weapon_id": profile["equipped_weapon_id"],
                "position": profile["position"],
                "online": profile["user_id"] in online_user_ids,
            })

        ok(self, {
            "players": world_players,
            "count": len(world_players),
        })

    def _handle_list_weapons(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        ok(self, {"weapons": self.db.list_weapons()})

    def _handle_list_skills(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        ok(self, {"skills": self.db.list_skills()})

    def _handle_list_quests(self) -> None:
        user_id = self._auth_user_id()
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid non-banned session required")
            return
        ok(self, {"quests": self.db.list_quests()})


def run(host: str, port: int) -> None:
    Handler.db = DB(DB_PATH)
    Handler.presence = PresenceStore()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Auth API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    run(args.host, args.port)

#!/usr/bin/env python3
import argparse
import hashlib
import hmac
import json
import secrets
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
USERS_PATH = DATA_DIR / "users.json"
SESSION_TTL_SECONDS = 60 * 60  # 1 hour


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


class UserStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._users = self._load()

    def _load(self) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {"users": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._users, indent=2), encoding="utf-8")

    def find_by_username_or_email(self, credential: str) -> dict | None:
        needle = credential.strip().lower()
        with self._lock:
            for user in self._users["users"]:
                if user["username"].lower() == needle or user["email"].lower() == needle:
                    return user
        return None

    def create_user(self, username: str, email: str, password: str) -> tuple[bool, dict | str]:
        user_record = {
            "id": secrets.token_hex(8),
            "username": username.strip(),
            "email": email.strip(),
            "password_hash": _hash_password(password),
            "created_at": int(time.time()),
            "assets": {
                "coins": 100,
                "inventory": ["starter_sword", "starter_potion"],
            },
        }
        with self._lock:
            for existing in self._users["users"]:
                if existing["username"].lower() == user_record["username"].lower() or existing["email"].lower() == user_record["email"].lower():
                    return False, "DUPLICATE_USER"
            self._users["users"].append(user_record)
            self._save()
        return True, user_record


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[sid] = {"user_id": user_id, "expires_at": int(time.time()) + SESSION_TTL_SECONDS}
        return sid

    def resolve(self, sid: str | None) -> str | None:
        if not sid:
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return None
            if session["expires_at"] <= int(time.time()):
                del self._sessions[sid]
                return None
            return session["user_id"]

    def destroy(self, sid: str | None) -> bool:
        if not sid:
            return False
        with self._lock:
            if sid not in self._sessions:
                return False
            del self._sessions[sid]
            return True


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


class Handler(BaseHTTPRequestHandler):
    user_store: UserStore
    sessions: SessionStore
    presence: PresenceStore

    def log_message(self, *_args) -> None:
        return

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
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")

    def do_GET(self) -> None:
        if self.path == "/profile/me":
            self._handle_profile_me()
            return
        if self.path == "/session/online":
            self._handle_online()
            return
        err(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")

    def _find_user_by_id(self, user_id: str) -> dict | None:
        for candidate in self.user_store._users["users"]:
            if candidate["id"] == user_id:
                return candidate
        return None

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

        created, result = self.user_store.create_user(username, email, password)
        if not created:
            err(self, HTTPStatus.CONFLICT, str(result), "A user with this username or email already exists")
            return

        user = result
        sid = self.sessions.create(user["id"])
        cookie = f"session_id={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL_SECONDS}"
        ok(self, {
            "session": {"token": sid, "expires_in": SESSION_TTL_SECONDS},
            "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
        }, status=HTTPStatus.CREATED, set_cookie=cookie)

    def _handle_login(self) -> None:
        payload = self._read_json()
        credential = str(payload.get("credential", "")).strip()
        password = str(payload.get("password", ""))
        if not credential or not password:
            err(self, HTTPStatus.BAD_REQUEST, "VALIDATION_ERROR", "credential and password are required")
            return

        user = self.user_store.find_by_username_or_email(credential)
        if not user or not _verify_password(password, user["password_hash"]):
            err(self, HTTPStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Credential or password is incorrect")
            return

        sid = self.sessions.create(user["id"])
        cookie = f"session_id={sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL_SECONDS}"
        ok(self, {
            "session": {"token": sid, "expires_in": SESSION_TTL_SECONDS},
            "user": {"id": user["id"], "username": user["username"], "email": user["email"]},
        }, set_cookie=cookie)

    def _handle_profile_me(self) -> None:
        sid = self._session_id()
        user_id = self.sessions.resolve(sid)
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid session required")
            return

        user = self._find_user_by_id(user_id)

        if not user:
            err(self, HTTPStatus.NOT_FOUND, "USER_NOT_FOUND", "User account not found")
            return

        ok(self, {
            "profile": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "created_at": user["created_at"],
            },
            "assets": user["assets"],
        })

    def _handle_connect(self) -> None:
        sid = self._session_id()
        user_id = self.sessions.resolve(sid)
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid session required")
            return

        self.presence.connect(user_id)
        user = self._find_user_by_id(user_id)
        ok(self, {
            "connected": True,
            "user": {
                "id": user_id,
                "username": user.get("username", "") if user else "",
            }
        })

    def _handle_disconnect(self) -> None:
        sid = self._session_id()
        user_id = self.sessions.resolve(sid)
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid session required")
            return

        self.presence.disconnect(user_id)
        ok(self, {"disconnected": True})

    def _handle_logout(self) -> None:
        sid = self._session_id()
        user_id = self.sessions.resolve(sid)
        if user_id:
            self.presence.disconnect(user_id)
        self.sessions.destroy(sid)
        clear_cookie = "session_id=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
        ok(self, {"logged_out": True}, set_cookie=clear_cookie)

    def _handle_online(self) -> None:
        sid = self._session_id()
        user_id = self.sessions.resolve(sid)
        if not user_id:
            err(self, HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Valid session required")
            return

        self.presence.touch(user_id)
        online_payload = []
        for online_user_id, presence in self.presence.online_user_ids().items():
            user = self._find_user_by_id(online_user_id)
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


def run(host: str, port: int) -> None:
    Handler.user_store = UserStore(USERS_PATH)
    Handler.sessions = SessionStore()
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

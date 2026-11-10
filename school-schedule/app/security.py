import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request

from . import config
from .db import get_db, now_local

SESSION_COOKIE = "session"
CSRF_HEADER = "X-CSRF-Token"

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Сверяем пароль и для несуществующего логина, чтобы по времени ответа нельзя было узнать, есть ли такой пользователь.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_credentials(conn: sqlite3.Connection, username: str, password: str):
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    ok = verify_password(password, user["password_hash"] if user else _DUMMY_HASH)
    return user if (user and ok) else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = now_local() + timedelta(hours=config.SESSION_HOURS)
    conn.execute(
        "DELETE FROM sessions WHERE expires_at < ?", (now_local().isoformat(),)
    )
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, csrf, expires.isoformat()),
    )
    return token, csrf


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def delete_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def cookie_secure(request: Request) -> bool:
    if config.COOKIE_SECURE in ("1", "true", "yes"):
        return True
    if config.COOKIE_SECURE in ("0", "false", "no"):
        return False
    return request.url.scheme == "https"


def _load_session(conn: sqlite3.Connection, request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return conn.execute(
        "SELECT s.csrf_token, u.id, u.username, u.full_name, u.role "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1",
        (_token_hash(token), now_local().isoformat()),
    ).fetchone()


def optional_user(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    row = _load_session(conn, request)
    return dict(row) if row else None


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    row = _load_session(conn, request)
    if not row:
        raise HTTPException(401, "Войдите в систему")
    user = dict(row)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, user["csrf_token"]):
            raise HTTPException(403, "Сессия устарела. Обновите страницу и повторите.")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Действие доступно только администратору")
    return user


def _window_start() -> str:
    return (now_local() - timedelta(minutes=config.LOGIN_WINDOW_MINUTES)).isoformat()


def login_blocked_minutes(conn: sqlite3.Connection, username: str, ip: str) -> int:
    """Сколько минут ещё ждать (0 — вход разрешён)."""
    since = _window_start()
    for key, limit in (
        (f"user:{username.lower()}", config.LOGIN_MAX_FAILS_PER_USER),
        (f"ip:{ip}", config.LOGIN_MAX_FAILS_PER_IP),
    ):
        rows = conn.execute(
            "SELECT ts FROM login_failures WHERE key = ? AND ts > ? ORDER BY ts",
            (key, since),
        ).fetchall()
        if len(rows) >= limit:
            oldest = datetime.fromisoformat(rows[-limit]["ts"])
            unblock = oldest + timedelta(minutes=config.LOGIN_WINDOW_MINUTES)
            return max(1, int((unblock - now_local()).total_seconds() // 60) + 1)
    return 0


def record_login_failure(conn: sqlite3.Connection, username: str, ip: str) -> None:
    ts = now_local().isoformat()
    conn.execute("DELETE FROM login_failures WHERE ts < ?", (_window_start(),))
    conn.executemany(
        "INSERT INTO login_failures (key, ts) VALUES (?, ?)",
        [(f"user:{username.lower()}", ts), (f"ip:{ip}", ts)],
    )


def clear_login_failures(conn: sqlite3.Connection, username: str) -> None:
    conn.execute("DELETE FROM login_failures WHERE key = ?", (f"user:{username.lower()}",))

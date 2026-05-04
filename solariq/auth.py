from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

PBKDF2_ITERATIONS = 240_000
PASSWORD_MIN_LENGTH = 8
SESSION_TTL_DAYS = 30
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 5
LOCKOUT_ERROR = f"Too many failed sign-in attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes."


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    is_admin: bool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_auth_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                failed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_login_attempts_username_failed_at
            ON login_attempts (username, failed_at);
            """
        )


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _validate_username(username: str) -> str:
    normalized = _normalize_username(username)
    if not normalized:
        raise ValueError("Username is required.")
    if len(normalized) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if len(normalized) > 64:
        raise ValueError("Username must be 64 characters or fewer.")
    return normalized


def _validate_password(password: str) -> None:
    error = validate_password_strength(password)
    if error is not None:
        raise ValueError(error)


def validate_password_strength(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."

    has_upper = any(ch.isupper() for ch in password)
    has_lower = any(ch.islower() for ch in password)
    has_numeric = any(ch.isdigit() for ch in password)
    has_symbol = any(not ch.isalnum() for ch in password)
    satisfied = sum([has_upper, has_lower, has_numeric, has_symbol])
    if satisfied < 3:
        return "Password must include at least 3 of: uppercase, lowercase, number, symbol."

    return None


def _hash_password(password: str, salt: bytes) -> str:
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hashed.hex()


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _lockout_cutoff(now: datetime | None = None) -> str:
    current = now or _utcnow()
    return (current - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)).isoformat()


def _prune_expired_login_attempts(conn: sqlite3.Connection, now: datetime | None = None) -> None:
    conn.execute("DELETE FROM login_attempts WHERE failed_at < ?", (_lockout_cutoff(now),))


def _is_locked_out(conn: sqlite3.Connection, username: str, now: datetime | None = None) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE username = ? AND failed_at >= ?",
        (username, _lockout_cutoff(now)),
    ).fetchone()
    return int(row[0]) >= MAX_FAILED_LOGIN_ATTEMPTS


def _record_failed_login(conn: sqlite3.Connection, username: str, now: datetime | None = None) -> None:
    failed_at = (now or _utcnow()).isoformat()
    conn.execute(
        "INSERT INTO login_attempts (username, failed_at) VALUES (?, ?)",
        (username, failed_at),
    )


def _clear_failed_logins(conn: sqlite3.Connection, username: str) -> None:
    conn.execute("DELETE FROM login_attempts WHERE username = ?", (username,))


def has_users(db_path: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()
    return bool(row[0])


def has_admin_users(db_path: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT EXISTS(SELECT 1 FROM users WHERE is_admin = 1)").fetchone()
    return bool(row[0])


def _insert_user_atomic(
    conn: sqlite3.Connection,
    username: str,
    password_hash: str,
    password_salt: str,
    created_at: str,
    *,
    is_admin: bool,
    require_no_existing_users: bool = False,
) -> UserRecord:
    conn.execute("BEGIN IMMEDIATE")
    first_user = bool(conn.execute("SELECT NOT EXISTS(SELECT 1 FROM users)").fetchone()[0])

    if require_no_existing_users and not first_user:
        raise ValueError("A user already exists. Please sign in.")

    effective_admin = bool(is_admin or first_user)

    try:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, password_salt, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, password_hash, password_salt, int(effective_admin), created_at),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username already exists.") from exc

    return UserRecord(
        id=int(cursor.lastrowid),
        username=username,
        is_admin=effective_admin,
    )


def create_user(db_path: str, username: str, password: str, *, is_admin: bool = False) -> UserRecord:
    normalized = _validate_username(username)
    _validate_password(password)
    now = _utcnow().isoformat()
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    with _connect(db_path) as conn:
        return _insert_user_atomic(
            conn,
            normalized,
            password_hash,
            salt.hex(),
            now,
            is_admin=is_admin,
        )


def create_initial_user(db_path: str, username: str, password: str) -> UserRecord:
    normalized = _validate_username(username)
    _validate_password(password)
    now = _utcnow().isoformat()
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    with _connect(db_path) as conn:
        return _insert_user_atomic(
            conn,
            normalized,
            password_hash,
            salt.hex(),
            now,
            is_admin=True,
            require_no_existing_users=True,
        )


def authenticate_user(db_path: str, username: str, password: str) -> UserRecord | None:
    normalized = _normalize_username(username)
    if not normalized or not password:
        return None

    with _connect(db_path) as conn:
        now = _utcnow()
        _prune_expired_login_attempts(conn, now)
        if _is_locked_out(conn, normalized, now):
            raise ValueError(LOCKOUT_ERROR)

        row = conn.execute(
            "SELECT id, username, password_hash, password_salt, is_admin FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()

        if row is None:
            _record_failed_login(conn, normalized, now)
            return None

        expected_hash = row["password_hash"]
        actual_hash = _hash_password(password, bytes.fromhex(row["password_salt"]))
        if not hmac.compare_digest(expected_hash, actual_hash):
            _record_failed_login(conn, normalized, now)
            return None

        _clear_failed_logins(conn, normalized)

    return UserRecord(id=int(row["id"]), username=row["username"], is_admin=bool(row["is_admin"]))


def create_session(db_path: str, user_id: int, *, ttl_days: int = SESSION_TTL_DAYS) -> str:
    now = _utcnow()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_session_token(token)
    expires_at = (now + timedelta(days=ttl_days)).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, last_seen_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, user_id, now.isoformat(), now.isoformat(), expires_at),
        )
    return token


def _prune_expired_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_utcnow().isoformat(),))


def get_session_user(db_path: str, token: str, *, ttl_days: int = SESSION_TTL_DAYS) -> UserRecord | None:
    if not token:
        return None

    token_hash = _hash_session_token(token)
    now = _utcnow()
    expires_at = (now + timedelta(days=ttl_days)).isoformat()

    with _connect(db_path) as conn:
        _prune_expired_sessions(conn)
        row = conn.execute(
            """
            SELECT u.id, u.username, u.is_admin
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token_hash,),
        ).fetchone()

        if row is None:
            # Backward compatibility: migrate any legacy plaintext token row on read.
            row = conn.execute(
                """
                SELECT u.id, u.username, u.is_admin
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()
            if row is None:
                return None

            conn.execute("UPDATE sessions SET token = ? WHERE token = ?", (token_hash, token))

        conn.execute(
            "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token = ?",
            (now.isoformat(), expires_at, token_hash),
        )

    return UserRecord(id=int(row["id"]), username=row["username"], is_admin=bool(row["is_admin"]))


def invalidate_session(db_path: str, token: str) -> None:
    if not token:
        return
    token_hash = _hash_session_token(token)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (token_hash, token))


def list_users(db_path: str) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT username FROM users ORDER BY username ASC").fetchall()
    return [str(row["username"]) for row in rows]


def list_users_with_roles(db_path: str) -> list[dict[str, object]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT username, is_admin FROM users ORDER BY username ASC"
        ).fetchall()
    return [
        {
            "username": str(row["username"]),
            "is_admin": bool(row["is_admin"]),
        }
        for row in rows
    ]


def delete_user(db_path: str, username: str) -> None:
    normalized = _normalize_username(username)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, is_admin FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found.")

        count = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if count <= 1:
            raise ValueError("Cannot delete the last user.")

        if bool(row["is_admin"]):
            admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0])
            if admin_count <= 1:
                raise ValueError("Cannot delete the last administrator.")

        conn.execute("DELETE FROM users WHERE id = ?", (int(row["id"]),))


def promote_user_to_admin(db_path: str, username: str) -> UserRecord:
    normalized = _normalize_username(username)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, username FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found.")

        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (int(row["id"]),))

    return UserRecord(id=int(row["id"]), username=row["username"], is_admin=True)


def create_user_as_admin(
    db_path: str,
    actor_username: str,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
) -> UserRecord:
    actor = get_user_by_username(db_path, actor_username)
    if actor is None or not actor.is_admin:
        raise ValueError("Only administrators can create users.")
    return create_user(db_path, username, password, is_admin=is_admin)


def get_user_by_username(db_path: str, username: str) -> UserRecord | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()

    if row is None:
        return None
    return UserRecord(id=int(row["id"]), username=row["username"], is_admin=bool(row["is_admin"]))


def change_password(db_path: str, username: str, current_password: str, new_password: str) -> None:
    user = authenticate_user(db_path, username, current_password)
    if user is None:
        raise ValueError("Current password is incorrect.")

    _validate_password(new_password)
    salt = secrets.token_bytes(16)
    password_hash = _hash_password(new_password, salt)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (password_hash, salt.hex(), user.id),
        )


def delete_user_as_admin(db_path: str, actor_username: str, username: str) -> None:
    actor = get_user_by_username(db_path, actor_username)
    if actor is None or not actor.is_admin:
        raise ValueError("Only administrators can delete users.")
    delete_user(db_path, username)


def set_user_admin_role_as_admin(
    db_path: str,
    actor_username: str,
    username: str,
    *,
    is_admin: bool,
) -> UserRecord:
    actor = get_user_by_username(db_path, actor_username)
    if actor is None or not actor.is_admin:
        raise ValueError("Only administrators can change user roles.")

    normalized = _normalize_username(username)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found.")

        current_is_admin = bool(row["is_admin"])
        target_is_admin = bool(is_admin)

        if current_is_admin and not target_is_admin:
            admin_count = int(conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0])
            if admin_count <= 1:
                raise ValueError("Cannot demote the last administrator.")

        conn.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?",
            (int(target_is_admin), int(row["id"])),
        )

    return UserRecord(
        id=int(row["id"]),
        username=str(row["username"]),
        is_admin=target_is_admin,
    )
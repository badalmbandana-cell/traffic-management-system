"""
User store for authentication - separate SQLite file (auth_users.db) from
traffic_logs.db, since users/roles are a different concern than traffic data.

Passwords are stored as PBKDF2-HMAC-SHA256 hashes with a random per-user
salt (stdlib `hashlib` only - no extra dependency like bcrypt/passlib
needed). 100,000 iterations is the OWASP-recommended minimum as of writing.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).parent / "auth_users.db"
PBKDF2_ITERATIONS = 100_000
VALID_ROLES = ("admin", "operator", "viewer")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('admin','operator','viewer')),
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


@contextmanager
def get_connection(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    path = db_path if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex). Pass salt=None to generate a new one."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    candidate_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, password_hash_hex)


def init_users_db(db_path: Optional[Path] = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def create_user(username: str, password: str, role: str, db_path: Optional[Path] = None) -> int:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got '{role}'")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    password_hash, salt = hash_password(password)
    with get_connection(db_path) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt, role),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"username '{username}' already exists") from exc
        return cur.lastrowid


def get_user(username: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    with get_connection(db_path) as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def authenticate(username: str, password: str, db_path: Optional[Path] = None) -> Optional[str]:
    """Returns the user's role if credentials are correct, else None."""
    user = get_user(username, db_path)
    if user is None:
        return None
    if not verify_password(password, user["password_hash"], user["salt"]):
        return None
    return user["role"]


def list_users(db_path: Optional[Path] = None) -> list[sqlite3.Row]:
    with get_connection(db_path) as conn:
        return conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()


def delete_user(username: str, db_path: Optional[Path] = None) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        return cur.rowcount > 0


def seed_default_users(db_path: Optional[Path] = None) -> None:
    """Creates the three demo accounts IF the users table is empty. Real
    deployments should change these passwords immediately (see
    auth/manage_users.py) - these are for local dev/demo only."""
    with get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return
    create_user("admin", "admin12345", "admin", db_path)
    create_user("operator", "operator12345", "operator", db_path)
    create_user("viewer", "viewer12345", "viewer", db_path)

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class InvalidUserToken(ValueError):
    """Raised when a user API token is absent, revoked, or unknown."""


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    google_sub: str
    email: str
    google_connected: bool


class MultiUserStore:
    """Encrypted user credentials and hashed MCP access tokens."""

    def __init__(self, database: str | Path, master_key_path: str | Path) -> None:
        self.database = Path(database).expanduser()
        self.master_key_path = Path(master_key_path).expanduser()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.master_key_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _enforce_permissions(self) -> None:
        for path in (
            self.database,
            Path(f"{self.database}-wal"),
            Path(f"{self.database}-shm"),
            self.master_key_path,
        ):
            if path.exists():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
            self._enforce_permissions()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    google_sub TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    encrypted_credentials BLOB,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    token_hash TEXT PRIMARY KEY,
                    token_prefix TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER,
                    revoked_at INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state_hash TEXT PRIMARY KEY,
                    binding_hash TEXT NOT NULL,
                    code_verifier TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS oauth_states_expires_idx
                    ON oauth_states(expires_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(oauth_states)")
            }
            if "binding_hash" not in columns:
                connection.execute(
                    "ALTER TABLE oauth_states ADD COLUMN binding_hash TEXT NOT NULL DEFAULT ''"
                )

    def _master_key(self) -> bytes:
        if not self.master_key_path.exists():
            key = os.urandom(32)
            try:
                descriptor = os.open(
                    self.master_key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
        self._enforce_permissions()
        key = self.master_key_path.read_bytes()
        if len(key) != 32:
            raise RuntimeError("Multi-user master key must contain exactly 32 bytes")
        return key

    def _fernet(self) -> Fernet:
        return Fernet(base64.urlsafe_b64encode(self._master_key()))

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=str(row["user_id"]),
            google_sub=str(row["google_sub"]),
            email=str(row["email"]),
            google_connected=row["encrypted_credentials"] is not None,
        )

    def upsert_google_user(self, google_sub: str, email: str, credentials_json: str) -> UserRecord:
        now = int(time.time())
        encrypted = self._fernet().encrypt(credentials_json.encode("utf-8"))
        with self._connection() as connection:
            row = connection.execute(
                "SELECT user_id FROM users WHERE google_sub = ?", (google_sub,)
            ).fetchone()
            if row is None:
                user_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, google_sub, email, encrypted_credentials,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, google_sub, email, encrypted, now, now),
                )
            else:
                user_id = str(row["user_id"])
                connection.execute(
                    """
                    UPDATE users
                    SET email = ?, encrypted_credentials = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (email, encrypted, now, user_id),
                )
        user = self.get_user(user_id)
        self.audit_event(user_id, "google_connected", {"email": email})
        return user

    def get_user(self, user_id: str) -> UserRecord:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(f"User not found: {user_id}")
        return self._user_from_row(row)

    def set_google_credentials(self, user_id: str, credentials_json: str) -> None:
        encrypted = self._fernet().encrypt(credentials_json.encode("utf-8"))
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET encrypted_credentials = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (encrypted, int(time.time()), user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"User not found: {user_id}")

    def get_google_credentials(self, user_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT encrypted_credentials FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or row["encrypted_credentials"] is None:
            return None
        try:
            return self._fernet().decrypt(bytes(row["encrypted_credentials"])).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Stored Google credentials cannot be decrypted") from exc

    def create_api_token(self, user_id: str, *, label: str) -> str:
        self.get_user(user_id)
        token = f"gfm_{secrets.token_urlsafe(32)}"
        now = int(time.time())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO api_tokens (
                    token_hash, token_prefix, user_id, label, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (self._hash(token), token[:12], user_id, label.strip()[:100], now),
            )
        self.audit_event(user_id, "api_token_created", {"label": label.strip()[:100]})
        return token

    def authenticate_api_token(self, token: str) -> UserRecord:
        token_hash = self._hash(token)
        now = int(time.time())
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT u.*
                FROM api_tokens AS t
                JOIN users AS u ON u.user_id = t.user_id
                WHERE t.token_hash = ? AND t.revoked_at IS NULL
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                raise InvalidUserToken("API token is invalid or revoked")
            connection.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
        return self._user_from_row(row)

    def revoke_api_token(self, user_id: str, token: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE api_tokens SET revoked_at = ?
                WHERE user_id = ? AND token_hash = ? AND revoked_at IS NULL
                """,
                (int(time.time()), user_id, self._hash(token)),
            )
        self.audit_event(user_id, "api_token_revoked", {})

    def disconnect_google(self, user_id: str) -> None:
        now = int(time.time())
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE users
                SET encrypted_credentials = NULL, updated_at = ?
                WHERE user_id = ?
                """,
                (now, user_id),
            )
            connection.execute(
                """
                UPDATE api_tokens SET revoked_at = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (now, user_id),
            )
        self.audit_event(user_id, "google_disconnected", {})

    def create_oauth_state(
        self,
        code_verifier: str,
        *,
        binding: str,
        now: int | None = None,
        ttl_seconds: int = 600,
    ) -> str:
        timestamp = int(time.time()) if now is None else now
        state = secrets.token_urlsafe(32)
        with self._connection() as connection:
            connection.execute("DELETE FROM oauth_states WHERE expires_at < ?", (timestamp,))
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state_hash, binding_hash, code_verifier, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self._hash(state),
                    self._hash(binding),
                    code_verifier,
                    timestamp + ttl_seconds,
                    timestamp,
                ),
            )
        return state

    def consume_oauth_state(
        self,
        state: str,
        *,
        binding: str,
        now: int | None = None,
    ) -> str | None:
        timestamp = int(time.time()) if now is None else now
        state_hash = self._hash(state)
        binding_hash = self._hash(binding)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT binding_hash, code_verifier, expires_at FROM oauth_states
                WHERE state_hash = ?
                """,
                (state_hash,),
            ).fetchone()
            if row is None:
                return None
            if not secrets.compare_digest(str(row["binding_hash"]), binding_hash):
                return None
            connection.execute("DELETE FROM oauth_states WHERE state_hash = ?", (state_hash,))
        if int(row["expires_at"]) < timestamp:
            return None
        return str(row["code_verifier"])

    def audit_event(self, user_id: str | None, event_type: str, details: dict[str, object]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    event_id, user_id, event_type, details, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    event_type,
                    json.dumps(details, sort_keys=True),
                    int(time.time()),
                ),
            )

    def list_audit_events(self, user_id: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_type, details, created_at
                FROM audit_events
                WHERE user_id = ?
                ORDER BY created_at, event_id
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "event_type": str(row["event_type"]),
                "details": json.loads(str(row["details"])),
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

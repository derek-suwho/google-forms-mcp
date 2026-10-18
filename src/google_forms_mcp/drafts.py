from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google_forms_mcp.models import FormSpec


class DraftNotFound(KeyError):
    """Raised when a draft ID does not exist."""


class DraftConflict(RuntimeError):
    """Raised when a patch was based on a stale draft version."""


class NothingToUndo(ValueError):
    """Raised when a draft is already at its first revision."""


@dataclass(frozen=True)
class DraftRecord:
    draft_id: str
    version: int
    spec: FormSpec
    published_form_id: str | None
    created_at: str
    updated_at: str


class DraftStore:
    """SQLite-backed form drafts with linear, undoable revisions."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _enforce_permissions(self) -> None:
        for path in (
            self.database,
            Path(f"{self.database}-wal"),
            Path(f"{self.database}-shm"),
        ):
            if path.exists():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
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
                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    current_version INTEGER NOT NULL,
                    published_form_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS draft_versions (
                    draft_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (draft_id, version),
                    FOREIGN KEY (draft_id) REFERENCES drafts(draft_id) ON DELETE CASCADE
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _spec_json(spec: FormSpec) -> str:
        return spec.model_dump_json(exclude_computed_fields=True)

    def create(self, spec: FormSpec) -> DraftRecord:
        draft_id = str(uuid.uuid4())
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO drafts (
                    draft_id, current_version, published_form_id, created_at, updated_at
                ) VALUES (?, 1, NULL, ?, ?)
                """,
                (draft_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO draft_versions (
                    draft_id, version, spec_json, changes_json, created_at
                ) VALUES (?, 1, ?, '[]', ?)
                """,
                (draft_id, self._spec_json(spec), now),
            )
        return self.get(draft_id)

    def get(self, draft_id: str) -> DraftRecord:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT d.draft_id, d.current_version, d.published_form_id,
                       d.created_at, d.updated_at, v.spec_json
                FROM drafts AS d
                JOIN draft_versions AS v
                  ON v.draft_id = d.draft_id AND v.version = d.current_version
                WHERE d.draft_id = ?
                """,
                (draft_id,),
            ).fetchone()
        if row is None:
            raise DraftNotFound(f"Draft not found: {draft_id}")
        return DraftRecord(
            draft_id=str(row["draft_id"]),
            version=int(row["current_version"]),
            spec=FormSpec.model_validate_json(str(row["spec_json"])),
            published_form_id=(str(row["published_form_id"]) if row["published_form_id"] else None),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def save_revision(
        self,
        draft_id: str,
        spec: FormSpec,
        *,
        changes: list[dict[str, Any]],
        expected_version: int,
    ) -> DraftRecord:
        now = self._now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version, published_form_id FROM drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise DraftNotFound(f"Draft not found: {draft_id}")
            if row["published_form_id"] is not None:
                raise DraftConflict(
                    f"Draft {draft_id} cannot change while publication is claimed or complete"
                )
            current_version = int(row["current_version"])
            if current_version != expected_version:
                raise DraftConflict(
                    f"Draft {draft_id} expected version {expected_version}, "
                    f"but current version is {current_version}"
                )
            next_version = current_version + 1
            connection.execute(
                "DELETE FROM draft_versions WHERE draft_id = ? AND version >= ?",
                (draft_id, next_version),
            )
            connection.execute(
                """
                INSERT INTO draft_versions (
                    draft_id, version, spec_json, changes_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    next_version,
                    self._spec_json(spec),
                    json.dumps(changes, sort_keys=True),
                    now,
                ),
            )
            connection.execute(
                "UPDATE drafts SET current_version = ?, updated_at = ? WHERE draft_id = ?",
                (next_version, now, draft_id),
            )
        return self.get(draft_id)

    def undo(self, draft_id: str) -> DraftRecord:
        now = self._now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version, published_form_id FROM drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise DraftNotFound(f"Draft not found: {draft_id}")
            if row["published_form_id"] is not None:
                raise DraftConflict(
                    f"Draft {draft_id} cannot change while publication is claimed or complete"
                )
            current_version = int(row["current_version"])
            if current_version == 1:
                raise NothingToUndo(f"Draft {draft_id} has no earlier revision")
            connection.execute(
                "UPDATE drafts SET current_version = ?, updated_at = ? WHERE draft_id = ?",
                (current_version - 1, now, draft_id),
            )
        return self.get(draft_id)

    @staticmethod
    def _publishing_marker(version: int) -> str:
        return f"__publishing__:{version}"

    def claim_publication(self, draft_id: str, *, expected_version: int) -> bool:
        marker = self._publishing_marker(expected_version)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version, published_form_id FROM drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise DraftNotFound(f"Draft not found: {draft_id}")
            current_version = int(row["current_version"])
            if current_version != expected_version:
                raise DraftConflict(
                    f"Draft {draft_id} expected version {expected_version}, "
                    f"but current version is {current_version}"
                )
            if row["published_form_id"] is not None:
                return False
            connection.execute(
                "UPDATE drafts SET published_form_id = ?, updated_at = ? WHERE draft_id = ?",
                (marker, self._now(), draft_id),
            )
        return True

    def release_publication(self, draft_id: str, *, expected_version: int) -> None:
        marker = self._publishing_marker(expected_version)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET published_form_id = NULL, updated_at = ?
                WHERE draft_id = ? AND published_form_id = ?
                """,
                (self._now(), draft_id, marker),
            )

    def record_failed_publication(
        self,
        draft_id: str,
        form_id: str,
        *,
        expected_version: int,
    ) -> DraftRecord:
        publishing_marker = self._publishing_marker(expected_version)
        failed_marker = f"__failed__:{expected_version}:{form_id}"
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE drafts
                SET published_form_id = ?, updated_at = ?
                WHERE draft_id = ?
                  AND current_version = ?
                  AND published_form_id = ?
                """,
                (
                    failed_marker,
                    self._now(),
                    draft_id,
                    expected_version,
                    publishing_marker,
                ),
            )
            if cursor.rowcount == 0:
                raise DraftConflict(f"Draft {draft_id} publication claim is no longer current")
        return self.get(draft_id)

    def mark_published(self, draft_id: str, form_id: str, *, expected_version: int) -> DraftRecord:
        marker = self._publishing_marker(expected_version)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE drafts
                SET published_form_id = ?, updated_at = ?
                WHERE draft_id = ?
                  AND current_version = ?
                  AND published_form_id = ?
                """,
                (form_id, self._now(), draft_id, expected_version, marker),
            )
            if cursor.rowcount == 0:
                exists = connection.execute(
                    "SELECT 1 FROM drafts WHERE draft_id = ?", (draft_id,)
                ).fetchone()
                if exists is None:
                    raise DraftNotFound(f"Draft not found: {draft_id}")
                raise DraftConflict(f"Draft {draft_id} publication claim is no longer current")
        return self.get(draft_id)

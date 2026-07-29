from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Protocol


class NotEnoughPasswords(RuntimeError):
    def __init__(self, needed: int, available: int):
        self.needed = needed
        self.available = available
        super().__init__(
            f"Недостаточно доступных паролей: нужно {needed}, доступно {available}."
        )


class PasswordConflict(RuntimeError):
    pass


class PasswordsUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    batch_id: str
    passwords: tuple[str, ...]


class Store(Protocol):
    hotel_id: str

    def initialize(self) -> None: ...
    def health(self) -> bool: ...
    def preview_import(self, passwords: Iterable[str]) -> dict: ...
    def import_passwords(self, passwords: Iterable[str]) -> dict[str, int]: ...
    def stats(self) -> dict[str, int]: ...
    def list_available(
        self, limit: int = 200, offset: int = 0, search: str = ""
    ) -> list[dict]: ...
    def list_generations(self, limit: int = 50) -> list[dict]: ...
    def update_available(self, password_id: int, password: str) -> bool: ...
    def delete_available(self, password_id: int) -> bool: ...
    def delete_available_many(self, password_ids: Iterable[int]) -> int: ...
    def issue_available(self, password_ids: Iterable[int]) -> list[str]: ...
    def reserve(
        self, count: int, ru_count: int = 0, en_count: int = 0
    ) -> Reservation: ...
    def commit(self, batch_id: str) -> int: ...
    def release(self, batch_id: str, error: str | None = None) -> int: ...
    def release_stale_reservations(self, max_age_minutes: int | None = None) -> int: ...


def normalize_password(password: str) -> str | None:
    value = str(password).strip()
    if not value or value.casefold() in {"password", "пароль"}:
        return None
    if len(value) > 256:
        return None
    return value


def build_import_preview(
    passwords: Iterable[str], existing: set[str]
) -> dict:
    items = []
    seen: set[str] = set()
    summary = {
        "recognized": 0,
        "new": 0,
        "duplicates": 0,
        "invalid": 0,
    }
    for raw in passwords:
        value = str(raw)
        normalized = normalize_password(value)
        if normalized is None:
            summary["invalid"] += 1
            items.append(
                {
                    "value": value,
                    "normalized": None,
                    "status": "invalid",
                    "reason": "Пустая строка, заголовок или слишком длинное значение",
                }
            )
            continue
        summary["recognized"] += 1
        if normalized in seen:
            summary["duplicates"] += 1
            status = "duplicate"
            reason = "Повтор внутри импортируемой партии"
        elif normalized in existing:
            summary["duplicates"] += 1
            status = "duplicate"
            reason = "Уже есть в базе"
        else:
            summary["new"] += 1
            status = "new"
            reason = None
        seen.add(normalized)
        items.append(
            {
                "value": value,
                "normalized": normalized,
                "status": status,
                "reason": reason,
            }
        )
    return {"items": items, "summary": summary}


class PasswordStore:
    """SQLite storage for local standalone operation and offline recovery."""

    def __init__(
        self,
        database_path: str,
        hotel_id: str = "standalone",
        hotel_name: str = "Standalone hotel",
        reservation_ttl_minutes: int = 15,
    ):
        self.database_path = Path(database_path)
        self.hotel_id = hotel_id
        self.hotel_name = hotel_name
        self.reservation_ttl_minutes = reservation_ttl_minutes

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(passwords)"
                ).fetchall()
            }
            if columns and "hotel_id" not in columns:
                self._migrate_legacy_schema(connection)

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS hotels (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS passwords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hotel_id TEXT NOT NULL REFERENCES hotels(id),
                    password TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK (status IN ('available', 'reserved', 'used')),
                    batch_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reserved_at TEXT,
                    used_at TEXT,
                    UNIQUE (hotel_id, password)
                );

                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    hotel_id TEXT NOT NULL REFERENCES hotels(id),
                    ru_count INTEGER NOT NULL DEFAULT 0,
                    en_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('reserved', 'completed', 'failed')),
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_passwords_hotel_status_id
                    ON passwords(hotel_id, status, id);
                CREATE INDEX IF NOT EXISTS idx_passwords_hotel_batch
                    ON passwords(hotel_id, batch_id);
                CREATE INDEX IF NOT EXISTS idx_generations_hotel_created
                    ON generations(hotel_id, created_at DESC);
                """
            )
            connection.execute(
                """
                INSERT INTO hotels(id, name)
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET name = excluded.name
                """,
                (self.hotel_id, self.hotel_name),
            )
        self.release_stale_reservations()

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            CREATE TABLE passwords_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id TEXT NOT NULL,
                password TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN ('available', 'reserved', 'used')),
                batch_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reserved_at TEXT,
                used_at TEXT,
                UNIQUE (hotel_id, password)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO passwords_v2(
                id, hotel_id, password, status, batch_id,
                created_at, reserved_at, used_at
            )
            SELECT id, ?, password, status, batch_id,
                   created_at, reserved_at, used_at
            FROM passwords
            """,
            (self.hotel_id,),
        )
        connection.executescript(
            """
            DROP TABLE passwords;
            ALTER TABLE passwords_v2 RENAME TO passwords;
            PRAGMA foreign_keys = ON;
            """
        )

    def health(self) -> bool:
        with self._connection() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def preview_import(self, passwords: Iterable[str]) -> dict:
        values = list(passwords)
        normalized = {
            value
            for value in (normalize_password(item) for item in values)
            if value is not None
        }
        existing: set[str] = set()
        with self._connection() as connection:
            candidates = list(normalized)
            for start in range(0, len(candidates), 500):
                chunk = candidates[start : start + 500]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT password
                    FROM passwords
                    WHERE hotel_id = ? AND password IN ({placeholders})
                    """,
                    (self.hotel_id, *chunk),
                ).fetchall()
                existing.update(row["password"] for row in rows)
        return build_import_preview(values, existing)

    def import_passwords(self, passwords: Iterable[str]) -> dict[str, int]:
        requested = 0
        invalid = 0
        added = 0

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for password in passwords:
                requested += 1
                normalized = normalize_password(password)
                if normalized is None:
                    invalid += 1
                    continue
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO passwords(hotel_id, password, status)
                    VALUES (?, ?, 'available')
                    """,
                    (self.hotel_id, normalized),
                )
                added += cursor.rowcount

        return {
            "requested": requested,
            "added": added,
            "duplicates": requested - invalid - added,
            "invalid": invalid,
        }

    def stats(self) -> dict[str, int]:
        counts = {"available": 0, "reserved": 0, "used": 0, "total": 0}
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM passwords
                WHERE hotel_id = ?
                GROUP BY status
                """,
                (self.hotel_id,),
            ).fetchall()
        for row in rows:
            counts[row["status"]] = row["count"]
            counts["total"] += row["count"]
        return counts

    def list_available(
        self, limit: int = 200, offset: int = 0, search: str = ""
    ) -> list[dict]:
        search_value = f"%{search.strip()}%"
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, password, created_at
                FROM passwords
                WHERE hotel_id = ?
                  AND status = 'available'
                  AND password LIKE ?
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (self.hotel_id, search_value, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_generations(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, ru_count, en_count, total_count, status,
                       error, created_at, completed_at
                FROM generations
                WHERE hotel_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (self.hotel_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_available(self, password_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM passwords
                WHERE id = ? AND hotel_id = ? AND status = 'available'
                """,
                (password_id, self.hotel_id),
            )
        return cursor.rowcount == 1

    def update_available(self, password_id: int, password: str) -> bool:
        normalized = normalize_password(password)
        if normalized is None:
            raise ValueError("Некорректный пароль")
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE passwords
                    SET password = ?
                    WHERE id = ? AND hotel_id = ? AND status = 'available'
                    """,
                    (normalized, password_id, self.hotel_id),
                )
        except sqlite3.IntegrityError as error:
            raise PasswordConflict("Такой пароль уже есть в базе") from error
        return cursor.rowcount == 1

    def delete_available_many(self, password_ids: Iterable[int]) -> int:
        ids = sorted(set(int(item) for item in password_ids))
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM passwords
                WHERE hotel_id = ?
                  AND status = 'available'
                  AND id IN ({placeholders})
                """,
                (self.hotel_id, *ids),
            )
        return cursor.rowcount

    def issue_available(self, password_ids: Iterable[int]) -> list[str]:
        ids = sorted(set(int(item) for item in password_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""
                SELECT id, password
                FROM passwords
                WHERE hotel_id = ?
                  AND status = 'available'
                  AND id IN ({placeholders})
                ORDER BY id
                """,
                (self.hotel_id, *ids),
            ).fetchall()
            if len(rows) != len(ids):
                raise PasswordsUnavailable(
                    "Один или несколько паролей уже недоступны"
                )
            connection.execute(
                f"""
                UPDATE passwords
                SET status = 'used',
                    used_at = CURRENT_TIMESTAMP,
                    reserved_at = NULL,
                    batch_id = NULL
                WHERE hotel_id = ? AND id IN ({placeholders})
                """,
                (self.hotel_id, *ids),
            )
        return [row["password"] for row in rows]

    def reserve(
        self, count: int, ru_count: int = 0, en_count: int = 0
    ) -> Reservation:
        if count <= 0:
            return Reservation(batch_id="", passwords=())

        batch_id = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._release_stale_in_connection(
                connection, self.reservation_ttl_minutes
            )
            rows = connection.execute(
                """
                SELECT id, password
                FROM passwords
                WHERE hotel_id = ? AND status = 'available'
                ORDER BY id
                LIMIT ?
                """,
                (self.hotel_id, count),
            ).fetchall()
            if len(rows) < count:
                raise NotEnoughPasswords(needed=count, available=len(rows))

            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""
                UPDATE passwords
                SET status = 'reserved',
                    batch_id = ?,
                    reserved_at = CURRENT_TIMESTAMP
                WHERE hotel_id = ?
                  AND id IN ({placeholders})
                  AND status = 'available'
                """,
                (batch_id, self.hotel_id, *ids),
            )
            connection.execute(
                """
                INSERT INTO generations(
                    id, hotel_id, ru_count, en_count, total_count, status
                )
                VALUES (?, ?, ?, ?, ?, 'reserved')
                """,
                (batch_id, self.hotel_id, ru_count, en_count, count),
            )

        return Reservation(
            batch_id=batch_id,
            passwords=tuple(row["password"] for row in rows),
        )

    def commit(self, batch_id: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE passwords
                SET status = 'used',
                    used_at = CURRENT_TIMESTAMP,
                    reserved_at = NULL,
                    batch_id = NULL
                WHERE hotel_id = ? AND status = 'reserved' AND batch_id = ?
                """,
                (self.hotel_id, batch_id),
            )
            connection.execute(
                """
                UPDATE generations
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND hotel_id = ? AND status = 'reserved'
                """,
                (batch_id, self.hotel_id),
            )
        return cursor.rowcount

    def release(self, batch_id: str, error: str | None = None) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE passwords
                SET status = 'available',
                    reserved_at = NULL,
                    batch_id = NULL
                WHERE hotel_id = ? AND status = 'reserved' AND batch_id = ?
                """,
                (self.hotel_id, batch_id),
            )
            connection.execute(
                """
                UPDATE generations
                SET status = 'failed',
                    error = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ? AND hotel_id = ? AND status = 'reserved'
                """,
                (error, batch_id, self.hotel_id),
            )
        return cursor.rowcount

    def _release_stale_in_connection(
        self, connection: sqlite3.Connection, max_age_minutes: int
    ) -> int:
        stale = connection.execute(
            """
            SELECT DISTINCT batch_id
            FROM passwords
            WHERE hotel_id = ?
              AND status = 'reserved'
              AND reserved_at < datetime('now', ?)
              AND batch_id IS NOT NULL
            """,
            (self.hotel_id, f"-{max_age_minutes} minutes"),
        ).fetchall()
        batch_ids = [row["batch_id"] for row in stale]
        if not batch_ids:
            return 0
        placeholders = ",".join("?" for _ in batch_ids)
        cursor = connection.execute(
            f"""
            UPDATE passwords
            SET status = 'available', reserved_at = NULL, batch_id = NULL
            WHERE hotel_id = ? AND batch_id IN ({placeholders})
            """,
            (self.hotel_id, *batch_ids),
        )
        connection.execute(
            f"""
            UPDATE generations
            SET status = 'failed',
                error = 'Reservation lease expired',
                completed_at = CURRENT_TIMESTAMP
            WHERE hotel_id = ? AND id IN ({placeholders}) AND status = 'reserved'
            """,
            (self.hotel_id, *batch_ids),
        )
        return cursor.rowcount

    def release_stale_reservations(self, max_age_minutes: int | None = None) -> int:
        max_age = max_age_minutes or self.reservation_ttl_minutes
        with self._connection() as connection:
            return self._release_stale_in_connection(connection, max_age)

    def release_all_reservations(self) -> int:
        """Administrative compatibility helper; normal recovery uses leases."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT batch_id
                FROM passwords
                WHERE hotel_id = ? AND status = 'reserved' AND batch_id IS NOT NULL
                """,
                (self.hotel_id,),
            ).fetchall()
        return sum(self.release(row["batch_id"], "Released administratively") for row in rows)


class PostgresPasswordStore:
    """PostgreSQL storage for the online module (including Supabase Postgres)."""

    schema = "wifi_voucher"

    def __init__(
        self,
        database_url: str,
        hotel_id: str,
        hotel_name: str,
        reservation_ttl_minutes: int = 15,
    ):
        self.database_url = database_url
        self.hotel_id = hotel_id
        self.hotel_name = hotel_name
        self.reservation_ttl_minutes = reservation_ttl_minutes

    @contextmanager
    def _connection(self):
        import psycopg
        from psycopg.rows import dict_row

        connection = psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=15,
            application_name="wifi-voucher",
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.hotels (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.passwords (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    hotel_id TEXT NOT NULL
                        REFERENCES {self.schema}.hotels(id),
                    password TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK (status IN ('available', 'reserved', 'used')),
                    batch_id UUID,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    reserved_at TIMESTAMPTZ,
                    used_at TIMESTAMPTZ,
                    UNIQUE (hotel_id, password)
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.schema}.generations (
                    id UUID PRIMARY KEY,
                    hotel_id TEXT NOT NULL
                        REFERENCES {self.schema}.hotels(id),
                    ru_count INTEGER NOT NULL DEFAULT 0,
                    en_count INTEGER NOT NULL DEFAULT 0,
                    total_count INTEGER NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('reserved', 'completed', 'failed')),
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_passwords_hotel_status_id
                ON {self.schema}.passwords(hotel_id, status, id)
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_passwords_hotel_batch
                ON {self.schema}.passwords(hotel_id, batch_id)
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_generations_hotel_created
                ON {self.schema}.generations(hotel_id, created_at DESC)
                """
            )
            connection.execute(
                f"""
                INSERT INTO {self.schema}.hotels(id, name)
                VALUES (%s, %s)
                ON CONFLICT(id) DO UPDATE SET name = excluded.name
                """,
                (self.hotel_id, self.hotel_name),
            )
        self.release_stale_reservations()

    def health(self) -> bool:
        with self._connection() as connection:
            return connection.execute("SELECT 1 AS ok").fetchone()["ok"] == 1

    def preview_import(self, passwords: Iterable[str]) -> dict:
        values = list(passwords)
        candidates = sorted(
            {
                value
                for value in (normalize_password(item) for item in values)
                if value is not None
            }
        )
        existing: set[str] = set()
        if candidates:
            with self._connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT password
                    FROM {self.schema}.passwords
                    WHERE hotel_id = %s AND password = ANY(%s)
                    """,
                    (self.hotel_id, candidates),
                ).fetchall()
                existing.update(row["password"] for row in rows)
        return build_import_preview(values, existing)

    def import_passwords(self, passwords: Iterable[str]) -> dict[str, int]:
        requested = 0
        invalid = 0
        added = 0
        with self._connection() as connection:
            for password in passwords:
                requested += 1
                normalized = normalize_password(password)
                if normalized is None:
                    invalid += 1
                    continue
                cursor = connection.execute(
                    f"""
                    INSERT INTO {self.schema}.passwords(
                        hotel_id, password, status
                    )
                    VALUES (%s, %s, 'available')
                    ON CONFLICT(hotel_id, password) DO NOTHING
                    """,
                    (self.hotel_id, normalized),
                )
                added += cursor.rowcount
        return {
            "requested": requested,
            "added": added,
            "duplicates": requested - invalid - added,
            "invalid": invalid,
        }

    def stats(self) -> dict[str, int]:
        counts = {"available": 0, "reserved": 0, "used": 0, "total": 0}
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT status, COUNT(*) AS count
                FROM {self.schema}.passwords
                WHERE hotel_id = %s
                GROUP BY status
                """,
                (self.hotel_id,),
            ).fetchall()
        for row in rows:
            count = int(row["count"])
            counts[row["status"]] = count
            counts["total"] += count
        return counts

    def list_available(
        self, limit: int = 200, offset: int = 0, search: str = ""
    ) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, password, created_at
                FROM {self.schema}.passwords
                WHERE hotel_id = %s
                  AND status = 'available'
                  AND password ILIKE %s
                ORDER BY id
                LIMIT %s OFFSET %s
                """,
                (self.hotel_id, f"%{search.strip()}%", limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_generations(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id::text AS id, ru_count, en_count, total_count, status,
                       error, created_at, completed_at
                FROM {self.schema}.generations
                WHERE hotel_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (self.hotel_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_available(self, password_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM {self.schema}.passwords
                WHERE id = %s AND hotel_id = %s AND status = 'available'
                """,
                (password_id, self.hotel_id),
            )
        return cursor.rowcount == 1

    def update_available(self, password_id: int, password: str) -> bool:
        import psycopg

        normalized = normalize_password(password)
        if normalized is None:
            raise ValueError("Некорректный пароль")
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"""
                    UPDATE {self.schema}.passwords
                    SET password = %s
                    WHERE id = %s
                      AND hotel_id = %s
                      AND status = 'available'
                    """,
                    (normalized, password_id, self.hotel_id),
                )
        except psycopg.errors.UniqueViolation as error:
            raise PasswordConflict("Такой пароль уже есть в базе") from error
        return cursor.rowcount == 1

    def delete_available_many(self, password_ids: Iterable[int]) -> int:
        ids = sorted(set(int(item) for item in password_ids))
        if not ids:
            return 0
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM {self.schema}.passwords
                WHERE hotel_id = %s
                  AND status = 'available'
                  AND id = ANY(%s)
                """,
                (self.hotel_id, ids),
            )
        return cursor.rowcount

    def issue_available(self, password_ids: Iterable[int]) -> list[str]:
        ids = sorted(set(int(item) for item in password_ids))
        if not ids:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, password
                FROM {self.schema}.passwords
                WHERE hotel_id = %s
                  AND status = 'available'
                  AND id = ANY(%s)
                ORDER BY id
                FOR UPDATE
                """,
                (self.hotel_id, ids),
            ).fetchall()
            if len(rows) != len(ids):
                raise PasswordsUnavailable(
                    "Один или несколько паролей уже недоступны"
                )
            connection.execute(
                f"""
                UPDATE {self.schema}.passwords
                SET status = 'used',
                    used_at = now(),
                    reserved_at = NULL,
                    batch_id = NULL
                WHERE hotel_id = %s AND id = ANY(%s)
                """,
                (self.hotel_id, ids),
            )
        return [row["password"] for row in rows]

    def reserve(
        self, count: int, ru_count: int = 0, en_count: int = 0
    ) -> Reservation:
        if count <= 0:
            return Reservation(batch_id="", passwords=())

        batch_id = uuid.uuid4()
        with self._connection() as connection:
            self._release_stale_in_connection(
                connection, self.reservation_ttl_minutes
            )
            rows = connection.execute(
                f"""
                SELECT id, password
                FROM {self.schema}.passwords
                WHERE hotel_id = %s AND status = 'available'
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (self.hotel_id, count),
            ).fetchall()
            if len(rows) < count:
                raise NotEnoughPasswords(needed=count, available=len(rows))

            ids = [row["id"] for row in rows]
            connection.execute(
                f"""
                UPDATE {self.schema}.passwords
                SET status = 'reserved', batch_id = %s, reserved_at = now()
                WHERE hotel_id = %s AND id = ANY(%s) AND status = 'available'
                """,
                (batch_id, self.hotel_id, ids),
            )
            connection.execute(
                f"""
                INSERT INTO {self.schema}.generations(
                    id, hotel_id, ru_count, en_count, total_count, status
                )
                VALUES (%s, %s, %s, %s, %s, 'reserved')
                """,
                (batch_id, self.hotel_id, ru_count, en_count, count),
            )
        return Reservation(
            batch_id=str(batch_id),
            passwords=tuple(row["password"] for row in rows),
        )

    def commit(self, batch_id: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {self.schema}.passwords
                SET status = 'used',
                    used_at = now(),
                    reserved_at = NULL,
                    batch_id = NULL
                WHERE hotel_id = %s
                  AND status = 'reserved'
                  AND batch_id = %s::uuid
                """,
                (self.hotel_id, batch_id),
            )
            connection.execute(
                f"""
                UPDATE {self.schema}.generations
                SET status = 'completed', completed_at = now()
                WHERE id = %s::uuid
                  AND hotel_id = %s
                  AND status = 'reserved'
                """,
                (batch_id, self.hotel_id),
            )
        return cursor.rowcount

    def release(self, batch_id: str, error: str | None = None) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                f"""
                UPDATE {self.schema}.passwords
                SET status = 'available', reserved_at = NULL, batch_id = NULL
                WHERE hotel_id = %s
                  AND status = 'reserved'
                  AND batch_id = %s::uuid
                """,
                (self.hotel_id, batch_id),
            )
            connection.execute(
                f"""
                UPDATE {self.schema}.generations
                SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s::uuid
                  AND hotel_id = %s
                  AND status = 'reserved'
                """,
                (error, batch_id, self.hotel_id),
            )
        return cursor.rowcount

    def _release_stale_in_connection(
        self, connection, max_age_minutes: int
    ) -> int:
        rows = connection.execute(
            f"""
            SELECT DISTINCT batch_id
            FROM {self.schema}.passwords
            WHERE hotel_id = %s
              AND status = 'reserved'
              AND reserved_at < now() - (%s * interval '1 minute')
              AND batch_id IS NOT NULL
            """,
            (self.hotel_id, max_age_minutes),
        ).fetchall()
        batch_ids = [row["batch_id"] for row in rows]
        if not batch_ids:
            return 0
        cursor = connection.execute(
            f"""
            UPDATE {self.schema}.passwords
            SET status = 'available', reserved_at = NULL, batch_id = NULL
            WHERE hotel_id = %s AND batch_id = ANY(%s)
            """,
            (self.hotel_id, batch_ids),
        )
        connection.execute(
            f"""
            UPDATE {self.schema}.generations
            SET status = 'failed',
                error = 'Reservation lease expired',
                completed_at = now()
            WHERE hotel_id = %s AND id = ANY(%s) AND status = 'reserved'
            """,
            (self.hotel_id, batch_ids),
        )
        return cursor.rowcount

    def release_stale_reservations(self, max_age_minutes: int | None = None) -> int:
        max_age = max_age_minutes or self.reservation_ttl_minutes
        with self._connection() as connection:
            return self._release_stale_in_connection(connection, max_age)


def create_password_store(
    *,
    database_url: str,
    database_path: str,
    hotel_id: str,
    hotel_name: str,
    reservation_ttl_minutes: int,
) -> Store:
    if database_url:
        return PostgresPasswordStore(
            database_url=database_url,
            hotel_id=hotel_id,
            hotel_name=hotel_name,
            reservation_ttl_minutes=reservation_ttl_minutes,
        )
    return PasswordStore(
        database_path=database_path,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
        reservation_ttl_minutes=reservation_ttl_minutes,
    )

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from api.storage import PostgresPasswordStore


def read_source(database: Path) -> list[dict]:
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database}")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(passwords)").fetchall()
        }
        if not columns:
            raise RuntimeError("The SQLite database has no passwords table")
        rows = connection.execute(
            """
            SELECT password, status, created_at, reserved_at, used_at
            FROM passwords
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def migrate(
    *,
    source: Path,
    database_url: str,
    hotel_id: str,
    hotel_name: str,
    apply: bool,
) -> dict[str, int | str]:
    rows = read_source(source)
    source_counts = {"available": 0, "reserved": 0, "used": 0}
    for row in rows:
        source_counts[row["status"]] += 1

    if not apply:
        return {
            "mode": "dry-run",
            "source_total": len(rows),
            **{f"source_{key}": value for key, value in source_counts.items()},
        }

    target = PostgresPasswordStore(
        database_url=database_url,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
    )
    target.initialize()
    added = 0
    with target._connection() as connection:
        for row in rows:
            # Interrupted local reservations are made available again online.
            status = "available" if row["status"] == "reserved" else row["status"]
            cursor = connection.execute(
                f"""
                INSERT INTO {target.schema}.passwords(
                    hotel_id, password, status, created_at, used_at
                )
                VALUES (%s, %s, %s, COALESCE(%s::timestamptz, now()), %s::timestamptz)
                ON CONFLICT(hotel_id, password) DO NOTHING
                """,
                (
                    hotel_id,
                    row["password"],
                    status,
                    row["created_at"],
                    row["used_at"],
                ),
            )
            added += cursor.rowcount

    stats = target.stats()
    return {
        "mode": "applied",
        "source_total": len(rows),
        "added": added,
        "target_total": stats["total"],
        "target_available": stats["available"],
        "target_reserved": stats["reserved"],
        "target_used": stats["used"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Wi-Fi passwords from local SQLite to PostgreSQL."
    )
    parser.add_argument("--source", type=Path, default=Path("data/vouchers.db"))
    parser.add_argument("--hotel-id", default=os.getenv("HOTEL_ID", "artstudio-nevsky"))
    parser.add_argument(
        "--hotel-name",
        default=os.getenv("HOTEL_NAME", "ARTSTUDIO NEVSKY"),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to PostgreSQL. Without this flag only source counts are shown.",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "")
    if args.apply and not database_url:
        raise RuntimeError("Set DATABASE_URL in the environment; it is never read from CLI")

    result = migrate(
        source=args.source,
        database_url=database_url,
        hotel_id=args.hotel_id,
        hotel_name=args.hotel_name,
        apply=args.apply,
    )
    print(result)


if __name__ == "__main__":
    main()

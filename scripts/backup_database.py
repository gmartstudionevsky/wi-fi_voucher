from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def backup_database(database: Path, output_dir: Path) -> Path:
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"vouchers-{timestamp}.db"

    with sqlite3.connect(database) as source:
        with sqlite3.connect(destination) as backup:
            source.backup(backup)
            integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]

    if integrity != "ok":
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity check failed: {integrity}")

    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a consistent SQLite backup of the Wi-Fi voucher database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/vouchers.db"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backups"),
    )
    args = parser.parse_args()
    destination = backup_database(args.database, args.output_dir)
    print(destination)


if __name__ == "__main__":
    main()

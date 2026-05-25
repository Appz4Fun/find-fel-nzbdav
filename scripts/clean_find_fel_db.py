#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_DB = Path("data/find-fel.db")


@dataclass(frozen=True)
class CleanSummary:
    db_path: Path
    backup_path: Path | None
    cleared: int
    remaining_unknown_or_error: int
    pending: int
    total: int
    integrity_check: str
    dry_run: bool = False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: no database at {db_path}")
        return 2

    summary = clean_db(
        db_path,
        backup=not args.no_backup,
        dry_run=args.dry_run,
    )
    print_summary(summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reset find-fel-nzbdav unknown/error scan outcomes back to pending "
            "so the default scanner can retry them."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped .bak copy before modifying the DB.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be cleared without writing changes.",
    )
    return parser


def clean_db(
    db_path: str | Path,
    *,
    backup: bool = True,
    dry_run: bool = False,
    now=None,
) -> CleanSummary:
    path = Path(db_path)
    timestamp = now or datetime_timestamp
    backup_path = backup_db(path, now=timestamp) if backup and not dry_run else None

    with sqlite3.connect(path) as conn:
        cleared = count_unknown_or_error(conn)
        if not dry_run:
            conn.execute(
                r"""
                UPDATE titles
                SET date_checked = NULL,
                    verdict = NULL,
                    reason = NULL
                WHERE verdict = 'unknown'
                   OR reason LIKE 'error\_%' ESCAPE '\'
                """
            )
            conn.commit()

        remaining = count_unknown_or_error(conn)
        pending = conn.execute(
            "SELECT COUNT(*) FROM titles WHERE date_checked IS NULL"
        ).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    return CleanSummary(
        db_path=path,
        backup_path=backup_path,
        cleared=cleared,
        remaining_unknown_or_error=remaining,
        pending=pending,
        total=total,
        integrity_check=integrity,
        dry_run=dry_run,
    )


def backup_db(db_path: Path, *, now=None) -> Path:
    timestamp = now or datetime_timestamp
    backup_path = db_path.with_name(
        f"{db_path.name}.before-clean-errors-{timestamp()}.bak"
    )
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def count_unknown_or_error(conn: sqlite3.Connection) -> int:
    return conn.execute(
        r"""
        SELECT COUNT(*) FROM titles
        WHERE verdict = 'unknown'
           OR reason LIKE 'error\_%' ESCAPE '\'
        """
    ).fetchone()[0]


def datetime_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def print_summary(summary: CleanSummary) -> None:
    print(f"db={summary.db_path}")
    if summary.backup_path is not None:
        print(f"backup={summary.backup_path}")
    elif summary.dry_run:
        print("backup=skipped_dry_run")
    else:
        print("backup=disabled")
    if summary.dry_run:
        print(f"would_clear={summary.cleared}")
    else:
        print(f"cleared={summary.cleared}")
    print(f"remaining_unknown_or_error={summary.remaining_unknown_or_error}")
    print(f"pending={summary.pending}")
    print(f"total={summary.total}")
    print(f"integrity_check={summary.integrity_check}")


if __name__ == "__main__":
    raise SystemExit(main())

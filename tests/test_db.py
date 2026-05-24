from __future__ import annotations

from pathlib import Path

import db


def test_connect_creates_schema_and_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "test.db"

    conn = db.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='titles'"
        )
        assert cursor.fetchone() == ("titles",)
    finally:
        conn.close()

    # Second connect on the same file should not raise.
    conn = db.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(titles)")}
        assert columns == {"title", "date_checked", "verdict", "reason"}
    finally:
        conn.close()


def test_connect_sets_wal_journal_mode(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = db.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()

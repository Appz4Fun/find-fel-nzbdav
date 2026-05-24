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


def test_insert_title_creates_row_with_null_fields(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    try:
        db.insert_title(conn, "Creepshow")
        row = conn.execute(
            "SELECT title, date_checked, verdict, reason FROM titles"
        ).fetchone()
        assert row == ("Creepshow", None, None, None)
    finally:
        conn.close()


def test_insert_title_is_idempotent_and_does_not_overwrite(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    try:
        db.insert_title(conn, "Creepshow")
        conn.execute(
            "UPDATE titles SET date_checked=?, verdict=?, reason=? WHERE title=?",
            ("2026-05-23T00:00:00", "fel", "profile_7_fel", "Creepshow"),
        )
        conn.commit()

        # Second insert must not clear the existing fields.
        db.insert_title(conn, "Creepshow")
        row = conn.execute(
            "SELECT date_checked, verdict, reason FROM titles WHERE title=?",
            ("Creepshow",),
        ).fetchone()
        assert row == ("2026-05-23T00:00:00", "fel", "profile_7_fel")
    finally:
        conn.close()

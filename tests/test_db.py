from __future__ import annotations

import datetime
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


def test_upsert_result_inserts_when_row_missing(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    when = datetime.datetime(2026, 5, 23, 12, 34, 56)
    try:
        db.upsert_result(conn, "Creepshow", "fel", "profile_7_fel", when)
        row = conn.execute(
            "SELECT title, date_checked, verdict, reason FROM titles"
        ).fetchone()
        assert row == ("Creepshow", "2026-05-23T12:34:56", "fel", "profile_7_fel")
    finally:
        conn.close()


def test_upsert_result_updates_existing_row(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    try:
        db.insert_title(conn, "Creepshow")
        first = datetime.datetime(2026, 5, 23, 10, 0, 0)
        db.upsert_result(conn, "Creepshow", "unknown", "error_URLError", first)
        second = datetime.datetime(2026, 5, 23, 11, 0, 0)
        db.upsert_result(conn, "Creepshow", "fel", "profile_7_fel", second)
        row = conn.execute(
            "SELECT date_checked, verdict, reason FROM titles WHERE title=?",
            ("Creepshow",),
        ).fetchone()
        assert row == ("2026-05-23T11:00:00", "fel", "profile_7_fel")
        # Still exactly one row.
        count = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_pending_titles_yields_unscanned_then_errors_alphabetical(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    when = datetime.datetime(2026, 5, 23, 0, 0, 0)
    try:
        # Un-scanned titles (NULL date_checked) inserted out of order:
        db.insert_title(conn, "Banshees of Inisherin")
        db.insert_title(conn, "Akira")
        db.insert_title(conn, "Creepshow")

        # Already scanned successfully — must be skipped.
        db.upsert_result(conn, "Done Movie", "fel", "profile_7_fel", when)
        db.upsert_result(conn, "Another Done", "not_fel", "no_dv_4k_candidates", when)
        db.upsert_result(conn, "Third Done", "not_fel", "no_confirmed_fel", when)

        # Errored — must come AFTER all NULLs, alphabetical within group.
        db.upsert_result(conn, "Zulu", "unknown", "error_URLError", when)
        db.upsert_result(conn, "Aliens", "unknown", "error_TimeoutError", when)

        assert list(db.pending_titles(conn)) == [
            "Akira",
            "Banshees of Inisherin",
            "Creepshow",
            "Aliens",
            "Zulu",
        ]
    finally:
        conn.close()


def test_pending_titles_returns_empty_when_db_has_no_rows(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    try:
        assert list(db.pending_titles(conn)) == []
    finally:
        conn.close()

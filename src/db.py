from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS titles (
        title        TEXT PRIMARY KEY,
        date_checked TEXT,
        verdict      TEXT,
        reason       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_titles_reason ON titles(reason)",
)


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


def insert_title(conn: sqlite3.Connection, title: str) -> None:
    conn.execute("INSERT OR IGNORE INTO titles(title) VALUES (?)", (title,))
    conn.commit()


def upsert_result(
    conn: sqlite3.Connection,
    title: str,
    verdict: str,
    reason: str,
    when: datetime.datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO titles(title, date_checked, verdict, reason)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(title) DO UPDATE SET
            date_checked = excluded.date_checked,
            verdict      = excluded.verdict,
            reason       = excluded.reason
        """,
        (title, when.isoformat(timespec="seconds"), verdict, reason),
    )
    conn.commit()

from __future__ import annotations

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

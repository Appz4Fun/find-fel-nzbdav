from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "clean_find_fel_db.py"
    spec = importlib.util.spec_from_file_location("clean_find_fel_db", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE titles (
            title TEXT PRIMARY KEY,
            date_checked TEXT,
            verdict TEXT,
            reason TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO titles(title, date_checked, verdict, reason)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("Hydra Fail", "2026-05-24T10:00:00", "unknown", "error_Hydra_900"),
            ("Unknown Probe", "2026-05-24T10:00:00", "unknown", "no_confirmed_fel"),
            ("FEL", "2026-05-24T10:00:00", "fel", "profile_7_fel"),
            ("Not FEL", "2026-05-24T10:00:00", "not_fel", "no_dv_4k_candidates"),
        ],
    )
    conn.commit()
    return conn


def test_clean_db_resets_unknown_and_error_rows_to_pending(tmp_path: Path):
    module = _load_script_module()
    db_path = tmp_path / "find-fel.db"
    conn = _create_db(db_path)
    conn.close()

    summary = module.clean_db(db_path, backup=False)

    assert summary.cleared == 2
    assert summary.remaining_unknown_or_error == 0
    assert summary.pending == 2
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT title, date_checked, verdict, reason FROM titles ORDER BY title"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("FEL", "2026-05-24T10:00:00", "fel", "profile_7_fel"),
        ("Hydra Fail", None, None, None),
        ("Not FEL", "2026-05-24T10:00:00", "not_fel", "no_dv_4k_candidates"),
        ("Unknown Probe", None, None, None),
    ]


def test_clean_db_writes_backup_by_default(tmp_path: Path):
    module = _load_script_module()
    db_path = tmp_path / "find-fel.db"
    conn = _create_db(db_path)
    conn.close()

    summary = module.clean_db(db_path, now=lambda: "20260524-120000")

    assert summary.backup_path == tmp_path / "find-fel.db.before-clean-errors-20260524-120000.bak"
    assert summary.backup_path.exists()

    backup = sqlite3.connect(summary.backup_path)
    try:
        backup_count = backup.execute(
            "SELECT COUNT(*) FROM titles WHERE verdict='unknown'"
        ).fetchone()[0]
    finally:
        backup.close()
    assert backup_count == 2


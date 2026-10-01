"""
Module 6 - SQLite event logging.

One table, one job: record every FSM decision so the API/dashboard can show
history. sqlite3 is in the Python standard library - no extra dependency,
and the whole DB is a single file (database/traffic_logs.db).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

DB_PATH = Path(__file__).parent / "traffic_logs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lane_id         TEXT    NOT NULL,
    vehicle_count   INTEGER NOT NULL,
    green_duration  INTEGER NOT NULL,
    is_emergency    INTEGER NOT NULL CHECK (is_emergency IN (0, 1)),
    timestamp       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON traffic_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_lane ON traffic_logs(lane_id);
"""


@contextmanager
def get_connection(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """
    Context manager so every caller gets 'open -> use -> commit/rollback -> close'
    for free, instead of repeating try/finally everywhere.

    db_path defaults to None and is resolved to the MODULE-LEVEL `DB_PATH`
    INSIDE the function body (not as a bind-time default parameter value).
    This matters: `db_path: Path = DB_PATH` as a parameter default captures
    DB_PATH's value once, at function-definition time - reassigning
    `database.db.DB_PATH` later (e.g. tests monkeypatching it, or a script
    pointing it elsewhere) would silently NOT affect already-defined
    functions. Resolving it at call time makes monkeypatching/reconfiguring
    DB_PATH actually work.
    """
    path = db_path if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["lane_id"]
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)


def log_cycle_result(result: Dict[str, Any], db_path: Optional[Path] = None) -> int:
    """
    Insert one FSMController.run_cycle() result. Returns the new row's id.
    Expected keys: lane, vehicle_count, green_duration, was_emergency.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO traffic_logs (lane_id, vehicle_count, green_duration, is_emergency)
            VALUES (?, ?, ?, ?)
            """,
            (
                result["lane"],
                int(result.get("vehicle_count", 0)),
                int(result["green_duration"]),
                1 if result.get("was_emergency") else 0,
            ),
        )
        return cur.lastrowid


def get_logs(
    limit: int = 50,
    offset: int = 0,
    lane_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Most-recent-first, optionally filtered by lane. Used by /logs and the dashboard."""
    query = "SELECT * FROM traffic_logs"
    params: List[Any] = []
    if lane_id is not None:
        query += " WHERE lane_id = ?"
        params.append(lane_id)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def count_logs(lane_id: Optional[str] = None, db_path: Optional[Path] = None) -> int:
    query = "SELECT COUNT(*) FROM traffic_logs"
    params: List[Any] = []
    if lane_id is not None:
        query += " WHERE lane_id = ?"
        params.append(lane_id)
    with get_connection(db_path) as conn:
        return conn.execute(query, params).fetchone()[0]


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")

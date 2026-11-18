"""SQLite storage for fetch state and raw responses.

Everything needed to resume a scrape lives here, so the process can be stopped
at any moment and restarted with the same command.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pipeline.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE INDEX IF NOT EXISTS jobs_kind_status ON jobs(kind, status);

CREATE TABLE IF NOT EXISTS raw_responses (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    fetched_at  REAL NOT NULL,
    status_code INTEGER NOT NULL,
    body_gz     BLOB NOT NULL,
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS apps (
    appid               INTEGER PRIMARY KEY,
    name                TEXT,
    last_modified       INTEGER,
    price_change_number INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # explicit transactions only
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


class transaction:
    """`with transaction(conn):` → BEGIN IMMEDIATE … COMMIT, ROLLBACK on error."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")


# --- meta ---------------------------------------------------------------------


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# --- raw responses ------------------------------------------------------------


def put_raw(conn: sqlite3.Connection, kind: str, key: str, status_code: int, body: Any) -> None:
    blob = gzip.compress(json.dumps(body, separators=(",", ":")).encode())
    conn.execute(
        "INSERT INTO raw_responses(kind, key, fetched_at, status_code, body_gz) "
        "VALUES(?, ?, ?, ?, ?) "
        "ON CONFLICT(kind, key) DO UPDATE SET fetched_at = excluded.fetched_at, "
        "status_code = excluded.status_code, body_gz = excluded.body_gz",
        (kind, key, time.time(), status_code, blob),
    )


def get_raw(conn: sqlite3.Connection, kind: str, key: str) -> Any | None:
    row = conn.execute(
        "SELECT body_gz FROM raw_responses WHERE kind = ? AND key = ?", (kind, key)
    ).fetchone()
    return json.loads(gzip.decompress(row["body_gz"])) if row else None


def iter_raw(conn: sqlite3.Connection, kind: str) -> Iterable[tuple[str, Any]]:
    for row in conn.execute(
        "SELECT key, body_gz FROM raw_responses WHERE kind = ? ORDER BY rowid", (kind,)
    ):
        yield row["key"], json.loads(gzip.decompress(row["body_gz"]))

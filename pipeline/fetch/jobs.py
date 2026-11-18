"""Persistent job queue on top of the `jobs` table.

A job is identified by (kind, key), e.g. ("items", "646570"). Results are always
written in the same transaction that marks the job done, so an interrupted run
either fully recorded a job or left it pending — never half of each.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Sequence

from pipeline.db import transaction

PENDING, DONE, FAILED = "pending", "done", "failed"


def enqueue(conn: sqlite3.Connection, kind: str, keys: Iterable[str]) -> int:
    """Add jobs that don't exist yet. Existing jobs (any status) are left alone."""
    now = time.time()
    with transaction(conn):
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO jobs(kind, key, status, updated_at) VALUES(?, ?, ?, ?)",
            ((kind, str(k), PENDING, now) for k in keys),
        )
        return conn.total_changes - before


def claim(conn: sqlite3.Connection, kind: str, n: int) -> list[str]:
    """Next `n` pending keys, in insertion order. Single-process, so no locking."""
    rows = conn.execute(
        "SELECT key FROM jobs WHERE kind = ? AND status = ? ORDER BY rowid LIMIT ?",
        (kind, PENDING, n),
    ).fetchall()
    return [r["key"] for r in rows]


def mark_done(conn: sqlite3.Connection, kind: str, keys: Sequence[str]) -> None:
    """Call inside the caller's transaction, together with writing results."""
    now = time.time()
    conn.executemany(
        "UPDATE jobs SET status = ?, last_error = NULL, updated_at = ? WHERE kind = ? AND key = ?",
        ((DONE, now, kind, k) for k in keys),
    )


def mark_failed_attempt(
    conn: sqlite3.Connection, kind: str, keys: Sequence[str], error: str, max_attempts: int
) -> None:
    """Count a failed attempt; the job becomes `failed` once it hits `max_attempts`."""
    now = time.time()
    with transaction(conn):
        conn.executemany(
            "UPDATE jobs SET attempts = attempts + 1, last_error = ?, updated_at = ?, "
            "status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE status END "
            "WHERE kind = ? AND key = ?",
            ((error[:500], now, max_attempts, kind, k) for k in keys),
        )


def retry_failed(conn: sqlite3.Connection, kind: str) -> int:
    with transaction(conn):
        cur = conn.execute(
            "UPDATE jobs SET status = ?, attempts = 0 WHERE kind = ? AND status = ?",
            (PENDING, kind, FAILED),
        )
        return cur.rowcount


def requeue_stale(conn: sqlite3.Connection, kind: str, older_than_s: float) -> int:
    """Re-queue done jobs last updated more than `older_than_s` ago (for refreshes)."""
    cutoff = time.time() - older_than_s
    with transaction(conn):
        cur = conn.execute(
            "UPDATE jobs SET status = ?, attempts = 0 "
            "WHERE kind = ? AND status = ? AND updated_at < ?",
            (PENDING, kind, DONE, cutoff),
        )
        return cur.rowcount


def counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for row in conn.execute("SELECT kind, status, COUNT(*) AS n FROM jobs GROUP BY kind, status"):
        out.setdefault(row["kind"], {PENDING: 0, DONE: 0, FAILED: 0})[row["status"]] = row["n"]
    return out


def pending_count(conn: sqlite3.Connection, kind: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE kind = ? AND status = ?", (kind, PENDING)
    ).fetchone()[0]

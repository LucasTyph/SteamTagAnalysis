"""One-request-per-game stages for the timeline set.

- `histogram`: monthly positive/negative review counts over the game's whole life
  (store.steampowered.com/appreviewhistogram)
- `news`: developer announcements (ISteamNews/GetNewsForApp), used to explain
  turning points in the timelines

Jobs, pausing and resume work exactly like the GetItems stages.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.config import FETCH
from pipeline.db import iter_raw, put_raw, transaction
from pipeline.fetch import jobs
from pipeline.fetch.client import FetchError, SteamClient, Stopped
from pipeline.fetch.items import KIND as ITEMS_KIND

HISTOGRAM = "histogram"
NEWS = "news"


@dataclass(frozen=True)
class Stage:
    kind: str
    url: Callable[[int], str]
    params: dict[str, str]


STAGES = {
    HISTOGRAM: Stage(
        HISTOGRAM,
        lambda appid: f"https://store.steampowered.com/appreviewhistogram/{appid}",
        {"l": "all", "review_score_preference": "0"},
    ),
    NEWS: Stage(
        NEWS,
        lambda appid: "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/",
        {"count": "500", "maxlength": "300", "feeds": "steam_community_announcements"},
    ),
}


def top_games(conn: sqlite3.Connection, n: int) -> list[str]:
    """App IDs of the `n` games with the most reviews (from the cached GetItems data)."""
    counts: list[tuple[int, str]] = []
    for key, item in iter_raw(conn, ITEMS_KIND):
        if item.get("missing") or item.get("type") != 0:
            continue
        reviews = (item.get("reviews") or {}).get("summary_filtered") or {}
        counts.append((int(reviews.get("review_count") or 0), key))
    counts.sort(reverse=True)
    return [key for _, key in counts[:n]]


def enqueue_top(conn: sqlite3.Connection, n: int) -> dict[str, int]:
    keys = top_games(conn, n)
    return {kind: jobs.enqueue(conn, kind, keys) for kind in STAGES}


def run(
    conn: sqlite3.Connection,
    client: SteamClient,
    kind: str,
    on_item: Callable[[int], None] | None = None,
) -> str | None:
    """Process pending jobs of `kind`. Returns a stop reason, or None when done."""
    stage = STAGES[kind]
    while True:
        if client.control.should_stop:
            return client.control.stop_reason
        keys = jobs.claim(conn, kind, 1)
        if not keys:
            return None
        key = keys[0]
        params = dict(stage.params)
        if kind == NEWS:
            params["appid"] = key
        try:
            status, body = client.get_json(stage.url(int(key)), params)
            if not isinstance(body, dict):
                raise FetchError(f"Unexpected {kind} body: {str(body)[:200]}")
        except Stopped as e:
            return str(e)
        except FetchError as e:
            jobs.mark_failed_attempt(conn, kind, keys, str(e), FETCH.max_job_attempts)
            if on_item:
                on_item(0)
            continue
        with transaction(conn):
            put_raw(conn, kind, key, status, body)
            jobs.mark_done(conn, kind, keys)
        if on_item:
            on_item(1)

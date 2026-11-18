"""GetItems stages (IStoreBrowseService/GetItems, many app IDs per request).

- `items`: tags (with weights), review summary, release date and price — every game
- `basic`: developers, publishers, franchises — games with enough reviews only

Jobs are per app, so batch size can change between runs without losing state.
Each app's slice of the response is stored as its own raw row.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence

from pipeline.config import FETCH
from pipeline.db import put_raw, transaction
from pipeline.fetch import jobs
from pipeline.fetch.client import FetchError, SteamClient, Stopped

KIND = "items"
BASIC_KIND = "basic"
URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"


DATA_REQUESTS = {
    KIND: {
        "include_tag_count": 20,
        "include_reviews": True,
        "include_release": True,
        "include_basic_info": False,
    },
    BASIC_KIND: {"include_basic_info": True},
}


def build_params(appids: Sequence[int], kind: str = KIND) -> dict[str, str]:
    payload = {
        "ids": [{"appid": a} for a in appids],
        "context": {"language": "english", "country_code": "US", "steam_realm": 1},
        "data_request": DATA_REQUESTS[kind],
    }
    return {"input_json": json.dumps(payload, separators=(",", ":"))}


def fetch_batch(
    client: SteamClient, appids: Sequence[int], kind: str = KIND
) -> tuple[int, dict[int, dict]]:
    """One GetItems request → {appid: store_item}. Apps Steam didn't return are absent."""
    status, body = client.get_json(URL, build_params(appids, kind))
    if not isinstance(body, dict) or "response" not in body:
        raise FetchError(f"Unexpected GetItems body: {str(body)[:200]}")
    items = body["response"].get("store_items", [])
    by_id: dict[int, dict] = {}
    for item in items:
        appid = item.get("appid") or item.get("id")
        if appid is not None:
            by_id[int(appid)] = item
    return status, by_id


def run(
    conn: sqlite3.Connection,
    client: SteamClient,
    batch_size: int = FETCH.items_batch_size,
    on_batch: Callable[[int], None] | None = None,
    kind: str = KIND,
) -> str | None:
    """Process pending jobs of `kind`. Returns a stop reason, or None when the queue is empty."""
    while True:
        if client.control.should_stop:
            return client.control.stop_reason
        keys = jobs.claim(conn, kind, batch_size)
        if not keys:
            return None
        appids = [int(k) for k in keys]
        try:
            status, by_id = fetch_batch(client, appids, kind)
        except Stopped as e:
            return str(e)
        except FetchError as e:
            jobs.mark_failed_attempt(conn, kind, keys, str(e), FETCH.max_job_attempts)
            if on_batch:
                on_batch(0)
            continue

        with transaction(conn):
            for appid in appids:
                # Store a marker for apps Steam didn't return, so they aren't retried forever
                # and the build step can tell "missing" from "never fetched".
                put_raw(conn, kind, str(appid), status, by_id.get(appid, {"missing": True}))
            jobs.mark_done(conn, kind, keys)
        if on_batch:
            on_batch(len(keys))


def enqueue_basic(conn: sqlite3.Connection, min_reviews: int) -> int:
    """Queue `basic` jobs for every fetched game with at least `min_reviews` reviews."""
    from pipeline.db import iter_raw

    keys = []
    for key, item in iter_raw(conn, KIND):
        reviews = (item.get("reviews") or {}).get("summary_filtered") or {}
        if int(reviews.get("review_count") or 0) >= min_reviews:
            keys.append(key)
    return jobs.enqueue(conn, BASIC_KIND, keys)

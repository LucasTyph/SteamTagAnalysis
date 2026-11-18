"""Stage 2: tags (with weights), review summary, release date and price per game.

Uses IStoreBrowseService/GetItems, which accepts many app IDs per request.
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
URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"


def build_params(appids: Sequence[int]) -> dict[str, str]:
    payload = {
        "ids": [{"appid": a} for a in appids],
        "context": {"language": "english", "country_code": "US", "steam_realm": 1},
        "data_request": {
            "include_tag_count": 20,
            "include_reviews": True,
            "include_release": True,
            "include_basic_info": False,
        },
    }
    return {"input_json": json.dumps(payload, separators=(",", ":"))}


def fetch_batch(client: SteamClient, appids: Sequence[int]) -> tuple[int, dict[int, dict]]:
    """One GetItems request → {appid: store_item}. Apps Steam didn't return are absent."""
    status, body = client.get_json(URL, build_params(appids))
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
) -> str | None:
    """Process pending item jobs. Returns a stop reason, or None when the queue is empty."""
    while True:
        if client.control.should_stop:
            return client.control.stop_reason
        keys = jobs.claim(conn, KIND, batch_size)
        if not keys:
            return None
        appids = [int(k) for k in keys]
        try:
            status, by_id = fetch_batch(client, appids)
        except Stopped as e:
            return str(e)
        except FetchError as e:
            jobs.mark_failed_attempt(conn, KIND, keys, str(e), FETCH.max_job_attempts)
            if on_batch:
                on_batch(0)
            continue

        with transaction(conn):
            for appid in appids:
                # Store a marker for apps Steam didn't return, so they aren't retried forever
                # and the build step can tell "missing" from "never fetched".
                put_raw(conn, KIND, str(appid), status, by_id.get(appid, {"missing": True}))
            jobs.mark_done(conn, KIND, keys)
        if on_batch:
            on_batch(len(keys))

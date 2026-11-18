"""Stage 1: list every game on Steam (IStoreService/GetAppList, needs an API key).

Resume state is the paging cursor in `meta`, committed together with each page.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from pipeline.db import get_meta, set_meta, transaction
from pipeline.fetch import jobs
from pipeline.fetch.client import SteamClient, Stopped

URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
PAGE_SIZE = 50_000
CURSOR_KEY = "applist.cursor"
COMPLETE_KEY = "applist.completed_at"


def is_complete(conn: sqlite3.Connection) -> bool:
    return get_meta(conn, COMPLETE_KEY) is not None


def reset(conn: sqlite3.Connection) -> None:
    """Start a fresh listing (existing apps are kept and updated)."""
    with transaction(conn):
        set_meta(conn, CURSOR_KEY, None)
        set_meta(conn, COMPLETE_KEY, None)


def run(
    conn: sqlite3.Connection,
    client: SteamClient,
    api_key: str,
    on_page: Callable[[int, int], None] | None = None,
) -> str | None:
    """Fetch remaining pages. Returns a stop reason, or None when the list is complete."""
    while not is_complete(conn):
        cursor = int(get_meta(conn, CURSOR_KEY) or 0)
        params = {
            "key": api_key,
            "include_games": "true",
            "include_dlc": "false",
            "include_software": "false",
            "include_videos": "false",
            "include_hardware": "false",
            "max_results": PAGE_SIZE,
            "last_appid": cursor,
        }
        try:
            _, body = client.get_json(URL, params)
        except Stopped as e:
            return str(e)

        resp = body.get("response", {}) if isinstance(body, dict) else {}
        apps = resp.get("apps", [])
        with transaction(conn):
            conn.executemany(
                "INSERT INTO apps(appid, name, last_modified, price_change_number) "
                "VALUES(:appid, :name, :last_modified, :price_change_number) "
                "ON CONFLICT(appid) DO UPDATE SET name = excluded.name, "
                "last_modified = excluded.last_modified, "
                "price_change_number = excluded.price_change_number",
                (
                    {
                        "appid": a["appid"],
                        "name": a.get("name"),
                        "last_modified": a.get("last_modified"),
                        "price_change_number": a.get("price_change_number"),
                    }
                    for a in apps
                ),
            )
            if resp.get("have_more_results") and resp.get("last_appid"):
                set_meta(conn, CURSOR_KEY, str(resp["last_appid"]))
            else:
                set_meta(conn, CURSOR_KEY, None)
                set_meta(conn, COMPLETE_KEY, str(time.time()))

        if on_page:
            total = conn.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
            on_page(len(apps), total)

        if client.control.should_stop and not is_complete(conn):
            return client.control.stop_reason
    return None


def enqueue_all(conn: sqlite3.Connection, kind: str) -> int:
    """Queue a job of `kind` for every known app. Returns how many were new."""
    keys = (str(r[0]) for r in conn.execute("SELECT appid FROM apps ORDER BY appid"))
    return jobs.enqueue(conn, kind, keys)

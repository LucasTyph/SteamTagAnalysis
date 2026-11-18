"""Stage 3: tag ID → name mapping (one request)."""

from __future__ import annotations

import sqlite3

from pipeline.db import get_raw, put_raw, transaction
from pipeline.fetch.client import SteamClient

KIND = "taglist"
URL = "https://api.steampowered.com/IStoreService/GetTagList/v1/"


def run(conn: sqlite3.Connection, client: SteamClient, refresh: bool = False) -> int:
    """Fetch the tag list unless already cached. Returns the number of tags."""
    if not refresh:
        cached = get_raw(conn, KIND, "english")
        if cached is not None:
            return len(cached.get("response", {}).get("tags", []))
    status, body = client.get_json(URL, {"language": "english"})
    with transaction(conn):
        put_raw(conn, KIND, "english", status, body)
    return len(body.get("response", {}).get("tags", []))

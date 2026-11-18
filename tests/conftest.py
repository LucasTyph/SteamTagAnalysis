from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import parse_qs

import httpx
import pytest

from pipeline import db
from pipeline.config import FETCH, HostLimit
from pipeline.fetch.client import SteamClient
from pipeline.fetch.control import RunControl

# No waiting in tests: zero rate limit, zero backoff.
FAST = replace(
    FETCH,
    host_limits={},
    default_limit=HostLimit(min_interval=0, jitter=0),
    backoff_base=0,
    max_retries=2,
)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.sqlite")
    yield c
    c.close()


def make_client(handler, control: RunControl | None = None) -> SteamClient:
    return SteamClient(control or RunControl(), FAST, transport=httpx.MockTransport(handler))


def getitems_handler(calls: list[list[int]], drop: set[int] = frozenset()):
    """Fake GetItems: echoes each requested appid back as a store item."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(parse_qs(request.url.query.decode())["input_json"][0])
        ids = [i["appid"] for i in payload["ids"]]
        calls.append(ids)
        items = [
            {"appid": a, "id": a, "success": 1, "tags": [{"tagid": 1, "weight": 10}]}
            for a in ids
            if a not in drop
        ]
        return httpx.Response(200, json={"response": {"store_items": items}})

    return handler

import httpx
import pytest
from conftest import getitems_handler, make_client

from pipeline import db
from pipeline.fetch import applist, items, jobs
from pipeline.fetch.client import FetchError
from pipeline.fetch.control import RunControl, parse_duration


@pytest.mark.parametrize(
    "text,seconds", [("90s", 90), ("30m", 1800), ("1h30m", 5400), ("2d", 172800)]
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "30", "m30", "1x", "1h 30m"])
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_client_retries_transient_errors():
    responses = iter(
        [httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"ok": 1})]
    )
    with make_client(lambda req: next(responses)) as client:
        assert client.get_json("https://api.steampowered.com/x") == (200, {"ok": 1})
        assert client.control.requests == 3


def test_client_does_not_retry_client_errors():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(403)

    with make_client(handler) as client, pytest.raises(FetchError):
        client.get_json("https://api.steampowered.com/x")
    assert len(calls) == 1


def test_items_pause_and_resume_without_loss_or_duplicates(conn):
    jobs.enqueue(conn, items.KIND, [str(i) for i in range(1, 26)])
    calls: list[list[int]] = []
    handler = getitems_handler(calls)

    # Session 1: allowed only 2 requests, then "the PC is turned off".
    with make_client(handler, RunControl(max_requests=2)) as client:
        reason = items.run(conn, client, batch_size=10)
    assert reason is not None
    assert jobs.pending_count(conn, items.KIND) == 5

    # Session 2: resumes and finishes.
    with make_client(handler) as client:
        assert items.run(conn, client, batch_size=10) is None

    fetched = [a for batch in calls for a in batch]
    assert sorted(fetched) == list(range(1, 26))  # each app requested exactly once
    assert jobs.counts(conn)[items.KIND] == {"pending": 0, "done": 25, "failed": 0}
    assert db.get_raw(conn, items.KIND, "7")["tags"][0]["tagid"] == 1


def test_items_marks_missing_apps(conn):
    jobs.enqueue(conn, items.KIND, ["1", "2"])
    with make_client(getitems_handler([], drop={2})) as client:
        items.run(conn, client, batch_size=10)
    assert db.get_raw(conn, items.KIND, "2") == {"missing": True}
    assert jobs.pending_count(conn, items.KIND) == 0


def test_items_failures_become_failed_jobs(conn):
    jobs.enqueue(conn, items.KIND, ["1"])
    with make_client(lambda req: httpx.Response(500)) as client:
        assert items.run(conn, client, batch_size=10) is None
    assert jobs.counts(conn)[items.KIND]["failed"] == 1


def test_applist_pages_and_resumes(conn):
    pages = {
        0: {
            "apps": [{"appid": 10, "name": "A"}, {"appid": 20, "name": "B"}],
            "have_more_results": True,
            "last_appid": 20,
        },
        20: {"apps": [{"appid": 30, "name": "C"}]},
    }
    seen = []

    def handler(req):
        cursor = int(req.url.params["last_appid"])
        seen.append(cursor)
        return httpx.Response(200, json={"response": pages[cursor]})

    with make_client(handler, RunControl(max_requests=1)) as client:
        assert applist.run(conn, client, "key") is not None
    assert not applist.is_complete(conn)

    with make_client(handler) as client:
        assert applist.run(conn, client, "key") is None
    assert seen == [0, 20]
    assert applist.is_complete(conn)
    assert applist.enqueue_all(conn, items.KIND) == 3

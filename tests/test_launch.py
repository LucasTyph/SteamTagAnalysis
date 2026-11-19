from datetime import UTC, date, datetime

import httpx
from conftest import make_client

from pipeline.fetch.control import RunControl
from pipeline.tracking import launch

TODAY = date(2026, 11, 20)


def ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def histogram(start: date | None) -> dict:
    if start is None:
        return {"success": 1, "results": {"start_date": 0, "rollups": [], "rollup_type": "week"}}
    rollup = {"date": ts(start), "recommendations_up": 5, "recommendations_down": 1}
    return {
        "success": 1,
        "results": {"start_date": ts(start), "rollups": [rollup], "rollup_type": "month"},
    }


FIRST = {10: date(2013, 12, 11), 20: date(2020, 5, 1), 30: None}


def handler(fail: set[int] = frozenset()):
    def h(request: httpx.Request) -> httpx.Response:
        appid = int(request.url.path.rsplit("/", 1)[1])
        if appid in fail:
            return httpx.Response(404)
        return httpx.Response(200, json=histogram(FIRST[appid]))

    return h


def test_first_review_reads_start_date():
    assert launch.first_review(histogram(date(2013, 12, 11))) == date(2013, 12, 11)
    assert launch.first_review(histogram(None)) is None
    assert launch.first_review({}) is None


def test_backfill_records_dates_and_retries_failures(tmp_path):
    with make_client(handler(fail={20})) as client:
        stats = launch.backfill(tmp_path, [10, 20, 30], client, TODAY, log=lambda m: None)
    assert stats["fetched"] == 2 and stats["errors"] == 1 and stats["pending"] == 1
    assert launch.load(tmp_path) == {10: date(2013, 12, 11), 30: None}

    calls = []

    def counting(request):
        calls.append(request.url.path)
        return handler()(request)

    with make_client(counting) as client:
        stats = launch.backfill(tmp_path, [10, 20, 30], client, TODAY, log=lambda m: None)
    assert calls == ["/appreviewhistogram/20"]  # only the failed one is retried
    assert launch.load(tmp_path)[20] == date(2020, 5, 1) and stats["pending"] == 0


def test_backfill_cut_short_keeps_what_it_fetched(tmp_path):
    with make_client(handler(), RunControl(max_requests=2)) as client:
        stats = launch.backfill(
            tmp_path, [10, 20, 30], client, TODAY, log=lambda m: None, checkpoint=1
        )
    assert stats["fetched"] == 2 and stats["pending"] == 1
    assert set(launch.load(tmp_path)) == {10, 20}


def test_seed_skips_games_already_recorded(tmp_path):
    launch.append(tmp_path, [(10, date(2013, 12, 11), TODAY)])
    bodies = [(10, histogram(date(2014, 1, 1)), TODAY), (20, histogram(date(2020, 5, 1)), TODAY)]
    n = launch.seed_from_histograms(tmp_path, bodies)
    assert n == 1
    assert launch.load(tmp_path) == {10: date(2013, 12, 11), 20: date(2020, 5, 1)}

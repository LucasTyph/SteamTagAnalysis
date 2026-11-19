import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs

import httpx
from conftest import make_client

from pipeline.fetch.control import RunControl
from pipeline.tracking.daily import (
    apply_item,
    classify,
    histogram_due,
    recheck_due,
    run_daily,
)
from pipeline.tracking.store import COMING_SOON, RELEASED, CatalogEntry, TrackingStore

TODAY = date(2026, 11, 20)


def ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 12, tzinfo=UTC).timestamp())


def item(appid, coming_soon=False, released=None, planned=None, **extra):
    release = {}
    if coming_soon:
        release["is_coming_soon"] = True
        if planned:
            release["steam_release_date"] = ts(planned)
    elif released:
        release["steam_release_date"] = ts(released)
    return {
        "appid": appid,
        "id": appid,
        "success": 1,
        "visible": True,
        "type": 0,
        "name": f"Game {appid}",
        "release": release,
        "reviews": {"summary_filtered": {"review_count": 40, "percent_positive": 85}},
        **extra,
    }


# --- pure rules ------------------------------------------------------------------


def test_classify():
    assert classify(item(1, coming_soon=True, planned=TODAY))[:2] == (COMING_SOON, "Game 1")
    assert classify(item(1, released=TODAY)) == (RELEASED, "Game 1", TODAY)
    assert classify({**item(1), "type": 4}) is None
    assert classify({**item(1), "visible": False}) is None


def test_recheck_daily_near_planned_date_weekly_otherwise():
    near = CatalogEntry(
        1, "a", COMING_SOON, planned_release="2026-11-23", last_checked="2026-11-19"
    )
    far = CatalogEntry(2, "b", COMING_SOON, planned_release="2027-06-01", last_checked="2026-11-19")
    tba = CatalogEntry(3, "c", COMING_SOON, last_checked="2026-11-13")
    assert recheck_due(near, TODAY)
    assert not recheck_due(far, TODAY)
    assert recheck_due(tba, TODAY)  # 7 days since last check
    late = CatalogEntry(
        4, "d", COMING_SOON, planned_release="2026-11-10", last_checked="2026-11-19"
    )
    assert recheck_due(late, TODAY)  # planned date passed recently: still daily


def test_histogram_every_21_days_plus_final_fetch():
    e = CatalogEntry(1, "a", RELEASED, release_date="2026-01-01", tracked_from="2026-01-01")
    assert histogram_due(e, TODAY)  # never fetched
    e.last_histogram = (TODAY - timedelta(days=20)).isoformat()
    assert not histogram_due(e, TODAY)
    e.last_histogram = (TODAY - timedelta(days=21)).isoformat()
    assert histogram_due(e, TODAY)
    e.last_histogram = "2026-12-25"  # year ends 2027-01-01
    assert histogram_due(e, date(2027, 1, 3))  # one final fetch after the year
    e.last_histogram = "2027-01-03"
    assert not histogram_due(e, date(2027, 1, 4))


def test_apply_item_tracks_new_releases_only():
    cat = {}
    assert apply_item(cat, 1, item(1, coming_soon=True, planned=TODAY), TODAY) is None
    assert cat[1].status == COMING_SOON and cat[1].planned_release == TODAY.isoformat()
    assert apply_item(cat, 1, item(1, released=TODAY), TODAY) == "tracked"
    assert cat[1].status == RELEASED and cat[1].tracked_from == TODAY.isoformat()
    # an old game showing up in the modified list is not a new release
    assert apply_item(cat, 2, item(2, released=TODAY - timedelta(days=400)), TODAY) is None
    assert 2 not in cat
    # hidden page keeps its entry
    assert apply_item(cat, 1, {"missing": True}, TODAY) is None and 1 in cat


# --- full run --------------------------------------------------------------------


def fake_steam(released_ids: set[int], calls: dict):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        calls.setdefault("urls", []).append(url)
        if "GetAppList" in url:
            calls.setdefault("since", []).append(req.url.params["if_modified_since"])
            return httpx.Response(200, json={"response": {"apps": [{"appid": 30}]}})
        if "GetItems" in url:
            payload = json.loads(parse_qs(req.url.query.decode())["input_json"][0])
            ids = [i["appid"] for i in payload["ids"]]
            calls.setdefault("items", []).append(ids)
            items = [
                item(a, released=TODAY - timedelta(days=1))
                if a in released_ids
                else item(a, coming_soon=True, planned=TODAY + timedelta(days=200))
                for a in ids
            ]
            return httpx.Response(200, json={"response": {"store_items": items}})
        if "appreviewhistogram" in url:
            recent = [
                {
                    "date": ts(TODAY - timedelta(days=k)),
                    "recommendations_up": 3,
                    "recommendations_down": 1,
                }
                for k in range(3)
            ]
            return httpx.Response(200, json={"success": 1, "results": {"recent": recent}})
        raise AssertionError(url)

    return handler


def seed_store(tmp_path):
    store = TrackingStore(tmp_path / "tracking")
    store.save_catalog(
        {
            10: CatalogEntry(
                10,
                "Game 10",
                COMING_SOON,
                planned_release=TODAY.isoformat(),
                last_checked="2026-11-19",
            ),
            20: CatalogEntry(
                20, "Game 20", COMING_SOON, planned_release="2027-05-01", last_checked="2026-11-19"
            ),
        }
    )
    store.save_state({"applist_since": 1700000000})
    return store


def test_daily_run_discovers_tracks_snapshots_and_counts(tmp_path):
    store = seed_store(tmp_path)
    calls: dict = {}
    with make_client(fake_steam({10, 30}, calls)) as client:
        stats = run_daily(store, client, TODAY, "key", log=lambda m: None)

    cat = store.load_catalog()
    assert cat[10].tracked_from == TODAY.isoformat()  # released from coming soon
    assert cat[30].tracked_from == TODAY.isoformat()  # brand-new page, already released
    assert cat[20].status == COMING_SOON  # not due: far-off date, checked yesterday
    assert calls["since"] == ["1700000000"]
    assert calls["items"] == [[10, 30]]  # 20 not re-checked; tracked games reused
    assert stats["newly_tracked"] == 2 and stats["snapshots"] == 2 and stats["histograms"] == 2
    assert store.load_state()["applist_since"] > 1700000000

    snap = (tmp_path / "tracking/snapshots/2026-11.csv").read_text().splitlines()
    assert snap[0] == "date,appid,review_count,pct_positive" and len(snap) == 3
    daily = (tmp_path / "tracking/daily_reviews/2026-11.csv").read_text().splitlines()
    assert len(daily) == 1 + 2 * 3  # header + 2 games x 3 days

    # Same day again: idempotent, no duplicate rows, histograms not due.
    with make_client(fake_steam({10, 30}, {})) as client:
        again = run_daily(store, client, TODAY, "key", log=lambda m: None)
    assert again["histograms"] == 0
    assert len((tmp_path / "tracking/snapshots/2026-11.csv").read_text().splitlines()) == 3
    assert len((tmp_path / "tracking/runs.csv").read_text().splitlines()) == 2  # one per day


def test_daily_run_cut_short_resumes_next_day(tmp_path):
    store = seed_store(tmp_path)
    # applist + 1 GetItems + 1 histogram, then out of requests
    with make_client(fake_steam({10, 30}, {}), RunControl(max_requests=3)) as client:
        stats = run_daily(store, client, TODAY, "key", log=lambda m: None)
    assert stats["stop_reason"] and stats["histograms"] == 1
    assert stats["histograms_pending"] == 1
    tomorrow = TODAY + timedelta(days=1)
    with make_client(fake_steam({10, 30}, {})) as client:
        stats = run_daily(store, client, tomorrow, "key", log=lambda m: None)
    assert stats["histograms"] == 1  # only the one left over
    assert all(e.last_histogram for e in store.load_catalog().values() if e.tracked_from)


def test_runs_without_api_key(tmp_path):
    store = seed_store(tmp_path)
    calls: dict = {}
    with make_client(fake_steam({10}, calls)) as client:
        stats = run_daily(store, client, TODAY, None, log=lambda m: None)
    assert not any("GetAppList" in u for u in calls["urls"])
    assert stats["newly_tracked"] == 1
    assert store.load_state()["applist_since"] == 1700000000  # cursor untouched


def test_released_without_date_only_tracked_if_seen_coming_soon():
    cat = {}
    no_date = item(5)  # released, but Steam gave no release date
    assert apply_item(cat, 5, no_date, TODAY) is None and 5 not in cat
    apply_item(cat, 6, item(6, coming_soon=True), TODAY - timedelta(days=1))
    assert apply_item(cat, 6, item(6), TODAY) == "tracked"
    assert cat[6].release_date == TODAY.isoformat()


def test_released_with_future_date_is_treated_as_coming_soon():
    cat = {}
    assert apply_item(cat, 7, item(7, released=TODAY + timedelta(days=200)), TODAY) is None
    assert cat[7].status == COMING_SOON


def test_skip_if_done_only_skips_completed_days(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pipeline.cli import app

    store = seed_store(tmp_path)
    store.save_state({"applist_since": 1700000000, "last_run": TODAY.isoformat()})
    ran = []
    monkeypatch.setattr(
        "pipeline.tracking.cli.run_daily",
        lambda *a, **k: ran.append(a[2]) or {"duration_s": 0, "requests": 0, "stop_reason": ""},
    )
    args = ["track", "daily", "--dir", str(tmp_path / "tracking"), "--skip-if-done"]
    runner = CliRunner()
    result = runner.invoke(app, [*args, "--today", TODAY.isoformat()])
    assert result.exit_code == 0 and "already completed" in result.output and ran == []
    # A day whose run hasn't completed (e.g. cut short or not started) still runs.
    result = runner.invoke(app, [*args, "--today", "2026-11-21"])
    assert result.exit_code == 0 and ran == [date(2026, 11, 21)]

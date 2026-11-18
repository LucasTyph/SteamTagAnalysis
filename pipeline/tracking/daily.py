"""One daily tracking run.

1. Discover: ask the app list for every game created or modified since the last run
   (needs STEAM_API_KEY; skipped with a warning without it).
2. Re-check "coming soon" games: daily when their planned date is close, weekly
   otherwise. Discovered and re-checked apps go through GetItems (200 per request).
3. Start tracking every game that is now released (released within `backfill_days`).
4. Snapshot: today's review total and % positive for every tracked game.
5. Exact daily counts: the review histogram's last 30 days, fetched for every tracked
   game at least every `histogram_every_days` (so windows overlap and no day is
   missed), oldest first, until the time budget runs out. Leftovers go first next day.

State is saved after every stage, so a run cut short keeps what it finished.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from pipeline.fetch.client import FetchError, SteamClient, Stopped
from pipeline.fetch.items import fetch_batch
from pipeline.fetch.perapp import STAGES as PERAPP_STAGES
from pipeline.tracking.store import COMING_SOON, RELEASED, CatalogEntry, TrackingStore

APPLIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"


@dataclass(frozen=True)
class TrackingConfig:
    backfill_days: int = 30  # games released this recently when first seen get tracked
    track_days: int = 365
    near_release_before: int = 7  # re-check daily from 7 days before the planned date…
    near_release_after: int = 14  # …until 14 days after it (delays are common)
    recheck_every_days: int = 7  # otherwise weekly
    histogram_every_days: int = 21  # < 30 so consecutive 30-day windows overlap
    batch_size: int = 200


TRACKING = TrackingConfig()


def _ts_date(ts) -> date | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=UTC).date()


def classify(item: dict) -> tuple[str, str, date | None] | None:
    """GetItems item → (status, name, date) for games; None if not a usable game.

    For coming-soon games the date is the planned release (if Steam shows one);
    for released games it's the first day on Steam (early access counts).
    """
    if item.get("missing") or item.get("success") != 1 or not item.get("visible"):
        return None
    if item.get("type") != 0:
        return None
    release = item.get("release") or {}
    name = item.get("name") or ""
    if release.get("is_coming_soon") or item.get("is_coming_soon"):
        return COMING_SOON, name, _ts_date(release.get("steam_release_date"))
    first = release.get("original_steam_release_date") or release.get("steam_release_date")
    return RELEASED, name, _ts_date(first)


def recheck_due(e: CatalogEntry, today: date, cfg: TrackingConfig = TRACKING) -> bool:
    if e.status != COMING_SOON:
        return False
    if not e.last_checked:
        return True
    age = (today - date.fromisoformat(e.last_checked)).days
    if e.planned_release:
        planned = date.fromisoformat(e.planned_release)
        lo = planned - timedelta(days=cfg.near_release_before)
        hi = planned + timedelta(days=cfg.near_release_after)
        if lo <= today <= hi:
            return age >= 1
    return age >= cfg.recheck_every_days


def histogram_due(e: CatalogEntry, today: date, cfg: TrackingConfig = TRACKING) -> bool:
    if not e.tracked_from:
        return False
    until = e.tracking_until()
    if until is None:
        return False
    if not e.last_histogram:
        return True
    last = date.fromisoformat(e.last_histogram)
    if today > until:
        return last < until  # one final fetch to cover the last days
    return (today - last).days >= cfg.histogram_every_days


def apply_item(
    catalog: dict[int, CatalogEntry],
    appid: int,
    item: dict,
    today: date,
    cfg: TrackingConfig = TRACKING,
) -> str | None:
    """Update the catalog from one GetItems item. Returns 'tracked' if tracking started."""
    parsed = classify(item)
    entry = catalog.get(appid)
    iso = today.isoformat()
    if parsed is None:
        # Hidden or missing pages are kept: they often reappear (e.g. at launch).
        if entry:
            entry.last_checked = iso
        return None
    status, name, when = parsed
    if status == RELEASED and when is not None and when > today:
        status = COMING_SOON  # marked released but dated in the future: not out yet
    if status == COMING_SOON:
        if entry is None:
            entry = catalog[appid] = CatalogEntry(appid, name, COMING_SOON, first_seen=iso)
        if entry.tracked_from:  # already released and tracked; ignore odd flips back
            entry.last_checked = iso
            return None
        entry.name = name
        entry.status = COMING_SOON
        entry.planned_release = when.isoformat() if when else ""
        entry.last_checked = iso
        return None

    if entry and entry.tracked_from:
        entry.name = name
        entry.last_checked = iso
        return None
    if when is None:
        # No release date from Steam: only trust "released today" if we saw the game
        # as coming soon before; otherwise it's usually an old game with missing data.
        if not (entry and entry.status == COMING_SOON):
            return None
        when = today
    released = when
    if released < today - timedelta(days=cfg.backfill_days):
        catalog.pop(appid, None)  # an older game; not a new release
        return None
    if entry is None:
        entry = catalog[appid] = CatalogEntry(appid, name, RELEASED, first_seen=iso)
    entry.name = name
    entry.status = RELEASED
    entry.release_date = released.isoformat()
    entry.tracked_from = iso
    entry.last_checked = iso
    return "tracked"


def list_modified_apps(client: SteamClient, api_key: str, since: int) -> list[int]:
    appids: list[int] = []
    cursor = 0
    while True:
        params = {
            "key": api_key,
            "if_modified_since": since,
            "include_games": "true",
            "include_dlc": "false",
            "include_software": "false",
            "include_videos": "false",
            "include_hardware": "false",
            "max_results": 50_000,
            "last_appid": cursor,
        }
        _, body = client.get_json(APPLIST_URL, params)
        resp = body.get("response", {}) if isinstance(body, dict) else {}
        appids += [int(a["appid"]) for a in resp.get("apps", [])]
        if not (resp.get("have_more_results") and resp.get("last_appid")):
            return appids
        cursor = int(resp["last_appid"])


def _batches(ids: list[int], n: int) -> Iterable[list[int]]:
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


def parse_recent(body: dict) -> list[tuple[date, int, int]]:
    """Daily (day, up, down) from a review histogram's `recent` block (~last 30 days)."""
    out = []
    for r in (body.get("results") or {}).get("recent") or []:
        out.append(
            (
                _ts_date(r["date"]),
                int(r.get("recommendations_up") or 0),
                int(r.get("recommendations_down") or 0),
            )
        )
    return out


def run_daily(
    store: TrackingStore,
    client: SteamClient,
    today: date,
    api_key: str | None,
    cfg: TrackingConfig = TRACKING,
    log: Callable[[str], None] = print,
) -> dict:
    t0 = time.monotonic()
    state = store.load_state()
    catalog = store.load_catalog()
    stats = {
        "date": today.isoformat(),
        "discovered": 0,
        "rechecked": 0,
        "newly_tracked": 0,
        "snapshots": 0,
        "histograms": 0,
        "histograms_pending": 0,
        "errors": 0,
        "stop_reason": "",
    }
    fetched: dict[int, dict] = {}

    def get_items(ids: list[int]) -> None:
        for batch in _batches(ids, cfg.batch_size):
            try:
                _, by_id = fetch_batch(client, batch)
            except FetchError as e:
                stats["errors"] += 1
                log(f"  GetItems batch failed: {e}")
                continue
            for a in batch:
                fetched[a] = by_id.get(a, {"missing": True})

    def finish(reason: str = "") -> dict:
        store.save_catalog(catalog)
        store.save_state(state)
        stats["stop_reason"] = reason
        stats["requests"] = client.control.requests
        stats["duration_s"] = round(time.monotonic() - t0)
        stats["tracked"] = sum(1 for e in catalog.values() if e.is_tracked(today))
        store.log_run(stats)
        return stats

    try:
        # 1. Discover new and changed pages.
        run_started = int(time.time())
        discovered: list[int] = []
        if api_key and state.get("applist_since"):
            discovered = list_modified_apps(client, api_key, int(state["applist_since"]))
            stats["discovered"] = len(discovered)
            log(f"discover: {len(discovered):,} new or changed games since last run")
        elif not api_key:
            log("discover: STEAM_API_KEY not set; relying on coming-soon re-checks only")

        # 2. Re-check coming-soon games that are due.
        due = [a for a, e in catalog.items() if recheck_due(e, today, cfg)]
        to_check = sorted(set(discovered) | set(due))
        get_items(to_check)
        for a in to_check:
            if a in fetched and apply_item(catalog, a, fetched[a], today, cfg) == "tracked":
                stats["newly_tracked"] += 1
        stats["rechecked"] = len(due)
        if api_key:
            state["applist_since"] = run_started
        log(
            f"recheck: {len(due):,} coming-soon games due, "
            f"{stats['newly_tracked']:,} newly released games now tracked"
        )
        store.save_catalog(catalog)
        store.save_state(state)

        # 3. Daily snapshot of every tracked game.
        tracked = sorted(a for a, e in catalog.items() if e.is_tracked(today))
        get_items([a for a in tracked if a not in fetched])
        rows = []
        for a in tracked:
            item = fetched.get(a) or {}
            reviews = (item.get("reviews") or {}).get("summary_filtered")
            if reviews is None:
                continue
            count = int(reviews.get("review_count") or 0)
            pct = reviews.get("percent_positive") if count else None
            rows.append((a, count, pct))
            if item:
                catalog[a].last_checked = today.isoformat()
        stats["snapshots"] = store.append_snapshots(today, rows)
        log(f"snapshot: {stats['snapshots']:,} of {len(tracked):,} tracked games")
        store.save_catalog(catalog)

        # 4. Exact daily counts, oldest first.
        due_h = sorted(
            (a for a, e in catalog.items() if histogram_due(e, today, cfg)),
            key=lambda a: catalog[a].last_histogram or "",
        )
        stage = PERAPP_STAGES["histogram"]
        pending: list[tuple[int, date, int, int]] = []
        for i, a in enumerate(due_h):
            try:
                _, body = client.get_json(stage.url(a), stage.params)
            except FetchError as e:
                stats["errors"] += 1
                log(f"  histogram {a} failed: {e}")
                continue
            pending += [(a, d, up, down) for d, up, down in parse_recent(body)]
            catalog[a].last_histogram = today.isoformat()
            stats["histograms"] += 1
            if (i + 1) % 200 == 0:  # checkpoint
                store.upsert_daily(pending)
                pending = []
                store.save_catalog(catalog)
        store.upsert_daily(pending)
        log(f"daily counts: {stats['histograms']:,} games updated")

        # Retire games whose year is over and whose final counts are in.
        for a in [a for a, e in catalog.items() if e.tracked_from and not e.is_tracked(today)]:
            if not histogram_due(catalog[a], today, cfg):
                del catalog[a]
        state["last_run"] = today.isoformat()
        return finish()
    except Stopped as e:
        stats["histograms_pending"] = sum(
            1 for e2 in catalog.values() if histogram_due(e2, today, cfg)
        )
        log(f"stopped early: {e}")
        if "pending" in locals():
            store.upsert_daily(pending)
        return finish(str(e))


def seed_from_raw(
    store: TrackingStore,
    raw_items: Iterable[tuple[str, dict, float]],
    today: date,
    cfg: TrackingConfig = TRACKING,
) -> dict:
    """Start the catalog from a local GetItems cache: every coming-soon game, plus games
    released within `backfill_days`. The app-list cursor starts at the cache's age."""
    catalog: dict[int, CatalogEntry] = {}
    newest = 0.0
    for key, item, fetched_at in raw_items:
        newest = max(newest, fetched_at)
        apply_item(catalog, int(key), item, today, cfg)
        if int(key) in catalog:
            catalog[int(key)].last_checked = _ts_date(fetched_at).isoformat()
    store.save_catalog(catalog)
    store.save_state({"applist_since": int(newest), "seeded": today.isoformat()})
    return {
        "coming_soon": sum(1 for e in catalog.values() if e.status == COMING_SOON),
        "tracked": sum(1 for e in catalog.values() if e.tracked_from),
    }

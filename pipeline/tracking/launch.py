"""First-review dates for every analysed game (the real launch of early-access games).

Steam's release date for a game that left early access is often the 1.0 date (Rust
shows 2018, not 2013), and the store doesn't always return the original early-access
date. The review histogram's `start_date` is the day of the game's first review,
which is a good proxy for when it actually went on sale.

Results go to `launch/first_reviews.csv` in the tracking directory (the
`tracking-data` branch), one row per game, so the backfill can run a slice at a
time in the scheduled workflow and resume where it stopped.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from pipeline.fetch.client import FetchError, SteamClient, Stopped
from pipeline.fetch.perapp import STAGES as PERAPP_STAGES

FILE = Path("launch") / "first_reviews.csv"
COLUMNS = ("appid", "first_review", "fetched_on")


def first_review(body: dict) -> date | None:
    """The histogram's first-review day, or None when the game has no reviews."""
    results = (body or {}).get("results") or {}
    start = results.get("start_date")
    if not start or not results.get("rollups"):
        return None
    return datetime.fromtimestamp(int(start), tz=UTC).date()


def load(dir: Path) -> dict[int, date | None]:
    return load_file(dir / FILE)


def load_file(path: Path) -> dict[int, date | None]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {
            int(r["appid"]): date.fromisoformat(r["first_review"]) if r["first_review"] else None
            for r in csv.DictReader(f)
        }


def append(dir: Path, rows: Iterable[tuple[int, date | None, date]]) -> int:
    path = dir / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    n = 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(COLUMNS)
        for appid, first, fetched in rows:
            w.writerow((appid, first.isoformat() if first else "", fetched.isoformat()))
            n += 1
    return n


def backfill(
    dir: Path,
    appids: list[int],
    client: SteamClient,
    today: date,
    log: Callable[[str], None] = print,
    checkpoint: int = 100,
) -> dict[str, int]:
    """Fetch first-review dates for `appids` not yet in the file, in the given order."""
    done = load(dir)
    todo = [a for a in appids if a not in done]
    stats = {"done_before": len(done), "pending": len(todo), "fetched": 0, "errors": 0}
    log(f"{len(done):,} games already have a date; {len(todo):,} to go")
    stage = PERAPP_STAGES["histogram"]
    rows: list[tuple[int, date | None, date]] = []
    try:
        for a in todo:
            try:
                _, body = client.get_json(stage.url(a), stage.params)
            except FetchError as e:
                stats["errors"] += 1  # not recorded, so the next run retries it
                log(f"  {a} failed: {e}")
                continue
            rows.append((a, first_review(body), today))
            stats["fetched"] += 1
            if len(rows) >= checkpoint:  # a killed run loses at most one checkpoint
                append(dir, rows)
                rows = []
                if stats["fetched"] % 1000 == 0:
                    log(f"  {stats['fetched']:,} fetched")
    except Stopped as e:
        log(f"stopped: {e}")
    finally:
        append(dir, rows)
    stats["pending"] -= stats["fetched"]
    return stats


def seed_from_histograms(dir: Path, bodies: Iterable[tuple[int, dict, date]]) -> int:
    """Add dates from histograms already fetched elsewhere (e.g. the timeline set)."""
    done = load(dir)
    return append(dir, ((a, first_review(b), d) for a, b, d in bodies if a not in done))

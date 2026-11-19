"""`stp track export`: tracking data → files for the website's New Releases page.

Output (default web/public/data/releases/):
    meta.json        coverage, run info, releases per day
    games.json       one summary row per tracked game with at least `min_reviews` reviews
    aggregates.json  first-year curves, "does it settle after week 1", early access vs
                     full launch, how fast each genre collects reviews, top movers
    g/<appid>.json   that game's daily reviews (days with reviews only), lazy-loaded

Only games whose daily history starts at release are used for curves ("clean"):
games with reviews dated before their listed release date usually came out of early
access earlier than Steam reports, so their day counts would be wrong.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pipeline.config import ANALYSIS
from pipeline.tracking.store import CatalogEntry, TrackingStore, _read_csv

CURVE_DAYS = 365
CURVE_MIN_REVIEWS = 20  # a game counts toward a day's curve once it has this many reviews
CURVE_MIN_GAMES = 10  # minimum games behind any curve point
SETTLE_PAIRS = ((3, 14), (7, 30), (30, 90))
SETTLE_MIN_REVIEWS = 20
SETTLE_MIN_GAMES = 25  # percentages from fewer games would overstate thin data
SPEED_DAY = 7
SPEED_MIN_GAMES = 15


@dataclass
class GameHistory:
    entry: CatalogEntry
    release: date
    observed_until: date | None
    days: dict[date, tuple[int, int]] = field(default_factory=dict)
    prior_reviews: int = 0  # reviews dated before the listed release date

    @property
    def clean(self) -> bool:
        return self.observed_until is not None and self.prior_reviews == 0

    def cumulative(self, day_offset: int) -> tuple[int, int] | None:
        """(up, down) from release through release + day_offset, if observed."""
        target = self.release + timedelta(days=day_offset)
        if self.observed_until is None or target > self.observed_until:
            return None
        up = down = 0
        for d, (u, n) in self.days.items():
            if self.release <= d <= target:
                up += u
                down += n
        return up, down

    def observed_days(self) -> int:
        if self.observed_until is None:
            return -1
        return (self.observed_until - self.release).days


def _pct(up: int, down: int) -> float | None:
    return round(100 * up / (up + down), 1) if up + down else None


def _quantiles(values: list[float]) -> tuple[float, float, float]:
    if len(values) == 1:
        return values[0], values[0], values[0]
    q = statistics.quantiles(values, n=4, method="inclusive")
    return round(q[0], 1), round(statistics.median(values), 1), round(q[2], 1)


def load_histories(store: TrackingStore) -> list[GameHistory]:
    catalog = store.load_catalog()
    tracked = {a: e for a, e in catalog.items() if e.tracked_from and e.release_date}
    histories = {
        a: GameHistory(
            entry=e,
            release=date.fromisoformat(e.release_date),
            observed_until=date.fromisoformat(e.last_histogram) if e.last_histogram else None,
        )
        for a, e in tracked.items()
    }
    for path in sorted((store.root / "daily_reviews").glob("*.csv")):
        for r in _read_csv(path):
            h = histories.get(int(r["appid"]))
            if h is None:
                continue
            d = date.fromisoformat(r["day"])
            up, down = int(r["up"]), int(r["down"])
            if d < h.release:
                h.prior_reviews += up + down
            h.days[d] = (up, down)
    return list(histories.values())


def latest_snapshots(store: TrackingStore) -> dict[int, tuple[int, int | None]]:
    out: dict[int, tuple[int, int | None]] = {}
    for path in sorted((store.root / "snapshots").glob("*.csv")):
        for r in _read_csv(path):  # files and rows are in date order: last one wins
            pct = int(r["pct_positive"]) if r["pct_positive"] else None
            out[int(r["appid"])] = (int(r["review_count"]), pct)
    return out


def primary_tag(entry: CatalogEntry, names: dict[int, str]) -> str | None:
    excluded = set(ANALYSIS.excluded_tags)
    for t in entry.tags.split(";") if entry.tags else []:
        name = names.get(int(t))
        if name and name not in excluded:
            return name
    return None


def curve(histories: list[GameHistory], max_day: int) -> list[list]:
    """Per day since release: [day, n_games, p25, median, p75] of cumulative % positive."""
    out = []
    for d in range(max_day + 1):
        values = []
        for h in histories:
            c = h.cumulative(d)
            if c and sum(c) >= CURVE_MIN_REVIEWS:
                values.append(100 * c[0] / sum(c))
        if len(values) >= CURVE_MIN_GAMES:
            out.append([d, len(values), *_quantiles(values)])
    return out


def settle(histories: list[GameHistory]) -> list[dict]:
    """How much cumulative % positive moves between two points in a game's life."""
    out = []
    for a, b in SETTLE_PAIRS:
        changes = []
        for h in histories:
            ca, cb = h.cumulative(a), h.cumulative(b)
            if ca and cb and sum(ca) >= SETTLE_MIN_REVIEWS:
                changes.append(100 * cb[0] / sum(cb) - 100 * ca[0] / sum(ca))
        entry = {"from_day": a, "to_day": b, "n": len(changes)}
        if len(changes) >= SETTLE_MIN_GAMES:
            p25, med, p75 = _quantiles(changes)
            entry |= {
                "p25": p25,
                "median": med,
                "p75": p75,
                "pct_moved_5": round(100 * sum(abs(c) > 5 for c in changes) / len(changes), 1),
                "pct_up_5": round(100 * sum(c > 5 for c in changes) / len(changes), 1),
                "pct_down_5": round(100 * sum(c < -5 for c in changes) / len(changes), 1),
                "changes": sorted(round(c, 1) for c in changes),
            }
        out.append(entry)
    return out


def speed_by_tag(histories: list[GameHistory], names: dict[int, str]) -> list[dict]:
    """Reviews collected in the first week, by primary tag."""
    by_tag: dict[str, list[int]] = defaultdict(list)
    for h in histories:
        tag = primary_tag(h.entry, names)
        c = h.cumulative(SPEED_DAY)
        if tag and c is not None:
            by_tag[tag].append(sum(c))
    rows = []
    for tag, counts in by_tag.items():
        if len(counts) >= SPEED_MIN_GAMES:
            rows.append(
                {
                    "tag": tag,
                    "n": len(counts),
                    "median": statistics.median(counts),
                    "mean": round(statistics.mean(counts), 1),
                    "pct_10plus": round(100 * sum(c >= 10 for c in counts) / len(counts), 1),
                }
            )
    return sorted(rows, key=lambda r: (-r["median"], -r["mean"]))


def run(store: TrackingStore, out: Path, min_reviews: int = 5) -> dict:
    histories = load_histories(store)
    snaps = latest_snapshots(store)
    names = store.load_tag_names()
    state = store.load_state()
    clean = [h for h in histories if h.clean]
    data_through = max((h.observed_until for h in histories if h.observed_until), default=None)
    max_day = min(CURVE_DAYS, max((h.observed_days() for h in clean), default=0))

    (out / "g").mkdir(parents=True, exist_ok=True)
    for old in (out / "g").glob("*.json"):
        old.unlink()

    games = []
    for h in histories:
        e = h.entry
        count, pct = snaps.get(e.appid, (0, None))
        if count < min_reviews:
            continue
        d7 = h.cumulative(7)
        days = sorted([(d - h.release).days, u, n] for d, (u, n) in h.days.items() if u + n > 0)
        (out / "g" / f"{e.appid}.json").write_text(
            json.dumps(
                {"appid": e.appid, "release": e.release_date, "days": days}, separators=(",", ":")
            ),
            "utf-8",
        )
        games.append(
            {
                "appid": e.appid,
                "name": e.name,
                "release": e.release_date,
                "ea": e.early_access == "1",
                "tag": primary_tag(e, names),
                "reviews": count,
                "pct": pct,
                "d7_reviews": sum(d7) if d7 else None,
                "d7_pct": _pct(*d7) if d7 else None,
                "clean": h.clean,
            }
        )
    games.sort(key=lambda g: -g["reviews"])

    movers = []
    for g in games:
        comparable = (
            g["clean"]
            and g["d7_pct"] is not None
            and g["pct"] is not None
            and g["reviews"] >= 50
            and (g["d7_reviews"] or 0) >= SETTLE_MIN_REVIEWS
        )
        if comparable:
            movers.append({**g, "change": round(g["pct"] - g["d7_pct"], 1)})
    movers.sort(key=lambda g: g["change"])

    aggregates = {
        "curve_all": curve(clean, max_day),
        "curve_early_access": curve([h for h in clean if h.entry.early_access == "1"], max_day),
        "curve_full_launch": curve([h for h in clean if h.entry.early_access == "0"], max_day),
        "settle": settle(clean),
        "speed_by_tag": speed_by_tag(clean, names),
        "fallers": movers[:10],
        "risers": movers[::-1][:10],
    }

    per_day: dict[str, int] = defaultdict(int)
    for h in histories:
        per_day[h.entry.release_date] += 1
    runs = _read_csv(store.root / "runs.csv")
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tracking_since": state.get("seeded"),
        "last_run": runs[-1]["date"] if runs else None,
        "data_through": data_through.isoformat() if data_through else None,
        "tracked": len(histories),
        "with_reviews": sum(1 for h in histories if snaps.get(h.entry.appid, (0,))[0] > 0),
        "clean": len(clean),
        "early_access": sum(1 for h in histories if h.entry.early_access == "1"),
        "listed_games": len(games),
        "min_reviews_listed": min_reviews,
        "releases_per_day": sorted([d, n] for d, n in per_day.items()),
    }
    for name, doc in (("meta", meta), ("games", games), ("aggregates", aggregates)):
        (out / f"{name}.json").write_text(json.dumps(doc, separators=(",", ":")), "utf-8")
    return meta

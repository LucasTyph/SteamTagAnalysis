"""File-backed state for release tracking.

Layout (all plain CSV, sorted, so git stores small diffs):

    catalog.csv                       one row per game being watched or tracked
    snapshots/YYYY-Www.csv            daily review totals per tracked game (ISO week)
    daily_reviews/YYYY-Www.csv        exact positive/negative reviews per game per day (ISO week)

Files are per ISO week (e.g. 2026-W47) so none grows past a few MB: at ~200 releases
a day, monthly files would reach ~55 MB, beyond GitHub's 50 MB warning.
    runs.csv                          one row per daily run
    state.json                        app-list cursor and last run date
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from pathlib import Path

COMING_SOON = "coming_soon"


def week_key(d: date) -> str:
    """ISO week label used for file names, e.g. 2026-W47."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


RELEASED = "released"


@dataclass
class CatalogEntry:
    appid: int
    name: str
    status: str  # coming_soon | released
    planned_release: str = ""  # ISO date Steam shows for coming-soon games, if any
    release_date: str = ""  # ISO date of release (released games)
    first_seen: str = ""
    last_checked: str = ""
    tracked_from: str = ""  # set when tracking starts
    last_histogram: str = ""  # last time the daily review counts were fetched

    def tracking_until(self) -> date | None:
        if not self.tracked_from or not self.release_date:
            return None
        return date.fromisoformat(self.release_date) + timedelta(days=365)

    def is_tracked(self, today: date) -> bool:
        until = self.tracking_until()
        return until is not None and today <= until


CATALOG_FIELDS = [f.name for f in fields(CatalogEntry)]
SNAPSHOT_FIELDS = ["date", "appid", "review_count", "pct_positive"]
DAILY_FIELDS = ["appid", "day", "up", "down"]
RUN_FIELDS = [
    "date",
    "duration_s",
    "requests",
    "discovered",
    "rechecked",
    "newly_tracked",
    "tracked",
    "snapshots",
    "histograms",
    "histograms_pending",
    "errors",
    "stop_reason",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TrackingStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._migrate_monthly_files()

    def _migrate_monthly_files(self) -> None:
        """One-time move from monthly files (YYYY-MM.csv) to ISO-week files."""
        for folder, fields_, date_col in (
            ("snapshots", SNAPSHOT_FIELDS, "date"),
            ("daily_reviews", DAILY_FIELDS, "day"),
        ):
            old = sorted(f for f in (self.root / folder).glob("????-??.csv") if "W" not in f.stem)
            for path in old:
                by_week: dict[str, list[dict]] = {}
                for r in _read_csv(path):
                    by_week.setdefault(week_key(date.fromisoformat(r[date_col])), []).append(r)
                for week, rows in by_week.items():
                    target = self.root / folder / f"{week}.csv"
                    merged = _read_csv(target) + rows
                    key = (
                        (lambda r: (r["date"], int(r["appid"])))
                        if date_col == "date"
                        else (lambda r: (int(r["appid"]), r["day"]))
                    )
                    dedup = {key(r): r for r in merged}
                    _write_csv(target, fields_, [dedup[k] for k in sorted(dedup)])
                path.unlink()

    # --- state ---------------------------------------------------------------------

    @property
    def _state_path(self) -> Path:
        return self.root / "state.json"

    def load_state(self) -> dict:
        if not self._state_path.exists():
            return {}
        return json.loads(self._state_path.read_text("utf-8"))

    def save_state(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", "utf-8")

    # --- catalog -------------------------------------------------------------------

    def load_catalog(self) -> dict[int, CatalogEntry]:
        out = {}
        for r in _read_csv(self.root / "catalog.csv"):
            e = CatalogEntry(**{**r, "appid": int(r["appid"])})
            out[e.appid] = e
        return out

    def save_catalog(self, catalog: dict[int, CatalogEntry]) -> None:
        rows = [asdict(catalog[a]) for a in sorted(catalog)]
        _write_csv(self.root / "catalog.csv", CATALOG_FIELDS, rows)

    # --- snapshots (append-only, one file per month) ---------------------------------

    def append_snapshots(self, day: date, rows: list[tuple[int, int, int | None]]) -> int:
        """Add today's (appid, review_count, pct_positive) rows, replacing any for `day`."""
        path = self.root / "snapshots" / f"{week_key(day)}.csv"
        iso = day.isoformat()
        existing = [r for r in _read_csv(path) if r["date"] != iso]
        new = [
            {"date": iso, "appid": a, "review_count": n, "pct_positive": "" if p is None else p}
            for a, n, p in sorted(rows)
        ]
        _write_csv(path, SNAPSHOT_FIELDS, existing + new)
        return len(new)

    # --- exact daily counts (upsert by appid + day) ----------------------------------

    def upsert_daily(self, rows: list[tuple[int, date, int, int]]) -> int:
        """Insert or update (appid, day, up, down). Later fetches win: Steam's counts for
        a day can still change as reviews are edited or removed."""
        by_week: dict[str, list[tuple[int, date, int, int]]] = {}
        for r in rows:
            by_week.setdefault(week_key(r[1]), []).append(r)
        for week, week_rows in by_week.items():
            path = self.root / "daily_reviews" / f"{week}.csv"
            merged = {(int(r["appid"]), r["day"]): r for r in _read_csv(path)}
            for appid, day, up, down in week_rows:
                merged[(appid, day.isoformat())] = {
                    "appid": appid,
                    "day": day.isoformat(),
                    "up": up,
                    "down": down,
                }
            _write_csv(path, DAILY_FIELDS, [merged[k] for k in sorted(merged)])
        return len(rows)

    # --- run log -------------------------------------------------------------------

    def log_run(self, row: dict) -> None:
        path = self.root / "runs.csv"
        rows = [r for r in _read_csv(path) if r["date"] != str(row["date"])]
        _write_csv(path, RUN_FIELDS, [*rows, {k: row.get(k, "") for k in RUN_FIELDS}])

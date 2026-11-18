"""Per-game review timelines: summary metrics and turning points.

Input: monthly (up, down) review counts for one game. Months without reviews in
between are filled with zeros. A month's positive % only counts when it has at least
`min_month_reviews` reviews.

Turning points come from PELT change-point detection (ruptures) on the monthly
positive %, with a penalty scaled to the series' own month-to-month noise. Only
shifts of at least `min_shift` percentage points (review-weighted segment means) are
kept. Each turning point is matched to the nearest developer update or launch
announcement within `news_window_days`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np


@dataclass(frozen=True)
class TimelineConfig:
    min_month_reviews: int = 20
    launch_months: int = 3
    max_launch_months: int = 6
    recent_months: int = 12
    min_recent_reviews: int = 50
    rolling_months: int = 3
    min_segment_months: int = 3
    penalty_factor: float = 3.0
    min_shift: float = 5.0
    max_changes: int = 6
    news_window_days: int = 45


TIMELINES = TimelineConfig()

# Steam user reviews started in October 2010.
REVIEWS_START = date(2010, 10, 1)


@dataclass
class ChangePoint:
    month: date
    before: float
    after: float

    @property
    def shift(self) -> float:
        return self.after - self.before


@dataclass
class TimelineSummary:
    first_month: date
    last_month: date
    months: int
    total_reviews: int
    overall_score: float
    launch_score: float | None
    recent_score: float | None
    drift: float | None
    trough_score: float | None
    trough_month: date | None
    peak_score: float | None
    peak_month: date | None
    recovery: float | None  # recent − trough (how far it climbed back)
    decline: float | None  # peak − recent (how far it fell)
    volatility: float | None  # review-weighted SD of monthly %, pp
    changes: list[ChangePoint] = field(default_factory=list)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def fill_months(months: list[date], up: list[int], down: list[int]):
    """Dense monthly arrays from the first to the last month."""
    start, end = min(months), max(months)
    n = (end.year - start.year) * 12 + end.month - start.month + 1
    grid = [_add_months(start, i) for i in range(n)]
    idx = {m: i for i, m in enumerate(grid)}
    u = np.zeros(n)
    d = np.zeros(n)
    for m, a, b in zip(months, up, down, strict=True):
        u[idx[m]] += a
        d[idx[m]] += b
    return grid, u, d


def _pct(u: np.ndarray, d: np.ndarray) -> float | None:
    tot = u.sum() + d.sum()
    return float(100 * u.sum() / tot) if tot > 0 else None


def rolling_pct(u: np.ndarray, d: np.ndarray, window: int, min_reviews: int) -> np.ndarray:
    """Trailing-window positive % (sum-based); NaN where the window is too thin."""
    cu = np.convolve(u, np.ones(window), mode="full")[: len(u)]
    cd = np.convolve(d, np.ones(window), mode="full")[: len(d)]
    tot = cu + cd
    out = np.full(len(u), np.nan)
    ok = tot >= min_reviews
    out[ok] = 100 * cu[ok] / tot[ok]
    return out


def detect_changes(
    grid: list[date], u: np.ndarray, d: np.ndarray, cfg: TimelineConfig = TIMELINES
) -> list[ChangePoint]:
    import ruptures as rpt

    n = u + d
    keep = np.flatnonzero(n >= cfg.min_month_reviews)
    if len(keep) < 2 * cfg.min_segment_months:
        return []
    signal = 100 * u[keep] / n[keep]
    diffs = np.diff(signal)
    sigma = 1.4826 * np.median(np.abs(diffs - np.median(diffs))) / np.sqrt(2)
    sigma = max(sigma, 1.0)  # avoid zero-noise series producing a change every month
    pen = cfg.penalty_factor * sigma**2 * np.log(len(signal))
    bkps = rpt.Pelt(model="l2", min_size=cfg.min_segment_months, jump=1).fit(signal).predict(pen)

    bounds = [0, *bkps]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    def seg_pct(a: int, b: int) -> float:
        rows = keep[a:b]
        return 100 * u[rows].sum() / n[rows].sum()

    changes = []
    for (a0, b0), (a1, b1) in zip(segs, segs[1:], strict=False):
        before, after = seg_pct(a0, b0), seg_pct(a1, b1)
        if abs(after - before) >= cfg.min_shift:
            changes.append(ChangePoint(grid[keep[a1]], before, after))
    changes.sort(key=lambda c: -abs(c.shift))
    return sorted(changes[: cfg.max_changes], key=lambda c: c.month)


def summarize(
    months: list[date],
    up: list[int],
    down: list[int],
    cfg: TimelineConfig = TIMELINES,
    launched_before_reviews: bool = False,
) -> TimelineSummary:
    """`launched_before_reviews`: the game predates Steam reviews (Oct 2010), so the
    first months of its history are not its launch and get no launch score."""
    grid, u, d = fill_months(months, up, down)
    n = u + d
    nonzero = np.flatnonzero(n > 0)
    first, last = nonzero[0], nonzero[-1]
    grid, u, d, n = (
        grid[first : last + 1],
        u[first : last + 1],
        d[first : last + 1],
        n[first : last + 1],
    )

    # Launch window: the first `launch_months`, extended (up to `max_launch_months`)
    # until it holds enough reviews to mean something.
    k = cfg.launch_months
    while k < min(cfg.max_launch_months, len(n)) and n[:k].sum() < cfg.min_recent_reviews:
        k += 1
    launch = _pct(u[:k], d[:k]) if n[:k].sum() >= cfg.min_recent_reviews else None
    if launched_before_reviews:
        launch = None
    recent_u, recent_d = u[-cfg.recent_months :], d[-cfg.recent_months :]
    recent = (
        _pct(recent_u, recent_d)
        if recent_u.sum() + recent_d.sum() >= cfg.min_recent_reviews
        else None
    )

    roll = rolling_pct(u, d, cfg.rolling_months, cfg.min_month_reviews)
    # Trough/peak after the launch window, so launch spikes don't count as peaks.
    post = roll.copy()
    post[:k] = np.nan
    trough = peak = None
    trough_month = peak_month = None
    if np.isfinite(post).any():
        ti, pi = int(np.nanargmin(post)), int(np.nanargmax(post))
        trough, peak = float(post[ti]), float(post[pi])
        trough_month, peak_month = grid[ti], grid[pi]

    ok = n >= cfg.min_month_reviews
    volatility = None
    if ok.sum() >= 3:
        p = 100 * u[ok] / n[ok]
        w = n[ok]
        mean = np.average(p, weights=w)
        volatility = float(np.sqrt(np.average((p - mean) ** 2, weights=w)))

    return TimelineSummary(
        first_month=grid[0],
        last_month=grid[-1],
        months=len(grid),
        total_reviews=int(n.sum()),
        overall_score=_pct(u, d) or 0.0,
        launch_score=launch,
        recent_score=recent,
        drift=recent - launch if recent is not None and launch is not None else None,
        trough_score=trough,
        trough_month=trough_month,
        peak_score=peak,
        peak_month=peak_month,
        recovery=recent - trough if recent is not None and trough is not None else None,
        decline=peak - recent if recent is not None and peak is not None else None,
        volatility=volatility,
        changes=detect_changes(grid, u, d, cfg),
    )


@dataclass
class NewsItem:
    date: datetime
    title: str
    url: str
    kind: str


def match_news(
    month: date, news: list[NewsItem], window_days: int = TIMELINES.news_window_days
) -> NewsItem | None:
    """Closest update/launch announcement to the middle of `month`, within the window."""
    mid = datetime(month.year, month.month, 15)
    best, best_gap = None, timedelta(days=window_days + 1)
    for item in news:
        if item.kind not in ("update", "launch"):
            continue
        gap = abs(item.date - mid)
        if gap < best_gap:
            best, best_gap = item, gap
    return best if best_gap <= timedelta(days=window_days) else None

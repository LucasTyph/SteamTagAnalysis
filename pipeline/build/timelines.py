"""Parse review histograms and news into rows for the timeline tables."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

# Announcement titles that usually mean a content/balance change or a launch.
_UPDATE = re.compile(
    r"\b(update|patch|hotfix|hot-fix|fix(es)?|changelog|patch ?notes|version|v\d+(\.\d+)+|"
    r"\d+\.\d+(\.\d+)?|season|expansion|dlc|rework|overhaul|balance|chapter|act \w+)\b",
    re.IGNORECASE,
)
_LAUNCH = re.compile(
    r"\b(out now|available now|launch(es|ed)?|release[ds]?|early access|full release)\b"
    r"|(?<![\d.])1\.0(?![\d.])",
    re.IGNORECASE,
)


def _month(ts: int) -> date:
    d = datetime.fromtimestamp(int(ts), tz=UTC)
    return date(d.year, d.month, 1)


def parse_histogram(appid: int, body: dict) -> list[tuple[int, date, int, int]]:
    """Rollups → (appid, month, up, down).

    Older games come back as monthly rollups; newer ones (roughly the last two years)
    as weekly rollups, which are summed into the month each week starts in.
    """
    results = body.get("results") or {}
    if results.get("rollup_type", "month") not in ("month", "week"):
        return []
    merged: dict[date, list[int]] = {}
    for r in results.get("rollups") or []:
        m = _month(r["date"])
        cur = merged.setdefault(m, [0, 0])
        cur[0] += int(r.get("recommendations_up") or 0)
        cur[1] += int(r.get("recommendations_down") or 0)
    return [(appid, m, up, down) for m, (up, down) in sorted(merged.items())]


def classify_news(title: str) -> str:
    if _LAUNCH.search(title):
        return "launch"
    if _UPDATE.search(title):
        return "update"
    return "other"


def parse_news(appid: int, body: dict) -> list[tuple[int, str, datetime, str, str, str]]:
    """Announcements → (appid, gid, date, title, url, kind)."""
    out = []
    for item in (body.get("appnews") or {}).get("newsitems") or []:
        title = (item.get("title") or "").strip()
        if not title or not item.get("date"):
            continue
        out.append(
            (
                appid,
                str(item.get("gid")),
                datetime.fromtimestamp(int(item["date"]), tz=UTC).replace(tzinfo=None),
                title,
                item.get("url") or "",
                classify_news(title),
            )
        )
    return out

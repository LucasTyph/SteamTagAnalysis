"""Sanity checks before a scheduled refresh replaces the published data.

Compares the new meta.json with the one currently on the site. A refresh that lost
a big share of games, mixes or timelines, or whose model fit or effect check went
off, is almost certainly a broken fetch rather than a real change on Steam, so it
must not be published.
"""

from __future__ import annotations

# (label, path in meta, minimum ratio new/old)
SHRINK_LIMITS = [
    ("games", ("counts", "games"), 0.95),
    ("developers", ("counts", "developers"), 0.9),
    ("tags", ("counts", "tags"), 0.95),
    ("pairs", ("counts", "pairs"), 0.85),
    ("triples", ("counts", "triples"), 0.85),
    ("timeline games", ("counts", "timeline_games"), 0.95),
]


def _get(meta: dict, path: tuple[str, ...]):
    for key in path:
        meta = (meta or {}).get(key)
    return meta


def problems(previous: dict, current: dict) -> list[str]:
    out = []
    for label, path, ratio in SHRINK_LIMITS:
        old, new = _get(previous, path), _get(current, path)
        if new is None or (old and new < ratio * old):
            out.append(f"{label}: {new} (was {old}; needs at least {ratio:.0%} of it)")
    old_r2, new_r2 = _get(previous, ("analysis", "cv_r2")), _get(current, ("analysis", "cv_r2"))
    if new_r2 is None or (old_r2 is not None and abs(new_r2 - old_r2) > 0.05):
        out.append(f"held-out R² {new_r2} (was {old_r2})")
    recovery = _get(current, ("analysis", "recovery_median"))
    if recovery is None or recovery < 0.9:
        out.append(f"planted-effect recovery {recovery} (needs at least 0.9)")
    return out

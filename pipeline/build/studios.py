"""Group developer accounts that are really one operation ("studio groups").

Developer clustering counts each developer once per tag mix, but clone operations
ship near-identical games under a new developer name each time, so they still count
as many independent developers. Two analysed games from different developers are
linked when their tags are near-identical (rank-weighted cosine), they came out
close together, and one more piece of evidence ties them:

- **publisher**: same publisher (a mill releasing look-alikes),
- **name**: near-identical titles once numbers and edition words are removed
  ("Hentai Girl Karen" / "Hentai Girl Linda"),

Publisher and name links only apply to small games (under 2,000 reviews), so
franchise sequels and the separate studios of big publishers stay apart.
- **shell**: both are self-named shells (developer or publisher named after the
  game), the pattern of the Chinese "传奇" MMO clones.

Linked developers are merged transitively (union-find) and the group is named by its
smallest developer key, so the result is deterministic.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StudioConfig:
    publisher_min_cos: float = 0.95
    publisher_max_months: int = 6
    max_reviews: int = 2_000  # publisher and name links are for small games: franchises and
    # big publishers' studios stay separate
    name_min_similarity: float = 0.5  # character-bigram Jaccard of cleaned titles
    name_min_cos: float = 0.8
    name_max_months: int = 24
    shell_min_cos: float = 0.85
    shell_max_months: int = 12
    max_block: int = 2_000  # skip name blocks bigger than this (generic prefixes)


STUDIOS = StudioConfig()


@dataclass(frozen=True)
class Game:
    appid: int
    name: str
    developer: str | None
    publisher: str | None
    dev_key: str
    released: date | None
    review_count: int
    tags: dict[int, int]  # tagid → weight (11 − vote rank)


def normalize(s: str | None) -> str:
    # Strip marks first: NFKC would turn "™" into "TM".
    s = unicodedata.normalize("NFKC", re.sub(r"[™®©]", "", s or "")).lower()
    return re.sub(r"\s+", " ", s).strip()


_EDITION = re.compile(
    r"\b(remastered|remaster|edition|deluxe|definitive|goty|demo|vr|hd|dx)\b|\b[ivx]+\b|[\d.]+"
)


def title_key(name: str) -> str:
    """Title without numbers, roman numerals, edition words or punctuation."""
    s = _EDITION.sub(" ", normalize(name))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def bigrams(s: str) -> set[str]:
    s = s.replace(" ", "")
    return {s[i : i + 2] for i in range(len(s) - 1)} or {s}


def tag_cosine(a: dict[int, int], b: dict[int, int]) -> float:
    dot = sum(w * b[t] for t, w in a.items() if t in b)
    na = sum(w * w for w in a.values()) ** 0.5
    nb = sum(w * w for w in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def months_apart(a: date | None, b: date | None) -> int | None:
    if a is None or b is None:
        return None
    return abs((a.year - b.year) * 12 + a.month - b.month)


def self_named(g: Game) -> bool:
    name = normalize(g.name)
    return bool(name) and name in (normalize(g.developer), normalize(g.publisher))


@dataclass(frozen=True)
class Link:
    a: int
    b: int
    rule: str
    similarity: float


def find_links(games: list[Game], cfg: StudioConfig = STUDIOS) -> list[Link]:
    """Candidate pairs per rule, filtered by tag similarity and release window."""
    by_id = {g.appid: g for g in games}
    found: dict[tuple[int, int], Link] = {}

    def consider(x: Game, y: Game, rule: str, min_cos: float, max_months: int) -> None:
        if x.dev_key == y.dev_key:
            return
        key = (min(x.appid, y.appid), max(x.appid, y.appid))
        if key in found:
            return
        gap = months_apart(x.released, y.released)
        if gap is None or gap > max_months:
            return
        cos = tag_cosine(x.tags, y.tags)
        if cos >= min_cos:
            found[key] = Link(key[0], key[1], rule, round(cos, 3))

    def pairs(ids: list[int]):
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                yield by_id[ids[i]], by_id[ids[j]]

    by_pub: dict[str, list[int]] = defaultdict(list)
    for g in games:
        if g.publisher and g.review_count < cfg.max_reviews:
            by_pub[normalize(g.publisher)].append(g.appid)
    for ids in by_pub.values():
        for x, y in pairs(ids):
            consider(x, y, "publisher", cfg.publisher_min_cos, cfg.publisher_max_months)

    keys = {g.appid: title_key(g.name) for g in games}
    grams = {a: bigrams(k) for a, k in keys.items()}
    by_prefix: dict[str, list[int]] = defaultdict(list)
    for a, k in keys.items():
        if len(k) >= 3 and by_id[a].review_count < cfg.max_reviews:
            by_prefix[k[:3]].append(a)
    for ids in by_prefix.values():
        if len(ids) > cfg.max_block:
            continue
        for x, y in pairs(ids):
            gx, gy = grams[x.appid], grams[y.appid]
            if len(gx & gy) / len(gx | gy) >= cfg.name_min_similarity:
                consider(x, y, "name", cfg.name_min_cos, cfg.name_max_months)

    shells = [g.appid for g in games if self_named(g)]
    for x, y in pairs(shells):
        consider(x, y, "shell", cfg.shell_min_cos, cfg.shell_max_months)

    return sorted(found.values(), key=lambda link: (link.a, link.b))


def studio_keys(games: list[Game], links: list[Link]) -> dict[str, str]:
    """dev_key → studio key (the smallest dev_key in its linked group)."""
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    dev_of = {g.appid: g.dev_key for g in games}
    for g in games:
        find(g.dev_key)
    for link in links:
        ra, rb = find(dev_of[link.a]), find(dev_of[link.b])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {k: find(k) for k in parent}

"""Build clean analysis tables (DuckDB) from cached raw GetItems responses.

Tables written to `data/analysis.duckdb`:
- games      one row per visible game (all review counts; filter at analysis time)
- game_tags  one row per (game, tag), with rank, weight, weight share and relevance flag
- tags       tag id → name, plus game counts
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pipeline import db
from pipeline.config import ANALYSIS_DB_PATH, BUILD, BuildConfig

STEAM_TYPE_GAME = 0


@dataclass(frozen=True)
class GameRow:
    appid: int
    name: str
    first_release: datetime | None  # first appearance on Steam (incl. early access)
    full_release: datetime | None  # 1.0 release, if it left early access
    original_release: datetime | None  # release on another platform first (ports), if given
    is_early_access: bool
    is_free: bool
    is_coming_soon: bool
    price_usd: float | None  # undiscounted current US price
    review_count: int
    pct_positive: int | None  # integer, as Steam reports it
    n_pos: int  # estimated from review_count * pct_positive
    n_neg: int
    n_tags: int


@dataclass(frozen=True)
class TagRow:
    appid: int
    tagid: int
    rank: int  # 1 = most-voted tag on this game
    weight: int
    weight_share: float  # weight / weight of the game's top tag
    relevant: bool


def _ts(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)


def parse_item(item: dict, cfg: BuildConfig = BUILD) -> tuple[GameRow, list[TagRow]] | None:
    """One raw store item → clean rows, or None if it isn't a visible game."""
    if item.get("missing") or item.get("success") != 1 or not item.get("visible"):
        return None
    if item.get("type") != STEAM_TYPE_GAME:
        return None

    appid = int(item["appid"])
    release = item.get("release") or {}
    reviews = (item.get("reviews") or {}).get("summary_filtered") or {}
    purchase = item.get("best_purchase_option") or {}

    first = _ts(release.get("original_steam_release_date") or release.get("steam_release_date"))
    full = _ts(release.get("steam_release_date"))
    if release.get("is_early_access"):
        full = None

    is_free = bool(item.get("is_free"))
    cents = purchase.get("original_price_in_cents") or purchase.get("final_price_in_cents")
    price = 0.0 if is_free else (int(cents) / 100 if cents is not None else None)

    count = int(reviews.get("review_count") or 0)
    pct = reviews.get("percent_positive")
    pct = int(pct) if pct is not None and count else None
    n_pos = round(count * pct / 100) if pct is not None else 0

    raw_tags = sorted(item.get("tags") or [], key=lambda t: -int(t.get("weight", 0)))
    top = int(raw_tags[0]["weight"]) if raw_tags else 0
    tags = []
    for rank, t in enumerate(raw_tags, start=1):
        weight = int(t.get("weight", 0))
        share = weight / top if top else 0.0
        tags.append(
            TagRow(
                appid=appid,
                tagid=int(t["tagid"]),
                rank=rank,
                weight=weight,
                weight_share=share,
                relevant=rank <= cfg.tag_max_rank
                or (cfg.tag_min_share is not None and share >= cfg.tag_min_share),
            )
        )

    game = GameRow(
        appid=appid,
        name=item.get("name") or "",
        first_release=first,
        full_release=full,
        original_release=_ts(release.get("original_release_date")),
        is_early_access=bool(release.get("is_early_access")),
        is_free=is_free,
        is_coming_soon=bool(release.get("is_coming_soon") or item.get("is_coming_soon")),
        price_usd=price,
        review_count=count,
        pct_positive=pct,
        n_pos=n_pos,
        n_neg=count - n_pos,
        n_tags=len(tags),
    )
    return game, tags


def parse_basic(item: dict) -> dict | None:
    """Developer / publisher / franchise from a `basic` GetItems response.

    `dev_key` identifies the developer for clustering: Steam's creator-page account ID
    when there is one, otherwise the lower-cased developer name.
    """
    if item.get("missing") or item.get("success") != 1:
        return None
    info = item.get("basic_info") or {}
    devs = info.get("developers") or []
    pubs = info.get("publishers") or []
    franchises = info.get("franchises") or []
    dev = devs[0] if devs else {}
    if dev.get("creator_clan_account_id"):
        dev_key = f"clan:{dev['creator_clan_account_id']}"
    elif dev.get("name"):
        dev_key = f"name:{dev['name'].strip().lower()}"
    else:
        dev_key = None
    return {
        "appid": int(item["appid"]),
        "developer": dev.get("name"),
        "publisher": pubs[0].get("name") if pubs else None,
        "franchise": franchises[0].get("name") if franchises else None,
        "dev_key": dev_key,
    }


def parse_taglist(body: dict) -> list[tuple[int, str]]:
    return [(int(t["tagid"]), t["name"]) for t in body.get("response", {}).get("tags", [])]


def run(
    sqlite_conn: sqlite3.Connection,
    out_path: Path = ANALYSIS_DB_PATH,
    cfg: BuildConfig = BUILD,
) -> dict[str, int]:
    """Rebuild every table from scratch. Returns row counts."""
    import duckdb
    import pyarrow as pa

    games: list[GameRow] = []
    tags: list[TagRow] = []
    for _, item in db.iter_raw(sqlite_conn, "items"):
        parsed = parse_item(item, cfg)
        if parsed:
            games.append(parsed[0])
            tags.extend(parsed[1])

    creators = [c for _, item in db.iter_raw(sqlite_conn, "basic") if (c := parse_basic(item))]

    from pipeline.build import timelines

    monthly = [
        row
        for key, body in db.iter_raw(sqlite_conn, "histogram")
        for row in timelines.parse_histogram(int(key), body)
    ]
    news = [
        row
        for key, body in db.iter_raw(sqlite_conn, "news")
        for row in timelines.parse_news(int(key), body)
    ]

    taglist = db.get_raw(sqlite_conn, "taglist", "english")
    if taglist is None:
        raise RuntimeError("Tag list not fetched; run `stp fetch taglist`.")
    tag_names = parse_taglist(taglist)

    def to_arrow(rows, cls):
        cols = cls.__dataclass_fields__
        return pa.table({c: [getattr(r, c) for r in rows] for c in cols})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        games_arrow = to_arrow(games, GameRow)  # noqa: F841 — referenced by DuckDB SQL
        tags_arrow = to_arrow(tags, TagRow)  # noqa: F841
        names_arrow = pa.table(  # noqa: F841
            {"tagid": [t[0] for t in tag_names], "name": [t[1] for t in tag_names]}
        )
        creators_arrow = pa.table(  # noqa: F841
            {
                k: pa.array(
                    [c[k] for c in creators], type=pa.int64() if k == "appid" else pa.string()
                )
                for k in ("appid", "developer", "publisher", "franchise", "dev_key")
            }
        )
        # Games without developer info form their own cluster (dev_key = app:<appid>).
        con.execute(
            """
            CREATE TABLE games AS
            SELECT g.*, c.developer, c.publisher, c.franchise,
                   COALESCE(c.dev_key, 'app:' || g.appid) AS dev_key
            FROM games_arrow g LEFT JOIN creators_arrow c USING (appid)
            ORDER BY g.appid
            """
        )
        con.execute("CREATE TABLE game_tags AS SELECT * FROM tags_arrow ORDER BY appid, rank")
        con.execute(
            """
            CREATE TABLE tags AS
            SELECT n.tagid, n.name,
                   COUNT(g.appid) FILTER (WHERE gt.relevant) AS n_games_relevant,
                   COUNT(g.appid) AS n_games_any
            FROM names_arrow n
            LEFT JOIN game_tags gt USING (tagid)
            LEFT JOIN games g ON g.appid = gt.appid AND g.review_count >= ?
            GROUP BY n.tagid, n.name
            ORDER BY n_games_relevant DESC
            """,
            [cfg.min_reviews],
        )
        monthly_arrow = pa.table(  # noqa: F841
            {
                "appid": pa.array([r[0] for r in monthly], pa.int64()),
                "month": pa.array([r[1] for r in monthly], pa.date32()),
                "up": pa.array([r[2] for r in monthly], pa.int64()),
                "down": pa.array([r[3] for r in monthly], pa.int64()),
            }
        )
        news_arrow = pa.table(  # noqa: F841
            {
                "appid": pa.array([r[0] for r in news], pa.int64()),
                "gid": pa.array([r[1] for r in news], pa.string()),
                "date": pa.array([r[2] for r in news], pa.timestamp("s")),
                "title": pa.array([r[3] for r in news], pa.string()),
                "url": pa.array([r[4] for r in news], pa.string()),
                "kind": pa.array([r[5] for r in news], pa.string()),
            }
        )
        con.execute(
            "CREATE TABLE review_monthly AS SELECT * FROM monthly_arrow ORDER BY appid, month"
        )
        con.execute(
            "CREATE TABLE news AS SELECT DISTINCT ON (appid, gid) * FROM news_arrow "
            "ORDER BY appid, date"
        )
        con.execute(
            "CREATE TABLE build_info AS SELECT ? AS built_at, ? AS min_reviews, "
            "? AS tag_max_rank, ? AS tag_min_share",
            [datetime.now(UTC).isoformat(), cfg.min_reviews, cfg.tag_max_rank, cfg.tag_min_share],
        )
        counts = {
            "games": len(games),
            "games_min_reviews": con.execute(
                "SELECT COUNT(*) FROM games WHERE review_count >= ?", [cfg.min_reviews]
            ).fetchone()[0],
            "game_tags": len(tags),
            "tags": len(tag_names),
            "with_developer": sum(1 for c in creators if c["dev_key"]),
            "timeline_games": len({r[0] for r in monthly}),
            "news": len(news),
        }
    finally:
        con.close()
    out_path.unlink(missing_ok=True)
    tmp.replace(out_path)
    return counts

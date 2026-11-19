import pytest

from pipeline import db
from pipeline.build.tables import parse_basic, parse_item, run
from pipeline.config import BuildConfig
from pipeline.db import transaction

CFG = BuildConfig(min_reviews=20, tag_max_rank=2, tag_min_share=0.5)


def item(**overrides):
    base = {
        "appid": 1,
        "id": 1,
        "success": 1,
        "visible": True,
        "type": 0,
        "name": "Game",
        "reviews": {"summary_filtered": {"review_count": 200, "percent_positive": 83}},
        "release": {"steam_release_date": 1600000000, "original_steam_release_date": 1575000000},
        "best_purchase_option": {"final_price_in_cents": "1499", "original_price_in_cents": 1999},
        "tags": [
            {"tagid": 10, "weight": 100},
            {"tagid": 30, "weight": 40},
            {"tagid": 20, "weight": 60},
            {"tagid": 40, "weight": 55},
        ],
    }
    base.update(overrides)
    return base


def test_parse_game_fields():
    game, _ = parse_item(item(), CFG)
    assert game.first_release.year == 2019  # original (early access) date
    assert game.full_release.year == 2020
    assert game.price_usd == 19.99  # undiscounted
    assert (game.n_pos, game.n_neg) == (166, 34)
    assert game.n_tags == 4


def test_default_relevance_is_rank_only():
    _, tags = parse_item(item(), BuildConfig(tag_max_rank=2))
    assert [t.relevant for t in tags] == [True, True, False, False]


def test_tags_ranked_by_weight_with_relevance_rule():
    _, tags = parse_item(item(), CFG)
    assert [(t.tagid, t.rank) for t in tags] == [(10, 1), (20, 2), (40, 3), (30, 4)]
    # rank <= 2, or share >= 0.5: tag 40 (0.55) is relevant by share, 30 (0.4) is not
    assert [t.relevant for t in tags] == [True, True, True, False]
    assert tags[2].weight_share == pytest.approx(0.55)


@pytest.mark.parametrize(
    "overrides",
    [{"missing": True}, {"success": 15}, {"visible": False}, {"type": 14}],
)
def test_non_games_skipped(overrides):
    assert parse_item(item(**overrides), CFG) is None


def test_free_and_early_access():
    game, _ = parse_item(
        item(
            is_free=True,
            best_purchase_option=None,
            release={"is_early_access": True, "steam_release_date": 1600000000},
        ),
        CFG,
    )
    assert game.price_usd == 0.0
    assert game.is_early_access and game.full_release is None


def test_no_reviews():
    game, _ = parse_item(item(reviews={"summary_filtered": {"review_count": 0}}), CFG)
    assert game.pct_positive is None and game.n_pos == 0


def test_run_writes_duckdb(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    conn = db.connect(tmp_path / "raw.sqlite")
    with transaction(conn):
        db.put_raw(conn, "items", "1", 200, item())
        db.put_raw(
            conn,
            "items",
            "2",
            200,
            item(
                appid=2,
                id=2,
                reviews={"summary_filtered": {"review_count": 5, "percent_positive": 100}},
            ),
        )
        db.put_raw(conn, "items", "3", 200, {"missing": True})
        db.put_raw(
            conn,
            "taglist",
            "english",
            200,
            {
                "response": {
                    "tags": [
                        {"tagid": 10, "name": "Roguelike"},
                        {"tagid": 20, "name": "Deckbuilding"},
                        {"tagid": 30, "name": "Indie"},
                        {"tagid": 40, "name": "Strategy"},
                    ]
                }
            },
        )
    out = tmp_path / "analysis.duckdb"
    counts = run(conn, out, CFG, launch_dates=None)
    assert counts["games"] == 2 and counts["games_min_reviews"] == 1

    con = duckdb.connect(str(out), read_only=True)
    rows = dict(con.execute("SELECT name, n_games_relevant FROM tags").fetchall())
    assert rows == {"Roguelike": 1, "Deckbuilding": 1, "Strategy": 1, "Indie": 0}


def test_parse_basic_dev_key():
    clan = {
        "appid": 1,
        "success": 1,
        "basic_info": {
            "developers": [{"name": "Supergiant Games", "creator_clan_account_id": 3584665}],
            "publishers": [{"name": "Supergiant Games"}],
            "franchises": [{"name": "Hades"}],
        },
    }
    assert parse_basic(clan)["dev_key"] == "clan:3584665"
    assert parse_basic(clan)["franchise"] == "Hades"
    named = {"appid": 2, "success": 1, "basic_info": {"developers": [{"name": " Mega Crit "}]}}
    assert parse_basic(named)["dev_key"] == "name:mega crit"
    assert parse_basic({"appid": 3, "success": 1})["dev_key"] is None
    assert parse_basic({"missing": True}) is None


def test_games_without_developer_get_own_cluster(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    conn = db.connect(tmp_path / "raw.sqlite")
    with transaction(conn):
        db.put_raw(conn, "items", "1", 200, item())
        db.put_raw(conn, "items", "2", 200, item(appid=2, id=2))
        db.put_raw(
            conn,
            "basic",
            "1",
            200,
            {
                "appid": 1,
                "success": 1,
                "basic_info": {"developers": [{"name": "Dev", "creator_clan_account_id": 9}]},
            },
        )
        db.put_raw(conn, "taglist", "english", 200, {"response": {"tags": []}})
    out = tmp_path / "a.duckdb"
    run(conn, out, CFG, launch_dates=None)
    con = duckdb.connect(str(out), read_only=True)
    # dev_key_raw is the per-developer key; dev_key may merge these two identical fixture
    # games into one studio group (see test_studios.py).
    assert con.execute("SELECT appid, dev_key_raw FROM games ORDER BY appid").fetchall() == [
        (1, "clan:9"),
        (2, "app:2"),
    ]


def test_parse_histogram_and_news():
    from pipeline.build.timelines import classify_news, parse_histogram, parse_news

    body = {
        "results": {
            "rollup_type": "month",
            "rollups": [
                {"date": 1575158400, "recommendations_up": 10, "recommendations_down": 2},
                {"date": 1577836800, "recommendations_up": 5, "recommendations_down": 5},
            ],
        }
    }
    rows = parse_histogram(7, body)
    assert [(r[1].isoformat(), r[2], r[3]) for r in rows] == [
        ("2019-12-01", 10, 2),
        ("2020-01-01", 5, 5),
    ]
    weekly = {
        "results": {
            "rollup_type": "week",
            "rollups": [
                {"date": 1575158400, "recommendations_up": 3, "recommendations_down": 1},
                {"date": 1575763200, "recommendations_up": 4, "recommendations_down": 0},
                {"date": 1577836800, "recommendations_up": 1, "recommendations_down": 1},
            ],
        }
    }
    assert [(r[1].isoformat(), r[2], r[3]) for r in parse_histogram(7, weekly)] == [
        ("2019-12-01", 7, 1),
        ("2020-01-01", 1, 1),
    ]
    day = {"results": {"rollup_type": "day", "rollups": [{"date": 1575158400}]}}
    assert parse_histogram(7, day) == []

    assert classify_news("Patch 1.0.4 is live") == "update"
    assert classify_news("Hotfix for crashes") == "update"
    assert classify_news("Version 1.0 is here") == "launch"
    assert classify_news("Hades II is out now!") == "launch"
    assert classify_news("Watch our orchestral concert") == "other"
    news = parse_news(
        7,
        {
            "appnews": {
                "newsitems": [
                    {"gid": "1", "title": "Update 2", "date": 1600000000, "url": "u"},
                    {"gid": "2", "title": "", "date": 1600000000},
                ]
            }
        },
    )
    assert len(news) == 1 and news[0][5] == "update"


def test_launch_dates_move_back_only_for_large_gaps():
    from datetime import date, datetime

    import duckdb

    from pipeline.build.tables import _apply_launch_dates

    con = duckdb.connect()
    con.execute("CREATE TABLE games (appid BIGINT, first_release TIMESTAMP)")
    con.executemany(
        "INSERT INTO games VALUES (?, ?)",
        [
            (1, datetime(2018, 2, 8)),  # left early access: Steam shows the 1.0 date
            (2, datetime(2020, 5, 10)),  # first review a few days early: keep Steam's
            (3, None),  # no Steam date at all
            (4, datetime(2004, 11, 16)),  # older than Steam reviews: keep Steam's
        ],
    )
    _apply_launch_dates(
        con,
        {1: date(2013, 12, 11), 2: date(2020, 5, 1), 3: date(2015, 3, 3), 4: date(2010, 10, 15)},
    )
    rows = con.execute(
        "SELECT appid, first_release::DATE, steam_release::DATE, launch_source FROM games "
        "ORDER BY appid"
    ).fetchall()
    assert rows == [
        (1, date(2013, 12, 11), date(2018, 2, 8), "first_review"),
        (2, date(2020, 5, 10), date(2020, 5, 10), "steam"),
        (3, date(2015, 3, 3), None, "first_review"),
        (4, date(2004, 11, 16), date(2004, 11, 16), "steam"),
    ]
